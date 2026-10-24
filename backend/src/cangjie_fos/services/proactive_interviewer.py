"""定时反向访谈：每天扫描停滞机构，生成追问推送给 NPC 对话流。

运行逻辑：
  1. 找出超过 N 天未更新、且 stage 不在终态的机构
  2. 生成 1-3 条追问，写入 NPC 消息队列
  3. 前端 NPC 面板轮询到后，像普通 NPC 消息一样展示
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# 停滞阈值：超过 3 天未更新视为"停滞"
STALE_DAYS = 3

# 终态阶段（不追问）
TERMINAL_STAGES = set()  # term_sheet 之后仍可追问，暂不设终态


def run_proactive_interview(tenant_id: str = "default") -> dict:
    """
    扫描停滞机构并生成追问。
    返回：{"questions_generated": N, "stale_institutions": [names...]}
    可被 APScheduler 直接调用，也可通过 API 手动触发。
    """
    stale = _find_stale_institutions(tenant_id)
    if not stale:
        logger.info("proactive_interview: 无停滞机构，跳过 tenant=%s", tenant_id)
        return {"questions_generated": 0, "stale_institutions": []}

    questions = _generate_questions(stale[:3])  # 每次最多追问3家
    _push_to_npc_queue(questions, tenant_id=tenant_id)

    logger.info(
        "proactive_interview: 推送 %d 条追问，停滞机构: %s",
        len(questions),
        [i["name"] for i in stale[:3]],
    )
    return {
        "questions_generated": len(questions),
        "stale_institutions": [i["name"] for i in stale],
    }


def _find_stale_institutions(tenant_id: str) -> list[dict]:
    """
    返回超过 STALE_DAYS 天未更新、且不在终态的机构。
    按 updated_at 升序（最久未动的排前面）。
    """
    from cangjie_fos.services.institution_store import list_institutions

    threshold = time.time() - STALE_DAYS * 86400
    institutions = list_institutions(tenant_id=tenant_id, limit=200)

    stale = []
    for inst in institutions:
        if inst.stage and inst.stage.value in TERMINAL_STAGES:
            continue
        updated = inst.updated_at or 0.0
        if updated < threshold:
            days_stale = (time.time() - updated) / 86400 if updated > 0 else 999
            stale.append({
                "name": inst.name,
                "stage": inst.stage.value if inst.stage else "unknown",
                "thermal": inst.thermal.value if inst.thermal else "unknown",
                "ai_summary": inst.ai_summary or "",
                "days_stale": round(days_stale, 1),
            })

    stale.sort(key=lambda x: x["days_stale"], reverse=True)
    return stale


def _generate_questions(institutions: list[dict]) -> list[str]:
    """
    为每家停滞机构生成一条追问文本。
    优先规则优于 LLM 调用（快速、离线可用）。
    """
    questions = []
    for inst in institutions:
        name = inst["name"]
        stage = inst["stage"]
        days = inst["days_stale"]
        thermal = inst["thermal"]

        if days > 30:
            q = f"【停滞预警】{name} 已超过 {int(days)} 天没有更新，现在是否还在推进？还是已经暂停？"
        elif stage == "dd":
            q = f"【尽调跟进】{name} 在尽调阶段已 {int(days)} 天没有动静，他们有没有反馈材料审核意见？"
        elif stage == "term_sheet":
            q = f"【TS 谈判】{name} 的 Term Sheet 谈了 {int(days)} 天，目前卡在哪个条款上？"
        elif stage == "pitched":
            q = f"【路演跟进】{name} 路演后已 {int(days)} 天，他们有没有表示进一步了解的意向？"
        elif thermal == "cold":
            q = f"【关系维护】{name} 热度已经 cold，是否要考虑暂停跟进或换策略激活？"
        else:
            q = f"【进度更新】{name}（{stage}阶段）已 {int(days)} 天没有更新，最近有什么新进展吗？"

        questions.append(q)

    return questions


def _push_to_npc_queue(questions: list[str], *, tenant_id: str) -> None:
    """将追问推入 NPC 消息队列，前端轮询后显示为主动消息。"""
    from cangjie_fos.services.npc_queue import push_line

    timestamp = datetime.now().strftime("%H:%M")
    header = f"【{timestamp} 豆豆每日扫描】发现 {len(questions)} 家机构需要跟进："

    push_line(role="assistant", text=header, proactive=True)
    for q in questions:
        push_line(role="assistant", text=q, proactive=True)


def run_proactive_interview_all_tenants() -> None:
    """
    遍历所有活跃租户运行反向访谈。
    被 APScheduler 直接调用。
    """
    from cangjie_fos.services.pitch_job_db import _connect

    try:
        conn = _connect()
        rows = conn.execute(
            "SELECT DISTINCT tenant_id FROM pitch_jobs ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        conn.close()
        tenant_ids = [r[0] for r in rows if r[0]]
    except Exception as e:
        logger.error("proactive_interview: 获取 tenant 列表失败: %s", e)
        return

    if not tenant_ids:
        tenant_ids = ["default"]

    for tid in tenant_ids:
        try:
            result = run_proactive_interview(tid)
            if result["questions_generated"] > 0:
                logger.info("proactive_interview tenant=%s: %s", tid, result)
        except Exception as e:
            logger.warning("proactive_interview tenant=%s 失败: %s", tid, e)
