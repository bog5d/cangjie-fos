#!/usr/bin/env python3
"""FOS #71 考生2 P0 修复：六态（候选为空的原因）**生产路径可达性**运行探针。

本探针载 **4/6** 口径：生产路径（薄入口 ``tools/dd_team_channel.py run`` ⇒ 桥接
``dd_v1_bridge_service`` ⇒ 语义层 ``dd_v1_semantic_retrieval_service``）上实测可达
**4/6**（``NO_MATERIAL`` / ``UNRESOLVED_DOC_TYPE`` / ``UNKNOWN_ENTITY`` /
``RETRIEVAL_EXHAUSTED``），不可达 **2/6**（``PERMISSION_BLOCKED`` / ``OTHER``），
两项各带机械理由。

★ 为什么要有本探针：仓内此前只有 ``backend/tests/test_dd_v1_fos71_t5_six_states_entry.py``
  里的一处**数字口径**（它自称生产路径可达 3/6，并把 ``NO_MATERIAL`` 列为不可达）。
  那个机制理由已被**同一 PR 的桥接层字节证伪** ⇒ 数字会误导后人。
  本探针把「4/6」变成**可重跑的运行件**：后人自己跑一次就能复核，不必只读到一个数字。

★ **「可写」≠「生产路径可达」**，这是两个不同的命题：
  - 六态在**语义层函数**层面全部可写（分支逻辑齐备）⇒ 见
    ``backend/tests/test_dd_v1_fos71_player2_p0.py::test_no_candidate_reason_distinguishes_six_states``；
  - 本探针只回答**第二个**问题：走**生产接线**（真实 meta 生产者 + 真实义务接线）时
    到底哪几态真的到得了。

★ 纪律：
  - **不写产品实现**、**不联网**、**不调外部模型**、**零费用**；
  - 材料与清单全部**自造合成内容**（零真实客户标识），只落在临时目录里，跑完即删；
  - 权威主体登记用**生产函数** ``dd_v1_requirement_service.register_entity``，
    ``source_ref`` 写明是合成登记（没有权威依据的主体不得入册，这条是生产契约）；
  - 取值域只从**权威枚举** ``dd_v1_semantic_retrieval_service.NO_CANDIDATE_REASONS`` 取，
    本探针**不另抄一份**。

用法：
    python3 tools/dd_v1_six_state_reachability_probe.py [--repo-root PATH] [--json] [--verbose]

退出码：
    0 = 实测可达集与预期 4/6 **逐位相等**（自证通过）
    1 = 实测与预期不符（打印差集；生产接线变了就应当红）
    2 = 用法 / 环境错误
"""
from __future__ import annotations

import argparse

import importlib

import json
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 生产路径上**实测可达**的四态（顺序按权威枚举里的书写顺序，便于逐位比对）。
EXPECTED_REACHABLE = (
    "NO_MATERIAL",
    "UNRESOLVED_DOC_TYPE",
    "UNKNOWN_ENTITY",
    "RETRIEVAL_EXHAUSTED",
)

#: 生产路径上**不可达**的两态，各带机械理由（不是「暂时没测到」，是有构造性理由）。
UNREACHABLE_REASONS = {
    "PERMISSION_BLOCKED": "生产 meta 生产者（桥接链 build_meta、入口 B cmd_scaffold）"
                          "都不写 access / restricted 两个字段 ⇒ 无生产者",
    "OTHER": "生产路径在 local_material_snapshot 先校验文件存在（缺文件直接 FileNotFoundError），"
             "而 PermissionError 被语义层原样上抛不计数 ⇒ read_errors 恒 0 ⇒ 兜底分支到不了",
}

#: 合成材料正文（零真实客户标识；主体名是合成占位，不是任何真实法人）。
SYNTHETIC_BODY = "审计报告\n本报告为{year}年度财务审计结论，由{ent}出具。\n"

#: 合成主体名（材料目录名 ＝ 主体名 ⇒ 认知卡据此推断主体）。
SYNTHETIC_ENTITY = "示例科技"


