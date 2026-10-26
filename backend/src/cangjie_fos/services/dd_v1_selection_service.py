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

## ★ 匹配证据闸（P0-1）：「对不上」就不该被选中

排序只决定**先后**，**不决定**「能不能选」。旧实现把「可交付」
（``deliverable``）当成唯一的入选条件 ⇒ 一份**认不出类型 / 主体 / 期间**
的材料只要「可交付」就可能被选中 ⇒ 同一份**无关**材料被反复当成
多条义务的答案（症状：组包清单 10 行指向同一份无关文件）。

现在多一道**匹配证据闸**（:func:`_match_evidence`）：候选必须在义务
**真正约束**的那些维度上**对得上**，否则它连「可选」都不是：

- **期间**：义务锚定了期间（``period_from``/``period_to``）⇒ 必须 ``period_ok``；
- **主体**：义务要求主体（判定层已算出 ``entity_ok``）⇒ 必须 ``entity_ok``；
- **类型**：义务要求类型 ⇒ 材料的**自身**类型必须落在义务要求的类型集合里
  （★ 走材料自己的类型，不是「整段的类型归属」——那是 PR #81 登记缺口 G5）。

**类型口径只有一份**：义务侧的类型集合 = 义务原文里提到的**全部**规范类型
（``rq.parse_doc_types``）∪ 义务侧的 ``doc_type``；材料侧 = 认知卡的
``doc_types`` 多值字段（``cs.doc_types_key``）。因此：

- 一段「营业执照与审计报告」⇒ 义务要**两类** ⇒ 段内可外发类材料不被连坐（G5 不回归）；
- 一份**认不出类型**的材料（认知卡 doc_type 空）⇒ 类型对不上 ⇒ **不得**靠
  「看起来像」放行。

★ 每一条选中项都带**可核的匹配证据**（:func:`_evidence_text`），
  写进组包清单 ⇒ 同一文件被 N 条义务引用时，**N 行各自带证据**。

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


# ── P0-1：匹配证据闸 ──────────────────────────────────────────────────────
def _obl_type_set(obl: dict) -> list[str]:
    """这条义务**要求哪些**材料类型（规范 key）。

    ★ 义务原文里**提到**的类型**全部**保留（G5 的同源口径）：
      一段「营业执照与审计报告」⇒ 两个类型都算这条义务要的
      ⇒ 段内**可外发类**材料不会被「整段的类型归属」连坐（G5 不回归）。
    ★ 原文提不出类型时，退回义务侧的 ``doc_type`` 单值。
    ★ 类型规则**只有一份**：走 ``dd_v1_requirement_service`` 的公开 API，
      本模块**不抄**类型表。
    """
    from cangjie_fos.services import dd_v1_requirement_service as rq  # noqa: PLC0415

    out: list[str] = []
    for t in rq.parse_doc_types(str(obl.get("raw_text") or "")):
        if t not in out:
            out.append(t)
    dt = str(obl.get("doc_type") or "").strip().lower()
    if dt and rq.doc_type_search_terms(dt) and dt not in out:
        out.append(dt)
    return out


def _period_constrained(obl: dict) -> bool:
    """义务**锚定了**期间吗？（锚定了 ⇒ 期间维度构成门槛）"""
    try:
        return bool(int(obl.get("period_from") or 0)) and bool(int(obl.get("period_to") or 0))
    except (TypeError, ValueError):
        return False


