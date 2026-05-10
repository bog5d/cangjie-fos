"""参与人身份确认 API（Phase 6.6）

流程：job 变为 completed → 前端弹强制确认弹层 → POST /participants → 写入 DB。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from cangjie_fos.services.pitch_job_db import (
    db_job_get,
    db_participants_get,
    db_participants_save,
    db_speaker_summary,
    _PARTICIPANT_VALID_ROLES,
)

router = APIRouter(prefix="/api/v1/pitch", tags=["participants"])
logger = logging.getLogger(__name__)


# ── 请求 / 响应 schema ─────────────────────────────────────────────────────────

class ParticipantIn(BaseModel):
    speaker_id: str
    real_name: str = ""
    institution: str = ""
    role: str = Field(default="其他", description="GP执行 / LP投资方 / 政府招商 / 企业方创始人 / 企业方高管 / 企业方投融资 / 其他")
    title: str = ""


class ConfirmParticipantsRequest(BaseModel):
    participants: list[ParticipantIn]
    confirmed_by: str = ""


class SpeakerSummaryItem(BaseModel):
    speaker_id: str
    sample_lines: list[str]
    word_count: int


# ── 路由 ───────────────────────────────────────────────────────────────────────

@router.get(
    "/jobs/{job_id}/speaker-summary",
    response_model=list[SpeakerSummaryItem],
    summary="返回每位说话人的前3句原文（供确认弹层对照身份）",
)
def get_speaker_summary(job_id: str) -> list[dict[str, Any]]:
    job = db_job_get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return db_speaker_summary(job_id)


@router.get(
    "/jobs/{job_id}/participants",
    summary="返回已确认的参与人列表",
)
def get_participants(job_id: str) -> list[dict[str, Any]]:
    if not db_job_get(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    return db_participants_get(job_id)


@router.post(
    "/jobs/{job_id}/participants",
    summary="提交参与人身份确认（幂等，重复提交覆盖旧数据）",
)
def confirm_participants(
    job_id: str,
    body: ConfirmParticipantsRequest,
    request: Request,
) -> dict[str, Any]:
    job = db_job_get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    # 从请求头或 body 中读取确认人名称
    confirmed_by = body.confirmed_by.strip()
    if not confirmed_by:
        confirmed_by = request.headers.get("X-FOS-Commander", "unknown")

    participants = [p.model_dump() for p in body.participants]
    db_participants_save(
        job_id=job_id,
        tenant_id=str(job["tenant_id"]),
        participants=participants,
        confirmed_by=confirmed_by,
    )
    logger.info(
        "participants_confirmed job_id=%s count=%d by=%s",
        job_id, len(participants), confirmed_by,
    )
    return {"ok": True, "confirmed": len(participants)}


@router.get(
    "/participants/valid-roles",
    summary="返回合法角色列表",
)
def get_valid_roles() -> list[str]:
    return sorted(_PARTICIPANT_VALID_ROLES)