def _bootstrap(repo_root: Path):
    """把生产模块装进来。

    DD-V1 这条链（桥接 / 语义 / 认知卡 / manifest / 解析 / 义务）**只依赖标准库**。
    但 ``cangjie_fos/services/__init__.py`` 会再导出四个**与本探针无关**的服务
    （音频 / 差异 / 演化 / 音高图），那条链要 pydantic。
    ⇒ 先试正常导入；缺 pydantic 时把两个包**占位**成只带 ``__path__`` 的壳
    （子模块照常按真实路径加载，生产字节一个不动）。
    """
    src = repo_root / "backend" / "src"
    tools = repo_root / "tools"
    for p in (str(src), str(tools)):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        import cangjie_fos.services  # noqa: F401
        stubbed = False
    except Exception:  # noqa: BLE001 — 缺 pydantic 之类 ⇒ 走壳
        stubbed = True
        for name, rel in (("cangjie_fos", "cangjie_fos"),
                          ("cangjie_fos.services", "cangjie_fos/services")):
            if name in sys.modules:
                continue
            mod = types.ModuleType(name)
            mod.__path__ = [str(src / rel)]
            mod.__package__ = name
            sys.modules[name] = mod
    return importlib.import_module, stubbed


def _materials(root: Path, n: int = 1, *, draft: bool = False) -> Path:
    """造一个**合成**材料库（主体放在子目录里 ⇒ 主体由认知卡推断）。"""
    (root / SYNTHETIC_ENTITY).mkdir(parents=True)
    suffix = "草稿" if draft else ""
    for i in range(n):
        (root / SYNTHETIC_ENTITY / f"审计报告2024{suffix}{i}.txt").write_text(
            SYNTHETIC_BODY.format(year=2024, ent=SYNTHETIC_ENTITY), encoding="utf-8")
    return root


def _reasons(bridge: dict) -> set[str]:
    """桥接产物里「没有可用候选」的义务行所带的原因集合。"""
    return {ob.get("no_candidate_reason")
            for ob in bridge.get("obligations", [])
            if ob.get("no_candidate_reason")}


def _run_captured(fn) -> tuple[int, str, str]:
    """跑 ``fn()``，把**文件描述符 1 / 2** 一并收进临时文件 ⇒ 返回 (返回码, stdout, stderr)。

    ★ 为什么要收 fd 而不是只改绑 ``sys.stdout`` / ``sys.stderr``：薄入口内部用
      ``os.popen`` 取 git 信息，那条路写的是**继承来的 fd 2** ⇒ 只改绑 Python 对象
      收不到，正常路径上会刷一串 ``fatal: not a git repository``（那是入口取不到
      代码版本号时的正常降级，**不是**探针失败，但会让人误读成失败）。
    ★ 成功时只在 --verbose 下回放；**失败时整段带进异常** ⇒ 一个错误都不藏。
    """
    fo = tempfile.TemporaryFile()
    fe = tempfile.TemporaryFile()
    saved_out, saved_err = os.dup(1), os.dup(2)
    try:
        os.dup2(fo.fileno(), 1)
        os.dup2(fe.fileno(), 2)
        try:
            sys.stdout.flush()
            sys.stderr.flush()
            rc = fn()
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(saved_out, 1)
            os.dup2(saved_err, 2)
    except BaseException:
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        raise
    finally:
        os.close(saved_out)
        os.close(saved_err)
    fo.seek(0)
    fe.seek(0)
    out = fo.read().decode("utf-8", "replace")
    err = fe.read().decode("utf-8", "replace")
    fo.close()
    fe.close()
    return rc, out, err


def _run_entry(tc, imp, tmp: Path, lib: str, root: Path, checklist: list[str],
               *, authority: str | None, verbose: bool) -> dict:
    """跑一次**正式薄入口**（``tools/dd_team_channel.py run``）并取回机读产物。

    ``authority`` 非空 ⇒ 先用**生产函数**登记权威主体（登记在同一个数据面里），
    义务侧于是走桥接层的 AUTHORITY 分支。
    """
    mf = imp("cangjie_fos.services.dd_v1_manifest_service")
    rq = imp("cangjie_fos.services.dd_v1_requirement_service")
    plane = tmp / "_plane"
    os.environ["CANGJIE_DD_V1_DATA_DIR"] = str(plane)
    os.environ["CANGJIE_DD_V1_POLICY"] = str(tmp / "无策略.json")
    cl = tmp / f"{lib}.tsv"
    cl.write_text("".join(f"{i + 1}\t{t}\n" for i, t in enumerate(checklist)), encoding="utf-8")

    if authority:
        mf.close_all()
        rq.register_entity(lib, "E1", authority, relation="other",
                           source_ref="合成登记（六态可达性探针，无真实权威依据）",
                           db_path=plane / "manifest.sqlite")
        mf.close_all()

    argv = ["dd_team_channel", "run", "--library", lib, "--root", str(root),
            "--checklist", str(cl), "--allow-real-material"]
    old_argv = sys.argv
    sys.argv = argv
    try:
        rc, out, err = _run_captured(tc.main)
    finally:
        sys.argv = old_argv
    if verbose:
        sys.stdout.write(out)
        sys.stderr.write(err)
    if rc != 0:
        raise RuntimeError(f"薄入口返回码 {rc}（场景 {lib}）\n{out[-2000:]}\n{err[-2000:]}")
    jss = sorted((plane / "团队报告").glob("*.json"))
    if not jss:
        raise RuntimeError(f"薄入口没产出机读结果（场景 {lib}）")
    data = json.loads(jss[-1].read_text(encoding="utf-8"))
    return data["semantic_bridge"]


