"""从粘贴的原始聊天记录中提取结构化融资情报，写入 institutions / follow_up_items 表。

使用场景：
  用户从微信工作群 Ctrl+A + Ctrl+C 复制一整天的聊天记录，
  粘贴到系统后，LLM 自动提取机构进展更新和行动项。
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# LLM 提取的数据模型（返回给调用方，调用方决定是否入库）
# institution_updates: [{"name": str, "stage": str|None, "note": str, "thermal": str|None}]
# followup_items:      [{"actor": str, "action": str, "priority": str, "institution": str}]


def ingest_chat_log(
    raw_text: str,
    *,
    tenant_id: str,
    persist: bool = True,
) -> dict:
    """
    解析原始聊天记录，提取融资情报并选择性写入数据库。

    返回：{
        "institution_updates": [...],
        "followup_items": [...],
        "summary": str,
        "persisted": bool,
    }
    """
    if not raw_text.strip():
        return {"institution_updates": [], "followup_items": [], "summary": "输入为空", "persisted": False}

    extracted = _llm_extract_from_chat(raw_text)

    if persist:
        _persist_updates(extracted, tenant_id=tenant_id)

    return {
        "institution_updates": extracted.get("institution_updates", []),
        "followup_items": extracted.get("followup_items", []),
        "summary": extracted.get("summary", ""),
        "persisted": persist,
    }


def _llm_extract_from_chat(raw_text: str) -> dict:
    """
    调用 LLM 从聊天记录中提取结构化情报。
    raw_text 可能很长（一整天群聊），最多截取前 6000 字。
    """
    from cangjie_fos.services.dd_llm_client import call_with_retry, get_dd_llm_client

    client = get_dd_llm_client()
    truncated = raw_text[:6000]
    if len(raw_text) > 6000:
        truncated += f"\n…（原文共 {len(raw_text)} 字，已截取前 6000 字）"

    prompt = f"""你是一级市场融资助手。以下是工作群的原始聊天记录（含时间戳、人名、系统消息等噪声）：

---
{truncated}
---

请从中提取与"融资推进"相关的信息，输出 JSON：
{{
  "institution_updates": [
    {{
      "name": "机构名称",
      "stage": "targeted|pitched|dd|term_sheet 或 null（无法判断时填 null）",
      "thermal": "cold|warm|hot 或 null",
      "note": "一句话描述最新进展（30字以内）"
    }}
  ],
  "followup_items": [
    {{
      "actor": "我方 或 对方 或 具体人名",
      "action": "具体行动（20字以内）",
      "priority": "high|normal|low",
      "institution": "关联机构名称，无法判断填空字符串"
    }}
  ],
  "summary": "整体进展一句话总结（50字以内）"
}}

规则：
- 只提取与投融资有关的信息，忽略闲聊、表情、系统消息
- institution_updates 和 followup_items 可以为空数组
- 只返回 JSON，不要任何解释"""

    def _call() -> dict:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=1500,
            temperature=0,
        )
        raw = resp.choices[0].message.content or "{}"
        return json.loads(raw)

    try:
        return call_with_retry(_call, max_retries=2)
    except Exception as e:
        logger.error("chat_log_llm_failed: %s", e)
        return {"institution_updates": [], "followup_items": [], "summary": f"LLM 解析失败：{e}"}


def _persist_updates(extracted: dict, *, tenant_id: str) -> None:
    """将提取结果写入数据库：更新机构档案 + 插入行动项。"""
    from cangjie_fos.services.institution_store import get_by_name, update_institution
    from cangjie_fos.schemas.institution import InstitutionProfileUpdate, PipelineStage, InstitutionThermal
    from cangjie_fos.services.pitch_job_db import db_follow_up_insert

    # ── 机构更新 ──────────────────────────────────────────────────────
    for upd in extracted.get("institution_updates", []):
        name = (upd.get("name") or "").strip()
        if not name:
            continue
        try:
            inst = get_by_name(tenant_id=tenant_id, name=name)
            if not inst:
                logger.info("chat_ingest: 机构 %s 不在库，跳过更新", name)
                continue

            patch: dict = {}
            if upd.get("stage"):
                try:
                    patch["stage"] = PipelineStage(upd["stage"]).value
                except ValueError:
                    pass
            if upd.get("thermal"):
                try:
                    patch["thermal"] = InstitutionThermal(upd["thermal"]).value
                except ValueError:
                    pass
            if upd.get("note"):
                existing = inst.ai_summary or ""
                patch["ai_summary"] = (upd["note"] + ("；" + existing if existing else ""))[:300]

            if patch:
                update_institution(inst.institution_id, InstitutionProfileUpdate(**patch))
                logger.info("chat_ingest: 更新机构 %s: %s", name, list(patch.keys()))
        except Exception as e:
            logger.warning("chat_ingest: 更新机构 %s 失败: %s", name, e)

    # ── 行动项插入 ────────────────────────────────────────────────────
    for item in extracted.get("followup_items", []):
        action = (item.get("action") or "").strip()
        if not action:
            continue
        try:
            db_follow_up_insert(
                tenant_id=tenant_id,
                job_id="",
                institution_id=item.get("institution") or "",
                actor=item.get("actor") or "我方",
                action=action,
                priority=item.get("priority") or "normal",
                source="chat_log",
            )
            logger.info("chat_ingest: 插入行动项 [%s] %s", item.get("institution"), action)
        except Exception as e:
            logger.warning("chat_ingest: 插入行动项失败: %s", e)
