#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MINOR-4 fixture 豁免闸口 · 独立复现探针 v2（监工第 38 条①）。

★ v2 修了 v1 的两个探针 bug（**都不是产品缺陷**）：
  ① v1 把 items.json 写到 `.../fixtures/` 而 CLI 读 `.../dd_v1_fos71/` ⇒ A 案 rc=1（假失败）；
  ② v1 没传 `--blind-leak-words` ⇒ `blind_material` 先抛 BLIND_NO_LEAK_WORDS ⇒
     B/B' 的 rc=1 发生在**闸口之前** ⇒ **B/B' 读数无效**（闸口根本没被走到）。
  ★ 教训照抄进纪律：探针自身报错时**不得**据此判主张成立/不成立。

★ 主张（待独立复现）：
  `tools/dd_v1_local_run.py` 的 fixture 豁免写成
      fixture = (sem._inside(orig_material_root, ROOT/"backend"/"tests"/"fixtures")
                 or sem._inside(material_root,      ROOT/"backend"/"tests"/"fixtures"))
  而 `material_root` 在 `_prepare_material()` 之后 = **盲化/冻结后的输出路径**
  ⇒ 闸口从「输入是不是真材料」退化成「输出落在哪」
  ⇒ 仓外真实材料 + 输出落仓内 fixtures ⇒ 闸口不触发 ⇒ **被放行**，
     且**仓外材料的盲化副本被写进仓内**（公开仓泄漏面）。

★ 四组对照（全部在**会话工作区的仓副本**上跑；副本的 ROOT 由副本位置决定 ⇒ 自洽）：
  A   仓内合成 fixture（正常流程）          ⇒ 期望：正常放行（rc 0）
  C   仓外材料 + 不盲化                     ⇒ 期望：拒绝（rc 3 + BLOCKED: 真实材料）
  B   仓外材料 + --blind-material-out 落**仓内** fixtures ⇒ 期望：拒绝（rc 3）
  B'  同 B，但豁免只按**原始材料根**（勘误前口径）       ⇒ 期望：拒绝（rc 3）
  ★ 污染面：仓外材料正文（PROBE-MARKER-7F3A）是否被写进仓副本。

★ 纪律：
  - 不碰任何真实工作树；全部在**会话工作区**的副本上跑。
  - 仓外材料用**自造合成内容**（零真实客户标识），只验证闸口行为。
  - 自证：记录被测 `tools/dd_v1_local_run.py` 的 sha256 + 副本路径 + 源树 commit。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MARKER = "PROBE-MARKER-7F3A"
LEAK_WORDS = "某外部机构"
#: A4 合成 fixture 自带泄漏词表（与 backend/tests/test_dd_v1_blind.py 一致）
A4_LEAK_WORDS = "Q-2024-07,案例甲机构,案例乙机构,星海项目"
OUTSIDE_MATERIAL = f"外部材料正文（合成探针用） {LEAK_WORDS} 2024 年度审计报告 金额 999 万元。{MARKER}"
OUTSIDE_ITEMS = json.dumps(
    [{"item_id": "1", "entity": "某外部机构", "text": "请提供2024年度审计报告"}],
    ensure_ascii=False)
OUTSIDE_META = json.dumps(
    [{"file_id": "X001", "relative_path": "audit_2024.txt",
      "entity": "某外部机构", "period": "2024", "doc_type": "审计报告"}],
    ensure_ascii=False)


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git_head(tree: Path) -> str:
    p = subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"],
                       capture_output=True, text=True)
    return p.stdout.strip() or "UNKNOWN"


def force_rmtree(path: Path) -> None:
    """清理工作目录：先放开只读权限（冻结快照是 0555）再删，否则 PermissionError。"""
    if not path.exists():
        return
    for p in path.rglob("*"):
        try:
            os.chmod(p, 0o755 if p.is_dir() else 0o644)
        except OSError:
            pass
    try:
        os.chmod(path, 0o755)
    except OSError:
        pass
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        shutil.rmtree(path)


