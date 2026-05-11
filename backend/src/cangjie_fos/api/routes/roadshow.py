"""路演分析专属 API（Phase 7.5）。

工作流：
  1. POST /api/v1/roadshow/start            — 上传音频或稿子，启动ASR（后台），返回 job_id
  2. GET  /api/v1/roadshow/jobs/{job_id}/speaker-preview
                                            — ASR完成后，返回说话人样本+AI推测角色
  3. POST /api/v1/roadshow/jobs/{job_id}/confirm-speakers
                                            — 用户确认说话人身份，触发LangGraph评估
  4. GET  /api/v1/roadshow/jobs/{job_id}/report
                                            — 获取 RoadshowIntelReport 结果
"""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from cangjie_fos.core.paths import get_backend_root
from cangjie_fos.schemas.pitch_upload import PitchJobStatus
from cangjie_fos.api.upload_io import stream_upload_to_path
from cangjie_fos.services.pitch_job_db import db_job_create, db_job_get, db_job_update
from cangjie_fos.services.pitch_job_store import job_create, job_update
from cangjie_fos.services.pitch_upload_pipeline import (
    resume_roadshow_analysis,
    run_roadshow_asr_job,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/roadshow", tags=["roadshow"])

# ── 合法角色 ───────────────────────────────────────────────────────────────────
_VALID_ROLES = {
    "引荐方",
    "企业方创始人",
    "企业方高管",
    "企业方投融资",
    "GP执行",
    "LP投资方",
    "政府招商",
    "其他",
}

# ── 说话人角色推测（基于台词特征的简单规则，无需LLM）──────────────────────────
_INVESTOR_KEYWORDS = re.compile(
    r"估值|退出|回报|IRR|DPI|MOIC|赛道|投资逻辑|基金规模|GP|LP"
    r"|我们主要看|我们关注|这个赛道|你们的数据|之前投过|看过类似",
    re.IGNORECASE,
)
_COMPANY_KEYWORDS = re.compile(
    r"我们的产品|我们的客户|我们的收入|我们的团队|我们做的|商业模式"
    r"|核心壁垒|技术优势|融资计划|上市",
    re.IGNORECASE,
)
_REFERRER_KEYWORDS = re.compile(
    r"帮你们介绍|认识一下|给你们引荐|我跟.*聊过|这个团队我很看好",
    re.IGNORECASE,
)


def _guess_role(sample_lines: list[str]) -> tuple[str, str]:
    """基于样本台词推测说话人角色。返回 (role, reason)。"""
    text = " ".join(sample_lines)
    investor_hits = len(_INVESTOR_KEYWORDS.findall(text))
    company_hits = len(_COMPANY_KEYWORDS.findall(text))
    referrer_hits = len(_REFERRER_KEYWORDS.findall(text))

    if referrer_hits >= 1:
        return "引荐方", "台词中有引荐/介绍相关表述"
    if investor_hits > company_hits and investor_hits >= 2:
        return "GP执行", "台词中有多个投资机构视角词汇"
    if company_hits > investor_hits and company_hits >= 2:
        return "企业方创始人", "台词中有多个企业方陈述词汇"
    return "其他", "无明显特征，请人工确认"


# ── Pydantic Models ────────────────────────────────────────────────────────────

class RoadshowStartResponse(BaseModel):
    job_id: str
    status: str
    message: str


class SpeakerPreviewItem(BaseModel):
    speaker_id: str
    sample_lines: list[str]
    word_count: int
    guessed_role: str = Field(default="其他", description="AI推测角色")
    guess_reason: str = Field(default="", description="推测理由")


class ConfirmedSpeaker(BaseModel):
    speaker_id: str
    real_name: str = ""
    institution: str = ""
    role: str = "其他"
    title: str = ""


class ConfirmSpeakersRequest(BaseModel):
    confirmed_by: str = Field(..., description="确认人（指挥官名称）")
    speakers: list[ConfirmedSpeaker]


class RoadshowJobStatus(BaseModel):
    job_id: str
    status: str
    substatus: str | None = None
    is_roadshow: bool = True
    referrer: str = ""
    has_report: bool = False
    report: dict | None = None
    created_at: float = 0.0


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/start", response_model=RoadshowStartResponse)
async def roadshow_start(
    background_tasks: BackgroundTasks,
    tenant_id: str = Query(..., description="租户 ID"),
    roadshow_date: str = Query(..., description="路演日期 YYYY-MM-DD"),
    institution_name: str = Query(default="", description="目标机构名称（可选，ASR完成后再确认）"),
    referrer: str = Query(default="", description="引荐方机构名称（可选）"),
    confirmed_by: str = Query(default="", description="指挥官名称"),
    file: UploadFile | None = None,
    transcript_text: str | None = None,
) -> RoadshowStartResponse:
    """上传路演录音或文字稿，启动ASR，返回 job_id。

    支持两种输入：
    - file: 音频文件（mp3/m4a/wav等）
    - transcript_text: 直接粘贴文字稿（query参数或form字段）
    """
    job_id = str(uuid.uuid4())
    label = f"路演_{roadshow_date}" + (f"_{institution_name}" if institution_name else "")

    # 创建内存 job 记录
    job_create(job_id, tenant_id=tenant_id)
    # 创建 DB 记录
    db_job_create(
        job_id,
        tenant_id,
        interviewee=label,
        category="01_机构路演",
        institution_id=institution_name or f"待确认_{roadshow_date}",
        is_roadshow=1,
        referrer=referrer,
    )

    if file is not None:
        # 音频上传路径
        fname = file.filename or f"roadshow_{job_id}.mp3"
        suffix = Path(fname).suffix or ".mp3"
        audio_dir = get_backend_root() / "data" / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        incoming_path = audio_dir / f"{job_id}_incoming{suffix}"
        await stream_upload_to_path(file, incoming_path)

        background_tasks.add_task(
            run_roadshow_asr_job,
            job_id=job_id,
            filename=fname,
            tenant_id=tenant_id,
            referrer=referrer,
            pre_written_path=incoming_path,
        )
        return RoadshowStartResponse(
            job_id=job_id,
            status="transcribing",
            message="音频已上传，ASR转写中，请稍候…",
        )

    elif transcript_text and transcript_text.strip():
        # 文字稿路径：直接跳过ASR，转换为 TranscriptionWord 格式
        from cangjie_fos.services.transcript_parser import parse_transcript_to_words  # noqa: PLC0415

        words = parse_transcript_to_words(transcript_text)
        word_count = len(words)

        db_job_update(
            job_id,
            status=str(PitchJobStatus.AWAITING_SPEAKERS),
            substatus=f"文字稿解析完成（{word_count} 词），请确认说话人身份",
            words_json=[w.model_dump() for w in words],
            is_roadshow=1,
            referrer=referrer,
        )
        job_update(job_id, status=PitchJobStatus.AWAITING_SPEAKERS)
        return RoadshowStartResponse(
            job_id=job_id,
            status="awaiting_speakers",
            message=f"文字稿解析完成（{word_count} 词），请确认说话人身份",
        )

    else:
        raise HTTPException(400, "必须提供音频文件（file）或文字稿（transcript_text）之一")


@router.get("/jobs/{job_id}/status", response_model=RoadshowJobStatus)
def roadshow_job_status(job_id: str) -> RoadshowJobStatus:
    """轮询 job 状态（前端步骤2等待页使用）。"""
    row = db_job_get(job_id)
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")
    return RoadshowJobStatus(
        job_id=job_id,
        status=row.get("status", "pending"),
        substatus=row.get("substatus"),
        is_roadshow=bool(row.get("is_roadshow", 0)),
        referrer=row.get("referrer", ""),
        has_report=bool(row.get("original_report")),
        report=row.get("original_report") if row.get("original_report") else None,
        created_at=row.get("created_at", 0.0),
    )


@router.get("/jobs/{job_id}/speaker-preview", response_model=list[SpeakerPreviewItem])
def roadshow_speaker_preview(job_id: str) -> list[SpeakerPreviewItem]:
    """ASR完成后，返回每位说话人的样本台词和AI推测角色。

    仅当 status == 'awaiting_speakers' 时调用有意义。
    """
    row = db_job_get(job_id)
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")

    status = row.get("status", "")
    if status not in ("awaiting_speakers", "completed"):
        raise HTTPException(
            400,
            f"Job {job_id} is in status '{status}', not ready for speaker preview. "
            "Wait for ASR to complete."
        )

    words_raw = row.get("words_json") or []
    if not words_raw:
        return []

    # 按 speaker_id 分组
    from collections import defaultdict  # noqa: PLC0415
    speaker_lines: dict[str, list[str]] = defaultdict(list)
    speaker_counts: dict[str, int] = defaultdict(int)

    for w in words_raw:
        sid = str(w.get("speaker_id", "0"))
        text = w.get("text", "").strip()
        if text:
            speaker_counts[sid] += 1
            # 收集较长的句子作为样本（至少5个字）
            if len(text) >= 5 and len(speaker_lines[sid]) < 10:
                speaker_lines[sid].append(text)

    result: list[SpeakerPreviewItem] = []
    for sid in sorted(speaker_lines.keys(), key=lambda x: (len(x), x)):
        lines = speaker_lines[sid]
        # 选取最具代表性的3条（选较长的）
        sample = sorted(lines, key=len, reverse=True)[:3]
        guessed_role, guess_reason = _guess_role(sample)
        result.append(SpeakerPreviewItem(
            speaker_id=sid,
            sample_lines=sample,
            word_count=speaker_counts[sid],
            guessed_role=guessed_role,
            guess_reason=guess_reason,
        ))

    return result


@router.post("/jobs/{job_id}/confirm-speakers")
def roadshow_confirm_speakers(
    job_id: str,
    request: ConfirmSpeakersRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = Query(..., description="租户 ID"),
) -> dict[str, Any]:
    """用户确认说话人身份后触发LangGraph路演情报评估。"""
    row = db_job_get(job_id)
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")

    if row.get("status") != str(PitchJobStatus.AWAITING_SPEAKERS):
        raise HTTPException(
            400,
            f"Job {job_id} status is '{row.get('status')}', expected 'awaiting_speakers'"
        )

    if not request.confirmed_by.strip():
        raise HTTPException(400, "confirmed_by（指挥官名称）不能为空")

    # 校验角色合法性
    speakers_data = []
    for sp in request.speakers:
        role = sp.role if sp.role in _VALID_ROLES else "其他"
        speakers_data.append({
            "speaker_id": sp.speaker_id,
            "real_name": sp.real_name.strip(),
            "institution": sp.institution.strip(),
            "role": role,
            "title": sp.title.strip(),
        })

    background_tasks.add_task(
        resume_roadshow_analysis,
        job_id=job_id,
        tenant_id=tenant_id,
        confirmed_speakers=speakers_data,
    )

    return {"ok": True, "message": "说话人身份已确认，路演情报分析已启动", "job_id": job_id}


@router.get("/jobs/{job_id}/report")
def roadshow_report(job_id: str) -> dict[str, Any]:
    """获取已完成的路演情报报告。"""
    row = db_job_get(job_id)
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")

    if row.get("status") != str(PitchJobStatus.COMPLETED):
        raise HTTPException(
            400,
            f"Job {job_id} not completed yet (status: {row.get('status')})"
        )

    report = row.get("original_report")
    if not report:
        raise HTTPException(404, f"Job {job_id} has no report")

    confirmed_speakers = row.get("confirmed_speakers_json") or []

    return {
        "job_id": job_id,
        "report": report,
        "confirmed_speakers": confirmed_speakers,
        "referrer": row.get("referrer", ""),
        "interviewee": row.get("interviewee", ""),
        "created_at": row.get("created_at", 0.0),
    }
