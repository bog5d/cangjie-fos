"""DD-V1 考场契约主体范围的应用服务 · cangjie-fos#71 / `#108` 实测 P0-1。

**问题**（`#108` 刘江 2026-10-28 Windows 实测）：

> 义务未指名主体，而本库登记了多个主体，无法判定该义务针对哪个主体；不得无门槛放行为 MATCHED

⇒ 42 题 91 条义务**全部 UNCERTAIN**、**0 件交付**。这不是「模型不够聪明」，
是**判定口径缺一条明确规则**。

**本模块做的事**：把**考场契约里的显式声明**（`SINGLE_ENTITY` / `GROUP`）
翻译成一条**可解析的主体范围**，写进那些**本来就没有指名主体**的义务上。

★ **不是**「题目没写主体 ⇒ 集团所有公司都符合要求」：
  - 名单来自**权威主体登记**（``dd_v1_entities``）＋契约里的**具体声明**；
  - 契约**没声明** ⇒ 不写任何东西 ⇒ 主体维度**仍然不可判定**（保留不确定状态）；
  - 已经**指名了主体**的义务**一律不动**（原文口径优先）。
"""
from __future__ import annotations

from typing import Any

from cangjie_fos.services import dd_v1_manifest_service as mf
from cangjie_fos.services import dd_v1_requirement_service as rq

SCOPE_SINGLE = "SINGLE_ENTITY"
SCOPE_GROUP = "GROUP"
SCOPE_UNSCOPED = "UNSCOPED"


def list_entities(library_id: str, db_path=None) -> list[dict[str, Any]]:
    """本库登记的全部权威主体。"""
    conn = mf._connect(db_path)
    rq._ensure_schema(conn)
    return [dict(r) for r in conn.execute(
        "SELECT * FROM dd_v1_entities WHERE library_id=? ORDER BY entity_id", (library_id,))]


def group_members(library_id: str, root_entity_id: str, db_path=None) -> list[dict[str, Any]]:
    """集团成员 ＝ 根 ＋ 沿 ``parent_id`` 链向下的全部后代（**按登记结构**）。"""
    rows = list_entities(library_id, db_path)
    members = rq._group_members(rows, str(root_entity_id))
    return [r for r in rows if str(r.get("entity_id") or "") in members]


def scope_keyword(scope: dict[str, Any] | None,
                  entity_ids: list[str] | None = None) -> str:
    """把契约声明翻译成 ``entity_scope`` 关键字；无法翻译 ⇒ 空串（不写任何东西）。"""
    sc = scope or {}
    mode = str(sc.get("scope_mode") or SCOPE_UNSCOPED)
    if mode == SCOPE_SINGLE:
        ids = [str(x).strip() for x in (sc.get("entity_ids") or []) if str(x).strip()]
        if len(ids) == 1:
            return f"{rq.CONTRACT_SINGLE_PREFIX}{ids[0]}"
        return ""
    if mode == SCOPE_GROUP:
        root = str(sc.get("group_root_id") or "").strip()
        if root:
            return f"{rq.CONTRACT_GROUP_PREFIX}{root}"
    return ""


