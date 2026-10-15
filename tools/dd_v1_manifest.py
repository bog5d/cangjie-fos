#!/usr/bin/env python3
"""DD-V1 材料库 Manifest 命令行入口（WP1）。

目的：给独立监工、刘江和后续运维一条**不依赖前端、不依赖 LLM key** 的可复核路径，
用来实测授权接管、增量扫描、断点恢复与同名跨主体保留。

用法（在 `backend/` 下执行，或用绝对路径）：

    # 1) 登记一个经过授权的材料库（只此一步需要显式 authorized_by）
    python tools/dd_v1_manifest.py register --library lib1 --root /path/to/材料库 \\
        --authorized-by "波总" --name "泽天集团材料库"

    # 2) 全量建库（源目录只读，产物落受控 Data Plane）
    python tools/dd_v1_manifest.py build --library lib1 --mode full

    # 3) 增量巡检（断点自动续跑：若上次中断，会先报出可恢复的 run_id）
    python tools/dd_v1_manifest.py build --library lib1 --mode incremental

    # 4) 只重试失败/截断的条目
    python tools/dd_v1_manifest.py build --library lib1 --mode retry

    # 5) 查概览 / 查断点 / 查同名跨主体是否共存
    python tools/dd_v1_manifest.py summary   --library lib1
    python tools/dd_v1_manifest.py resume   --library lib1
    python tools/dd_v1_manifest.py same-name --library lib1 --name 营业执照.pdf

    # 6) 自检：不碰真实材料库，造临时库跑一遍不变量
    python tools/dd_v1_manifest.py selftest

设计约束（与 dd_v1_manifest_service 一致）：
- **源文件只读**：本入口从不向材料库写入。
- **不碰 LLM**：无需任何 API key 即可运行。
- 退出码：0 成功 / 1 运行失败 / 2 用法错误（与 cangjie-gm 约定一致）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]        # cangjie-fos/
_BACKEND = _REPO / "backend"                       # cangjie-fos/backend/
_SRC = _BACKEND / "src"                            # cangjie-fos/backend/src
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _svc():
    from cangjie_fos.services import dd_v1_manifest_service as mf
    return mf


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


# ── 子命令 ──────────────────────────────────────────────────────────────────
def cmd_register(a) -> int:
    mf = _svc()
    r = mf.register_library(a.library, a.root, authorized_by=a.authorized_by,
                            display_name=a.name or "")
    _out(r)
    return 0


def cmd_build(a) -> int:
    mf = _svc()
    # 断点自动续跑：显式 --run-id 优先，否则自动捡起未完成的 running
    run_id = a.run_id
    if not run_id:
        pending = mf.find_resumable_run(a.library)
        if pending:
            run_id = pending["run_id"]
            print(f"[resume] 检测到中断运行 {run_id}，"
                  f"已处理 {pending['processed']}/{pending['total_files']}，自动续跑",
                  file=sys.stderr)
    r = mf.build_manifest(a.library, mode=a.mode, resume_run_id=run_id,
                          lease_owner=a.owner or f"cli-{os.getpid()}")
    _out(r)
    return 0


def cmd_summary(a) -> int:
    mf = _svc()
    _out(mf.manifest_summary(a.library))
    return 0


def cmd_resume(a) -> int:
    mf = _svc()
    r = mf.find_resumable_run(a.library)
    if r is None:
        _out({"resumable": False, "hint": "无中断运行，可直接 build"})
        return 0
    r["resumable"] = True
    _out(r)
    return 0


def cmd_same_name(a) -> int:
    mf = _svc()
    rows = mf.find_same_name_across_subjects(a.library, a.name)
    _out({"library": a.library, "name": a.name, "count": len(rows), "entries": rows})
    return 0


def cmd_selftest(a) -> int:
    """自检：在临时目录里实跑三条关键不变量，不接触任何真实材料。"""
    mf = _svc()
    results: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append({"检查": name, "结果": "PASS" if ok else "FAIL", "说明": detail})

    with tempfile.TemporaryDirectory(prefix="dd_v1_selftest_") as td:
        base = Path(td)
        os.environ["CANGJIE_DD_V1_DATA_DIR"] = str(base / "_plane")
        mf.close_all()

        root = base / "materials"
        root.mkdir()
        # 同名不同主体，mtime 刻意拉开
        for i, sub in enumerate(["集团母公司", "子公司甲", "子公司乙"]):
            d = root / sub
            d.mkdir()
            f = d / "营业执照.pdf"
            f.write_text(f"{sub} 正文 {i}", encoding="utf-8")
            os.utime(f, (1_700_000_000 + i * 86400,) * 2)

        try:
            mf.register_library("selftest", str(root), authorized_by="selftest",
                                db_path=base / "_dp" / "manifest.sqlite")
        except Exception as exc:  # noqa: BLE001
            check("授权登记", False, str(exc))
            _out({"selftest": results})
            return 1

        db = base / "_dp" / "manifest.sqlite"
        first = None
        try:
            first = mf.build_manifest("selftest", db_path=db)
            check("授权目录扫描", first["added"] == 3,
                  f"首次全量应新增 3，实际 {first['added']}")
        except Exception as exc:  # noqa: BLE001
            check("授权目录扫描", False, str(exc))

        rows = mf.find_same_name_across_subjects(
            "selftest", "营业执照.pdf", db_path=db)
        check("同名跨主体全部保留（D2 守卫）", len(rows) == 3,
              f"实际 {len(rows)} 份，应为 3 份")
        check("内容哈希互不相同", len({r['content_hash'] for r in rows}) == 3,
              f"不同主体内容应互异")

        if first is not None:
            again = mf.build_manifest("selftest", mode="full", db_path=db)
            check("重复全量扫描幂等",
                  again["added"] == 0 and again["unchanged"] == 3,
                  f"二次新增 {again['added']}（应 0），未变 {again['unchanged']}（应 3）")

        # 源目录只读
        after = sorted(p.name for p in root.rglob("*") if p.is_file())
        check("源目录未被污染", len(after) == 3, f"库内现有 {len(after)} 个文件，应为 3")

        mf.close_all()

    ok = all(r["结果"] == "PASS" for r in results)
    _out({"selftest": "PASS" if ok else "FAIL", "checks": results})
    return 0 if ok else 1


# ── 解析 ────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dd_v1_manifest",
        description="DD-V1 材料库 Manifest：授权接管 / 增量扫描 / 断点恢复",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("register", help="登记授权材料库")
    sp.add_argument("--library", required=True)
    sp.add_argument("--root", required=True)
    sp.add_argument("--authorized-by", required=True)
    sp.add_argument("--name", default="")
    sp.set_defaults(func=cmd_register)

    sp = sub.add_parser("build", help="建立/更新 Manifest")
    sp.add_argument("--library", required=True)
    sp.add_argument("--mode", choices=["full", "incremental", "retry"],
                    default="incremental")
    sp.add_argument("--run-id", default=None, help="显式指定续跑的 run_id")
    sp.add_argument("--owner", default="")
    sp.set_defaults(func=cmd_build)

    sp = sub.add_parser("summary", help="材料库概览")
    sp.add_argument("--library", required=True)
    sp.set_defaults(func=cmd_summary)

    sp = sub.add_parser("resume", help="查询可恢复的断点")
    sp.add_argument("--library", required=True)
    sp.set_defaults(func=cmd_resume)

    sp = sub.add_parser("same-name", help="查同名文件是否跨主体共存")
    sp.add_argument("--library", required=True)
    sp.add_argument("--name", required=True)
    sp.set_defaults(func=cmd_same_name)

    sp = sub.add_parser("selftest", help="临时库自检，不碰真实材料")
    sp.set_defaults(func=cmd_selftest)
    return p


def main() -> int:
    p = build_parser()
    try:
        a = p.parse_args()
    except SystemExit as e:
        return 2 if e.code else 0
    try:
        return a.func(a)
    except PermissionError as e:
        print(json.dumps({"error": "PERMISSION_DENIED", "detail": str(e)},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": type(e).__name__, "detail": str(e)},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
