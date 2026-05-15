"""LangGraph 融资评估 REST 桥接（Phase 2 SPEC A5）+ Phase 3 对话/上传。"""
from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from cangjie_fos.api.upload_io import stream_upload_to_path
from cangjie_fos.core.paths import get_backend_root, get_audio_dir
from cangjie_fos.core.job_semaphore import release_job_slot, try_reserve_jobs
from cangjie_fos.services import github_sync
from cangjie_fos.engine.schema import TranscriptionWord as _TranscriptionWord
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
from cangjie_fos.services.pitch_job_db import db_job_get, db_job_update, db_job_list_for_tenant
from cangjie_fos.services.pitch_job_store import job_create, job_get, job_list_for_tenant
from cangjie_fos.services.pitch_upload_pipeline import run_pitch_upload_job

logger = logging.getLogger(__name__)


def _run_retry_eval(*, job_id: str, tenant_id: str, words_json: list) -> None:
    """Background task: re-run LangGraph eval using stored words_json."""
    from cangjie_fos.services.pitch_failure_present import job_failure_update_kwargs  # noqa: PLC0415
    from cangjie_fos.services.pitch_job_store import job_update  # noqa: PLC0415
    from cangjie_fos.services.report_post_process import expand_risk_original_text  # noqa: PLC0415

    try:
        try:
            words: list = [_TranscriptionWord(**w) for w in words_json]
        except Exception:  # noqa: BLE001
            words = words_json  # type: ignore[assignment]
        db_job_update(job_id, substatus="场景分析中（重跑）…")

        report, _excerpt = PitchGraphService.run_evaluation_with_state(
            tenant_id=tenant_id,
            words=words,
            model_choice="deepseek",
            trace_id=job_id,
        )

        report_dict = report.model_dump()
        expand_risk_original_text(report_dict, words_json)

        job_update(
            job_id,
            status=PitchJobStatus.COMPLETED,
            report=report_dict,
            exp_delta=20,
            exp_reason="重跑 LangGraph 评估完成",
            substatus=None,
        )
        db_job_update(
            job_id,
            status=str(PitchJobStatus.COMPLETED),
            original_report=report_dict,
            exp_delta=20,
            exp_reason="重跑 LangGraph 评估完成",
            substatus=None,
        )
        logger.info("retry_eval_done job_id=%s tenant_id=%s", job_id, tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("retry_eval_failed job_id=%s", job_id)
        failure_kwargs = job_failure_update_kwargs(e, job_id=job_id)
        job_update(job_id, status=PitchJobStatus.FAILED, **failure_kwargs)
        db_update_kwargs = {k: v for k, v in failure_kwargs.items() if k != "status"}
        db_job_update(job_id, status=str(PitchJobStatus.FAILED), substatus=None, **db_update_kwargs)


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

    words = [
        _TranscriptionWord(
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

    job_id = uuid.uuid4().hex
    fname = file.filename or "upload.bin"
    suffix = Path(fname).suffix or ".bin"

    # 流式落盘：直接写到 data/audio/，不把整个文件读入内存
    audio_dir = get_audio_dir()
    audio_dir.mkdir(parents=True, exist_ok=True)
    incoming_path = audio_dir / f"{job_id}_incoming{suffix}"

    try:
        bytes_written = await stream_upload_to_path(file, incoming_path)
        if bytes_written == 0:
            incoming_path.unlink(missing_ok=True)
            release_job_slot()
            raise HTTPException(status_code=400, detail="empty file")
    except HTTPException:
        incoming_path.unlink(missing_ok=True)
        release_job_slot()
        raise

    job_create(job_id, tenant_id)

    def _run() -> None:
        try:
            run_pitch_upload_job(
                job_id=job_id,
                pre_written_path=incoming_path,
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
    page: int = Query(1, ge=1, description="页码（1-based），与 size 配合使用"),
    size: int = Query(20, ge=1, le=100, description="每页条数"),
) -> list[PitchJobSummary]:
    # page>1 时使用 SQLite 分页（支持 OFFSET）；page=1 保持原有行为（内存 store）
    use_db_pagination = page > 1
    effective_limit = size if use_db_pagination else limit
    effective_offset = (page - 1) * size if use_db_pagination else 0

    if use_db_pagination:
        job_pairs: list[tuple[str, dict]] = db_job_list_for_tenant(
            tenant_id, limit=effective_limit, offset=effective_offset
        )
    else:
        job_pairs = list(job_list_for_tenant(tenant_id, limit=effective_limit))

    out: list[PitchJobSummary] = []
    for jid, j in job_pairs:
        rep = j.get("report") or j.get("original_report")
        st = j.get("status")
        errs = resolve_stored_job_errors(j, jid)
        # 仅 completed 且确有 report 才视为可消费
        has_report = bool(
            rep is not None
            and (st == PitchJobStatus.COMPLETED or st == "completed")
        )
        # substatus / words_json: SQLite 分页路径已有完整行，否则按需查
        if use_db_pagination:
            db_row = j
        else:
            db_row = db_job_get(jid)
        substatus = db_row.get("substatus") if db_row else None
        _words = db_row.get("words_json") if db_row else None
        has_words_json = isinstance(_words, list) and len(_words) > 0
        participants_confirmed = bool(db_row.get("participants_confirmed")) if db_row else False
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
                has_words_json=has_words_json,
                warnings=j.get("warnings"),
                substatus=substatus,
                participants_confirmed=participants_confirmed,
                interviewee=db_row.get("interviewee") if db_row else None,
                category=db_row.get("category") if db_row else None,
                institution_id=db_row.get("institution_id") if db_row else None,
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
    # GitHub 同步：把路演报告 push 到 coach_data 仓库
    background_tasks.add_task(github_sync.push_pitch_job, job_id)

    return PitchReviewCommitResponse(job_id=job_id, committed_at=committed_at)


@router.delete("/jobs/{job_id}/review-lock")
def pitch_job_review_unlock(job_id: str) -> dict:
    """解除审查锁定，允许重新编辑报告（仅清除 committed_at，保留 edited_report）。"""
    job_row = db_job_get(job_id)
    if job_row is None:
        raise HTTPException(status_code=404, detail="unknown job")
    db_job_update(job_id, committed_at=None)
    return {"ok": True, "job_id": job_id}


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
    from cangjie_fos.core.paths import get_backend_root, get_audio_dir  # noqa: PLC0415

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


@router.post("/jobs/{job_id}/retry-eval", response_model=PitchUploadAck)
def retry_eval(job_id: str, background_tasks: BackgroundTasks) -> PitchUploadAck:
    """重跑 LangGraph 评估（无需重新上传音频，从 words_json 恢复）。

    条件：job 存在 + words_json 非空 + 当前不在 active 状态。
    """
    job_row = db_job_get(job_id)
    if job_row is None:
        raise HTTPException(status_code=404, detail="unknown job")

    active_statuses = {
        str(PitchJobStatus.PENDING),
        str(PitchJobStatus.TRANSCRIBING),
        str(PitchJobStatus.EVALUATING),
    }
    if str(job_row.get("status")) in active_statuses:
        raise HTTPException(status_code=409, detail="job is already active; wait for it to finish")

    words_json = job_row.get("words_json")
    if not isinstance(words_json, list) or not words_json:
        raise HTTPException(
            status_code=422,
            detail="no words_json available; please re-upload the audio file",
        )

    tenant_id = job_row.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=500, detail="job record missing tenant_id")
    tenant_id = str(tenant_id)
    db_job_update(
        job_id,
        status=str(PitchJobStatus.EVALUATING),
        substatus="准备重跑评估…",
        error_summary=None,
        error_detail=None,
        error_code=None,
    )
    from cangjie_fos.services.pitch_job_store import job_update as _job_update  # noqa: PLC0415
    _job_update(job_id, status=PitchJobStatus.EVALUATING, error_summary=None, error_detail=None, error_code=None)

    background_tasks.add_task(
        _run_retry_eval,
        job_id=job_id,
        tenant_id=tenant_id,
        words_json=words_json,
    )
    logger.info("retry_eval_queued job_id=%s tenant_id=%s", job_id, tenant_id)
    return PitchUploadAck(job_id=job_id, status=PitchJobStatus.EVALUATING)


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
    from cangjie_fos.core.paths import get_backend_root, get_audio_dir  # noqa: PLC0415
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
    # 健康检查：创建并验证关键目录
    audio_d = get_audio_dir()
    audio_d.mkdir(parents=True, exist_ok=True)
    if not audio_d.is_dir():
        issues.append("missing dir: audio")
    html_d = root / "data" / "html_reports"
    html_d.mkdir(parents=True, exist_ok=True)
    if not html_d.is_dir():
        issues.append("missing dir: data/html_reports")

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


@router.get("/institution-stats")
def get_institution_pitch_stats(
    tenant_id: str = Query(..., description="租户 ID"),
) -> list[dict]:
    """返回各机构的路演次数和最近路演时间（用于机构列表展示）。

    数据合并自 pitch_jobs.institution_id 和 job_participants.institution，
    确保即使参与人确认绑定不完整也能统计到数据。
    """
    from cangjie_fos.services.pitch_job_db import db_institution_pitch_stats  # noqa: PLC0415

    return db_institution_pitch_stats(tenant_id)
