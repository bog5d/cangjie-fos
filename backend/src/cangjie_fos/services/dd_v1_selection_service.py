"""DD-V1 精确选中规则（G-A3-2 · A3）。

## 要治的病

旧行为：``dd_v1_package_service.package_approved`` 对每条义务的**每个**
deliverable 候选都 ``shutil.copy2`` ⇒ 交付包里**顺带装进了同类型的无关材料**。
「多一份」比「少一份」更难被发现——收件人不会去数目录。

## 新口径

    交付集合 = 每条义务**被选中的那几份主件** + **明确列出的必备附件**

★ 候选池里其余材料**一律不复制**，但**必须留痕**
  （进「未选用」清单，逐条写明**为什么没选**）——
  「不交」是决定，「不解释」是失职。

## 选中规则（**确定性可复现**）

同一输入 ⇒ 同一集合。排序键（依次比较）：

    1. 四维命中分 ``score`` 降序（判定层给的 entity/period/doctype/seal 命中率）
    2. 主体命中 ``entity_ok`` 降序
    3. 期间命中 ``period_ok`` 降序
    4. 类型命中 ``doctype_ok`` 降序
    5. ``file_id`` **升序**（最后的稳定化，保证同分同序、可逐字复现）

选中**几份**由份数权威决定（A3-1 的三态）：

| ``expected_count`` | 选中份数 | 理由 |
|---|---|---|
| ``N > 0`` | N（不足则取全部可交付） | 清单规定了权威份数 |
| ``0``（未规定） | 1 | ★ **去冗余**原则：一条义务只交一份主件；这不是「认定应有 1 份」 |
| ``None``（不可判定） | 0 | ★ **不得默认 1 份**：要几份不知道 ⇒ 不擅自交付，列入待人工确认 |

## 附件

必备附件**只认**认知卡 ``fields.related_files`` 里**显式列出**的文件
（与判定层 ``dd_v1_match_service`` 的附件识别同源），
不靠文件名相似度猜——猜出来的附件是事故。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: 未规定份数时的去冗余份数（**不是**「认定应有 1 份」）
DEFAULT_PRIMARY_COUNT = 1


def _sort_key(c: dict) -> tuple:
    """确定性排序键。★ 最后一列必须是 ``file_id``，保证同分同序。"""
    return (
        -float(c.get("score") or 0.0),
        -int(c.get("entity_ok") or 0),
        -int(c.get("period_ok") or 0),
        -int(c.get("doctype_ok") or 0),
        str(c.get("file_id") or ""),
    )


def _why_selected(c: dict, rank: int) -> str:
    """写清「为什么选它」——必须可人工复核。"""
    return (f"选中规则第 {rank} 顺位：四维命中分 {float(c.get('score') or 0.0):.2f}"
            f"（主体{'命中' if c.get('entity_ok') else '未命中'}/"
            f"期间{'命中' if c.get('period_ok') else '未命中'}/"
            f"类型{'命中' if c.get('doctype_ok') else '未命中'}）"
            f"，同分按 file_id 升序")


def _why_not(c: dict, target: int) -> str:
    if not c.get("deliverable"):
        return "不可交付（受限/不可读/敏感等级未知/索引件），不进入交付集合"
    return (f"未进入选中集合：按确定性选中规则取前 {target} 份"
            f"（本候选排序第 {_rank_of(c)} 顺位）")


def _rank_of(c: dict) -> int:
    return int(c.get("_sel_rank") or 0)


def _is_attachment(primary: dict, cand: dict, related: dict) -> bool:
    """候选是不是主件的**显式附件**（related_files 双向引用）。"""
    p_rel = str(primary.get("card_rel_path") or primary.get("rel_path") or "")
    c_rel = str(cand.get("card_rel_path") or cand.get("rel_path") or "")
    if not p_rel or not c_rel:
        return False
    p_related = {str(x) for x in (related.get(str(primary.get("file_id"))) or [])}
    c_related = {str(x) for x in (related.get(str(cand.get("file_id"))) or [])}
    return c_rel in p_related or p_rel in c_related


def target_count(obl: dict) -> tuple[int, str]:
    """该义务要交几份主件。返回 ``(份数, 理由)``。"""
    # ★ 「键不存在」= 义务**早于份数维度**（旧库/旧数据）⇒ 按「未规定」处理；
    #   「键存在但值为 None」= 提及了份数但解析不出 ⇒ 不擅自交付。
    raw = obl.get("expected_count", 0)
    if raw is None:
        return 0, ("份数不可判定：清单提及份数但无法解析出权威份数，"
                   "不擅自交付（不得默认 1 份），列入待人工确认")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return DEFAULT_PRIMARY_COUNT, (
            "清单未规定份数：按去冗余原则只交 1 份主件"
            "（这是交付集合规则，不是「认定应有 1 份」）")
    return n, f"清单规定应有 {n} 份：按份数取 {n} 份主件"


def select_for_obligation(
    obl: dict,
    candidates: list[dict],
    related: dict | None = None,
) -> dict:
    """给一条义务选出**要交的那几份**。

    ``candidates``：判定层候选（``list_matches`` 的行），每项含
    ``file_id / card_rel_path / score / deliverable / entity_ok / period_ok /
    doctype_ok / evidence``。
    ``related``：``file_id → related_files 相对路径列表``（用于识别显式附件）。

    返回::

        {
          "selected":      [{file_id, rel_path, reason, role}],
          "unselected":    [{file_id, rel_path, reason}],
          "target":        份数,
          "target_reason": 份数理由,
          "expected_count": 权威份数（None/0/N）,
          "count_pending": 份数是否待人工确认,
          "rule":          选中规则的文字说明（写进核对表）,
        }
    """
    related = related or {}
    cands = [dict(c) for c in (candidates or [])]
    # ★ 排序后**按排序结果**取候选——否则「同分按 file_id 升序」的稳定化失效。
    ordered = sorted(cands, key=_sort_key)
    for i, c in enumerate(ordered, 1):
        c["_sel_rank"] = i

    eligible = [c for c in ordered if c.get("deliverable")]
    ineligible = [c for c in ordered if not c.get("deliverable")]

    target, target_reason = target_count(obl)
    picked: list[dict] = []
    for c in eligible[:max(target, 0)]:
        picked.append({
            "file_id": c.get("file_id") or "",
            "rel_path": c.get("card_rel_path") or c.get("rel_path") or "",
            "title": c.get("card_title") or "",
            "score": float(c.get("score") or 0.0),
            "role": "主件",
            "reason": _why_selected(c, int(c.get("_sel_rank") or 0)),
        })

    # ── 必备附件：只认 related_files 里**显式列出**的 ──────────────────────
    chosen_ids = {p["file_id"] for p in picked}
    for p in list(picked):
        for c in eligible:
            if c.get("file_id") in chosen_ids:
                continue
            if _is_attachment(p, c, related):
                chosen_ids.add(c.get("file_id") or "")
                picked.append({
                    "file_id": c.get("file_id") or "",
                    "rel_path": c.get("card_rel_path") or c.get("rel_path") or "",
                    "title": c.get("card_title") or "",
                    "score": float(c.get("score") or 0.0),
                    "role": "必备附件",
                    "reason": f"必备附件：主件「{p['rel_path']}」的 related_files 显式列出",
                })

    picked_ids = {p["file_id"] for p in picked}
    unselected = []
    for c in eligible:
        if c.get("file_id") in picked_ids:
            continue
        unselected.append({
            "file_id": c.get("file_id") or "",
            "rel_path": c.get("card_rel_path") or c.get("rel_path") or "",
            "score": float(c.get("score") or 0.0),
            "reason": _why_not(c, target),
        })
    for c in ineligible:
        unselected.append({
            "file_id": c.get("file_id") or "",
            "rel_path": c.get("card_rel_path") or c.get("rel_path") or "",
            "score": float(c.get("score") or 0.0),
            "reason": _why_not(c, target),
        })
    unselected.sort(key=lambda x: (x["rel_path"], x["file_id"]))

    return {
        "selected": picked,
        "unselected": unselected,
        "target": target,
        "target_reason": target_reason,
        "expected_count": obl.get("expected_count"),
        "count_pending": obl.get("expected_count") is None,
        "rule": ("选中规则：可交付候选按「四维命中分 → 主体命中 → 期间命中 → 类型命中 → "
                 "file_id 升序」确定性排序，取前 N 份为主件；"
                 "必备附件只认 related_files 显式列出的文件；"
                 "其余候选一律不复制并逐条留痕"),
    }
