"""从粘贴的原始聊天记录中提取结构化融资情报，写入 institutions / follow_up_items 表。

使用场景：
  用户从微信工作群 Ctrl+A + Ctrl+C 复制一整天的聊天记录，
  粘贴到系统后，LLM 自动提取机构进展更新和行动项。

结构化输出实现：
  使用 Pydantic BaseModel + model_json_schema() 注入精确 JSON Schema，
  LLM 的输出被枚举值约束（stage/thermal/priority），
  解析时用 model_validate_json() 强校验，杜绝幻觉字段。
"""
from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field

from cangjie_fos.schemas.institution import InstitutionThermal, PipelineStage

logger = logging.getLogger(__name__)


# ── Pydantic 结构化输出模型 ────────────────────────────────────────────────────

class InstitutionUpdate(BaseModel):
    """单家机构的进展更新。"""
    name: str = Field(..., description="机构常用名，如 红杉资本")
    stage: PipelineStage | None = Field(None, description="融资阶段，无法判断填 null")
    thermal: InstitutionThermal | None = Field(None, description="沟通热度，无法判断填 null")
    note: str = Field("", max_length=60, description="最新进展一句话（60字以内）")


class FollowupItem(BaseModel):
    """行动项（待办事项）。"""
    actor: str = Field(..., description="责任方：我方 / 对方 / 具体人名")
    action: str = Field(..., max_length=40, description="具体行动（40字以内）")
    priority: Literal["high", "normal", "low"] = "normal"
    institution: str = Field("", description="关联机构名称，无法判断填空字符串")


class ChatLogExtraction(BaseModel):
    """LLM 从群聊提取的完整结果。"""
    institution_updates: list[InstitutionUpdate] = []
    followup_items: list[FollowupItem] = []
    summary: str = Field("", max_length=100, description="整体进展一句话总结（100字以内）")


# ── 公开接口 ──────────────────────────────────────────────────────────────────

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


# ── 内部实现 ──────────────────────────────────────────────────────────────────

def _llm_extract_from_chat(raw_text: str) -> dict:
    """
    调用 LLM 从聊天记录中提取结构化情报。

    使用 Pydantic Structured Output：
    - 将 ChatLogExtraction.model_json_schema() 注入 system prompt
    - LLM 输出被枚举值约束（stage/thermal/priority 不能乱填）
    - 用 model_validate_json() 解析并强校验，返回 model_dump()
    """
    from cangjie_fos.services.dd_llm_client import call_with_retry, get_dd_llm_client

    client = get_dd_llm_client()
    truncated = raw_text[:6000]
    if len(raw_text) > 6000:
        truncated += f"\n…（原文共 {len(raw_text)} 字，已截取前 6000 字）"

    # 自动生成精确 JSON Schema，注入 system prompt
    schema = ChatLogExtraction.model_json_schema()
    schema_str = json.dumps(schema, ensure_ascii=False, indent=2)

    system_prompt = f"""你是一级市场融资助手。从聊天记录中提取与融资推进相关的信息。

你必须且只能输出严格符合以下 JSON Schema 的 JSON 对象，不允许有任何额外字段：

{schema_str}

规则：
- 只提取与投融资有关的信息，忽略闲聊、表情、系统消息
- institution_updates 和 followup_items 可以为空数组
- stage 字段只能是 "targeted"/"pitched"/"dd"/"term_sheet"/null，不能用其他值
- thermal 字段只能是 "cold"/"warm"/"hot"/null
- priority 字段只能是 "high"/"normal"/"low"
- 只返回 JSON，不要任何解释"""

    def _call() -> dict:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": truncated},
            ],
            response_format={"type": "json_object"},
            max_tokens=1500,
            temperature=0,
        )
        raw = resp.choices[0].message.content or "{}"
        # Pydantic 强校验：枚举值非法会抛 ValidationError，不会默默通过
        validated = ChatLogExtraction.model_validate_json(raw)
        return validated.model_dump()

    try:
        return call_with_retry(_call, max_retries=2)
    except Exception as e:
        logger.error("chat_log_llm_failed: %s", e)
        return ChatLogExtraction().model_dump() | {"summary": f"LLM 解析失败：{e}"}


def _persist_updates(extracted: dict, *, tenant_id: str) -> None:
    """将提取结果写入数据库：更新机构档案 + 插入行动项。"""
    from cangjie_fos.schemas.institution import InstitutionProfileUpdate
    from cangjie_fos.services.institution_store import get_by_name, update_institution
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
                patch["stage"] = upd["stage"]  # 已由 Pydantic 校验为合法枚举值
            if upd.get("thermal"):
                patch["thermal"] = upd["thermal"]
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
