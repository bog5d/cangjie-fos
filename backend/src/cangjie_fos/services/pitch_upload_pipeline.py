"""上传后：压缩 → ASR → LangGraph 评估（后台任务）。"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from cangjie_fos.core.paths import ensure_pitch_coach_runtime
from cangjie_fos.schemas.pitch_upload import PitchJobStatus
from cangjie_fos.services.audio_service import AudioService
from cangjie_fos.services.pitch_graph_service import PitchGraphService
from cangjie_fos.services.pitch_failure_present import job_failure_update_kwargs
from cangjie_fos.services.pitch_job_store import job_update

logger = logging.getLogger(__name__)


def run_pitch_upload_job(*, job_id: str, raw_bytes: bytes, filename: str, tenant_id: str) -> None:
    """同步后台线程/BackgroundTasks 调用。"""
    tmp: Path | None = None
    try:
        job_update(job_id, status=PitchJobStatus.TRANSCRIBING)
        compressed = AudioService.smart_compress_media(raw_bytes, filename_hint=filename)
        data = compressed.data
        suffix = Path(filename).suffix or ".bin"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(data)
            tmp = Path(f.name)

        ensure_pitch_coach_runtime()
        from transcriber import transcribe_audio

        words = transcribe_audio(tmp)

        job_update(job_id, status=PitchJobStatus.EVALUATING)
        report, _excerpt = PitchGraphService.run_evaluation_with_state(
            tenant_id=tenant_id,
            words=words,
            model_choice="deepseek",
            explicit_context={"source": "fos_upload", "filename": filename},
            qa_text="",
            company_background="",
            trace_id=job_id,
        )
        job_update(
            job_id,
            status=PitchJobStatus.COMPLETED,
            report=report.model_dump(),
            exp_delta=40,
            exp_reason="录音解析并完成 LangGraph 复盘",
        )
        logger.info("pitch_upload_job_done job_id=%s tenant_id=%s", job_id, tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("pitch_upload_job_failed job_id=%s", job_id)
        job_update(job_id, status=PitchJobStatus.FAILED, **job_failure_update_kwargs(e, job_id=job_id))
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
