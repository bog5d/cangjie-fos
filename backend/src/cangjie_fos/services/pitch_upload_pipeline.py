"""上传后：压缩 → ASR → LangGraph 评估（后台任务）。"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from cangjie_fos.core.paths import get_backend_root
from cangjie_fos.engine.transcriber import transcribe_audio
from cangjie_fos.schemas.pitch_upload import PitchJobStatus
from cangjie_fos.services.audio_service import AudioService
from cangjie_fos.services.evolution_injector import build_investor_context
from cangjie_fos.services.pitch_graph_service import PitchGraphService
from cangjie_fos.services.pitch_failure_present import job_failure_update_kwargs
from cangjie_fos.services.pitch_job_store import job_update
from cangjie_fos.services.pitch_job_db import db_job_update

logger = logging.getLogger(__name__)

_MB = 1024 * 1024
_COMPRESS_THRESHOLD_BYTES = 10 * _MB  # must match AudioService


def _mb(n: int) -> str:
    return f"{n / _MB:.0f}MB"


def run_pitch_upload_job(*, job_id: str, raw_bytes: bytes, filename: str, tenant_id: str) -> None:
    """同步后台线程/BackgroundTasks 调用。"""
    tmp: Path | None = None
    audio_path: Path | None = None
    try:
        orig_size = len(raw_bytes)

        # ── 步骤 1：压缩（仅 ≥10MB 文件）─────────────────────────────────
        if orig_size >= _COMPRESS_THRESHOLD_BYTES:
            db_job_update(
                job_id,
                status=str(PitchJobStatus.TRANSCRIBING),
                substatus=f"正在压缩音频（{_mb(orig_size)}）…",
            )
        else:
            db_job_update(
                job_id,
                status=str(PitchJobStatus.TRANSCRIBING),
                substatus="准备上传至转写服务…",
            )
        job_update(job_id, status=PitchJobStatus.TRANSCRIBING)

        compressed = AudioService.smart_compress_media(raw_bytes, filename_hint=filename)
        data = compressed.data
        compressed_size = len(data)

        if getattr(compressed, "did_compress", False):
            db_job_update(
                job_id,
                substatus=f"压缩完成（{_mb(orig_size)} → {_mb(compressed_size)}），写入磁盘…",
            )
        else:
            db_job_update(job_id, substatus="写入磁盘…")

        # ── 步骤 2：写入临时文件 → 移到永久位置 ──────────────────────────
        suffix = Path(filename).suffix or ".bin"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(data)
            tmp = Path(f.name)

        audio_dir = get_backend_root() / "data" / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = audio_dir / f"{job_id}{suffix}"
        shutil.move(str(tmp), str(audio_path))
        tmp = None  # tmp has been moved; don't unlink in finally

        # ── 步骤 3：ASR 转写 ──────────────────────────────────────────────
        db_job_update(job_id, substatus="ASR 转写中，较长录音请耐心等待…")
        words = transcribe_audio(audio_path)
        word_count = len(words)

        # Persist words_json and audio_path to DB
        db_job_update(
            job_id,
            words_json=[w.model_dump() for w in words],
            audio_path=str(audio_path),
            substatus=f"转写完成（{word_count} 词），准备评估…",
        )

        # ── 步骤 4：LangGraph 评估 ────────────────────────────────────────
        job_update(job_id, status=PitchJobStatus.EVALUATING)
        db_job_update(
            job_id,
            status=str(PitchJobStatus.EVALUATING),
            substatus="场景分析中…",
        )

        upload_context: dict = {"source": "fos_upload", "filename": filename}
        upload_context.update(build_investor_context(tenant_id))

        db_job_update(job_id, substatus="风险诊断中（Tier1 / Tier2）…")
        report, _excerpt = PitchGraphService.run_evaluation_with_state(
            tenant_id=tenant_id,
            words=words,
            model_choice="deepseek",
            explicit_context=upload_context,
            qa_text="",
            company_background="",
            trace_id=job_id,
        )

        # ── 步骤 5：后处理 ────────────────────────────────────────────────
        db_job_update(job_id, substatus="生成报告…")
        from cangjie_fos.services.report_post_process import expand_risk_original_text  # noqa: PLC0415

        report_dict = report.model_dump()
        words_list = [w.model_dump() for w in words]
        expand_risk_original_text(report_dict, words_list)

        # In-memory store (backward compat): uses 'report' key
        job_update(
            job_id,
            status=PitchJobStatus.COMPLETED,
            report=report_dict,
            exp_delta=40,
            exp_reason="录音解析并完成 LangGraph 复盘",
        )
        # SQLite: uses 'original_report' key; clear substatus on completion
        db_job_update(
            job_id,
            status=str(PitchJobStatus.COMPLETED),
            original_report=report_dict,
            exp_delta=40,
            exp_reason="录音解析并完成 LangGraph 复盘",
            substatus=None,
        )
        # ── wiki 摄入（非阻塞，失败不影响主流程）────────────────────────────
        try:
            from cangjie_fos.services.wiki_service import ingest_text_to_wiki  # noqa: PLC0415
            words_text = " ".join(w.text for w in (words or []) if w.text)
            if words_text.strip():
                wiki_result = ingest_text_to_wiki(
                    text=words_text,
                    source_type="pitch_recording",
                    source_id=job_id,
                )
                logger.info(
                    "wiki_ingest job_id=%s entities=%d links=%d",
                    job_id,
                    wiki_result.get("entities_updated", 0),
                    wiki_result.get("links_updated", 0),
                )
        except Exception as wiki_exc:  # noqa: BLE001
            logger.warning("wiki_ingest 失败（非致命）job_id=%s exc=%s", job_id, wiki_exc)
        # ── wiki 摄入 END ─────────────────────────────────────────────────

        logger.info("pitch_upload_job_done job_id=%s tenant_id=%s", job_id, tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("pitch_upload_job_failed job_id=%s", job_id)
        failure_kwargs = job_failure_update_kwargs(e, job_id=job_id)
        job_update(job_id, status=PitchJobStatus.FAILED, **failure_kwargs)
        db_update_kwargs = {k: v for k, v in failure_kwargs.items() if k != "status"}
        db_job_update(job_id, status=str(PitchJobStatus.FAILED), substatus=None, **db_update_kwargs)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)  # only unlink if move failed
