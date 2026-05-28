"""NPC Chat 工具集：DeepSeek 可按需调用的查询工具。

阶段一（当前）：仅绑定 get_institution_detail（验证参数提取能力）
阶段二：并入 query_pipeline_overview 及其余工具
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# ── Tool Schemas（OpenAI function-calling 格式）────────────────────────────────

GET_INSTITUTION_DETAIL: dict = {
    "type": "function",
    "function": {
        "name": "get_institution_detail",
        "description": (
            "查询单家投资机构的档案信息，包括当前 pipeline 阶段、热度、AI 画像摘要、"
            "已知关注点和偏好。当用户提到某个具体机构名称时调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "institution_name": {
                    "type": "string",
                    "description": "机构名称或关键词，例如：红杉、高瓴资本、民生证券",
                }
            },
            "required": ["institution_name"],
        },
    },
}

QUERY_PIPELINE_OVERVIEW: dict = {
    "type": "function",
    "function": {
        "name": "query_pipeline_overview",
        "description": (
            "查询当前融资 pipeline 全景：各阶段机构数量统计，以及最近更新的机构列表。"
            "当用户询问整体融资进展、漏斗状态、有多少机构在谈时调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

# 阶段一仅绑定 get_institution_detail
PHASE1_TOOLS = [GET_INSTITUTION_DETAIL]

# 阶段二全量工具（目前预留）
ALL_TOOLS = [GET_INSTITUTION_DETAIL, QUERY_PIPELINE_OVERVIEW]


# ── Tool 执行器 ────────────────────────────────────────────────────────────────

def execute_tool(tool_name: str, arguments: dict, *, tenant_id: str) -> str:
    """
    根据工具名和参数执行对应查询，返回供 LLM 消费的字符串摘要。
    所有错误都返回可读字符串，不向上抛（LLM 会据此告知用户）。
    """
    try:
        if tool_name == "get_institution_detail":
            return _exec_get_institution_detail(arguments, tenant_id=tenant_id)
        if tool_name == "query_pipeline_overview":
            return _exec_query_pipeline_overview(tenant_id=tenant_id)
        return f"未知工具：{tool_name}"
    except Exception as e:
        logger.warning("npc_tool_exec_failed tool=%s: %s", tool_name, e)
        return f"工具执行失败：{e}"


def _exec_get_institution_detail(args: dict, *, tenant_id: str) -> str:
    from cangjie_fos.services.institution_store import find_matching_names

    name_query = (args.get("institution_name") or "").strip()
    if not name_query:
        return "请提供机构名称。"

    hits = find_matching_names(tenant_id=tenant_id, text=name_query)
    if not hits:
        # 降级：按名称子串搜索
        from cangjie_fos.services.institution_store import list_institutions
        all_insts = list_institutions(tenant_id=tenant_id, limit=500)
        hits = [i for i in all_insts if name_query in (i.name or "")]

    if not hits:
        return f"未找到名称包含「{name_query}」的机构。"

    inst = hits[0]
    lines = [
        f"机构：{inst.name}",
        f"阶段：{inst.stage.value if inst.stage else '未知'}",
        f"热度：{inst.thermal.value if inst.thermal else '未知'}",
    ]
    if inst.ai_summary:
        lines.append(f"AI画像：{inst.ai_summary}")
    if inst.concerns:
        lines.append(f"关注点：{inst.concerns}")
    if inst.preferences:
        lines.append(f"偏好：{inst.preferences}")

    if len(hits) > 1:
        others = "、".join(h.name for h in hits[1:4])
        lines.append(f"（另有相关机构：{others}）")

    return "\n".join(lines)


def _exec_query_pipeline_overview(*, tenant_id: str) -> str:
    from cangjie_fos.services.institution_store import count_by_stage, list_institutions

    counts = count_by_stage(tenant_id=tenant_id)
    total = sum(counts.values())
    stage_lines = [
        f"  {stage}: {n} 家"
        for stage, n in counts.items()
        if n > 0
    ]

    recent = list_institutions(tenant_id=tenant_id, limit=5)
    recent_lines = [
        f"  {i.name}（{i.stage.value}，热度{i.thermal.value}）"
        for i in recent
    ]

    parts = [f"当前 pipeline 共 {total} 家机构："]
    if stage_lines:
        parts.extend(stage_lines)
    else:
        parts.append("  暂无机构数据")

    if recent_lines:
        parts.append("最近更新：")
        parts.extend(recent_lines)

    return "\n".join(parts)
