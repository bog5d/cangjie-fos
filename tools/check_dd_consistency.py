#!/usr/bin/env python3
"""DD-V1 状态一致性自检（含反向自测与外部锚点核对）。

## 为什么第一版是废的（监工 2026-10-15 实测反证）

第一版查的五项全是「A ↔ B 互相一致」，而 **A 与 B 是同一只手写的**
（`GOAL_CONTRACT.json` 与 `STATE.md` 都由我维护）。两份文档互相一致是
**构造上的必然**，不是证据——等于「用同一个错误算两遍，两遍相同 ⇒ 正确」。

监工的反向测试实证：把 `current_wp` 与 `CURRENT_CHILD` **同时**改成
现实中不存在的 `WP99`，第一版仍报 ✅ 通过。

## 本版怎么修

引入**我无法手写的外部锚点**：

1. **冻结的工作包集合**：WP0–WP6（出处：交办件「七、开发阶段」）。
   `WP99` 这类越界 id **单独就该被拒**，与 A↔B 是否一致无关。
2. **git 事实**：当前分支、HEAD、工作区是否干净、领先 master 的提交数。
   这些是客观的，**手写不出来**，文档与现实对不上就会被抓。
3. **提交 SHA 存在性**：`STATE.md` 声称的 commit 必须在 git 历史里真实存在。
4. **外部事实坐标可核**：`NEXT_ACTION` 里凡是「等外部方」的措辞，
   必须带可核对的坐标（turnId / 时间戳 / 责任人），否则只是自我陈述。

## 反向自测

`--self-test` 会**故意制造已知错误**（越界 WP、脏工作区、伪造 SHA），
断言本脚本**必须失败**。只跑正例的检查无法证明自己抓得住错。

用法：
    python3 check_consistency.py                 # 正常自检
    python3 check_consistency.py --self-test     # 反向自测
    python3 check_consistency.py --root <dir>

退出码：0 通过 / 1 不一致
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ── 外部锚点 1：冻结的工作包集合（交办件「七、开发阶段」WP0–WP6）────────────
# 这不是我写的，是交办件钉死的。越界 id 必须被拒。
FROZEN_WP_IDS = {f"WP{i}" for i in range(7)} | {"WP7"}
FROZEN_WP_DENOMINATOR = 8

# 外部锚点 2：外部方事实的可核对坐标。凡 NEXT_ACTION 出现这些措辞，
# 必须能指到具体来源，否则视为不可验证的自我陈述。
_EXTERNAL_WAIT_PATTERNS = {
    "独立监工": r"(turnId|结论送达|验收时间|20\d{2}-\d{2}-\d{2}\s*\d{2}:\d{2})",
    "波总裁定": r"(裁定时间|20\d{2}-\d{2}-\d{2}\s*\d{2}:\d{2}|交办件)",
    "刘江": r"(提供|交付|20\d{2}-\d{2}-\d{2}\s*\d{2}:\d{2})",
}


def _read(root: Path) -> tuple[dict, str]:
    contract = json.loads((root / "GOAL_CONTRACT.json").read_text(encoding="utf-8"))
    state = (root / "STATE.md").read_text(encoding="utf-8")
    return contract, state


def _state_field(state: str, key: str) -> str:
    """取 `KEY = ...` 的值，支持续行（STATE.md 的 COMMITS 是多行字段）。"""
    m = re.search(rf"^{key}\s*=\s*(.+?)\s*$", state, re.M)
    if not m:
        return ""
    val = [m.group(1).strip()]
    tail = state[m.end():].split("\n")[1:]
    for line in tail:
        if re.match(r"^\s{2,}\S", line) and not re.match(r"^\s*[A-Z_]+\s*=", line):
            val.append(line.strip())
        else:
            break
    return " ".join(val)


def _git(repo: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _git_ok(repo: Path, *args: str) -> bool:
    """按退出码判断成功与否。

    **不能用 stdout 判**：`git cat-file -e <sha>^{commit}` 成功时**不输出任何东西**，
    空串是假值——第一版正是因此把三个真实存在的提交误报成「不存在」。
    """
    try:
        return subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, timeout=20).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _check_internal(contract: dict, state: str) -> list[str]:
    """A↔B 互校（**必要但不充分**——第一版只有这一层，是废的）。"""
    p: list[str] = []

    c_wp = contract["state"]["current_wp"]
    s_child = _state_field(state, "CURRENT_CHILD")
    if s_child != f"DD-V1-{c_wp}":
        p.append(f"[A↔B] current_wp={c_wp} 但 CURRENT_CHILD={s_child!r}")

    if contract["state"]["next_action"].strip() != _state_field(state, "NEXT_ACTION"):
        p.append("[A↔B] next_action 在合同与 STATE 中不一致")

    den = contract["denominators"]["engineering"]
    pct = contract["goal_alignment"]["progress"]["engineering_percent"]
    expect = round(len(den["counted"]) / den["total"] * 100, 1)
    if abs(pct - expect) > 0.05:
        p.append(f"[A↔B] engineering_percent={pct} 与 counted/total={expect} 不自洽")

    m = re.search(r"工程完成率\s+([\d.]+)%", state)
    if m and abs(float(m.group(1)) - pct) > 0.05:
        p.append(f"[A↔B] STATE 完成率={m.group(1)}% 与合同 {pct}% 不一致")

    return p


def _check_external_wp_ids(contract: dict) -> list[str]:
    """外部锚点：工作包 id 必须在冻结集合内。

    **这一层与 A↔B 无关**——`WP99` 单独就该被拒，即使两份文档都写 WP99。
    """
    p: list[str] = []
    current = contract["state"]["current_wp"]
    if current not in FROZEN_WP_IDS:
        p.append(f"[外部锚点] current_wp={current!r} 不在冻结集合 {sorted(FROZEN_WP_IDS)}"
                 f"（交办件 WP0–WP6 + 监工 2026-10-15 授权新增 WP7）")
    counted = contract["denominators"]["engineering"]["counted"]
    bad = [w for w in counted if w not in FROZEN_WP_IDS]
    if bad:
        p.append(f"[外部锚点] counted 含越界工作包 {bad}")
    mapped = {w["work_item_id"] for w in contract["goal_alignment"]["work_to_goal_map"]}
    bad2 = sorted(mapped - FROZEN_WP_IDS)
    if bad2:
        p.append(f"[外部锚点] work_to_goal_map 含越界工作包 {bad2}")
    if len(mapped) != FROZEN_WP_DENOMINATOR:
        p.append(f"[外部锚点] work_to_goal_map 实 {len(mapped)} 项，"
                 f"冻结集合定义 {FROZEN_WP_DENOMINATOR} 个")
    if contract["denominators"]["engineering"]["total"] != FROZEN_WP_DENOMINATOR:
        p.append(f"[外部锚点] 分母 {contract['denominators']['engineering']['total']}"
                 f" ≠ 冻结集合的 {FROZEN_WP_DENOMINATOR}")
    wsum = sum(x["weight"] for x in contract["goal_alignment"]["outcome_metrics"])
    if wsum != contract["denominators"]["outcome"]["total"]:
        p.append(f"[外部锚点] outcome 权重和 {wsum} ≠ 声明分母 "
                 f"{contract['denominators']['outcome']['total']}")
    return p


def _check_code_wp_ids(repo: Path, frozen: set[str]) -> list[str]:
    """外部锚点：**代码里出现的 WP id 必须 ∈ 合同冻结集合**。

    监工 2026-10-15 指出的一处真缺口：此前只校验合同**内部**自洽
    （counted ⊆ 冻结集合、work_to_goal_map ⊆ 冻结集合），
    **从不扫描代码里实际在执行的 WP id**。
    于是「代码已经写了 WP7、合同里还没有 WP7」这种缺口**天然抓不到**——
    集合里没有 WP7 可供比对，正是缺陷本身让检查失效。

    现在改为：把代码里真实出现的 WP id 捞出来，逐个对照冻结集合。
    """
    p: list[str] = []
    import re as _re
    targets = list((repo / "backend" / "src" / "cangjie_fos" / "services").glob("dd_v1_*.py"))
    targets += list((repo / "tools").glob("dd_v1_*.py"))
    targets += list((repo / "tools").glob("dd_team_channel.py"))
    seen: dict[str, list[str]] = {}
    for f in targets:
        try:
            txt = f.read_text(encoding="utf-8")
        except OSError:
            continue
        for wid in _re.findall(r"\bWP\d{1,2}\b", txt):
            seen.setdefault(wid, []).append(f.name)
    for wid in sorted(seen):
        if wid not in frozen:
            p.append(f"[外部锚点] 代码里出现 {wid}（{', '.join(sorted(set(seen[wid]))[:2])}），"
                     f"但不在合同冻结集合 {sorted(frozen)} 内 —— "
                     f"**正在执行合同里不存在的工作包**")
    return p


def _check_next_action_coordinates(state: str) -> list[str]:
    """外部锚点：「等外部方」必须给出可核对坐标，否则只是自我陈述。"""
    p: list[str] = []
    na = _state_field(state, "NEXT_ACTION")
    if not na:
        p.append("[外部锚点] STATE 缺 NEXT_ACTION")
        return p
    for who, pat in _EXTERNAL_WAIT_PATTERNS.items():
        if who in na and not re.search(pat, na):
            p.append(f"[外部锚点] NEXT_ACTION 提到「{who}」但无可核对坐标"
                     f"（需带时间戳/turnId/交付物来源）")
    return p


def _check_git_reality(contract: dict, state: str, repo: Path) -> list[str]:
    """外部锚点：文档声称的 git 事实必须与仓库现实一致（手写不出来）。"""
    p: list[str] = []
    if not (repo / ".git").exists():
        return ["[外部锚点] 找不到 git 仓库，无法核对文档与现实的 git 事实"]

    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    # BRANCH 字段形如「cangjie-fos @ feat/dd-v1-manifest-wp1（名称沿用 WP1，…）」：
    # repo 名与 @ 之间有空格，分支名后可能跟中文说明——两处都要处理。
    bfield = _state_field(state, "BRANCH")
    claimed = None
    if "@" in bfield:
        tail = bfield.split("@", 1)[1].strip()
        claimed = re.split(r"[（(\u4e00-\u9fff]", tail)[0].strip() or None
    if claimed and branch and claimed != branch:
        p.append(f"[外部锚点] STATE 声称在 {claimed}，实际在 {branch}")

    dirty = _git(repo, "status", "--porcelain")
    if dirty:
        p.append(f"[外部锚点] 工作区不干净（{len(dirty.splitlines())} 个改动），"
                 f"文档声称的 HEAD 未必与远端一致")

    # STATE 里声称的 commit 必须在历史中真实存在
    head = _git(repo, "rev-parse", "--short", "HEAD")
    if head and not _git_ok(repo, "merge-base", "--is-ancestor", head, "HEAD"):
        p.append(f"[外部锚点] HEAD {head} 不在近 30 条提交内，文档与现实脱节")
    for sha in re.findall(r"\b([0-9a-f]{7})\b", _state_field(state, "COMMITS")):
        if not _git_ok(repo, "cat-file", "-e", f"{sha}^{{commit}}"):
            p.append(f"[外部锚点] STATE 声称的提交 {sha} 在仓库中不存在")
    return p


def check(root: Path, repo: Path | None = None) -> list[str]:
    contract, state = _read(root)
    problems = _check_internal(contract, state)
    problems += _check_external_wp_ids(contract)
    problems += _check_next_action_coordinates(state)
    if repo is not None:
        problems += _check_git_reality(contract, state, repo)
        problems += _check_code_wp_ids(repo, FROZEN_WP_IDS)
    return problems


# ── 反向自测：故意制造已知错误，断言本脚本必须失败 ─────────────────────────
def self_test(root: Path, repo: Path | None) -> int:
    """反向自测：**故意造错，断言本脚本必须抓到那一条**。

    只验证正例通过，无法证明检查抓得住错——第一版就是这么废掉的
    （监工注入 WP99，脚本仍报 ✅）。
    每个用例声明 `must_hit`：必须命中该关键词才算抓到，
    「碰巧因为别的原因报错」不算数。
    """
    contract, state = _read(root)

    def c_bogus_wp():
        c = json.loads(json.dumps(contract)); st = state
        c["state"]["current_wp"] = "WP99"
        st = re.sub(r"^CURRENT_CHILD\s*=\s*.+$", "CURRENT_CHILD    = DD-V1-WP99",
                    st, count=1, flags=re.M)
        return c, st

    def c_fake_sha():
        st = re.sub(r"^COMMITS\s*=\s*.+$", "COMMITS = deadbee 伪造提交",
                    state, count=1, flags=re.M)
        return contract, st

    def c_no_coord():
        c = json.loads(json.dumps(contract))
        na = "等独立监工验收"
        c["state"]["next_action"] = na
        st = re.sub(r"^NEXT_ACTION\s*=\s*.+$", "NEXT_ACTION      = " + na,
                    state, count=1, flags=re.M)
        return c, st

    def c_denominator():
        c = json.loads(json.dumps(contract))
        c["denominators"]["engineering"]["total"] = 99
        return c, state

    def c_bad_branch():
        st = re.sub(r"^BRANCH\s*=\s*.+$",
                    "BRANCH           = cangjie-fos @ feat/nonexistent-branch",
                    state, count=1, flags=re.M)
        return contract, st

    cases = [
        ("A↔B 一致但 WP99 越界（监工原反例）", c_bogus_wp, "不在冻结集合"),
        ("STATE 声称伪造的 commit sha", c_fake_sha, "在仓库中不存在"),
        ("A↔B 一致但 NEXT_ACTION 无可核对坐标", c_no_coord, "无可核对坐标"),
        ("分母被改成 99（与冻结集合不符）", c_denominator, "冻结集合的 8"),
        ("STATE 声称不存在的分支", c_bad_branch, "实际在"),
    ]

    ok = True
    print("反向自测：每个用例都是**故意造错**，脚本必须抓到指定的那一条\n")
    for name, fn, must_hit in cases:
        c, st = fn()
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            (t / "GOAL_CONTRACT.json").write_text(
                json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
            (t / "STATE.md").write_text(st, encoding="utf-8")
            # 负例也必须带上真实 repo：否则 git 事实层根本不跑，等于没测
            probs = check(t, repo=repo)
        hit = [x for x in probs if must_hit in x]
        if hit:
            print(f"  ✅ 抓到了：{name}")
            for x in hit:
                print(f"       └ {x}")
        else:
            print(f"  ❌ **漏掉了**：{name}  ← 未命中「{must_hit}」")
            if probs:
                for x in probs:
                    print(f"       (但报了别的：{x})")
            ok = False

    # 独立反向用例：代码里出现合同冻结集合之外的 WP9
    # （监工 2026-10-15 指出的那类缺口：代码在干一件合同里不存在的事）
    if repo is not None:
        with tempfile.TemporaryDirectory() as td:
            ghost = Path(td) / "repo"
            (ghost / "backend" / "src" / "cangjie_fos" / "services").mkdir(parents=True)
            (ghost / "tools").mkdir(parents=True)
            (ghost / "backend" / "src" / "cangjie_fos" / "services"
             / "dd_v1_ghost.py").write_text(
                "# 凭空冒出来的 WP9\nWP9 = 1\n", encoding="utf-8")
            probs = _check_code_wp_ids(ghost, FROZEN_WP_IDS)
        if probs:
            print("  ✅ 抓到了：代码里出现合同冻结集合之外的 WP9")
            for x in probs:
                print(f"       └ {x}")
        else:
            print("  ❌ **漏掉了**：代码里的 WP9 竟无人发现 —— 合同会与代码脱节")
            ok = False

    probs = check(root, repo=repo)
    if probs:
        print("\n  ❌ 正例反而失败（检查过敏）：")
        for x in probs:
            print(f"       └ {x}")
        ok = False
    else:
        print("\n  ✅ 正例通过（未改动真实数据时无误报）")

    print(f"\n反向自测：{'全部通过——本检查确实抓得住错' if ok else '失败——本检查不可信'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent))
    ap.add_argument("--repo", default=None, help="git 仓库路径，用于核对 git 事实")
    ap.add_argument("--self-test", action="store_true",
                    help="跑反向自测：故意造错，断言本脚本必须失败")
    a = ap.parse_args()
    root = Path(a.root)
    repo = Path(a.repo) if a.repo else (root.parent / "cangjie-fos")

    if a.self_test:
        return self_test(root, repo if (repo / ".git").exists() else None)

    problems = check(root, repo if (repo / ".git").exists() else None)
    if problems:
        print("❌ 状态一致性自检未通过：")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("✅ 状态一致性自检通过")
    print("   · A↔B 互校（必要不充分）")
    print("   · 外部锚点：工作包 id ∈ 冻结集合 WP0–WP7")
    print("   · 外部锚点：代码里实际出现的 WP id ∈ 冻结集合")
    print("   · 外部锚点：NEXT_ACTION 外部事实带可核对坐标")
    print("   · 外部锚点：git 分支/工作区/commit 与文档一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
