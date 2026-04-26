"""LangGraph 融资评估 REST 桥接（Phase 2 SPEC A5）+ Phase 3 对话/上传。"""
from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from cangjie_fos.api.upload_io import read_upload_limited
from cangjie_fos.core.job_semaphore import release_job_slot, try_reserve_jobs
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
    PitchHtmlReportResponse,
    PitchJobStatus,
    PitchJobStatusResponse,
    PitchJobSummary,
    PitchReviewCommitRequest,
    PitchReviewCommitResponse,
    PitchReviewResponse,
    PitchUploadAck,
    WordsSummary,
)
from cangjie_fos.services.html_report_service import generate_job_html_report
from cangjie_fos.services.npc_chat_graph import export_thread_messages, invoke_npc_chat
from cangjie_fos.services.pitch_graph_service import PitchGraphService
from cangjie_fos.services.pitch_failure_present import resolve_stored_job_errors
from cangjie_fos.services.evolution_capture import capture_review_diff
from cangjie_fos.services.evolution_extractor import run_preference_extraction
from cangjie_fos.services.pitch_job_db import db_job_get, db_job_update
from cangjie_fos.services.pitch_job_store import job_create, job_get, job_list_for_tenant
from cangjie_fos.services.pitch_upload_pipeline import run_pitch_upload_job

logger = logging.getLogger(__name__)
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
        active_job_id=body.active_job_id,
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
    request: Request,
    background_tasks: BackgroundTasks,
    tenant_id: str = Form(...),
    file: UploadFile = File(...),
) -> PitchUploadAck:
    if not try_reserve_jobs(1):
        raise HTTPException(
            status_code=429,
            detail={"code": "E_QUEUE_FULL", "message": "任务队列已满，请稍后再试"},
        )
    try:
        raw = await read_upload_limited(file)
        if not raw:
            raise HTTPException(status_code=400, detail="empty file")
    except HTTPException:
        release_job_slot()
        raise
    job_id = uuid.uuid4().hex
    job_create(job_id, tenant_id)
    fname = file.filename or "upload.bin"

    def _run() -> None:
        try:
            run_pitch_upload_job(
                job_id=job_id,
                raw_bytes=raw,
                filename=fname,
                tenant_id=tenant_id,
            )
        finally:
            release_job_slot()

    background_tasks.add_task(_run)
    logger.info(
        "pitch_upload_queued request_id=%s job_id=%s tenant_id=%s",
        getattr(request.state, "request_id", ""),
        job_id,
        tenant_id,
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
        # substatus lives only in SQLite (not in-memory store)
        db_row = db_job_get(jid)
        substatus = db_row.get("substatus") if db_row else None
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
                warnings=j.get("warnings"),
                substatus=substatus,
            )
        )
    return out


@router.get("/jobs/{job_id}", response_model=PitchJobStatusResponse)
def pitch_job_status(job_id: str) -> PitchJobStatusResponse:
    j = job_get(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="unknown job")
    errs = resolve_stored_job_errors(j, job_id)
    job_row = db_job_get(job_id)
    warnings = job_row.get("warnings") if job_row else None
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
        warnings=warnings,
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
    words_list = words_json if isinstance(words_json, list) else []
    words_total = len(words_list)
    duration_sec = 0.0
    if words_list:
        last = words_list[-1]
        duration_sec = float(last.get("end_time", 0) or 0)

    audio_path = job_row.get("audio_path")
    audio_available = bool(audio_path and Path(audio_path).exists())

    return PitchReviewResponse(
        job_id=job_id,
        status=job_row["status"],
        original_report=job_row.get("original_report"),
        edited_report=job_row.get("edited_report"),
        committed_at=job_row.get("committed_at"),
        words_summary=WordsSummary(total_words=words_total, duration_sec=duration_sec),
        audio_available=audio_available,
        interviewee=job_row.get("interviewee"),
    )