def _measure(tc, imp, tmp: Path, verbose: bool) -> tuple[set[str], list[dict], dict]:
    """跑四个场景，量出生产路径上真的到得了的原因集合。

    第四个场景是**关键**：它与第二个场景**只差一件东西** —— 有没有登记权威主体。
    差这一件，原因就从 ``UNKNOWN_ENTITY`` 变成 ``NO_MATERIAL`` ⇒ 这就是旧口径
    （把 ``NO_MATERIAL`` 说成不可达）被证伪的机械证。
    """
    rows: list[dict] = []
    observed: set[str] = set()

    def scenario(tag: str, note: str, lib: str, mats: dict, checklist: list[str],
                 authority: str | None):
        nonlocal observed
        root = _materials(tmp / ("m" + lib), **mats)
        bridge = _run_entry(tc, imp, tmp, lib, root, checklist,
                            authority=authority, verbose=verbose)
        rs = _reasons(bridge)
        observed |= rs
        rows.append({"scenario": tag, "note": note, "library": lib,
                     "reasons": sorted(rs), "authoritative_subject": bool(authority)})
        return rs

    scenario("UNRESOLVED_DOC_TYPE", "义务侧类型判不出（材料里没有「类型也判不出」的那份）",
             "PROBE1", {}, ["请提供示例科技的说明材料"], None)
    scenario("UNKNOWN_ENTITY", "该类型无材料 ⇒ 主体取不到（无权威名单）",
             "PROBE2", {}, ["请提供示例科技2024年度营业执照"], None)
    scenario("RETRIEVAL_EXHAUSTED", "候选超上限且全不可用（8 份草稿，超过上限）",
             "PROBE3", {"n": 8, "draft": True}, ["请提供示例科技2024年度审计报告"], None)
    scenario("NO_MATERIAL", "**权威主体已登记** ⇒ 主体非空，但名下只有别类材料",
             "PROBE4", {}, ["请提供示例科技2024年度营业执照"], SYNTHETIC_ENTITY)

    # ★ 反差对照：同一个库、同一份清单，**只差**「有没有登记权威主体」。
    #   没有 ⇒ UNKNOWN_ENTITY；有 ⇒ NO_MATERIAL。
    #   这一对照就是「旧机制理由被证伪」的机械证。
    root = _materials(tmp / "mPROBE5")
    contrast_without = _reasons(_run_entry(
        tc, imp, tmp, "PROBE5", root, ["请提供示例科技2024年度营业执照"],
        authority=None, verbose=verbose))
    root = _materials(tmp / "mPROBE6")
    contrast_with = _reasons(_run_entry(
        tc, imp, tmp, "PROBE6", root, ["请提供示例科技2024年度营业执照"],
        authority=SYNTHETIC_ENTITY, verbose=verbose))
    return observed, rows, {"without": contrast_without, "with": contrast_with}


