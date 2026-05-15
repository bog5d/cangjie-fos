"""上传后：压缩 → ASR → LangGraph 评估（后台任务）。"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from cangjie_fos.core.paths import get_backend_root, get_audio_dir
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


def run_pitch_upload_job(
    *,
    job_id: str,
    filename: str,
    tenant_id: str,
    raw_bytes: bytes | None = None,
    pre_written_path: Path | None = None,
) -> None:
    """同步后台线程/BackgroundTasks 调用。

    支持两种输入模式：
    - raw_bytes: 小文件 / 测试用途（旧接口，保留兼容）
    - pre_written_path: 大文件流式上传后的落盘路径（推荐，避免 OOM）
    两者必须提供其一。
    """
    if raw_bytes is None and pre_written_path is None:
        raise ValueError("run_pitch_upload_job: raw_bytes 和 pre_written_path 必须提供其一")

    tmp: Path | None = None
    audio_path: Path | None = None
    try:
        # ── 步骤 1：获取原始字节（或从落盘路径读取）并确定大小 ──────────
        audio_dir = get_audio_dir()
        audio_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix or ".bin"

        if pre_written_path is not None:
            # 大文件路径模式：从磁盘读取用于压缩（避免重复内存拷贝）
            orig_size = pre_written_path.stat().st_size
            raw_for_compress = pre_written_path.read_bytes()
            source_path: Path | None = pre_written_path
        else:
            assert raw_bytes is not None  # type narrowing
            orig_size = len(raw_bytes)
            raw_for_compress = raw_bytes
            source_path = None

        # ── 步骤 2：压缩（仅 ≥10MB 文件）─────────────────────────────────
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

        compressed = AudioService.smart_compress_media(raw_for_compress, filename_hint=filename)
        data = compressed.data
        compressed_size = len(data)

        if getattr(compressed, "did_compress", False):
            db_job_update(
                job_id,
                substatus=f"压缩完成（{_mb(orig_size)} → {_mb(compressed_size)}），写入磁盘…",
            )
        else:
            db_job_update(job_id, substatus="写入磁盘…")

        # ── 步骤 3：写到永久位置 ──────────────────────────────────────────
        audio_path = audio_dir / f"{job_id}{suffix}"
        if source_path is not None and not getattr(compressed, "did_compress", False):
            # 未压缩 + 已在磁盘 → 直接移动，无需再写一次
            shutil.move(str(source_path), str(audio_path))
            source_path = None
        else:
            # 压缩过，或 raw_bytes 路径 → 写入临时文件再移动
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                f.write(data)
                tmp = Path(f.name)
            shutil.move(str(tmp), str(audio_path))
            tmp = None
            # 清理原始落盘临时文件（如有）
            if source_path is not None:
                source_path.unlink(missing_ok=True)
                source_path = None

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


# ── 路演分析专属 Pipeline ──────────────────────────────────────────────────────

def run_roadshow_asr_job(
    *,
    job_id: str,
    filename: str,
    tenant_id: str,
    referrer: str = "",
    raw_bytes: bytes | None = None,
    pre_written_path: Path | None = None,
) -> None:
    """路演分析专属：只做压缩+ASR，完成后暂停于 awaiting_speakers 状态。

    用户确认说话人身份后，调用 resume_roadshow_analysis() 继续LangGraph评估。
    """
    if raw_bytes is None and pre_written_path is None:
        raise ValueError("run_roadshow_asr_job: raw_bytes 和 pre_written_path 必须提供其一")

    tmp: Path | None = None
    audio_path: Path | None = None
    try:
        audio_dir = get_audio_dir()
        audio_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix or ".bin"

        if pre_written_path is not None:
            orig_size = pre_written_path.stat().st_size
            raw_for_compress = pre_written_path.read_bytes()
            source_path: Path | None = pre_written_path
        else:
            assert raw_bytes is not None
            orig_size = len(raw_bytes)
            raw_for_compress = raw_bytes
            source_path = None

        # ── 压缩 ────────────────────────────────────────────────────────────
        db_job_update(
            job_id,
            status=str(PitchJobStatus.TRANSCRIBING),
            substatus=f"正在压缩音频（{_mb(orig_size)}）…" if orig_size >= _COMPRESS_THRESHOLD_BYTES else "准备转写…",
            is_roadshow=1,
            referrer=referrer,
        )
        job_update(job_id, status=PitchJobStatus.TRANSCRIBING)

        compressed = AudioService.smart_compress_media(raw_for_compress, filename_hint=filename)
        data = compressed.data
        compressed_size = len(data)

        # ── 写入磁盘 ─────────────────────────────────────────────────────────
        audio_path = audio_dir / f"{job_id}{suffix}"
        if source_path is not None and not getattr(compressed, "did_compress", False):
            shutil.move(str(source_path), str(audio_path))
            source_path = None
        else:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                f.write(data)
                tmp = Path(f.name)
            shutil.move(str(tmp), str(audio_path))
            tmp = None
            if source_path is not None:
                source_path.unlink(missing_ok=True)

        # ── ASR ──────────────────────────────────────────────────────────────
        db_job_update(job_id, substatus="ASR 转写中，较长录音请耐心等待…")
        words = transcribe_audio(audio_path)
        word_count = len(words)

        # ── 保存转写结果，切换到 awaiting_speakers 状态（暂停，等用户确认说话人）
        db_job_update(
            job_id,
            words_json=[w.model_dump() for w in words],
            audio_path=str(audio_path),
            status=str(PitchJobStatus.AWAITING_SPEAKERS),
            substatus=f"转写完成（{word_count} 词），请确认说话人身份后继续分析",
        )
        job_update(job_id, status=PitchJobStatus.AWAITING_SPEAKERS)
        logger.info("roadshow_asr_done job_id=%s word_count=%d awaiting_speakers", job_id, word_count)

    except Exception as e:  # noqa: BLE001
        logger.exception("roadshow_asr_job_failed job_id=%s", job_id)
        failure_kwargs = job_failure_update_kwargs(e, job_id=job_id)
        job_update(job_id, status=PitchJobStatus.FAILED, **failure_kwargs)
        db_update_kwargs = {k: v for k, v in failure_kwargs.items() if k != "status"}
        db_job_update(job_id, status=str(PitchJobStatus.FAILED), substatus=None, **db_update_kwargs)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def resume_roadshow_analysis(
    *,
    job_id: str,
    tenant_id: str,
    confirmed_speakers: list[dict],
) -> None:
    """路演分析第二阶段：用户确认说话人后，注入身份上下文，继续LangGraph评估。"""
    from cangjie_fos.services.pitch_job_db import db_job_get  # noqa: PLC0415

    try:
        job_update(job_id, status=PitchJobStatus.RESUMING_ANALYSIS)
        db_job_update(
            job_id,
            status=str(PitchJobStatus.RESUMING_ANALYSIS),
            substatus="正在分析路演内容…",
            confirmed_speakers_json=confirmed_speakers,
        )

        job_row = db_job_get(job_id)
        if not job_row:
            raise RuntimeError(f"job {job_id} not found in DB")

        raw_words = job_row.get("words_json") or []
        from cangjie_fos.engine.schema import TranscriptionWord  # noqa: PLC0415
        words = [TranscriptionWord(**w) if isinstance(w, dict) else w for w in raw_words]

        # 构建说话人身份上下文（注入到LangGraph prompt中）
        speaker_context_lines = []
        for sp in confirmed_speakers:
            sid = sp.get("speaker_id", "")
            name = sp.get("real_name", "")
            role = sp.get("role", "")
            institution = sp.get("institution", "")
            title = sp.get("title", "")
            parts = [p for p in [name, title, institution, f"({role})" if role else ""] if p]
            speaker_context_lines.append(f"说话人{sid}：{'、'.join(parts)}")

        speaker_context = "本场路演说话人身份：\n" + "\n".join(speaker_context_lines)

        upload_context: dict = {
            "source": "roadshow_analysis",
            "filename": job_row.get("interviewee", job_id),
            "biz_type": "01_机构路演",          # 触发路演情报分析分支（不是评分分支）
            "confirmed_speakers_context": speaker_context,
        }
        upload_context.update(build_investor_context(tenant_id))

        db_job_update(job_id, status=str(PitchJobStatus.EVALUATING), substatus="路演情报提取中…")
        job_update(job_id, status=PitchJobStatus.EVALUATING)

        report, _excerpt = PitchGraphService.run_evaluation_with_state(
            tenant_id=tenant_id,
            words=words,
            model_choice="deepseek",
            explicit_context=upload_context,
            qa_text="",
            company_background="",
            trace_id=job_id,
        )

        db_job_update(job_id, substatus="生成情报报告…")
        report_dict = report.model_dump()

        job_update(
            job_id,
            status=PitchJobStatus.COMPLETED,
            report=report_dict,
            exp_delta=30,
            exp_reason="路演情报分析完成",
        )
        db_job_update(
            job_id,
            status=str(PitchJobStatus.COMPLETED),
            original_report=report_dict,
            exp_delta=30,
            exp_reason="路演情报分析完成",
            substatus=None,
        )

        # 保存确认的参与人到 job_participants 表
        from cangjie_fos.services.pitch_job_db import db_participants_save  # noqa: PLC0415
        if confirmed_speakers:
            try:
                db_participants_save(
                    job_id=job_id,
                    tenant_id=tenant_id,
                    confirmed_by="roadshow_wizard",
                    participants=confirmed_speakers,
                )
            except Exception as pe:  # noqa: BLE001
                logger.warning("roadshow participants_save failed job_id=%s: %s", job_id, pe)

        # ── 自动写入 Pipeline CRM（数据打通）──────────────────────────────────
        # 路演完成后自动将机构写入/更新 Pipeline CRM，使 War Room 大屏实时反映
        institution_name = (job_row.get("institution_id") or "").strip()
        # 过滤占位符（"待确认_YYYY-MM-DD" 格式）
        if institution_name and not institution_name.startswith("待确认_"):
            try:
                from cangjie_fos.services.institution_store import (  # noqa: PLC0415
                    get_by_name, upsert_institution,
                )
                from cangjie_fos.schemas.institution import (  # noqa: PLC0415
                    InstitutionProfile, InstitutionThermal, PipelineStage,
                )
                import time as _time, uuid as _uuid  # noqa: PLC0415

                existing = get_by_name(tenant_id=tenant_id, name=institution_name)
                # 已有机构保留阶段（不降级：如已是 DD，维持 DD）
                stage_order = {
                    "targeted": 0, "pitched": 1, "dd": 2, "term_sheet": 3,
                }
                new_stage = PipelineStage.PITCHED
                if existing and stage_order.get(existing.stage.value, 0) > stage_order["pitched"]:
                    new_stage = existing.stage  # 保留更高阶段

                # 从路演报告中提取 meeting_atmosphere → 机构热度
                atmosphere = report_dict.get("meeting_atmosphere", "warm")
                thermal_map = {"hot": InstitutionThermal.HOT, "cold": InstitutionThermal.COLD}
                thermal = thermal_map.get(atmosphere, InstitutionThermal.WARM)

                profile = InstitutionProfile(
                    institution_id=existing.institution_id if existing else _uuid.uuid4().hex,
                    tenant_id=tenant_id,
                    name=institution_name,
                    stage=new_stage,
                    thermal=thermal,
                    preferences=existing.preferences if existing else "",
                    concerns=existing.concerns if existing else "",
                    ai_summary=existing.ai_summary if existing else "",
                    updated_at=_time.time(),
                    source_trace_id=job_id,
                )
                upsert_institution(profile)
                logger.info(
                    "roadshow institution_crm_synced job_id=%s inst=%s stage=%s",
                    job_id, institution_name, new_stage,
                )
            except Exception as crm_exc:  # noqa: BLE001
                logger.warning(
                    "roadshow institution_crm_sync 失败（非致命）job_id=%s exc=%s",
                    job_id, crm_exc,
                )

        # GitHub 同步（非阻塞）
        try:
            from cangjie_fos.services.github_sync import push_roadshow_report  # noqa: PLC0415
            push_roadshow_report(job_id)
        except Exception as sync_exc:  # noqa: BLE001
            logger.warning("roadshow github_sync 失败（非致命）job_id=%s exc=%s", job_id, sync_exc)

        logger.info("roadshow_analysis_done job_id=%s tenant_id=%s", job_id, tenant_id)

    except Exception as e:  # noqa: BLE001
        logger.exception("roadshow_analysis_failed job_id=%s", job_id)
        failure_kwargs = job_failure_update_kwargs(e, job_id=job_id)
        job_update(job_id, status=PitchJobStatus.FAILED, **failure_kwargs)
        db_update_kwargs = {k: v for k, v in failure_kwargs.items() if k != "status"}
        db_job_update(job_id, status=str(PitchJobStatus.FAILED), substatus=None, **db_update_kwargs)
