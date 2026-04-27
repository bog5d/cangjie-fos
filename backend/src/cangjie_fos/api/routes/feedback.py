"""捕获层：文本 Diff 反馈（SPEC A3）。"""
from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Depends

import logging as _logging

from cangjie_fos.core.config import settings

_fb_logger = _logging.getLogger(__name__)


def try_capture_diff_to_executive_memory(
    *,
    tenant_id: str,
    ai_text: str,
    user_text: str,
    tag: str,
    risk_type: str = "",
):
    """原 coach_memory_bridge 逻辑内联：失败不抛，返回 None。"""
    try:
        from cangjie_fos.engine.coach.agent_tenant import resolve_memory_company_id
        from cangjie_fos.engine.memory_engine import capture_and_distill_diff

        cid = resolve_memory_company_id(tenant_id)
        if not cid:
            return None
        tg = (tag or "").strip() or "default"
        return capture_and_distill_diff(
            ai_text,
            user_text,
            cid,
            tg,
            risk_type=(risk_type or "").strip(),
        )
    except Exception as e:  # noqa: BLE001
        _fb_logger.warning(
            "capture_diff_to_executive_memory_failed tenant=%s err=%s", tenant_id, e
        )
        return None
from cangjie_fos.reflection.reflection_service import ReflectionService
from cangjie_fos.schemas.evolution import EvolutionRecord, TextDiffFeedbackRequest
from cangjie_fos.services.evolution_store import EvolutionJsonStore

logger = logging.getLogger(__name__)
router = APIRouter()


def get_store() -> EvolutionJsonStore:
    return EvolutionJsonStore()


def get_reflection() -> ReflectionService:
    return ReflectionService()


@router.post("/feedback/text-diff", response_model=EvolutionRecord)
def submit_text_diff(
    body: TextDiffFeedbackRequest,
    store: EvolutionJsonStore = Depends(get_store),
    reflection: ReflectionService = Depends(get_reflection),
) -> EvolutionRecord:
    if not settings.log_full_feedback_body:
        h_ai = hashlib.sha256(body.ai_text.encode("utf-8")).hexdigest()[:12]
        h_us = hashlib.sha256(body.user_text.encode("utf-8")).hexdigest()[:12]
        logger.info(
            "text_diff_feedback tenant_id=%s trace_id=%s ai_sha12=%s user_sha12=%s",
            body.tenant_id,
            body.trace_id,
            h_ai,
            h_us,
        )
    else:
        logger.info(
            "text_diff_feedback tenant_id=%s trace_id=%s (full body logging enabled)",
            body.tenant_id,
            body.trace_id,
        )
    record = store.persist_text_diff(body)
    reflection.enqueue_reflection(record.record_id, tenant_id=body.tenant_id)
    mem_tag = (body.memory_tag or "").strip() or "default"
    try_capture_diff_to_executive_memory(
        tenant_id=body.tenant_id,
        ai_text=body.ai_text,
        user_text=body.user_text,
        tag=mem_tag,
        risk_type="",
    )
    return record
