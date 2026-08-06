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


def _institution_background(tenant_id: str, institution_name: str) -> str:
    """从机构 CRM 档案拼出一段背景，注入分析（J3 / 游梦秋 #08）。

    机构名是占位符/空/查不到 → 返回空串（等价于旧行为，安全）。
    """
    name = (institution_name or "").strip()
    if not name or name.startswith("待确认_"):
        return ""
    try:
        from cangjie_fos.services.institution_store import get_by_name  # noqa: PLC0415
        inst = get_by_name(tenant_id=tenant_id, name=name)
    except Exception:  # noqa: BLE001
        return ""
    if not inst:
        return ""
    bits = []
    if inst.ai_summary:
        bits.append(f"机构画像：{inst.ai_summary}")
    if inst.concerns:
        bits.append(f"已知关注/疑虑：{inst.concerns}")
    if inst.preferences:
        bits.append(f"投资偏好：{inst.preferences}")
    if getattr(inst, "stage", None):
        bits.append(f"当前阶段：{inst.stage.value}")
    return f"【对方机构背景：{name}】\n" + "\n".join(bits) if bits else ""


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


def sync_roadshow_institution(
    tenant_id: str, institution_name: str, report_dict: dict, job_id: str,
) -> bool:
    """路演完成后把机构写入/更新 Pipeline CRM。返回是否实际写入。

    F4 人工确认锁：机构档案被人工锁定（review_locked）后，AI 自动分析不再覆盖，
    落实"谁路演谁主笔"，避免手动确认的版本被后台分析冲掉 → 返回 False。
    占位符机构名（"待确认_YYYY-MM-DD"）或空名 → 不写，返回 False。
    """
    institution_name = (institution_name or "").strip()
    if not institution_name or institution_name.startswith("待确认_"):
        return False

    from cangjie_fos.services.institution_store import get_by_name, upsert_institution
    from cangjie_fos.schemas.institution import (
        InstitutionProfile, InstitutionThermal, PipelineStage,
    )
    import time as _time, uuid as _uuid

    existing = get_by_name(tenant_id=tenant_id, name=institution_name)
    if existing and getattr(existing, "review_locked", False):
        logger.info(
            "roadshow institution_crm_sync 跳过（已人工锁定）job_id=%s inst=%s",
            job_id, institution_name,
        )
        return False

    stage_order = {"targeted": 0, "pitched": 1, "dd": 2, "term_sheet": 3}
    new_stage = PipelineStage.PITCHED
    if existing and stage_order.get(existing.stage.value, 0) > stage_order["pitched"]:
        new_stage = existing.stage  # 保留更高阶段

    atmosphere = (report_dict or {}).get("meeting_atmosphere", "warm")
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
    # 游梦秋 #2/#3：路演更新了机构 CRM，也要推到 GitHub，否则同事 pull 不到阶段/热度变化
    # （以前只推了"路演报告"，没推"机构更新"）。走离线暂存队列，断网也不丢。
    try:
        from cangjie_fos.services.sync_outbox import enqueue_and_try  # noqa: PLC0415
        enqueue_and_try("institution", profile.institution_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("路演后机构同步入队失败（非致命）: %s", e)
    logger.info(
        "roadshow institution_crm_synced job_id=%s inst=%s stage=%s",
        job_id, institution_name, new_stage,
    )
    return True


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

        # J2（游梦秋 #08）：业务类型不再硬编码。用 job 存的 category，非法/缺省回落机构路演，
        # 保证仍走情报分析分支（客户/供应商/高管访谈现也都走情报分支）。
        _INTEL = {"01_机构路演", "03_客户访谈", "04_供应商访谈", "05_高管访谈"}
        biz_type = (job_row.get("category") or "").strip()
        if biz_type not in _INTEL:
            biz_type = "01_机构路演"

        upload_context: dict = {
            "source": "roadshow_analysis",
            "filename": job_row.get("interviewee", job_id),
            "biz_type": biz_type,
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
            # J3（游梦秋 #08）：从机构 CRM 档案自动带入背景，不再空字符串
            company_background=_institution_background(tenant_id, job_row.get("institution_id") or ""),
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
        institution_name = (job_row.get("institution_id") or "").strip()
        try:
            sync_roadshow_institution(tenant_id, institution_name, report_dict, job_id)
        except Exception as crm_exc:  # noqa: BLE001
            logger.warning(
                "roadshow institution_crm_sync 失败（非致命）job_id=%s exc=%s",
                job_id, crm_exc,
            )

        # GitHub 同步（非阻塞）
        try:
            from cangjie_fos.services.sync_outbox import enqueue_and_try  # noqa: PLC0415
            enqueue_and_try("roadshow", job_id)  # 入队+即时补传，离线不丢
        except Exception as sync_exc:  # noqa: BLE001
            logger.warning("roadshow github_sync 失败（非致命）job_id=%s exc=%s", job_id, sync_exc)

        logger.info("roadshow_analysis_done job_id=%s tenant_id=%s", job_id, tenant_id)

    except Exception as e:  # noqa: BLE001
        logger.exception("roadshow_analysis_failed job_id=%s", job_id)
        failure_kwargs = job_failure_update_kwargs(e, job_id=job_id)
        job_update(job_id, status=PitchJobStatus.FAILED, **failure_kwargs)
        db_update_kwargs = {k: v for k, v in failure_kwargs.items() if k != "status"}
        db_job_update(job_id, status=str(PitchJobStatus.FAILED), substatus=None, **db_update_kwargs)


# ── 通用会议纪要专属 Pipeline（单阶段：压缩 → ASR → 纪要 → 完成）─────────────────

def run_meeting_minutes_job(
    *,
    job_id: str,
    filename: str,
    tenant_id: str,
    meeting_title: str = "",
    raw_bytes: bytes | None = None,
    pre_written_path: Path | None = None,
) -> None:
    """会议纪要专属：压缩 + ASR + 纪要提炼一气呵成，无需确认发言人。

    与路演两阶段不同，普通会议不必逐一标注说话人身份，上传即得纪要初稿。
    """
    if raw_bytes is None and pre_written_path is None:
        raise ValueError("run_meeting_minutes_job: raw_bytes 和 pre_written_path 必须提供其一")

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
            category="06_通用会议纪要",
            interviewee=meeting_title or "会议",
            is_roadshow=0,
        )
        job_update(job_id, status=PitchJobStatus.TRANSCRIBING)

        compressed = AudioService.smart_compress_media(raw_for_compress, filename_hint=filename)
        data = compressed.data

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

        db_job_update(
            job_id,
            words_json=[w.model_dump() for w in words],
            audio_path=str(audio_path),
            status=str(PitchJobStatus.EVALUATING),
            substatus=f"转写完成（{word_count} 词），正在提炼会议纪要…",
        )
        job_update(job_id, status=PitchJobStatus.EVALUATING)

        # ── 会议纪要提炼（走 biz_type=='06_通用会议纪要' 分支）──────────────────
        explicit_context: dict = {
            "source": "meeting_minutes",
            "filename": meeting_title or job_id,
            "interviewee": meeting_title or "会议",
            "biz_type": "06_通用会议纪要",
        }
        report, _excerpt = PitchGraphService.run_evaluation_with_state(
            tenant_id=tenant_id,
            words=words,
            model_choice="deepseek",
            explicit_context=explicit_context,
            qa_text="",
            company_background="",
            trace_id=job_id,
        )
        report_dict = report.model_dump()

        job_update(
            job_id,
            status=PitchJobStatus.COMPLETED,
            report=report_dict,
            exp_delta=10,
            exp_reason="会议纪要生成完成",
        )
        db_job_update(
            job_id,
            status=str(PitchJobStatus.COMPLETED),
            original_report=report_dict,
            exp_delta=10,
            exp_reason="会议纪要生成完成",
            substatus=None,
        )
        logger.info("meeting_minutes_done job_id=%s word_count=%d", job_id, word_count)

    except Exception as e:  # noqa: BLE001
        logger.exception("meeting_minutes_job_failed job_id=%s", job_id)
        failure_kwargs = job_failure_update_kwargs(e, job_id=job_id)
        job_update(job_id, status=PitchJobStatus.FAILED, **failure_kwargs)
        db_update_kwargs = {k: v for k, v in failure_kwargs.items() if k != "status"}
        db_job_update(job_id, status=str(PitchJobStatus.FAILED), substatus=None, **db_update_kwargs)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
