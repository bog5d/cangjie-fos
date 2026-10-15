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


# ── WP2 子命令：正文抽取与认知卡 ────────────────────────────────────────────
def cmd_parse(a) -> int:
    from cangjie_fos.services import dd_v1_parser_service as ps
    r = ps.parse_pending_batch(a.library, limit=a.limit,
                               allow_docling=not a.no_docling)
    _out(r)
    return 0


def cmd_cards(a) -> int:
    from cangjie_fos.services import dd_v1_card_service as cs
    _out(cs.build_cards_for_library(a.library, limit=a.limit))
    return 0


def cmd_coverage(a) -> int:
    from cangjie_fos.services import dd_v1_card_service as cs
    _out(cs.card_coverage(a.library))
    return 0


def cmd_search(a) -> int:
    from cangjie_fos.services import dd_v1_card_service as cs
    hits = cs.search_materials(a.library, a.query, limit=a.limit)
    _out({"library": a.library, "query": a.query, "count": len(hits), "hits": hits})
    return 0


def cmd_card(a) -> int:
    from cangjie_fos.services import dd_v1_card_service as cs
    from cangjie_fos.services import dd_v1_manifest_service as mf
    row = mf.get_manifest_entry(a.library, a.path)
    if row is None:
        print(json.dumps({"error": "NOT_FOUND", "path": a.path}, ensure_ascii=False))
        return 1
    _out(cs.get_card(row["file_id"]) or {"error": "CARD_NOT_BUILT"})
    return 0


