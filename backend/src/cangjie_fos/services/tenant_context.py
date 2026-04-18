"""租户级资料室摘要 + 错题本摘要（Phase 4 SPEC A3）。"""
from __future__ import annotations

from cangjie_fos.core.paths import ensure_pitch_coach_import_path
from cangjie_fos.services.fss_asset_scan import count_data_room_files, load_asset_index_assets


def build_asset_inventory_summary(*, tenant_id: str, max_lines: int = 24) -> str:
    assets = load_asset_index_assets()
    if not assets:
        n_files = count_data_room_files(tenant_id)
        return f"[资料室索引] asset_index.json 暂无或为空；本地资料室目录已扫描到 {n_files} 个文件。"
    lines: list[str] = []
    for a in assets[:max_lines]:
        fn = a.get("filename") or a.get("name") or "?"
        rp = a.get("relative_path") or ""
        sm = (a.get("summary") or "")[:120]
        lines.append(f"- {fn} ({rp}) :: {sm}")
    extra = len(assets) - max_lines
    tail = f"\n… 另有 {extra} 条资产未展示" if extra > 0 else ""
    return "[资料室清单摘要]\n" + "\n".join(lines) + tail


def build_executive_memory_digest(*, tenant_id: str, max_items: int = 12) -> str:
    """company_id 使用 tenant_id 对齐 Pitch_Coach 存储桶。"""
    ensure_pitch_coach_import_path()
    from memory_engine import list_all_executive_memories_for_company

    pairs = list_all_executive_memories_for_company(tenant_id)
    if not pairs:
        return "[历史错题本] 当前 tenant 下暂无 Executive Memory 记录。"
    lines: list[str] = []
    for tag, mem in pairs[:max_items]:
        raw = (mem.raw_text or "")[:160]
        cor = (mem.correction or "")[:160]
        lines.append(f"- [{tag}] 原述: {raw} → 纠正口径: {cor}")
    extra = len(pairs) - max_items
    tail = f"\n… 另有 {extra} 条未展示" if extra > 0 else ""
    return "[历史错题本 ExecutiveMemory]\n" + "\n".join(lines) + tail


def build_tenant_context_block(*, tenant_id: str) -> str:
    a = build_asset_inventory_summary(tenant_id=tenant_id)
    m = build_executive_memory_digest(tenant_id=tenant_id)
    return f"{a}\n\n{m}"


def build_episodic_memory_snippet_for_npc(*, tenant_id: str, tag: str, limit: int = 5) -> str:
    """与评估图 retrieve_memory 对齐：同一 company_id + tag 下 Top-N Executive Memory（控制 token）。"""
    ensure_pitch_coach_import_path()
    from agent_tenant import resolve_memory_company_id
    from memory_engine import load_top_executive_memories_for_prompt

    cid = resolve_memory_company_id(tenant_id)
    if not cid:
        return ""
    tg = (tag or "").strip() or "default"
    try:
        mems = load_top_executive_memories_for_prompt(cid, tg, limit=max(1, min(limit, 12)))
    except Exception:  # noqa: BLE001
        return ""
    if not mems:
        return ""
    lines: list[str] = []
    for mem in mems:
        raw = (mem.raw_text or "").strip().replace("\n", " ")[:220]
        cor = (mem.correction or "").strip().replace("\n", " ")[:220]
        lines.append(f"- raw: {raw}\n  correction: {cor}")
    return "\n".join(lines)
