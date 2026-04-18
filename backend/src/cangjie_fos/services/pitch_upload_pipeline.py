"""上传后：压缩 → ASR → LangGraph 评估（后台任务）。"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from cangjie_fos.core.paths import ensure_pitch_coach_runtime, get_backend_root
from cangjie_fos.schemas.pitch_upload import PitchJobStatus
from cangjie_fos.services.audio_service import AudioService
from cangjie_fos.services.pitch_graph_service import PitchGraphService
from cangjie_fos.services.pitch_failure_present import job_failure_update_kwargs
from cangjie_fos.services.pitch_job_store import job_update
from cangjie_fos.services.pitch_job_db import db_job_update

logger = logging.getLogger(__name__)


def run_pitch_upload_job(*, job_id: str, raw_bytes: bytes, filename: str, tenant_id: str) -> None:
    """同步后台线程/BackgroundTasks 调用。"""
    tmp: Path | None = None
    audio_path: Path | None = None
    try:
        job_update(job_id, status=PitchJobStatus.TRANSCRIBING)
        db_job_update(job_id, status=str(PitchJobStatus.TRANSCRIBING))

        compressed = AudioService.smart_compress_media(raw_bytes, filename_hint=filename)
        data = compressed.data
        suffix = Path(filename).suffix or ".bin"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(data)
            tmp = Path(f.name)

        # Move audio to permanent location
        audio_dir = get_backend_root() / "data" / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = audio_dir / f"{job_id}{suffix}"
        shutil.move(str(tmp), str(audio_path))
        tmp = None  # tmp has been moved; don't unlink in finally

        ensure_pitch_coach_runtime()
        from transcriber import transcribe_audio

        words = transcribe_audio(audio_path)

        # Persist words_json and audio_path to DB
        db_job_update(
            job_id,
            words_json=[w.model_dump() for w in words],
            audio_path=str(audio_path),
        )

        job_update(job_id, status=PitchJobStatus.EVALUATING)
        db_job_update(job_id, status=str(PitchJobStatus.EVALUATING))

        report, _excerpt = PitchGraphService.run_evaluation_with_state(
            tenant_id=tenant_id,
            words=words,
            model_choice="deepseek",
            explicit_context={"source": "fos_upload", "filename": filename},
            qa_text="",
            company_background="",
            trace_id=job_id,
        )

        # In-memory store (backward compat): uses 'report' key
        job_update(
            job_id,
            status=PitchJobStatus.COMPLETED,
            report=report.model_dump(),
            exp_delta=40,
            exp_reason="录音解析并完成 LangGraph 复盘",
        )
        # SQLite: uses 'original_report' key
        db_job_update(
            job_id,
            status=str(PitchJobStatus.COMPLETED),
            original_report=report.model_dump(),
            exp_delta=40,
            exp_reason="录音解析并完成 LangGraph 复盘",
        )
        logger.info("pitch_upload_job_done job_id=%s tenant_id=%s", job_id, tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("pitch_upload_job_failed job_id=%s", job_id)
        failure_kwargs = job_failure_update_kwargs(e, job_id=job_id)
        job_update(job_id, status=PitchJobStatus.FAILED, **failure_kwargs)
        db_update_kwargs = {k: v for k, v in failure_kwargs.items() if k != "status"}
        db_job_update(job_id, status=str(PitchJobStatus.FAILED), **db_update_kwargs)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)  # only unlink if move failed