# ── WP3 子命令：需求拆解与多文件匹配 ────────────────────────────────────────
def cmd_checklist(a) -> int:
    from cangjie_fos.services import dd_v1_requirement_service as rq
    rows = []
    for ln, line in enumerate(Path(a.file).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t", 1)
        if len(parts) == 2:
            rows.append({"item_no": parts[0].strip(), "raw_text": parts[1].strip()})
        else:
            rows.append({"item_no": f"L{ln}", "raw_text": parts[0].strip()})
    _out(rq.ingest_checklist(a.library, rows, anchor_year=a.anchor_year,
                             institution=a.institution))
    return 0


def cmd_obligations(a) -> int:
    from cangjie_fos.services import dd_v1_requirement_service as rq
    obl = rq.list_obligations(a.library)
    _out({
        "library": a.library,
        "count": len(obl),
        "quality": rq.obligation_quality(a.library),
        "obligations": [
            {k: o[k] for k in ("obligation_id", "obligation", "entity_scope",
                               "entity_basis", "period_from", "period_to",
                               "period_basis", "doc_type", "doc_type_basis",
                               "caliber", "seal_required", "notes")}
            for o in obl[:a.limit]
        ],
    })
    return 0


def cmd_match(a) -> int:
    from cangjie_fos.services import dd_v1_match_service as ms
    kw = {}
    if a.cap is not None:
        kw["candidate_cap"] = a.cap
    _out(ms.match_library(a.library, **kw))
    return 0


def cmd_status(a) -> int:
    from cangjie_fos.services import dd_v1_match_service as ms
    st = ms.get_status(a.obligation)
    if st is None:
        print(json.dumps({"error": "NO_STATUS", "obligation": a.obligation}))
        return 1
    out = dict(st)
    out["matches"] = [
        {k: m.get(k) for k in ("rank", "score", "card_rel_path", "card_title",
                               "entity_ok", "period_ok", "doctype_ok",
                               "deliverable")}
        for m in ms.list_matches(a.obligation)
    ]
    _out(out)
    return 0


def cmd_entity(a) -> int:
    from cangjie_fos.services import dd_v1_requirement_service as rq
    rq.register_entity(a.library, a.id, a.name, relation=a.relation,
                       parent_id=a.parent, valid_from=a.valid_from,
                       valid_to=a.valid_to, is_group_root=a.group_root,
                       source_ref=a.source)
    _out({"registered": a.id, "name": a.name, "relation": a.relation,
          "total": rq.entities_registered(a.library)})
    return 0


# ── WP4 子命令：人工审核、组包与安全 Gate ──────────────────────────────────
def cmd_review(a) -> int:
    from cangjie_fos.services import dd_v1_package_service as pkg
    _out(pkg.build_review_pack(a.library, institution=a.institution))
    return 0


def cmd_approve(a) -> int:
    from cangjie_fos.services import dd_v1_package_service as pkg
    _out(pkg.approve(a.review, approved_by=a.by, note=a.note))
    return 0


def cmd_package(a) -> int:
    from cangjie_fos.services import dd_v1_package_service as pkg
    _out(pkg.package_approved(a.review, output_dir=a.out))
    return 0


def cmd_edits(a) -> int:
    from cangjie_fos.services import dd_v1_package_service as pkg
    _out({"review_id": a.review, "edits": pkg.list_edits(a.review),
          "promoted_to_global_rule": False})
    return 0


# ── WP5 子命令：纠错经验、回归数据集与评分 ────────────────────────────────
def cmd_feedback(a) -> int:
    from cangjie_fos.services import dd_v1_experience_service as xs
    _out(xs.record_feedback(a.library, a.requirement, reason=a.reason,
                            edited_by=a.by, institution=a.institution,
                            template=a.template, scope_entity=a.entity))
    return 0


def cmd_recall(a) -> int:
    from cangjie_fos.services import dd_v1_experience_service as xs
    _out(xs.recall_experience(a.library, a.requirement, current_entity=a.entity,
                              institution=a.institution, template=a.template))
    return 0


def cmd_gold(a) -> int:
    from cangjie_fos.services import dd_v1_experience_service as xs
    _out(xs.add_regression_case(a.library, a.text, source_ref=a.source,
                                item_no=a.item_no, expected_verdict=a.verdict))
    return 0


def cmd_score(a) -> int:
    from cangjie_fos.services import dd_v1_experience_service as xs
    s = xs.score_library(a.library)
    _out({
        "scored_on": s["scored_on"],
        "regression_cases": s["regression_cases"],
        "verified_points": s["verified_points"],
        "total_points": s["total_points"],
        "goal_state": s["goal_state"],
        "metrics": [{"id": m["id"], "weight": m["weight"],
                     "points": m["verified_points"], "status": m["status"]}
                    for m in s["metrics"]],
        "hard_gates": [{"id": g["id"], "status": g["status"]} for g in s["hard_gates"]],
        "note": s["self_report_prohibited"],
    })
    return 0


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

    # ── WP2：抽取与认知卡 ────────────────────────────────────────────────
    sp = sub.add_parser("parse", help="批量抽取正文并写回解析状态位")
    sp.add_argument("--library", required=True)
    sp.add_argument("--limit", type=int, default=200)
    sp.add_argument("--no-docling", action="store_true",
                    help="跳过可选的 Docling 层（默认装了才用）")
    sp.set_defaults(func=cmd_parse)

    sp = sub.add_parser("cards", help="批量构建结构化材料认知卡")
    sp.add_argument("--library", required=True)
    sp.add_argument("--limit", type=int, default=500)
    sp.set_defaults(func=cmd_cards)

    sp = sub.add_parser("coverage", help="认知卡出处分布（多少字段其实我们不知道）")
    sp.add_argument("--library", required=True)
    sp.set_defaults(func=cmd_coverage)

    sp = sub.add_parser("search", help="中文全文检索（FTS5 + bigram，无需 LLM）")
    sp.add_argument("--library", required=True)
    sp.add_argument("--query", required=True)
    sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("card", help="查看单份材料的认知卡")
    sp.add_argument("--library", required=True)
    sp.add_argument("--path", required=True, help="相对路径")
    sp.set_defaults(func=cmd_card)

    # ── WP3：需求拆解与多文件匹配 ────────────────────────────────────────
    sp = sub.add_parser("checklist", help="录入机构清单并拆成原子义务")
    sp.add_argument("--library", required=True)
    sp.add_argument("--file", required=True, help="清单文件（每行：编号<TAB>原文）")
    sp.add_argument("--anchor-year", type=int, default=None,
                    help="相对年份（如「近三年」）的锚定年；不给则不擅自假定")
    sp.add_argument("--institution", default="")
    sp.set_defaults(func=cmd_checklist)

    sp = sub.add_parser("obligations", help="查看拆解出的原子义务及其出处")
    sp.add_argument("--library", required=True)
    sp.add_argument("--limit", type=int, default=50)
    sp.set_defaults(func=cmd_obligations)

    sp = sub.add_parser("match", help="对全库义务做匹配并给出四维覆盖判定")
    sp.add_argument("--library", required=True)
    sp.add_argument("--cap", type=int, default=None, help="候选上限（默认 20，可配置）")
    sp.set_defaults(func=cmd_match)

    sp = sub.add_parser("status", help="查看某条义务的最终判定与缺口明细")
    sp.add_argument("--library", required=True)
    sp.add_argument("--obligation", required=True)
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("entity", help="登记权威主体（集团成员名单）")
    sp.add_argument("--library", required=True)
    sp.add_argument("--id", required=True)
    sp.add_argument("--name", required=True)
    sp.add_argument("--relation", default="other")
    sp.add_argument("--parent", default="")
    sp.add_argument("--group-root", action="store_true")
    sp.add_argument("--valid-from", type=int, default=0)
    sp.add_argument("--valid-to", type=int, default=0)
    sp.add_argument("--source", required=True, help="权威依据出处（必填）")
    sp.set_defaults(func=cmd_entity)

    # ── WP4：人工审核、组包与安全 Gate ──────────────────────────────────
    sp = sub.add_parser("review", help="生成审核包（只读材料、零复制原件）")
    sp.add_argument("--library", required=True)
    sp.add_argument("--institution", default="")
    sp.set_defaults(func=cmd_review)

    sp = sub.add_parser("approve", help="人工最终批准（组包前置条件）")
    sp.add_argument("--review", required=True)
    sp.add_argument("--by", required=True, help="批准人（可追责，必填）")
    sp.add_argument("--note", default="")
    sp.set_defaults(func=cmd_approve)

    sp = sub.add_parser("package", help="按机构编号组包并复制原件（须已批准）")
    sp.add_argument("--review", required=True)
    sp.add_argument("--out", default=None)
    sp.set_defaults(func=cmd_package)

    sp = sub.add_parser("edits", help="查看人工修改留痕")
    sp.add_argument("--review", required=True)
    sp.set_defaults(func=cmd_edits)

    # ── WP5：纠错经验、回归数据集与评分 ─────────────────────────────────
    sp = sub.add_parser("feedback", help="记录一次人工纠错（tier 恒为 feedback）")
    sp.add_argument("--library", required=True)
    sp.add_argument("--requirement", required=True)
    sp.add_argument("--reason", required=True)
    sp.add_argument("--by", required=True)
    sp.add_argument("--entity", required=True, help="适用主体（必填）")
    sp.add_argument("--institution", default="")
    sp.add_argument("--template", default="")
    sp.set_defaults(func=cmd_feedback)

    sp = sub.add_parser("recall", help="召回同类已批准经验（逐条复验适用范围）")
    sp.add_argument("--library", required=True)
    sp.add_argument("--requirement", required=True)
    sp.add_argument("--entity", default="")
    sp.add_argument("--institution", default="")
    sp.add_argument("--template", default="")
    sp.set_defaults(func=cmd_recall)

    sp = sub.add_parser("gold", help="录入回归用例（必须带出处）")
    sp.add_argument("--library", required=True)
    sp.add_argument("--text", required=True)
    sp.add_argument("--source", required=True, help="来源：历史人工交付包/机构原件")
    sp.add_argument("--item-no", default="")
    sp.add_argument("--verdict", default="", help="期望判定")
    sp.set_defaults(func=cmd_gold)

    sp = sub.add_parser("score", help="自动化评分（无回归数据集则全 0，不自评高分）")
    sp.add_argument("--library", required=True)
    sp.set_defaults(func=cmd_score)
    return p


def main() -> int:
    from cangjie_fos.services.dd_v1_package_service import ApprovalRequired
    p = build_parser()
    try:
        a = p.parse_args()
    except SystemExit as e:
        return 2 if e.code else 0
    try:
        return a.func(a)
    except ApprovalRequired as e:
        print(json.dumps({"error": "APPROVAL_REQUIRED", "detail": str(e),
                          "gate": "HG1 未经人工最终批准不得组包"},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
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
