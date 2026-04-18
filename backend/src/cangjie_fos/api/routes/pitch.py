"""LangGraph 融资评估 REST 桥接（Phase 2 SPEC A5）+ Phase 3 对话/上传。"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from cangjie_fos.core.paths import ensure_pitch_coach_runtime
from cangjie_fos.core.thread_sqlite import list_threads, upsert_thread
from cangjie_fos.schemas.pitch_chat import (
    PitchChatRequest,
    PitchChatResponse,
    PitchThreadMessagesResponse,
    PitchThreadSummary,
)
from cangjie_fos.schemas.pitch_run import PitchRunRequest
from cangjie_fos.schemas.pitch_upload import (
    PitchJobStatus,
    PitchJobStatusResponse,
    PitchJobSummary,
    PitchReviewCommitRequest,
    PitchReviewCommitResponse,
    PitchReviewResponse,
    PitchUploadAck,
)
from cangjie_fos.services.npc_chat_graph import export_thread_messages, invoke_npc_chat
from cangjie_fos.services.pitch_graph_service import PitchGraphService
from cangjie_fos.services.pitch_failure_present import resolve_stored_job_errors
from cangjie_fos.services.pitch_job_db import db_job_get, db_job_update
from cangjie_fos.services.pitch_job_store import job_create, job_get, job_list_for_tenant
from cangjie_fos.services.pitch_upload_pipeline import run_pitch_upload_job

router = APIRouter(prefix="/api/pitch", tags=["pitch"])


@router.post("/run")
def run_pitch_graph(body: PitchRunRequest) -> dict[str, Any]:
    if body.dry_run:
        return {
            "dry_run": True,
            "tenant_id": body.tenant_id,
            "trace_id": body.trace_id,
            "report": {
                "scene_analysis": {
                    "scene_type": "Dry-run 占位",
                    "speaker_roles": "双方",
                },
                "total_score": 88,
                "total_score_deduction_reason": "",
                "positive_highlights": ["结构清晰", "节奏稳"],
                "risk_points": [],
            },
            "state_excerpt": {"dry_run": True},
        }

    ensure_pitch_coach_runtime()
    from schema import TranscriptionWord

    words = [
        TranscriptionWord(
            word_index=w.word_index,
            text=w.text,
            start_time=w.start_time,
            end_time=w.end_time,
            speaker_id=w.speaker_id,
        )
        for w in body.words
    ]
    try:
        report, excerpt = PitchGraphService.run_evaluation_with_state(
            tenant_id=body.tenant_id,
            words=words,
            model_choice=body.model_choice,
            explicit_context=body.explicit_context,
            qa_text=body.qa_text,
            company_background=body.company_background,
            trace_id=body.trace_id,
        )
    except Exception as e:  # noqa: BLE001 — 对外统一错误壳
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {
        "dry_run": False,
        "tenant_id": body.tenant_id,
        "trace_id": body.trace_id,
        "report": report.model_dump(),
        "state_excerpt": excerpt,
    }


@router.post("/chat", response_model=PitchChatResponse)
def pitch_chat(body: PitchChatRequest) -> PitchChatResponse:
    reply, tr, tid = invoke_npc_chat(
        tenant_id=body.tenant_id,
        user_message=body.message,
        thread_id=body.thread_id,
        user_name=(body.user_name or "").strip() or None,
    )
    upsert_thread(thread_id=tid, tenant_id=body.tenant_id, preview=body.message)
    return PitchChatResponse(
        reply=reply,
        trace_id=tr,
        thread_id=tid,
        graph_invoked=True,
        exp_delta=12,
        exp_reason="完成一轮 NPC 对话",
    )


@router.get("/threads", response_model=list[PitchThreadSummary])
def list_npc_threads(tenant_id: str = Query(..., min_length=1)) -> list[PitchThreadSummary]:
    rows = list_threads(tenant_id=tenant_id)
    return [PitchThreadSummary(**r) for r in rows]


@router.get("/threads/{thread_id}/messages", response_model=PitchThreadMessagesResponse)
def npc_thread_messages(thread_id: str) -> PitchThreadMessagesResponse:
    msgs = export_thread_messages(thread_id=thread_id)
    return PitchThreadMessagesResponse(thread_id=thread_id, messages=msgs)


@router.post("/upload", response_model=PitchUploadAck)
async def pitch_upload(
    background_tasks: BackgroundTasks,
    tenant_id: str = Form(...),
    file: UploadFile = File(...),
) -> PitchUploadAck:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    job_id = uuid.uuid4().hex
    job_create(job_id, tenant_id)
    fname = file.filename or "upload.bin"
    background_tasks.add_task(
        run_pitch_upload_job,
        job_id=job_id,
        raw_bytes=raw,
        filename=fname,
        tenant_id=tenant_id,
    )
    return PitchUploadAck(job_id=job_id, status=PitchJobStatus.PENDING)


@router.get("/jobs", response_model=list[PitchJobSummary])
def pitch_job_list(
    tenant_id: str = Query(..., min_length=1),
    limit: int = Query(30, ge=1, le=100),
) -> list[PitchJobSummary]:
    out: list[PitchJobSummary] = []
    for jid, j in job_list_for_tenant(tenant_id, limit=limit):
        rep = j.get("report")
        st = j.get("status")
        errs = resolve_stored_job_errors(j, jid)
        # 仅 completed 且确有 report 才视为可消费，避免与转写中态竞态导致前端误显「查看报告」
        has_report = bool(rep is not None and st == PitchJobStatus.COMPLETED)
        out.append(
            PitchJobSummary(
                job_id=jid,
                status=st,
                tenant_id=str(j.get("tenant_id") or tenant_id),
                created_at=float(j.get("created_at") or 0.0),
                exp_delta=int(j.get("exp_delta") or 0),
                exp_reason=str(j.get("exp_reason") or ""),
                error_summary=errs["error_summary"],
                error_detail=errs["error_detail"],
                error_code=errs["error_code"],
                error=errs["error"],
                has_report=has_report,
            )
        )
    return out


@router.get("/jobs/{job_id}", response_model=PitchJobStatusResponse)
def pitch_job_status(job_id: str) -> PitchJobStatusResponse:
    j = job_get(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="unknown job")
    errs = resolve_stored_job_errors(j, job_id)
    return PitchJobStatusResponse(
        job_id=job_id,
        status=j["status"],
        tenant_id=j["tenant_id"],
        created_at=float(j.get("created_at") or 0.0),
        exp_delta=int(j.get("exp_delta") or 0),
        exp_reason=str(j.get("exp_reason") or ""),
        report=j.get("report"),
        error_summary=errs["error_summary"],
        error_detail=errs["error_detail"],
        error_code=errs["error_code"],
        error=errs["error"],
    )


# ---------------------------------------------------------------------------
# Phase 6.4 Task 3 — HITL Review endpoints
# ---------------------------------------------------------------------------


@router.get("/jobs/{job_id}/review", response_model=PitchReviewResponse)
def pitch_job_review_get(job_id: str) -> PitchReviewResponse:
    """Return both original and edited reports for the HITL workbench."""
    job_row = db_job_get(job_id)
    if job_row is None:
        raise HTTPException(status_code=404, detail="unknown job")

    words_json = job_row.get("words_json")
    words_total = len(words_json) if isinstance(words_json, list) else 0

    audio_path = job_row.get("audio_path")
    audio_available = bool(audio_path and Path(audio_path).exists())

    return PitchReviewResponse(
        job_id=job_id,
        status=job_row["status"],
        original_report=job_row.get("original_report"),
        edited_report=job_row.get("edited_report"),
        committed_at=job_row.get("committed_at"),
        words_total=words_total,
        audio_available=audio_available,
    )


@router.patch("/jobs/{job_id}/review", response_model=PitchReviewCommitResponse)
def pitch_job_review_commit(job_id: str, body: PitchReviewCommitRequest) -> PitchReviewCommitResponse:
    """Save human-edited report. Only writes edited_report — never touches original_report."""
    job_row = db_job_get(job_id)
    if job_row is None:
        raise HTTPException(status_code=404, detail="unknown job")

    if not body.edited_report:
        raise HTTPException(status_code=422, detail="edited_report must be a non-empty dict")

    committed_at = time.time()
    db_job_update(job_id, edited_report=body.edited_report, committed_at=committed_at)

    return PitchReviewCommitResponse(job_id=job_id, committed_at=committed_at)


@router.get("/jobs/{job_id}/words")
def pitch_job_words(job_id: str) -> list[dict]:
    """Return the list of transcription words for audio time-alignment."""
    job_row = db_job_get(job_id)
    if job_row is None:
        raise HTTPException(status_code=404, detail="unknown job")

    return job_row.get("words_json") or []


@router.get("/jobs/{job_id}/audio")
def pitch_job_audio(job_id: str) -> FileResponse:
    """Stream the audio file for the given job."""
    job_row = db_job_get(job_id)
    if job_row is None:
        raise HTTPException(status_code=404, detail="unknown job")

    audio_path = job_row.get("audio_path")
    if not audio_path or not Path(audio_path).exists():
        raise HTTPException(status_code=404, detail="audio not available")

    suffix = Path(audio_path).suffix.lower()
    media_type_map = {
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
    }
    media_type = media_type_map.get(suffix, "application/octet-stream")

    return FileResponse(
        path=audio_path,
        media_type=media_type,
        filename=f"pitch-{job_id}{suffix}",
    )