def make_repo_copy(tree: Path, dst: Path) -> Path:
    """复制被测树的 tools/ + backend/src/ + A4 合成 fixture 到副本；副本 ROOT = 副本位置。"""
    repo = dst / "repo"
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    shutil.copytree(tree / "tools", repo / "tools",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(tree / "backend" / "src", repo / "backend" / "src",
                    ignore=shutil.ignore_patterns("__pycache__"))
    fx_src = tree / "backend" / "tests" / "fixtures" / "dd-v1-fos71-a4"
    fx_dst = repo / "backend" / "tests" / "fixtures" / "dd-v1-fos71-a4"
    # ★ 只抄必要子目录：仓内 fixture 的 frozen/ 是只读交付物（0555）⇒ 抄进来删不掉
    fx_dst.mkdir(parents=True)
    shutil.copytree(fx_src / "material", fx_dst / "material")
    shutil.copytree(fx_src / "replies", fx_dst / "replies")
    shutil.copy2(fx_src / "raw_items.json", fx_dst / "raw_items.json")
    return repo


def run_case(repo: Path, material_root: Path, items: Path, meta: Path,
             out: Path, extra: list[str], python: str) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo / "backend" / "src")
    for k in ("http_proxy", "https_proxy", "all_proxy",
              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env.pop(k, None)
    cmd = [python, str(repo / "tools" / "dd_v1_local_run.py"), "run",
           "--material-root", str(material_root),
           "--meta", str(meta),
           "--items", str(items),
           "--out", str(out)]
    cmd += extra
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(repo))
    err = p.stdout + p.stderr
    # ★ 区分「被材料安全闸口拒绝」与「因无关原因退出 3」：
    #   修前 B 案正是后者（拒绝语 = 「DeepSeek Harness 需要显式 --allow-local-dsh」）
    #   ⇒ 只看 rc 会把「真放行」误判成「已拒绝」。
    gate_blocked = "BLOCKED: 真实材料" in err       # 真实材料闸口（fixture 豁免）
    write_blocked = "不得写入仓库目录" in err       # 写入门（仓外材料副本不得进仓）
    return {
        "rc": p.returncode,
        "gate_blocked": gate_blocked,
        "write_blocked": write_blocked,
        "refused": gate_blocked or write_blocked,
        "cmd": " ".join(cmd),
        "err_tail": err[-600:],
    }


def patch_fixture_only_original(repo: Path) -> bool:
    """把豁免改回「只看原始材料根」（= 勘误前口径）⇒ 验证绕过确由 `or` 引入。"""
    p = repo / "tools" / "dd_v1_local_run.py"
    text = p.read_text(encoding="utf-8")
    old = ('    fixture = (sem._inside(orig_material_root, ROOT / "backend" / "tests" / "fixtures")\n'
           '               or sem._inside(material_root, ROOT / "backend" / "tests" / "fixtures"))')
    new = '    fixture = sem._inside(orig_material_root, ROOT / "backend" / "tests" / "fixtures")'
    if text.count(old) != 1:
        return False
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def outside_case(root: Path, tag: str) -> tuple[Path, Path, Path]:
    """仓外材料：材料根 + meta（**必须在材料根内**：blind_material 要求）+ items（根外）。"""
    case = root / tag
    mat = case / "materials"
    mat.mkdir(parents=True, exist_ok=True)
    (mat / "audit_2024.txt").write_text(OUTSIDE_MATERIAL, encoding="utf-8")
    (mat / "meta.json").write_text(OUTSIDE_META, encoding="utf-8")
    items = case / "items.json"
    items.write_text(OUTSIDE_ITEMS, encoding="utf-8")
    return mat, items, mat / "meta.json"


def scan_marker(root: Path) -> list[str]:
    hits = []
    for p in root.rglob("*"):
        if p.is_file():
            try:
                if MARKER in p.read_text(encoding="utf-8", errors="ignore"):
                    hits.append(str(p.relative_to(root)))
            except Exception:
                pass
    return hits