def _check_unreachable(imp, repo_root: Path) -> list[dict]:
    """两项不可达态的**机械理由**核对（不是「没测到」，是有构造性理由）。"""
    out: list[dict] = []

    # ① PERMISSION_BLOCKED：两个生产 meta 生产者都不写 access / restricted。
    br = imp("cangjie_fos.services.dd_v1_bridge_service")
    import inspect
    build_meta = inspect.getsource(br.build_meta)
    scaffold = (repo_root / "tools" / "dd_v1_local_run.py").read_text(encoding="utf-8") \
        .split("def cmd_scaffold", 1)[1][:4000]
    for fn_name, body in (("build_meta", build_meta), ("cmd_scaffold", scaffold)):
        clean = '"access"' not in body and '"restricted"' not in body
        out.append({"state": "PERMISSION_BLOCKED", "check": f"{fn_name} 不写 access/restricted",
                    "passed": clean})
        if not clean:
            raise AssertionError(f"{fn_name} 疑似写了 access/restricted ⇒ 已知缺口已变化")

    # ② OTHER：生产路径在 local_material_snapshot 先校验文件存在 ⇒ read_errors 恒 0。
    sem = imp("cangjie_fos.services.dd_v1_semantic_retrieval_service")
    with tempfile.TemporaryDirectory() as td:
        meta = [{"file_id": "S9", "relative_path": "missing.txt", "entity": "X", "period": "2024"}]
        try:
            sem.local_material_snapshot(Path(td), meta, allow_real=True)
            raised = "NONE"
        except FileNotFoundError:
            raised = "FileNotFoundError"
        except Exception as exc:  # noqa: BLE001
            raised = type(exc).__name__
    out.append({"state": "OTHER",
                "check": "local_material_snapshot 对缺文件抛 FileNotFoundError",
                "passed": raised == "FileNotFoundError"})
    if raised != "FileNotFoundError":
        raise AssertionError(f"缺文件时抛的是 {raised} ⇒ 兜底分支的可达性已变化")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="dd_v1_six_state_reachability_probe",
        description="六态（候选为空的原因）生产路径可达性探针：实测并自证 4/6 口径")
    ap.add_argument("--repo-root", type=Path, default=ROOT, help="仓根目录（默认取本文件的上级）")
    ap.add_argument("--json", action="store_true", help="只打印 JSON 摘要")
    ap.add_argument("--verbose", action="store_true", help="同时打印薄入口的原始输出")
    a = ap.parse_args(argv)

    repo_root = a.repo_root.resolve()
    if not (repo_root / "tools" / "dd_team_channel.py").is_file():
        print(f"[错误] 不是仓根目录：{repo_root}", file=sys.stderr)
        return 2
    imp, stubbed = _bootstrap(repo_root)
    try:
        tc = imp("dd_team_channel")
        sem = imp("cangjie_fos.services.dd_v1_semantic_retrieval_service")
    except Exception as exc:  # noqa: BLE001
        print(f"[错误] 生产模块装不进来：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    six = tuple(sem.NO_CANDIDATE_REASONS)
    expected = set(EXPECTED_REACHABLE)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        observed, rows, contrast = _measure(tc, imp, tmp, a.verbose)
        unreachable_checks = _check_unreachable(imp, repo_root)

    missing = sorted(expected - observed)
    extra = sorted(observed - expected)
    contrast_ok = (contrast["without"] == {"UNKNOWN_ENTITY"}
                   and contrast["with"] == {"NO_MATERIAL"})
    ok = (not missing) and (not extra) and (len(observed) == 4) and contrast_ok

    summary = {
        "caliber": "4/6",
        "reachable_expected": sorted(expected),
        "reachable_measured": sorted(observed),
        "reachable_count": len(observed),
        "six_states": list(six),
        "unreachable_expected": sorted(UNREACHABLE_REASONS),
        "unreachable_checks": unreachable_checks,
        "missing": missing,
        "extra": extra,
        "contrast_without_authority": sorted(contrast["without"]),
        "contrast_with_authority": sorted(contrast["with"]),
        "contrast_ok": contrast_ok,
        "stubbed_package_import": stubbed,
        "verdict": "OK" if ok else "MISMATCH",
    }

    if a.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("六态生产路径可达性探针（FOS #71 考生2 P0）")
        print(f"  权威枚举（6 态）：{', '.join(six)}")
        print("  逐场景读数：")
        for r in rows:
            print(f"    · {r['scenario']:<22} {r['note']}")
            print(f"      权威主体已登记：{r['authoritative_subject']}｜实测原因：{r['reasons']}")
        print("  反差对照（同一库、同一清单，只差「有没有登记权威主体」）：")
        print(f"    · 没登记 ⇒ {summary['contrast_without_authority']}")
        print(f"    · 已登记 ⇒ {summary['contrast_with_authority']}")
        print("  不可达两态的机械理由核对：")
        for c in unreachable_checks:
            print(f"    · {c['state']:<20} {c['check']} ⇒ {'通过' if c['passed'] else '未通过'}")
        print(f"  实测可达 = {len(observed)}/6：{sorted(observed)}")
        if missing:
            print(f"  [红] 预期可达但没测到：{missing}")
        if extra:
            print(f"  [红] 预期不可达却测到了：{extra}")
        if not contrast_ok:
            print("  [红] 反差对照不成立：登记权威主体前后没出现 UNKNOWN_ENTITY → NO_MATERIAL 的翻转")
        print(f"  判定：{summary['verdict']}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
