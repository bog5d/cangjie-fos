"""Phase 6.2：调用 Coach run_pitch_file_job + 机构情报落盘（临时目录落盘）。"""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from cangjie_fos.core.paths import get_backend_root
from cangjie_fos.engine.job_pipeline import HtmlExportOptions, PitchFileJobParams, build_explicit_context, run_pitch_file_job
from cangjie_fos.engine.document_reader import extract_text_from_files
from cangjie_fos.schemas.pitch_upload import PitchJobStatus
from cangjie_fos.services.evolution_injector import build_investor_context
from cangjie_fos.services.pitch_failure_present import job_failure_update_kwargs
from cangjie_fos.services.pitch_job_db import db_job_update
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


def _text_to_words(text: str) -> list[dict]:
    """把文字稿转换为 words_json 格式（跳过 ASR，直接走 LangGraph）。

    支持手机 ASR 说话人格式：
      - "说话人A: 内容"  / "说话人 1: 内容"
      - "Speaker A: 内容" / "S1: 内容"
    没有说话人标记时统一归 speaker_id="0"。
    """
    import re

    speaker_re = re.compile(
        r"^(?:说话人\s*|Speaker\s*|S)([^\s:：]{1,10})\s*[：:]\s*(.+)",
        re.IGNORECASE,
    )
    words: list[dict] = []
    fake_time = 0.0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = speaker_re.match(line)
        if m:
            speaker_id = m.group(1).strip()
            content = m.group(2).strip()
        else:
            speaker_id = "0"
            content = line
        if not content:
            continue
        end_time = fake_time + max(2.0, len(content) * 0.15)
        words.append(
            {
                "word_index": len(words),
                "text": content,
                "start_time": round(fake_time, 2),
                "end_time": round(end_time, 2),
                "speaker_id": speaker_id,
            }
        )
        fake_time = end_time + 0.5
    return words


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
    permanent_audio_path: Path | None = None
    try:
        job_update(job_id, status=PitchJobStatus.TRANSCRIBING)
        db_job_update(job_id, status=str(PitchJobStatus.TRANSCRIBING), category=category)
        explicit_context = build_explicit_context(
            category,
            project_name,
            interviewee,
            session_notes=session_notes,
            sniper_targets_json=sniper_targets_json,
            recording_label=recording_label,
            custom_roles_other=custom_roles_other,
        )
        explicit_context.update(build_investor_context(memory_company_id))
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
        # ── 文字稿模式（.txt）：跳过 ASR，直接转换为 words_json ──────────────
        is_transcript_mode = audio_path.suffix.lower() == ".txt"
        if is_transcript_mode:
            logger.info("transcript_mode job_id=%s: 跳过 ASR，直接解析文字稿", job_id)
            transcript_text = audio_path.read_text(encoding="utf-8", errors="ignore")
            # 把文字稿也追加到 qa_text，补充 LangGraph 上下文
            combined_qa = (transcript_text + "\n\n" + params.qa_text).strip()
            params = PitchFileJobParams(
                transcription_json_path=params.transcription_json_path,
                analysis_json_path=params.analysis_json_path,
                html_output_path=params.html_output_path,
                sensitive_words=params.sensitive_words,
                explicit_context=params.explicit_context,
                qa_text=combined_qa,
                model_choice=params.model_choice,
                html_export_options=params.html_export_options,
                hot_words=params.hot_words,
                company_background=params.company_background,
                memory_company_id=params.memory_company_id,
                skip_asr_polish=params.skip_asr_polish,
                use_langgraph_v1=params.use_langgraph_v1,
            )
            fake_words_list = _text_to_words(transcript_text)
            # 直接用 fake_words_list 跑 LangGraph（通过 cached_words）
            job_update(job_id, status=PitchJobStatus.EVALUATING)
            db_job_update(job_id, status=str(PitchJobStatus.EVALUATING))
            from cangjie_fos.engine.schema import TranscriptionWord  # noqa: PLC0415
            cached = [TranscriptionWord(**w) for w in fake_words_list]
            words, report = run_pitch_file_job(
                audio_path,
                params,
                on_status=None,
                skip_html_export=True,
                cached_words=cached,
            )
        else:
            # ── 普通音频模式（含 FFmpeg 压缩网关，与旧版单文件上传保持一致）──────
            from cangjie_fos.services.audio_service import AudioService  # noqa: PLC0415
            audio_dir = get_backend_root() / "data" / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)

            raw_bytes = audio_path.read_bytes()
            orig_mb = len(raw_bytes) // (1024 * 1024)
            if len(raw_bytes) >= 10 * 1024 * 1024:
                db_job_update(job_id, substatus=f"正在压缩音频（{orig_mb}MB）…")

            compressed = AudioService.smart_compress_media(raw_bytes, filename_hint=audio_path.name)
            del raw_bytes  # 原始字节已交给压缩器，释放内存

            final_suffix = ".mp3" if compressed.did_compress else (audio_path.suffix or ".bin")
            permanent_audio_path = audio_dir / f"{job_id}{final_suffix}"
            permanent_audio_path.write_bytes(compressed.data)

            if compressed.did_compress:
                comp_mb = len(compressed.data) // (1024 * 1024)
                db_job_update(
                    job_id,
                    substatus=f"压缩完成（{orig_mb}MB → {comp_mb}MB），准备转写…",
                )
            del compressed  # 已落盘，释放内存

            job_update(job_id, status=PitchJobStatus.EVALUATING)
            db_job_update(job_id, status=str(PitchJobStatus.EVALUATING),
                          audio_path=str(permanent_audio_path))

            words, report = run_pitch_file_job(
                permanent_audio_path,  # 使用落盘后的路径（可能已压缩为 .mp3）
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

        # ── 路演情报：将 next_actions 持久化到 follow_up_items ───────────────
        try:
            from cangjie_fos.engine.schema import RoadshowIntelReport
            from cangjie_fos.services.pitch_job_db import db_follow_up_insert

            if isinstance(report, RoadshowIntelReport) and report.next_actions:
                # 从 DB 查一次 institution_id（participants 确认后会写入）
                from cangjie_fos.services.pitch_job_db import db_job_get
                job_row = db_job_get(job_id) or {}
                inst_id = job_row.get("institution_id") or ""
                for act in report.next_actions:
                    db_follow_up_insert(
                        tenant_id=tenant_id,
                        job_id=job_id,
                        institution_id=inst_id,
                        actor=act.actor or "我方",
                        action=act.action,
                        priority=act.priority or "normal",
                        source=act.source or "suggestion",
                    )
                logger.info(
                    "follow_up_items_written job_id=%s count=%d",
                    job_id,
                    len(report.next_actions),
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("follow_up_persist_skipped job_id=%s: %s", job_id, e)

        report_dict = report.model_dump()
        words_list = [w.model_dump() if hasattr(w, "model_dump") else w for w in words]

        from cangjie_fos.services.report_post_process import expand_risk_original_text
        expand_risk_original_text(report_dict, words_list)

        job_update(
            job_id,
            status=PitchJobStatus.COMPLETED,
            report=report_dict,
            exp_delta=40,
            exp_reason="向导提交：录音解析并完成 LangGraph 复盘",
        )
        db_job_update(
            job_id,
            status=str(PitchJobStatus.COMPLETED),
            original_report=report_dict,
            words_json=words_list,
            audio_path=str(permanent_audio_path) if permanent_audio_path else None,
            exp_delta=40,
            exp_reason="向导提交：录音解析并完成 LangGraph 复盘",
        )
        logger.info("pitch_wizard_job_done job_id=%s tenant_id=%s", job_id, tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("pitch_wizard_job_failed job_id=%s", job_id)
        failure_kwargs = job_failure_update_kwargs(e, job_id=job_id)
        job_update(job_id, status=PitchJobStatus.FAILED, **failure_kwargs)
        db_update_kwargs = {k: v for k, v in failure_kwargs.items() if k != "status"}
        db_job_update(job_id, status=str(PitchJobStatus.FAILED), **db_update_kwargs)
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
    if not qa_items:
        return ""
    try:
        uploads: list[_BytesUpload] = []
        for it in qa_items:
            p = Path(it.get("path") or "")
            name = it.get("name") or "qa.bin"
            if not p.is_file():
                continue
            uploads.append(_BytesUpload(name, p.read_bytes()))
        return extract_text_from_files(uploads, max_chars=max_chars) if uploads else ""
    except Exception as e:  # noqa: BLE001
        logger.warning("merge_qa_text_from_paths_failed, falling back to empty: %s", e)
        return ""
