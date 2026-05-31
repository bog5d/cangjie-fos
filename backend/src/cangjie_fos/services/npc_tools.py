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

SUGGEST_PITCH_IMPROVEMENTS: dict = {
    "type": "function",
    "function": {
        "name": "suggest_pitch_improvements",
        "description": (
            "基于某场路演的评分报告，提炼 3 条具体改进建议。"
            "当用户询问如何改进路演、下次该注意什么、怎么提升评分时调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "路演任务 job_id，前端会传入当前复盘任务 ID",
                }
            },
            "required": ["job_id"],
        },
    },
}

GENERATE_FOLLOWUP_MESSAGE: dict = {
    "type": "function",
    "function": {
        "name": "generate_followup_message",
        "description": (
            "为某家机构生成一段跟进话术（微信/邮件均适用，100字以内）。"
            "当用户要求起草跟进消息、催进度、或不知道怎么跟对方说时调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "institution_name": {
                    "type": "string",
                    "description": "机构名称",
                },
                "context": {
                    "type": "string",
                    "description": "最新进展或背景，一句话，如「上周刚开了视频会」",
                },
            },
            "required": ["institution_name"],
        },
    },
}

GET_DEAL_PROBABILITY: dict = {
    "type": "function",
    "function": {
        "name": "get_deal_probability",
        "description": (
            "查询某家机构的成交概率评分（0-100）及当前关键指标。"
            "当用户询问某家机构成功率、胜算、这家有没有希望时调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "institution_name": {
                    "type": "string",
                    "description": "机构名称",
                }
            },
            "required": ["institution_name"],
        },
    },
}

# 全量七个工具
ALL_TOOLS = [
    GET_INSTITUTION_DETAIL,
    QUERY_PIPELINE_OVERVIEW,
    LIST_RECENT_ROADSHOWS,
    LIST_PENDING_FOLLOWUPS,
    SUGGEST_PITCH_IMPROVEMENTS,
    GENERATE_FOLLOWUP_MESSAGE,
    GET_DEAL_PROBABILITY,
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
        if tool_name == "suggest_pitch_improvements":
            return _exec_suggest_pitch_improvements(arguments)
        if tool_name == "generate_followup_message":
            return _exec_generate_followup_message(arguments, tenant_id=tenant_id)
        if tool_name == "get_deal_probability":
            return _exec_get_deal_probability(arguments, tenant_id=tenant_id)
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


def _exec_suggest_pitch_improvements(args: dict) -> str:
    """从路演报告风险点提炼3条改进建议，不需调 LLM。"""
    job_id = (args.get("job_id") or "").strip()
    if not job_id:
        return "请提供 job_id。"
    try:
        from cangjie_fos.services.pitch_job_db import db_job_get
        row = db_job_get(job_id)
    except Exception as e:
        return f"获取路演报告失败：{e}"
    if not row:
        return f"未找到 job_id={job_id} 的路演记录。"

    report = row.get("original_report") or {}
    if not isinstance(report, dict):
        return "路演报告格式异常，无法解析。"

    risk_points = report.get("risk_points") or []
    if not risk_points:
        total = report.get("total_score", "未知")
        return f"该路演（总分 {total}）暂无风险点记录，建议先完成路演评估。"

    suggestions = []
    for rp in risk_points[:5]:
        problem = rp.get("problem_summary") or rp.get("issue") or rp.get("description") or ""
        suggestion = rp.get("suggestion") or rp.get("improvement") or ""
        if not problem and not suggestion:
            continue
        if suggestion:
            suggestions.append(f"• 针对「{problem}」：{suggestion}")
        else:
            suggestions.append(f"• 建议改善「{problem}」这个环节，准备更具体的数据或案例支撑")
        if len(suggestions) >= 3:
            break

    if not suggestions:
        return "风险点记录不含建议文字，请在审查台手动补充改进方向。"

    total_score = report.get("total_score", "未知")
    lines = [f"本场路演评分 {total_score}，建议重点改进："] + suggestions
    return "\n".join(lines)


def _exec_generate_followup_message(args: dict, *, tenant_id: str) -> str:
    """用 DeepSeek 生成 100 字以内的跟进话术。"""
    from cangjie_fos.services.dd_llm_client import call_with_retry, get_dd_llm_client

    name = (args.get("institution_name") or "").strip()
    context = (args.get("context") or "").strip()
    if not name:
        return "请提供机构名称。"

    stage_info = ""
    try:
        from cangjie_fos.services.institution_store import find_matching_names
        hits = find_matching_names(tenant_id=tenant_id, text=name)
        if hits:
            inst = hits[0]
            stage_info = f"当前阶段：{inst.stage.value}，热度：{inst.thermal.value}"
            if inst.ai_summary:
                stage_info += f"，背景：{inst.ai_summary}"
    except Exception:
        pass

    prompt_parts = [f"请为融资方起草一段针对「{name}」的简短跟进消息（微信/邮件均适用，100字以内，语气专业友好）。"]
    if stage_info:
        prompt_parts.append(f"机构信息：{stage_info}")
    if context:
        prompt_parts.append(f"最新背景：{context}")
    prompt_parts.append("直接给出消息正文，不要任何解释。")

    client = get_dd_llm_client()

    def _call() -> str:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "\n".join(prompt_parts)}],
            max_tokens=200,
            temperature=0.7,
        )
        return (resp.choices[0].message.content or "").strip()

    try:
        return call_with_retry(_call, max_retries=2)
    except Exception as e:
        return f"生成失败：{e}"


def _exec_get_deal_probability(args: dict, *, tenant_id: str) -> str:
    """从机构档案读取成功概率及关键指标。"""
    name = (args.get("institution_name") or "").strip()
    if not name:
        return "请提供机构名称。"

    from cangjie_fos.services.institution_store import find_matching_names
    import time as _time

    hits = find_matching_names(tenant_id=tenant_id, text=name)
    if not hits:
        return f"未找到名称包含「{name}」的机构，请先在 Pipeline 中添加。"

    inst = hits[0]
    prob = inst.probability if hasattr(inst, "probability") else 0
    days_stale = 0
    if inst.updated_at:
        days_stale = int((_time.time() - inst.updated_at) / 86400)

    lines = [
        f"机构：{inst.name}",
        f"成功概率：{prob}%",
        f"当前阶段：{inst.stage.value}  热度：{inst.thermal.value}",
        f"最后更新：{days_stale} 天前",
    ]
    if hasattr(inst, "valuation") and inst.valuation:
        lines.append(f"估值：{inst.valuation}")
    if hasattr(inst, "deal_size") and inst.deal_size:
        lines.append(f"目标融资：{inst.deal_size}")
    if hasattr(inst, "legal_status") and inst.legal_status:
        lines.append(f"法务进度：{inst.legal_status}")

    if prob == 0:
        lines.append("（概率未设置，请在机构档案中手动更新）")
    elif prob >= 70:
        lines.append("判断：胜算较高，建议加速推进 TS 谈判。")
    elif prob >= 40:
        lines.append("判断：中等概率，需持续跟进并解决核心疑虑。")
    else:
        lines.append("判断：概率偏低，建议复盘卡点或考虑重新激活策略。")

    return "\n".join(lines)