def apply_contract_scope(library_id: str,
                         scope: dict[str, Any] | None,
                         *,
                         db_path=None,
                         dry_run: bool = False) -> dict[str, Any]:
    """把契约声明的主体范围应用到**未指名主体**的义务上。

    返回::

        {"applied": bool, "scope_keyword": "...", "updated": n, "skipped_named": n,
         "members": [...], "note": "..."}

    ★ 只改**没有**指名主体的义务；已经指名的一律不动（原文口径优先）。
    ★ 契约没声明 ⇒ ``applied=False``，**一条都不改**（保留「不可判定」）。
    """
    kw = scope_keyword(scope)
    conn = mf._connect(db_path)
    rq._ensure_schema(conn)
    rows = [dict(r) for r in conn.execute(
        "SELECT obligation_id, entity_scope, entity_basis, obligation FROM dd_v1_obligations "
        "WHERE library_id=?", (library_id,))]
    if not kw:
        return {"applied": False, "scope_keyword": "", "updated": 0, "skipped_named": 0,
                "members": [],
                "note": ("考场契约未声明主体范围（SINGLE_ENTITY / GROUP）⇒ "
                         "**不写任何东西** ⇒ 未指名主体的义务仍然不可判定（保留不确定状态）")}
    if scope and str(scope.get("scope_mode")) == SCOPE_GROUP:
        members = group_members(library_id, str(scope.get("group_root_id") or ""), db_path)
        member_ids = [str(m.get("entity_id") or "") for m in members]
        if not member_ids:
            return {"applied": False, "scope_keyword": kw, "updated": 0, "skipped_named": 0,
                    "members": [],
                    "note": "契约声明 GROUP 但权威主体登记里找不到该集团根 ⇒ 不写任何东西"}
    else:
        member_ids = [str(x) for x in (scope or {}).get("entity_ids") or []]

    updated = 0
    replaced = 0
    skipped = 0
    stale: list[str] = []
    for r in rows:
        named = str(r.get("entity_scope") or "").strip()
        basis = str(r.get("entity_basis") or "").strip()
        if named and basis == "CONTRACT_SCOPE":
            # ★ **上一场契约粘在库里**（独立 Reviewer 增量复核的重要发现）：
            #   契约是**按场次**的 ⇒ 换一场声明不同范围时，旧的 CONTRACT_SCOPE 行
            #   必须**可替换**，否则会静默沿用上一场的主体范围。
            if named == kw:
                skipped += 1
                continue
            replaced += 1
            stale.append(named)
            if dry_run:
                continue
            conn.execute(
                "UPDATE dd_v1_obligations SET entity_scope=?, entity_basis=? "
                "WHERE library_id=? AND obligation_id=?",
                (kw, "CONTRACT_SCOPE", library_id, r["obligation_id"]))
            continue
        if named:
            skipped += 1
            continue
        if dry_run:
            updated += 1
            continue
        conn.execute(
            "UPDATE dd_v1_obligations SET entity_scope=?, entity_basis=? "
            "WHERE library_id=? AND obligation_id=?",
            (kw, "CONTRACT_SCOPE", library_id, r["obligation_id"]))
        updated += 1
    if not dry_run:
        conn.commit()
    touched = updated + replaced
    return {
        "applied": touched > 0,
        "scope_keyword": kw,
        "updated": updated,
        "replaced": replaced,
        "stale_scopes": stale[:20],
        "skipped_named": skipped,
        "members": member_ids,
        "note": (f"已把契约声明的主体范围（{kw}）应用到 {updated} 条未指名主体的义务"
                 + (f"，并替换了 {replaced} 条**上一场**契约留下的范围" if replaced else "")
                 + f"；{skipped} 条已指名主体的义务未动"),
    }


def scope_view(library_id: str, scope: dict[str, Any] | None, db_path=None) -> dict[str, Any]:
    """主体范围的可读视图（预检报告 / 交接文档用）。"""
    ents = list_entities(library_id, db_path)
    mode = str((scope or {}).get("scope_mode") or SCOPE_UNSCOPED)
    kw = scope_keyword(scope)
    members: list[dict[str, Any]] = []
    if mode == SCOPE_GROUP and str((scope or {}).get("group_root_id") or "").strip():
        members = group_members(library_id, str((scope or {}).get("group_root_id") or ""), db_path)
    elif mode == SCOPE_SINGLE:
        ids = {str(x) for x in (scope or {}).get("entity_ids") or []}
        members = [e for e in ents if str(e.get("entity_id") or "") in ids]
    return {
        "scope_mode": mode,
        "scope_keyword": kw,
        "entities_registered": len(ents),
        "members": [{"entity_id": str(e.get("entity_id") or ""),
                     "display_name": str(e.get("display_name") or ""),
                     "relation": str(e.get("relation") or ""),
                     "is_group_root": bool(e.get("is_group_root"))}
                    for e in members],
        "declared_by": str((scope or {}).get("declared_by") or ""),
        "declared_at": str((scope or {}).get("declared_at") or ""),
    }