def default_tree() -> Path:
    """默认被测仓 = 本脚本所在仓的根（git rev-parse）；不在仓内则必须显式 --tree。"""
    p = subprocess.run(["git", "-C", str(Path(__file__).resolve().parent), "rev-parse",
                        "--show-toplevel"], capture_output=True, text=True)
    out = p.stdout.strip()
    return Path(out).resolve() if out else Path.cwd().resolve()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", default=None,
                    help="被测仓根（含 tools/）；默认 = 本脚本所在仓的根")
    ap.add_argument("--work-dir", default=None,
                    help="探针工作目录（副本落点）；默认 = 临时目录下的 dd-v1-minor4-probe")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    tree = Path(args.tree).resolve() if args.tree else default_tree()
    work = (Path(args.work_dir).resolve() if args.work_dir
            else Path(tempfile.gettempdir()) / "dd-v1-minor4-probe")
    force_rmtree(work)
    work.mkdir(parents=True)

    src_local_run = tree / "tools" / "dd_v1_local_run.py"
    results: dict = {}
    fingerprints = {
        "tree": str(tree),
        "tree_head": git_head(tree),
        "source_local_run_sha256": sha256(src_local_run),
        "work_dir": str(work),
        "python": args.python,
    }

    # ---------- A：仓内合成 fixture（正常流程）----------
    repo_a = make_repo_copy(tree, work / "A_inside")
    mat_a = repo_a / "backend" / "tests" / "fixtures" / "dd-v1-fos71-a4" / "material"
    items_a = repo_a / "backend" / "tests" / "fixtures" / "dd-v1-fos71-a4" / "raw_items.json"
    meta_a = mat_a / "meta.json"
    extra_a = ["--adapter", "manual", "--synthetic-replies",
               str(repo_a / "backend" / "tests" / "fixtures" / "dd-v1-fos71-a4" / "replies"),
               "--blind-leak-words", A4_LEAK_WORDS,
               "--blind-material-out", str(work / "A_inside" / "blind"),
               "--blind-mapping-out", str(work / "A_inside" / "map.json")]
    if not mat_a.is_dir():
        results["A_inside_fixture"] = {"rc": -1, "blocked": False,
                                       "err_tail": f"MATERIAL_FIXTURE_MISSING:{mat_a}"}
    else:
        results["A_inside_fixture"] = run_case(
            repo_a, mat_a, items_a, meta_a, work / "A_inside" / "out", extra_a, args.python)
    results["_A_repo_pollution"] = scan_marker(repo_a)

    # ---------- C：仓外材料 + 不盲化 ----------
    repo_c = make_repo_copy(tree, work / "C_outside")
    mat_c, items_c, meta_c = outside_case(work / "C_outside", "materials")
    results["C_outside_plain"] = run_case(
        repo_c, mat_c, items_c, meta_c, work / "C_outside" / "out", [], args.python)
    results["_C_repo_pollution"] = scan_marker(repo_c)

    # ---------- B：仓外材料 + --blind-material-out 落**仓内** fixtures ----------
    repo_b = make_repo_copy(tree, work / "B_outside_blind_into_repo")
    mat_b, items_b, meta_b = outside_case(work / "B_outside_blind_into_repo", "materials")
    blind_into = repo_b / "backend" / "tests" / "fixtures" / "probe-evilcase" / "blind"
    results["B_outside_blind_into_repo"] = run_case(
        repo_b, mat_b, items_b, meta_b, work / "B_outside_blind_into_repo" / "out",
        ["--blind-material-out", str(blind_into),
         "--blind-leak-words", LEAK_WORDS,
         "--blind-mapping-out", str(work / "B_outside_blind_into_repo" / "map.json")],
        args.python)
    results["_B_repo_pollution"] = scan_marker(repo_b)

    # ---------- B'：同 B，但豁免只按原始材料根（勘误前口径）----------
    repo_b2 = make_repo_copy(tree, work / "Bprime_original_only")
    patched = patch_fixture_only_original(repo_b2)
    mat_b2, items_b2, meta_b2 = outside_case(work / "Bprime_original_only", "materials")
    blind_into2 = repo_b2 / "backend" / "tests" / "fixtures" / "probe-evilcase" / "blind"
    r_b2 = run_case(
        repo_b2, mat_b2, items_b2, meta_b2, work / "Bprime_original_only" / "out",
        ["--blind-material-out", str(blind_into2),
         "--blind-leak-words", LEAK_WORDS,
         "--blind-mapping-out", str(work / "Bprime_original_only" / "map.json")],
        args.python)
    r_b2["patched_to_original_only"] = patched
    if not patched:
        r_b2["note"] = ("修后树：旧文本不存在 ⇒ B' 补丁不适用 ⇒ 本组与 B 同源"
                        "（修后 B 与 B' 都必须被拒绝）")
    results["Bprime_original_only"] = r_b2
    results["_Bprime_repo_pollution"] = scan_marker(repo_b2)

    # ---------- 汇总 ----------
    label = args.label or f"{tree.name}@{fingerprints['tree_head'][:7]}"
    print("=" * 78)
    print(f"MINOR-4 fixture 豁免闸口 · 独立复现探针 v2   —— {label}")
    print("=" * 78)
    print(f"被测 tools/dd_v1_local_run.py sha256 = {fingerprints['source_local_run_sha256'][:16]}…")
    print(f"源树 = {tree} @ {fingerprints['tree_head'][:12]}")
    print()
    for name in ("A_inside_fixture", "C_outside_plain",
                 "B_outside_blind_into_repo", "Bprime_original_only"):
        r = results[name]
        if r["gate_blocked"]:
            verdict = "拒绝（真实材料闸口）"
        elif r["write_blocked"]:
            verdict = "拒绝（写入门）"
        elif r["rc"] == 0:
            verdict = "放行（rc 0）"
        else:
            verdict = f"★ 无关拒绝 rc={r['rc']}（闸口**未**拦住）"
        print(f"  {name:30s} rc={r['rc']:<3} 闸口={str(r['gate_blocked']):5s} "
              f"写入门={str(r['write_blocked']):5s} ⇒ {verdict}")
    print()
    print(f"★ B 案仓内污染（仓外材料正文写进仓副本）= {results['_B_repo_pollution'] or '无'}")
    print(f"★ B' 案仓内污染                        = {results['_Bprime_repo_pollution'] or '无'}")
    print(f"★ A 案仓内污染                        = {results['_A_repo_pollution'] or '无'}")
    print(f"★ C 案仓内污染                        = {results['_C_repo_pollution'] or '无'}")

    exp = {
        "A_inside_fixture": (False, 0, True, "仓内合成 fixture 正常放行"),
        "C_outside_plain": (True, 3, True, "仓外材料必须被真实材料闸口拒绝"),
        "B_outside_blind_into_repo": (True, 3, True, "★ 输出落仓内也不得放行，且仓内零副本"),
        "Bprime_original_only": (True, 3, True, "只按原始材料根 ⇒ 拒绝且仓内零副本"),
    }
    print("-" * 78)
    print("★ 判据（期望：refused / rc / 仓内零污染；四案都必须零污染）")
    all_ok = True
    for k, (should_refuse, should_rc, should_clean, desc) in exp.items():
        r = results[k]
        clean = not results.get(f"_{k.split('_')[0]}_repo_pollution")
        ok = (r["refused"] == should_refuse and r["rc"] == should_rc and clean == should_clean)
        all_ok = all_ok and ok
        print(f"  {'PASS' if ok else 'FAIL'}  {k:30s} 期望=refused{should_refuse}/rc{should_rc}/"
              f"{'零污染' if should_clean else '—'}  实测=refused{r['refused']}/rc{r['rc']}/"
              f"{'零污染' if clean else '有污染'}   （{desc}）")
    print("-" * 78)
    b = results["B_outside_blind_into_repo"]
    b_polluted = bool(results["_B_repo_pollution"])
    if b["refused"] and not b_polluted:
        verdict = "FIXED"
        print("★ 结论：修法生效 —— B 案被材料安全闸口/写入门拒绝，且仓内零材料副本")
    elif not b["refused"]:
        verdict = "REPRODUCED"
        print("★ 结论：主张**成立** —— 仓外材料 + 输出落仓内 ⇒ 闸口未触发（放行）")
        if b_polluted:
            print(f"  ⇒ 且仓外材料正文被写进仓副本：{results['_B_repo_pollution']}")
    else:
        verdict = "PARTIAL"
        print("★ 结论：B 案被拒绝，但仓外材料副本仍被写进仓副本 ⇒ 写入门仍需收紧")
    print(f"PROBE_VERDICT={verdict}")
    print(f"CRITERIA_ALL_PASS={all_ok}")

    out_json = work / "minor4-repro.json"
    out_json.write_text(json.dumps(
        {"fingerprints": fingerprints, "results": results,
         "verdict": verdict, "criteria_all_pass": all_ok},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"证据：{out_json}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
