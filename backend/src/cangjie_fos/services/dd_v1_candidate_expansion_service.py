"""DD-V1 候选分批扩展与停止条件 · cangjie-fos#71 / `#108` 实测 P0-3。

**问题**（`#108`）：候选上限 20 触顶，实测「已达候选上限 20，还有 **96** 份候选未看」
⇒ 结论只覆盖窗口内的 20 份，**正确答案可能根本没被检查**。

**处置原则**（不靠「取消所有上限」，那会让资源失控）：

1. **分批**：按递增的候选上限分批重跑匹配，每批都记读数；
2. **停止条件**（必须显式、可复核）：
   - ``VERDICT_STABLE`` —— 结论（verdict + 选中文件集）在相邻两批**逐位相同**
     ⇒ 结论不再依赖未看部分 ⇒ 停；
   - ``BUDGET_EXHAUSTED`` —— 到达候选总预算 ⇒ 停，**并如实报「还有多少未看」**；
   - ``STEPS_EXHAUSTED`` —— 分批用完 ⇒ 停，同样报未看数；
3. **读数必须外显**：``candidates_found``（找到多少）／``candidates_checked``（实际检查多少）
   ／``candidates_unchecked``（还有多少未看）／``stop_reason``（为什么停）。

★ 复用既有 ``dd_v1_match_service.match_obligation`` 的 ``candidate_cap`` 参数
  ⇒ **不改判定逻辑**，只改「看多少」；既有判定口径与安全闸**一字不动**。
"""
from __future__ import annotations

from typing import Any

from cangjie_fos.services import dd_v1_match_service as ms

#: 默认分批计划（候选上限逐步放大）
DEFAULT_STEPS = (20, 60, 180)
#: 停止原因（**闭枚举**）
STOP_REASONS = ("VERDICT_STABLE", "BUDGET_EXHAUSTED", "STEPS_EXHAUSTED", "SINGLE_STEP")


def _files_of(result: dict[str, Any]) -> list[str]:
    """从匹配结果里取出「被判为该义务可用」的文件集合（**逐位可比**）。"""
    out: list[str] = []
    for c in (result.get("candidates") or []):
        if isinstance(c, dict) and c.get("deliverable"):
            fid = str(c.get("file_id") or "")
            if fid:
                out.append(fid)
    if not out:
        # 老结构：没有 candidates 列表时退化为 missing_detail 里的文件名（不可比时如实退化）
        for m in (result.get("missing_detail") or []):
            out.append(str(m))
    return sorted(out)


def match_with_expansion(library_id: str, obligation_id: str, *,
                          steps: tuple[int, ...] = DEFAULT_STEPS,
                          db_path=None,
                          max_candidates: int = 180) -> dict[str, Any]:
    """分批扩展候选窗口地匹配一条义务。

    返回::

        {"verdict": ..., "files": [...],
         "attempts": [{cap, verdict, files, candidates_found, candidates_checked,
                       candidates_unchecked, truncated}],
         "stop_reason": "...", "expanded": bool,
         "candidates_found": n, "candidates_checked": n, "candidates_unchecked": n,
         "note": "..."}
    """
    plan = [int(c) for c in (steps or ()) if int(c) > 0] or [int(ms.DEFAULT_CANDIDATE_CAP)]
    attempts: list[dict[str, Any]] = []
    prev_sig: tuple[str, tuple[str, ...]] | None = None
    stop_reason = "STEPS_EXHAUSTED"
    last: dict[str, Any] = {}

    for cap in plan:
        res = ms.match_obligation(library_id, obligation_id, candidate_cap=cap, db_path=db_path)
        last = res
        files = _files_of(res)
        found = int(res.get("candidate_count") or 0)
        checked = found
        unchecked = int(res.get("truncated_candidate_count") or 0)
        attempts.append({
            "cap": cap,
            "verdict": str(res.get("verdict") or ""),
            "files": files,
            "candidates_found": found,
            "candidates_checked": checked,
            "candidates_unchecked": unchecked,
            "truncated": bool(res.get("capped")),
            "candidate_cap_note": str(res.get("candidate_cap_note") or ""),
        })
        sig = (str(res.get("verdict") or ""), tuple(files))
        # ★ 停止条件（收紧后的口径）：「结论稳定」**且**「候选池已穷尽」。
        #   只看「结论稳定」是**巧合式停止** —— 正确答案可能排在窗口之外的第 100 份，
        #   前两批没抽到它，两批结论自然一样 ⇒ 停了就永远看不到它。
        #   ⇒ 只有**看完了整个候选池**，才敢说「结论不再依赖未看部分」。
        if prev_sig is not None and sig == prev_sig and not res.get("capped"):
            stop_reason = "VERDICT_STABLE"
            break
        prev_sig = sig
        if checked >= int(max_candidates):
            stop_reason = "BUDGET_EXHAUSTED"
            break
    else:
        stop_reason = "STEPS_EXHAUSTED"
    if len(plan) == 1 and stop_reason == "STEPS_EXHAUSTED":
        stop_reason = "SINGLE_STEP"

    final = attempts[-1] if attempts else {}
    # ★ 读数报**停止那一刻**的真实值（不是各批的 max）：
    #   最后一批没看完 ⇒ 「还有 N 份未看」必须如实是 N。
    found = int(final.get("candidates_found") or 0)
    checked = int(final.get("candidates_checked") or 0)
    unchecked = int(final.get("candidates_unchecked") or 0)
    note = ""
    if unchecked:
        note = (f"已检查 {checked} 份，还有 {unchecked} 份候选未看；"
                f"停止原因：{stop_reason} ⇒ 结论只覆盖已检查部分，"
                "未看部分**不得**当作「不存在」")
    else:
        note = f"候选池已穷尽（检查 {checked} 份），停止原因：{stop_reason}"
    return {
        "obligation_id": obligation_id,
        "verdict": str(final.get("verdict") or (last.get("verdict") if last else "")),
        "files": list(final.get("files") or []),
        "attempts": attempts,
        "expanded": len(attempts) > 1,
        "stop_reason": stop_reason,
        "candidates_found": found,
        "candidates_checked": checked,
        "candidates_unchecked": unchecked,
        "note": note,
        "raw": last,
    }
