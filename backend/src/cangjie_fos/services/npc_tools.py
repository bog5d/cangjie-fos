"""NPC Chat 工具集：DeepSeek 可按需调用的查询工具。

四个徒弟：
  1. get_institution_detail    — 查单家机构档案（参数提取型）
  2. query_pipeline_overview   — 融资全景大盘（无参数型）
  3. list_recent_roadshows     — 最近几场路演记录
  4. list_pending_followups    — 未完成的待办行动项
"""
from __future__ import annotations

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

LIST_RECENT_ROADSHOWS: dict = {
    "type": "function",
    "function": {
        "name": "list_recent_roadshows",
        "description": (
            "查询最近几场路演（BP 路演 / 沟通会）的记录，包括机构名、时间、状态和得分。"
            "当用户询问最近开了哪些会、路演情况、上周或近期有什么进展时调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "返回条数，默认 5，最多 20",
                    "default": 5,
                }
            },
            "required": [],
        },
    },
}

LIST_PENDING_FOLLOWUPS: dict = {
    "type": "function",
    "function": {
        "name": "list_pending_followups",
        "description": (
            "查询当前未完成的跟进行动项和承诺事项。"
            "当用户询问还有什么事没做、今天要干什么、有哪些待办或承诺未兑现时调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "返回条数，默认 10，最多 30",
                    "default": 10,
                }
            },
            "required": [],
        },
    },
}

# 全量四个工具
ALL_TOOLS = [
    GET_INSTITUTION_DETAIL,
    QUERY_PIPELINE_OVERVIEW,
    LIST_RECENT_ROADSHOWS,
    LIST_PENDING_FOLLOWUPS,
]

# 向后兼容别名
PHASE1_TOOLS = ALL_TOOLS


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
        if tool_name == "list_recent_roadshows":
            return _exec_list_recent_roadshows(arguments, tenant_id=tenant_id)
        if tool_name == "list_pending_followups":
            return _exec_list_pending_followups(arguments, tenant_id=tenant_id)
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
    parts.extend(stage_lines or ["  暂无机构数据"])
    if recent_lines:
        parts.append("最近更新：")
        parts.extend(recent_lines)

    return "\n".join(parts)


def _exec_list_recent_roadshows(args: dict, *, tenant_id: str) -> str:
    import time as _time
    from cangjie_fos.services.pitch_job_db import db_job_list_for_tenant

    limit = min(int(args.get("limit") or 5), 20)
    jobs = db_job_list_for_tenant(tenant_id, limit=limit)

    if not jobs:
        return "暂无路演记录。"

    lines = [f"最近 {len(jobs)} 场路演："]
    for _, job in jobs:
        institution = job.get("institution_id") or "（机构未确认）"
        status = job.get("status") or "unknown"
        score = job.get("exp_delta")
        created = job.get("created_at")
        date_str = ""
        if created:
            import datetime
            date_str = datetime.datetime.fromtimestamp(float(created)).strftime("%m-%d")
        score_str = f"  得分±{score}" if score else ""
        lines.append(f"  {date_str} {institution}（{status}）{score_str}")

    return "\n".join(lines)


def _exec_list_pending_followups(args: dict, *, tenant_id: str) -> str:
    from cangjie_fos.services.pitch_job_db import db_follow_up_list

    limit = min(int(args.get("limit") or 10), 30)
    items = db_follow_up_list(tenant_id, limit=limit, include_done=False)

    if not items:
        return "当前没有未完成的待办行动项。"

    lines = [f"未完成行动项（共 {len(items)} 条）："]
    for item in items:
        actor = item.get("actor") or "我方"
        action = item.get("action") or ""
        priority = item.get("priority") or "normal"
        institution = item.get("institution_id") or ""
        inst_str = f"[{institution}] " if institution else ""
        priority_mark = "🔴" if priority == "high" else "⚪"
        lines.append(f"  {priority_mark} {inst_str}{actor}：{action}")

    return "\n".join(lines)