def _match_evidence(obl: dict, cand: dict, obl_types: list[str],
                     cand_types: list[str]) -> dict:
    """这条候选**对不对得上**这条义务（★ P0-1 的匹配证据闸）。

    返回 ``{"ok", "reason", "entity_ok", "period_ok", "doctype_ok",
    "evidence_text"}``。

    ★ 三条判据**各自独立**，**取其严**（任一不过 ⇒ 不是「可选」）：

    1. **主体**：义务要求了主体（判定层的 ``entity_ok`` 为 0 ⇒ 主体对不上）。
       义务**没**要求主体时判定层给 ``entity_ok=1`` ⇒ 本条自动放行（不构成门槛）。
    2. **期间**：义务锚定了期间 ⇒ 必须 ``period_ok``（期间对不上）。
    3. **类型**：义务要求了类型 ⇒ 材料的**自身**类型必须落在义务的类型集合里
       （★ 材料认不出类型 ⇒ **对不上** ⇒ 不得靠「看起来像」放行）。
    """
    ent_ok = int(cand.get("entity_ok") or 0)
    per_ok = int(cand.get("period_ok") or 0)
    doc_ok = int(cand.get("doctype_ok") or 0)
    failures: list[str] = []
    notes: list[str] = []

    # ① 主体
    if not ent_ok:
        failures.append("主体对不上（材料不属于本条义务要求的主体）")
    else:
        notes.append("主体对得上")

    # ② 期间
    if _period_constrained(obl):
        if not per_ok:
            failures.append("期间对不上（义务锚定了期间，材料期间不满足）")
        else:
            notes.append("期间对得上")
    else:
        notes.append("期间维度不构成门槛（义务未锚定期间）")

    # ③ 类型
    if obl_types:
        if doc_ok:
            notes.append(f"类型对得上（义务要求 {'/'.join(obl_types)}）")
        elif cand_types:
            hit = [t for t in cand_types if t in obl_types]
            if hit:
                notes.append(f"类型对得上（材料自身类型 {'/'.join(hit)}）")
            else:
                failures.append(
                    f"类型对不上（材料自身类型 {'/'.join(cand_types)}，"
                    f"义务要求 {'/'.join(obl_types)}）")
        else:
            failures.append("类型对不上（材料认不出类型 ⇒ 拿不到类型，不得靠「看起来像」放行）")
    else:
        # 义务**没**要求类型 ⇒ 类型维度不构成门槛；
        # 但材料**必须认得出类型**——否则「可核的类型证据」无从谈起，
        # 交付清单里那一行就只能是「看起来像」（P0-1 的反面）。
        if doc_ok or cand_types:
            notes.append("类型维度不构成门槛（义务未要求材料类型；材料类型可辨）")
        else:
            failures.append("类型对不上（义务未要求类型，但材料认不出类型 ⇒ 无可核类型证据）")

    ok = not failures
    return {
        "ok": ok,
        "reason": "；".join(failures) if failures else "；".join(notes),
        "entity_ok": ent_ok,
        "period_ok": per_ok,
        "doctype_ok": doc_ok,
        "evidence_text": _evidence_text(notes, failures, ent_ok, per_ok, doc_ok),
    }