@router.patch("/jobs/{job_id}/review", response_model=PitchReviewCommitResponse)
def pitch_job_review_commit(
    job_id: str, body: PitchReviewCommitRequest, background_tasks: BackgroundTasks
) -> PitchReviewCommitResponse:
    """Save human-edited report and capture diff for self-evolution flywheel."""
    job_row = db_job_get(job_id)
    if job_row is None:
        raise HTTPException(status_code=404, detail="unknown job")

    if not body.edited_report:
        raise HTTPException(status_code=422, detail="edited_report must be a non-empty dict")

    committed_at = time.time()
    original_report: dict | None = job_row.get("original_report")
    tenant_id: str = job_row.get("tenant_id", "unknown")

    db_job_update(job_id, edited_report=body.edited_report, committed_at=committed_at)

    background_tasks.add_task(
        capture_review_diff,
        job_id=job_id,
        tenant_id=tenant_id,
        committed_at=committed_at,
        original_report=original_report,
        edited_report=body.edited_report,
    )
    background_tasks.add_task(run_preference_extraction, tenant_id=tenant_id)

    return PitchReviewCommitResponse(job_id=job_id, committed_at=committed_at)


@router.post("/jobs/{job_id}/html-report", response_model=PitchHtmlReportResponse)
def generate_html_report_endpoint(job_id: str) -> PitchHtmlReportResponse:
    """Trigger FFmpeg-based HTML report generation for a completed job.

    Uses edited_report if committed, else original_report.
    Requires audio file and words_json to be present in DB.
    """
    try:
        result_path = generate_job_html_report(job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}") from e
    return PitchHtmlReportResponse(
        job_id=job_id,
        html_path=str(result_path),
        generated_at=time.time(),
    )


@router.get("/jobs/{job_id}/html-report")
def get_html_report_endpoint(job_id: str) -> FileResponse:
    """Serve the generated HTML report file."""
    from cangjie_fos.core.paths import get_backend_root  # noqa: PLC0415

    report_path = get_backend_root() / "data" / "html_reports" / f"{job_id}.html"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="HTML report not yet generated")
    return FileResponse(
        path=str(report_path),
        media_type="text/html",
        filename=f"report_{job_id}.html",
    )


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


@router.get("/health")
def health_check() -> dict:
    """系统健康检查：DB 连通性 + 目录 + 关键依赖。"""
    from cangjie_fos.core.paths import get_backend_root  # noqa: PLC0415
    from cangjie_fos.services.pitch_job_db import _connect  # noqa: PLC0415
    import importlib

    issues: list[str] = []

    try:
        conn = _connect()
        conn.execute("SELECT 1")
        conn.close()
    except Exception as e:  # noqa: BLE001
        issues.append(f"db: {e}")

    root = get_backend_root()
    for d in ["data/audio", "data/html_reports"]:
        p = root / d
        p.mkdir(parents=True, exist_ok=True)
        if not p.is_dir():
            issues.append(f"missing dir: {d}")

    for pkg in ["pandas", "docx", "jinja2", "openai"]:
        try:
            importlib.import_module(pkg)
        except ImportError:
            issues.append(f"missing pkg: {pkg}")

    status = "ok" if not issues else "degraded"
    return {"status": status, "issues": issues}


@router.get("/prefs")
def get_investor_prefs(
    tenant_id: str = Query(..., description="租户 ID"),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """返回该租户的历史投资人偏好列表及摘要。"""
    from cangjie_fos.services.pitch_job_db import db_pref_list_for_tenant  # noqa: PLC0415
    from cangjie_fos.services.evolution_injector import build_investor_context  # noqa: PLC0415

    prefs = db_pref_list_for_tenant(tenant_id, limit=limit)
    context = build_investor_context(tenant_id)
    return {
        "tenant_id": tenant_id,
        "total": len(prefs),
        "prefs": prefs,
        "injected_context": context.get("investor_preferences", ""),
    }
