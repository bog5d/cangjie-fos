"""Phase 6.2：调用 Coach run_pitch_file_job + 机构情报落盘（临时目录落盘）。"""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from cangjie_fos.core.paths import ensure_pitch_coach_import_path, ensure_pitch_coach_runtime
from cangjie_fos.schemas.pitch_upload import PitchJobStatus
from cangjie_fos.services.pitch_failure_present import job_failure_update_kwargs
from cangjie_fos.services.pitch_job_store import job_update
from cangjie_fos.services.pitch_wizard_batch import build_session_notes

logger = logging.getLogger(__name__)


class _BytesUpload:
    __slots__ = ("name", "_data")

    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


def run_pitch_wizard_track_job(
    *,
    job_id: str,
    tenant_id: str,
    audio_path: Path,
    recording_label: str,
    category: str,
    project_name: str,
    interviewee: str,
    session_notes: str,
    sniper_targets_json: str,
    custom_roles_other: str,
    qa_text: str,
    company_background: str,
    sensitive_words: list[str],
    hot_words: list[str] | None,
    memory_company_id: str,
    skip_asr_polish: bool,
    use_langgraph_v1: bool,
) -> None:
    """后台线程入口：单条音频完整 Coach 流水线（skip HTML）。"""
    tmpdir = Path(tempfile.mkdtemp(prefix=f"fos_wiz_{job_id}_"))
    trans_json = tmpdir / "transcription.json"
    analysis_json = tmpdir / "analysis_report.json"
    html_path = tmpdir / "report_placeholder.html"
    try:
        job_update(job_id, status=PitchJobStatus.TRANSCRIBING)
        ensure_pitch_coach_runtime()
        from job_pipeline import PitchFileJobParams, build_explicit_context, run_pitch_file_job
        from report_builder import HtmlExportOptions

        explicit_context = build_explicit_context(
            category,
            project_name,
            interviewee,
            session_notes=session_notes,
            sniper_targets_json=sniper_targets_json,
            recording_label=recording_label,
            custom_roles_other=custom_roles_other,
        )
        params = PitchFileJobParams(
            transcription_json_path=trans_json,
            analysis_json_path=analysis_json,
            html_output_path=html_path,
            sensitive_words=sensitive_words,
            explicit_context=explicit_context,
            qa_text=qa_text,
            model_choice="deepseek",
            html_export_options=HtmlExportOptions(),
            hot_words=hot_words,
            company_background=company_background,
            memory_company_id=memory_company_id,
            skip_asr_polish=skip_asr_polish,
            use_langgraph_v1=use_langgraph_v1,
        )
        job_update(job_id, status=PitchJobStatus.EVALUATING)

        words, report = run_pitch_file_job(
            audio_path,
            params,
            on_status=None,
            skip_html_export=True,
            cached_words=None,
        )

        try:
            from cangjie_fos.services.institution_intel_extract import extract_and_persist_institution_intel

            extract_and_persist_institution_intel(
                tenant_id=tenant_id,
                words=words,
                report=report,
                trace_id=job_id,
                explicit_context=dict(explicit_context),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("institution_intel_extract_skipped wizard: %s", e)

        job_update(
            job_id,
            status=PitchJobStatus.COMPLETED,
            report=report.model_dump(),
            exp_delta=40,
            exp_reason="向导提交：录音解析并完成 LangGraph 复盘",
        )
        logger.info("pitch_wizard_job_done job_id=%s tenant_id=%s", job_id, tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("pitch_wizard_job_failed job_id=%s", job_id)
        job_update(job_id, status=PitchJobStatus.FAILED, **job_failure_update_kwargs(e, job_id=job_id))
    finally:
        try:
            import shutil

            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass
        try:
            audio_path.unlink(missing_ok=True)
        except OSError:
            pass


def merge_qa_text_from_paths(qa_items: list[dict[str, str]], *, max_chars: int = 30000) -> str:
    ensure_pitch_coach_import_path()
    from document_reader import extract_text_from_files

    uploads: list[_BytesUpload] = []
    for it in qa_items or []:
        p = Path(it.get("path") or "")
        name = it.get("name") or "qa.bin"
        if not p.is_file():
            continue
        uploads.append(_BytesUpload(name, p.read_bytes()))
    return extract_text_from_files(uploads, max_chars=max_chars) if uploads else ""