def _evidence_text(notes: list[str], failures: list[str], ent_ok: int,
                   per_ok: int, doc_ok: int) -> str:
    """选中项的**可核匹配证据**（写进组包清单 ⇒ N 行各自带证据）。"""
    parts = [f"类型匹配={'是' if doc_ok else '否'}",
             f"主体匹配={'是' if ent_ok else '否'}",
             f"期间匹配={'是' if per_ok else '否'}"]
    parts.extend(notes)
    parts.extend(failures)
    return "；".join(parts)


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
    cand_types: dict | None = None,
) -> dict:
    """给一条义务选出**要交的那几份**。

    ``candidates``：判定层候选（``list_matches`` 的行），每项含
    ``file_id / card_rel_path / score / deliverable / entity_ok / period_ok /
    doctype_ok / evidence``。
    ``related``：``file_id → related_files 相对路径列表``（用于识别显式附件）。
    ``cand_types``：``file_id → 材料自己命中的全部规范类型``（★ P0-1 类型闸输入；
    缺省时类型闸退化为「只看判定层的 ``doctype_ok``」，向后兼容）。

    返回::

        {
          "selected":      [{file_id, rel_path, reason, role, match_evidence, ...}],
          "unselected":    [{file_id, rel_path, reason}],
          "target":        份数,
          "target_reason": 份数理由,
          "expected_count": 权威份数（None/0/N）,
          "count_pending": 份数是否待人工确认,
          "rule":          选中规则的文字说明（写进核对表）,
        }
    """
    related = related or {}
    cand_types = cand_types or {}
    cands = [dict(c) for c in (candidates or [])]
    # ★ 排序后**按排序结果**取候选——否则「同分按 file_id 升序」的稳定化失效。
    ordered = sorted(cands, key=_sort_key)
    for i, c in enumerate(ordered, 1):
        c["_sel_rank"] = i

    # ★ P0-1：匹配证据闸 —— 「对不上」的候选**连可选都不是**。
    obl_types = _obl_type_set(obl)
    ev_by_id: dict[str, dict] = {}
    eligible: list[dict] = []
    ineligible: list[dict] = []
    for c in ordered:
        ev = _match_evidence(obl, c, obl_types,
                             list(cand_types.get(c.get("file_id") or "") or []))
        ev_by_id[c.get("file_id") or ""] = ev
        if not ev["ok"]:
            ineligible.append(c)
        elif c.get("deliverable"):
            eligible.append(c)
        else:
            ineligible.append(c)

    target, target_reason = target_count(obl)
    picked: list[dict] = []
    for c in eligible[:max(target, 0)]:
        ev = ev_by_id.get(c.get("file_id") or "") or {}
        picked.append({
            "file_id": c.get("file_id") or "",
            "rel_path": c.get("card_rel_path") or c.get("rel_path") or "",
            "title": c.get("card_title") or "",
            "score": float(c.get("score") or 0.0),
            "role": "主件",
            "reason": _why_selected(c, int(c.get("_sel_rank") or 0)),
            # ★ 可核的匹配证据（类型 / 主体 / 期间对不对得上）
            "match_evidence": ev.get("evidence_text", ""),
            "entity_ok": ev.get("entity_ok", 0),
            "period_ok": ev.get("period_ok", 0),
            "doctype_ok": ev.get("doctype_ok", 0),
        })

    # ── 必备附件：只认 related_files 里**显式列出**的 ──────────────────────
    chosen_ids = {p["file_id"] for p in picked}
    for p in list(picked):
        for c in eligible:
            if c.get("file_id") in chosen_ids:
                continue
            if _is_attachment(p, c, related):
                chosen_ids.add(c.get("file_id") or "")
                ev = ev_by_id.get(c.get("file_id") or "") or {}
                picked.append({
                    "file_id": c.get("file_id") or "",
                    "rel_path": c.get("card_rel_path") or c.get("rel_path") or "",
                    "title": c.get("card_title") or "",
                    "score": float(c.get("score") or 0.0),
                    "role": "必备附件",
                    "reason": f"必备附件：主件「{p['rel_path']}」的 related_files 显式列出",
                    "match_evidence": ev.get("evidence_text", ""),
                    "entity_ok": ev.get("entity_ok", 0),
                    "period_ok": ev.get("period_ok", 0),
                    "doctype_ok": ev.get("doctype_ok", 0),
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
        ev = ev_by_id.get(c.get("file_id") or "") or {}
        if not ev.get("ok", True):
            # ★ 对不上 ⇒ 理由写清**哪一维对不上**（可复核，不是「看起来像」）
            reason = f"不进入选中集合：匹配证据闸未通过（{ev.get('reason', '')}）"
        else:
            reason = _why_not(c, target)
        unselected.append({
            "file_id": c.get("file_id") or "",
            "rel_path": c.get("card_rel_path") or c.get("rel_path") or "",
            "score": float(c.get("score") or 0.0),
            "reason": reason,
        })
    unselected.sort(key=lambda x: (x["rel_path"], x["file_id"]))

    return {
        "selected": picked,
        "unselected": unselected,
        "target": target,
        "target_reason": target_reason,
        "expected_count": obl.get("expected_count"),
        "count_pending": obl.get("expected_count") is None,
        "obligation_types": obl_types,
        "rule": ("选中规则：★ 先过**匹配证据闸**（主体/期间/类型对不对得上，"
                 "对不上 ⇒ 连可选都不是）；"
                 "再按「四维命中分 → 主体命中 → 期间命中 → 类型命中 → "
                 "file_id 升序」确定性排序，取前 N 份为主件；"
                 "必备附件只认 related_files 显式列出的文件；"
                 "其余候选一律不复制并逐条留痕"),
    }
