"""Phase 6.2：两阶段上传向导 API（JSON session + multipart 分片 + commit）。"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile

from cangjie_fos.api.upload_io import read_upload_limited
from cangjie_fos.core.job_semaphore import release_job_slot, try_reserve_jobs
from cangjie_fos.core.paths import ensure_pitch_coach_import_path
from cangjie_fos.events.npc_ws_house import schedule_broadcast_to_tenant
from cangjie_fos.schemas.pitch_upload_wizard import (
    UploadSessionCommitResponse,
    UploadSessionCreateResponse,
    UploadWizardCreateRequest,
    WizardPartAck,
)
from cangjie_fos.services.pitch_job_store import job_create
from cangjie_fos.services.pitch_upload_session_store import (
    session_append_qa,
    session_create,
    session_delete,
    session_get,
    session_set_audio,
)
from cangjie_fos.services.pitch_wizard_batch import (
    SCENE_PLACEHOLDER,
    build_session_notes as _build_notes,
    compute_batch_name,
    safe_fs_segment,
    sniper_rows_to_json,
)
from cangjie_fos.services.pitch_wizard_runner import merge_qa_text_from_paths, run_pitch_wizard_track_job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/pitch", tags=["pitch-wizard"])


def _coach_scene_keys() -> tuple[dict[str, str], str]:
    ensure_pitch_coach_import_path()
    from job_pipeline import OTHER_SCENE_KEY, SCENE_MAP

    return SCENE_MAP, OTHER_SCENE_KEY


def _validate_wizard(payload: UploadWizardCreateRequest) -> None:
    if payload.category.strip() == SCENE_PLACEHOLDER:
        raise HTTPException(status_code=400, detail="请选择真实业务大类")
    sc, other = _coach_scene_keys()
    valid = set(sc.keys()) | {other}
    if payload.category not in valid:
        raise HTTPException(status_code=400, detail=f"未知业务大类: {payload.category}")
    if payload.category == other and not (payload.custom_roles_other or "").strip():
        raise HTTPException(status_code=400, detail="其他场景须填写具体双方身份")
    if not (payload.institution_name or "").strip():
        raise HTTPException(status_code=400, detail="请填写投资机构名称")
    for i, t in enumerate(payload.tracks):
        if not (t.interviewee or "").strip():
            raise HTTPException(status_code=400, detail=f"第 {i + 1} 条录音缺少被访谈人")


@router.post("/upload-sessions", response_model=UploadSessionCreateResponse)
def create_upload_session(body: UploadWizardCreateRequest) -> UploadSessionCreateResponse:
    """Phase A：仅 JSON，不落音频。"""
    if not body.tracks:
        raise HTTPException(status_code=400, detail="至少一条录音轨道")
    sid = session_create(body)
    return UploadSessionCreateResponse(session_id=sid, track_count=len(body.tracks))


@router.post("/upload-sessions/{session_id}/tracks/{track_index}/audio", response_model=WizardPartAck)
async def upload_session_audio(
    session_id: str,
    track_index: int,
    file: UploadFile = File(...),
) -> WizardPartAck:
    """Phase B：单条轨道音频。"""
    s = session_get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="unknown session")
    payload = UploadWizardCreateRequest.model_validate(s["payload"])
    if track_index < 0 or track_index >= len(payload.tracks):
        raise HTTPException(status_code=400, detail="track_index 越界")
    raw = await read_upload_limited(file)
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    suffix = Path(file.filename or "upload.bin").suffix or ".bin"
    fd, name = tempfile.mkstemp(prefix="fos_audio_", suffix=suffix)
    os.close(fd)
    Path(name).write_bytes(raw)
    ok = session_set_audio(session_id, track_index, Path(name), file.filename or "upload.bin")
    if not ok:
        Path(name).unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail="session lost")
    return WizardPartAck(ok=True, track_index=track_index)


@router.post("/upload-sessions/{session_id}/tracks/{track_index}/qa", response_model=dict)
async def upload_session_qa(
    session_id: str,
    track_index: int,
    file: UploadFile = File(...),
) -> dict[str, bool]:
    """Phase B：追加本条参考 QA（可多调）。"""
    s = session_get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="unknown session")
    payload = UploadWizardCreateRequest.model_validate(s["payload"])
    if track_index < 0 or track_index >= len(payload.tracks):
        raise HTTPException(status_code=400, detail="track_index 越界")
    raw = await read_upload_limited(file)
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    suffix = Path(file.filename or "qa.bin").suffix or ".bin"
    fd, name = tempfile.mkstemp(prefix="fos_qa_", suffix=suffix)
    os.close(fd)
    Path(name).write_bytes(raw)
    ok = session_append_qa(
        session_id, track_index, temp_path=Path(name), original_name=file.filename or "qa.bin"
    )
    if not ok:
        Path(name).unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail="session lost")
    return {"ok": True}


@router.post("/upload-sessions/{session_id}/commit", response_model=UploadSessionCommitResponse)
def commit_upload_session(
    request: Request,
    session_id: str,
    background_tasks: BackgroundTasks,
) -> UploadSessionCommitResponse:
    """Phase C：校验、起 job、WS/HTTP 双通道豆豆反馈。"""
    raw = session_get(session_id)
    if not raw:
        raise HTTPException(status_code=404, detail="unknown session")
    payload = UploadWizardCreateRequest.model_validate(raw["payload"])
    _validate_wizard(payload)

    n = len(payload.tracks)
    audio_map: dict[int, str] = {int(k): v for k, v in (raw.get("audio") or {}).items()}
    filenames: dict[int, str] = {int(k): v for k, v in (raw.get("filenames") or {}).items()}
    qa_map: dict[int, list[dict[str, str]]] = raw.get("qa") or {}

    for i in range(n):
        if i not in audio_map:
            raise HTTPException(status_code=400, detail=f"轨道 {i} 尚未上传音频")

    if not try_reserve_jobs(n):
        raise HTTPException(
            status_code=429,
            detail={"code": "E_QUEUE_FULL", "message": "任务队列已满，请稍后或减少同时提交数"},
        )

    ensure_pitch_coach_import_path()
    from sensitive_words import parse_sensitive_words

    sensitive = parse_sensitive_words(payload.sensitive_words_raw or "")
    hw_raw = payload.hot_words_raw or ""
    hot_words = [
        w.strip()
        for w in hw_raw.replace("，", ",").replace("；", ",").split(",")
        if w.strip()
    ] or None

    project_name = compute_batch_name(
        institution_name=payload.institution_name, batch_label=payload.batch_label
    )
    skip_asr_polish = not bool(payload.enable_asr_polish)
    mem_cid = (payload.memory_company_id or "").strip() or payload.tenant_id

    job_ids: list[str] = []
    for i, tr in enumerate(payload.tracks):
        src = Path(audio_map[i])
        if not src.is_file():
            raise HTTPException(status_code=400, detail=f"轨道 {i} 音频丢失")
        fd, dst_name = tempfile.mkstemp(suffix=src.suffix or ".bin", prefix=f"fos_job_{i}_")
        os.close(fd)
        dst = Path(dst_name)
        shutil.copyfile(src, dst)
        src.unlink(missing_ok=True)

        qa_items = list(qa_map.get(i) or [])
        qa_text = merge_qa_text_from_paths(qa_items)
        for it in qa_items:
            try:
                Path(it["path"]).unlink(missing_ok=True)
            except (KeyError, OSError):
                pass

        sniper_json = sniper_rows_to_json(tr.sniper_rows)
        notes = _build_notes(
            institution_name=payload.institution_name,
            investor_name=payload.investor_name,
            interviewee=tr.interviewee,
            speaker_hint=tr.speaker_hint,
        )
        rec_label = filenames.get(i) or tr.client_temp_id

        job_id = uuid.uuid4().hex
        job_create(
            job_id,
            payload.tenant_id,
            submitted_by=(payload.user_name or "").strip(),
            upload_session_id=session_id,
            wizard_track_index=i,
            interviewee=tr.interviewee.strip(),
        )
        job_ids.append(job_id)

        kw = dict(
            job_id=job_id,
            tenant_id=payload.tenant_id,
            audio_path=dst,
            recording_label=rec_label,
            category=payload.category,
            project_name=project_name,
            interviewee=tr.interviewee.strip(),
            session_notes=notes,
            sniper_targets_json=sniper_json,
            custom_roles_other=(payload.custom_roles_other or "").strip(),
            qa_text=qa_text,
            company_background=payload.company_background or "",
            sensitive_words=sensitive,
            hot_words=hot_words,
            memory_company_id=mem_cid,
            skip_asr_polish=skip_asr_polish,
            use_langgraph_v1=bool(payload.use_langgraph_v1),
        )

        snap = dict(kw)

        def _run(captured: dict = snap) -> None:  # noqa: B008
            try:
                run_pitch_wizard_track_job(**captured)  # type: ignore[arg-type]
            finally:
                release_job_slot()

        background_tasks.add_task(_run)

    inst = safe_fs_segment(payload.institution_name)
    assistant_echo = (
        f"豆豆：已收到 {n} 条关于「{inst}」的录音，正在逐条分析…"
        f"（任务数 {len(job_ids)}，可在任务状态轮询查看进度）"
    )
    ws_payload = {
        "type": "upload_job_started",
        "message": assistant_echo,
        "job_ids": job_ids,
        "tenant_id": payload.tenant_id,
    }
    schedule_broadcast_to_tenant(payload.tenant_id, ws_payload)

    session_delete(session_id)

    logger.info(
        "pitch_wizard_committed request_id=%s session=%s jobs=%s tenant=%s submitted_by=%s",
        getattr(request.state, "request_id", ""),
        session_id,
        job_ids,
        payload.tenant_id,
        (payload.user_name or "").strip(),
    )
    return UploadSessionCommitResponse(job_ids=job_ids, assistant_echo=assistant_echo)
