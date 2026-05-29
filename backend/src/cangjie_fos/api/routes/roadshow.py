"""路演分析专属 API（Phase 7.5）。

工作流：
  1. POST /api/v1/roadshow/start            — 上传音频或稿子，启动ASR（后台），返回 job_id
  2. GET  /api/v1/roadshow/jobs/{job_id}/speaker-preview
                                            — ASR完成后，返回说话人样本+AI推测角色
  3. POST /api/v1/roadshow/jobs/{job_id}/confirm-speakers
                                            — 用户确认说话人身份，触发LangGraph评估
  4. GET  /api/v1/roadshow/jobs/{job_id}/report
                                            — 获取 RoadshowIntelReport 结果
"""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from cangjie_fos.core.paths import get_backend_root, get_audio_dir
from cangjie_fos.schemas.pitch_upload import PitchJobStatus
from cangjie_fos.api.upload_io import stream_upload_to_path
from cangjie_fos.services.pitch_job_db import db_job_create, db_job_get, db_job_update
from cangjie_fos.services.pitch_job_store import job_create, job_update
from cangjie_fos.services.pitch_upload_pipeline import (
    resume_roadshow_analysis,
    run_roadshow_asr_job,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/roadshow", tags=["roadshow"])

# ── 合法角色 ───────────────────────────────────────────────────────────────────
_VALID_ROLES = {
    "引荐方",
    "企业方创始人",
    "企业方高管",
    "企业方投融资",
    "GP执行",
    "LP投资方",
    "政府招商",
    "其他",
}

# ── 说话人角色推测（基于台词特征的简单规则，无需LLM）──────────────────────────
_INVESTOR_KEYWORDS = re.compile(
    r"估值|退出|回报|IRR|DPI|MOIC|赛道|投资逻辑|基金规模|GP|LP"
    r"|我们主要看|我们关注|这个赛道|你们的数据|之前投过|看过类似",
    re.IGNORECASE,
)
_COMPANY_KEYWORDS = re.compile(
    r"我们的产品|我们的客户|我们的收入|我们的团队|我们做的|商业模式"
    r"|核心壁垒|技术优势|融资计划|上市",
    re.IGNORECASE,
)
_REFERRER_KEYWORDS = re.compile(
    r"帮你们介绍|认识一下|给你们引荐|我跟.*聊过|这个团队我很看好",
    re.IGNORECASE,
)


def _guess_role(sample_lines: list[str]) -> tuple[str, str]:
    """基于样本台词推测说话人角色。返回 (role, reason)。"""
    text = " ".join(sample_lines)
    investor_hits = len(_INVESTOR_KEYWORDS.findall(text))
    company_hits = len(_COMPANY_KEYWORDS.findall(text))
    referrer_hits = len(_REFERRER_KEYWORDS.findall(text))

    if referrer_hits >= 1:
        return "引荐方", "台词中有引荐/介绍相关表述"
    if investor_hits > company_hits and investor_hits >= 2:
        return "GP执行", "台词中有多个投资机构视角词汇"
    if company_hits > investor_hits and company_hits >= 2:
        return "企业方创始人", "台词中有多个企业方陈述词汇"
    return "其他", "无明显特征，请人工确认"


# ── Pydantic Models ────────────────────────────────────────────────────────────

class RoadshowStartResponse(BaseModel):
    job_id: str
    status: str
    message: str


class SpeakerPreviewItem(BaseModel):
    speaker_id: str
    sample_lines: list[str]
    word_count: int
    guessed_role: str = Field(default="其他", description="AI推测角色")
    guess_reason: str = Field(default="", description="推测理由")


class ConfirmedSpeaker(BaseModel):
    speaker_id: str
    real_name: str = ""
    institution: str = ""
    role: str = "其他"
    title: str = ""


class ConfirmSpeakersRequest(BaseModel):
    confirmed_by: str = Field(..., description="确认人（指挥官名称）")
    speakers: list[ConfirmedSpeaker]


class RoadshowJobStatus(BaseModel):
    job_id: str
    status: str
    substatus: str | None = None
    is_roadshow: bool = True
    referrer: str = ""
    has_report: bool = False
    report: dict | None = None
    created_at: float = 0.0


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/start", response_model=RoadshowStartResponse)
async def roadshow_start(
    background_tasks: BackgroundTasks,
    tenant_id: str = Query(..., description="租户 ID"),
    roadshow_date: str = Query(..., description="路演日期 YYYY-MM-DD"),
    institution_name: str = Query(default="", description="目标机构名称（可选，ASR完成后再确认）"),
    referrer: str = Query(default="", description="引荐方机构名称（可选）"),
    confirmed_by: str = Query(default="", description="指挥官名称"),
    file: UploadFile | None = None,
    transcript_text: str | None = None,
) -> RoadshowStartResponse:
    """上传路演录音或文字稿，启动ASR，返回 job_id。

    支持两种输入：
    - file: 音频文件（mp3/m4a/wav等）
    - transcript_text: 直接粘贴文字稿（query参数或form字段）
    """
    job_id = str(uuid.uuid4())
    label = f"路演_{roadshow_date}" + (f"_{institution_name}" if institution_name else "")

    # 创建内存 job 记录（job_create 内部已同步写 SQLite，不需要再调 db_job_create）
    job_create(job_id, tenant_id=tenant_id)
    # 补写路演专属字段（job_create 内部的 db_job_create 不知道这些字段）
    db_job_update(
        job_id,
        interviewee=label,
        category="01_机构路演",
        institution_id=institution_name or f"待确认_{roadshow_date}",
        is_roadshow=1,
        referrer=referrer,
    )

    if file is not None:
        # 音频上传路径
        fname = file.filename or f"roadshow_{job_id}.mp3"
        suffix = Path(fname).suffix or ".mp3"
        audio_dir = get_audio_dir()
        audio_dir.mkdir(parents=True, exist_ok=True)
        incoming_path = audio_dir / f"{job_id}_incoming{suffix}"
        await stream_upload_to_path(file, incoming_path)

        background_tasks.add_task(
            run_roadshow_asr_job,
            job_id=job_id,
            filename=fname,
            tenant_id=tenant_id,
            referrer=referrer,
            pre_written_path=incoming_path,
        )
        return RoadshowStartResponse(
            job_id=job_id,
            status="transcribing",
            message="音频已上传，ASR转写中，请稍候…",
        )

    elif transcript_text and transcript_text.strip():
        # 文字稿路径：直接跳过ASR，转换为 TranscriptionWord 格式
        from cangjie_fos.services.transcript_parser import parse_transcript_to_words  # noqa: PLC0415

        words = parse_transcript_to_words(transcript_text)
        word_count = len(words)

        db_job_update(
            job_id,
            status=str(PitchJobStatus.AWAITING_SPEAKERS),
            substatus=f"文字稿解析完成（{word_count} 词），请确认说话人身份",
            words_json=[w.model_dump() for w in words],
            is_roadshow=1,
            referrer=referrer,
        )
        job_update(job_id, status=PitchJobStatus.AWAITING_SPEAKERS)
        return RoadshowStartResponse(
            job_id=job_id,
            status="awaiting_speakers",
            message=f"文字稿解析完成（{word_count} 词），请确认说话人身份",
        )

    else:
        raise HTTPException(400, "必须提供音频文件（file）或文字稿（transcript_text）之一")


@router.get("/jobs/{job_id}/status", response_model=RoadshowJobStatus)
def roadshow_job_status(job_id: str) -> RoadshowJobStatus:
    """轮询 job 状态（前端步骤2等待页使用）。"""
    row = db_job_get(job_id)
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")
    return RoadshowJobStatus(
        job_id=job_id,
        status=row.get("status", "pending"),
        substatus=row.get("substatus"),
        is_roadshow=bool(row.get("is_roadshow", 0)),
        referrer=row.get("referrer", ""),
        has_report=bool(row.get("original_report")),
        report=row.get("original_report") if row.get("original_report") else None,
        created_at=row.get("created_at", 0.0),
    )


@router.get("/jobs/{job_id}/speaker-preview", response_model=list[SpeakerPreviewItem])
def roadshow_speaker_preview(job_id: str) -> list[SpeakerPreviewItem]:
    """ASR完成后，返回每位说话人的样本台词和AI推测角色。

    仅当 status == 'awaiting_speakers' 时调用有意义。
    """
    row = db_job_get(job_id)
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")

    status = row.get("status", "")
    if status not in ("awaiting_speakers", "completed"):
        raise HTTPException(
            400,
            f"Job {job_id} is in status '{status}', not ready for speaker preview. "
            "Wait for ASR to complete."
        )

    words_raw = row.get("words_json") or []
    if not words_raw:
        return []

    # 第一步：把 words_json 按说话人分组，同一说话人的连续片段拼成完整话语
    # （ASR 输出是时间切割的短段，需要先拼句再取样本）
    from collections import defaultdict  # noqa: PLC0415

    speaker_counts: dict[str, int] = defaultdict(int)
    # utterances: 每位说话人的"完整话语"列表，每条是多个连续词段拼接的结果
    speaker_utterances: dict[str, list[str]] = defaultdict(list)

    prev_sid = None
    buf: list[str] = []

    def _flush(sid: str, buf: list[str]) -> None:
        text = "".join(buf).strip()
        if text and len(text) >= 8:  # 拼完后至少8字才算有意义的话语
            speaker_utterances[sid].append(text)

    for w in words_raw:
        sid = str(w.get("speaker_id", "0"))
        text = w.get("text", "").strip()
        if not text:
            continue
        speaker_counts[sid] += 1

        if sid != prev_sid:
            # 说话人切换，先把上一段 flush
            if prev_sid is not None:
                _flush(prev_sid, buf)
            buf = [text]
            prev_sid = sid
        else:
            buf.append(text)
            # 单段话语超过 100 字就提前切断，避免整段合成一条超长话语
            if len("".join(buf)) >= 100:
                _flush(sid, buf)
                buf = []

    # flush 最后一段
    if prev_sid is not None and buf:
        _flush(prev_sid, buf)

    # 第二步：为每位说话人选最具代表性的 3 条（选较长的）
    result: list[SpeakerPreviewItem] = []
    all_sids = set(speaker_counts.keys()) | set(speaker_utterances.keys())
    for sid in sorted(all_sids, key=lambda x: (len(x), x)):
        utterances = speaker_utterances.get(sid, [])
        sample = sorted(utterances, key=len, reverse=True)[:3]
        guessed_role, guess_reason = _guess_role(sample)
        result.append(SpeakerPreviewItem(
            speaker_id=sid,
            sample_lines=sample,
            word_count=speaker_counts[sid],
            guessed_role=guessed_role,
            guess_reason=guess_reason,
        ))

    return result


@router.post("/jobs/{job_id}/confirm-speakers")
def roadshow_confirm_speakers(
    job_id: str,
    request: ConfirmSpeakersRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = Query(..., description="租户 ID"),
) -> dict[str, Any]:
    """用户确认说话人身份后触发LangGraph路演情报评估。"""
    row = db_job_get(job_id)
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")

    if row.get("status") != str(PitchJobStatus.AWAITING_SPEAKERS):
        raise HTTPException(
            400,
            f"Job {job_id} status is '{row.get('status')}', expected 'awaiting_speakers'"
        )

    if not request.confirmed_by.strip():
        raise HTTPException(400, "confirmed_by（指挥官名称）不能为空")

    # 校验角色合法性
    speakers_data = []
    for sp in request.speakers:
        role = sp.role if sp.role in _VALID_ROLES else "其他"
        speakers_data.append({
            "speaker_id": sp.speaker_id,
            "real_name": sp.real_name.strip(),
            "institution": sp.institution.strip(),
            "role": role,
            "title": sp.title.strip(),
        })

    background_tasks.add_task(
        resume_roadshow_analysis,
        job_id=job_id,
        tenant_id=tenant_id,
        confirmed_speakers=speakers_data,
    )

    return {"ok": True, "message": "说话人身份已确认，路演情报分析已启动", "job_id": job_id}


@router.get("/jobs/{job_id}/report")
def roadshow_report(job_id: str) -> dict[str, Any]:
    """获取已完成的路演情报报告。"""
    row = db_job_get(job_id)
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")

    if row.get("status") != str(PitchJobStatus.COMPLETED):
        raise HTTPException(
            400,
            f"Job {job_id} not completed yet (status: {row.get('status')})"
        )

    report = row.get("original_report")
    if not report:
        raise HTTPException(404, f"Job {job_id} has no report")

    confirmed_speakers = row.get("confirmed_speakers_json") or []

    return {
        "job_id": job_id,
        "report": report,
        "confirmed_speakers": confirmed_speakers,
        "referrer": row.get("referrer", ""),
        "interviewee": row.get("interviewee", ""),
        "created_at": row.get("created_at", 0.0),
    }


# ── HTML 报告生成 ──────────────────────────────────────────────────────────────

def _build_roadshow_html(report: dict, meta: dict) -> str:
    """根据 RoadshowIntelReport dict 生成自包含 HTML 字符串。"""
    import html as _html

    def e(v: Any) -> str:
        """HTML 转义辅助。"""
        return _html.escape(str(v or ""), quote=True)

    atmosphere_map = {
        "hot": ("🔥 高度积极", "#f97316"),
        "warm": ("✅ 正常推进", "#10b981"),
        "cold": ("❄️ 兴趣不足", "#64748b"),
    }
    stage_map = {
        "first_contact": "初次路演",
        "deep_discussion": "深度沟通",
        "pre_dd": "准尽调",
        "unknown": "阶段未知",
    }
    priority_color = {
        "high": "#f43f5e", "medium": "#f59e0b", "low": "#64748b",
        "urgent": "#f43f5e", "normal": "#06b6d4", "optional": "#64748b",
    }
    signal_color = {
        "positive": "#10b981", "concern": "#f43f5e", "neutral": "#64748b",
    }
    signal_label = {
        "positive": "正面信号", "concern": "疑虑/抵触", "neutral": "中性陈述",
    }

    atm_text, atm_color = atmosphere_map.get(
        report.get("meeting_atmosphere", "warm"), ("✅ 正常推进", "#10b981")
    )
    stage_text = stage_map.get(report.get("meeting_stage", "unknown"), "阶段未知")
    interviewee = e(meta.get("interviewee", ""))
    referrer = e(meta.get("referrer", ""))
    created_at = meta.get("created_at", 0.0)
    from datetime import datetime  # noqa: PLC0415
    try:
        date_str = datetime.fromtimestamp(float(created_at)).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        date_str = ""

    sections: list[str] = []

    # ── 关键问题 ──────────────────────────────────────────────────────────────
    key_questions = report.get("key_questions") or []
    if key_questions:
        rows = ""
        for i, q in enumerate(key_questions, 1):
            pri = q.get("priority", "medium")
            col = priority_color.get(pri, "#f59e0b")
            pri_label = {"high": "核心", "medium": "关注", "low": "礼节"}.get(pri, pri)
            speaker = f'<span class="tag">{e(q["speaker_id"])}</span> ' if q.get("speaker_id") else ""
            rows += (
                f"<tr><td>{i}</td><td>{speaker}"
                f'<span class="tag" style="background:{col}22;color:{col};border-color:{col}44">{e(pri_label)}</span>'
                f"</td>"
                f"<td>「{e(q.get('verbatim',''))}」</td>"
                f"<td>{e(q.get('underlying_concern',''))}</td></tr>"
            )
        sections.append(
            f'<h2>对方关键问题 ({len(key_questions)})</h2>'
            f'<table><thead><tr><th>#</th><th>优先级</th><th>原话</th><th>背后关切</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
        )

    # ── 兴趣信号 ──────────────────────────────────────────────────────────────
    interest_signals = report.get("interest_signals") or []
    if interest_signals:
        rows = ""
        for s in interest_signals:
            st = s.get("signal_type", "neutral")
            col = signal_color.get(st, "#64748b")
            lbl = signal_label.get(st, st)
            speaker = f'<span class="tag">{e(s["speaker_id"])}</span> ' if s.get("speaker_id") else ""
            rows += (
                f"<tr><td>{speaker}"
                f'<span class="tag" style="background:{col}22;color:{col};border-color:{col}44">{e(lbl)}</span>'
                f"</td>"
                f"<td>「{e(s.get('verbatim',''))}」</td>"
                f"<td>{e(s.get('interpretation',''))}</td></tr>"
            )
        sections.append(
            f'<h2>兴趣信号 ({len(interest_signals)})</h2>'
            f'<table><thead><tr><th>类型</th><th>原话</th><th>解读</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
        )

    # ── 隐性顾虑 ──────────────────────────────────────────────────────────────
    hidden_concerns = report.get("hidden_concerns") or []
    if hidden_concerns:
        items = "".join(f"<li>⚠ {e(c)}</li>" for c in hidden_concerns)
        sections.append(f'<h2>隐性顾虑</h2><ul class="concerns">{items}</ul>')

    # ── 关键原声 ──────────────────────────────────────────────────────────────
    key_verbatim = report.get("key_verbatim_moments") or []
    if key_verbatim:
        items = "".join(f"<li>{e(m)}</li>" for m in key_verbatim)
        sections.append(f'<h2>关键原声</h2><ul class="verbatim">{items}</ul>')

    # ── 机构档案更新建议 ───────────────────────────────────────────────────────
    institution_update = report.get("institution_update") or ""
    if institution_update:
        sections.append(
            f'<h2>机构档案更新建议</h2><p class="text-block">{e(institution_update)}</p>'
        )

    # ── 下一步行动 ────────────────────────────────────────────────────────────
    next_actions = report.get("next_actions") or []
    if next_actions:
        rows = ""
        for a in next_actions:
            pri = a.get("priority", "normal")
            col = priority_color.get(pri, "#06b6d4")
            pri_label = {"urgent": "紧急", "normal": "正常", "optional": "可选"}.get(pri, pri)
            src_label = "已承诺" if a.get("source") == "commitment" else "建议"
            rows += (
                f'<tr><td><span class="tag" style="background:{col}22;color:{col};border-color:{col}44">'
                f'{e(pri_label)}</span></td>'
                f"<td>{e(src_label)}</td>"
                f"<td>{e(a.get('action',''))}</td>"
                f"<td>{e(a.get('actor',''))}</td></tr>"
            )
        sections.append(
            f'<h2>下一步行动 ({len(next_actions)})</h2>'
            f'<table><thead><tr><th>优先级</th><th>性质</th><th>行动</th><th>负责方</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
        )

    body = "\n".join(sections)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>路演情报报告 — {interviewee}</title>
<style>
  body{{font-family:"PingFang SC","Microsoft YaHei",sans-serif;background:#0d0d1a;color:#e2e8f0;margin:0;padding:24px}}
  .header{{background:linear-gradient(135deg,#0f172a,#1e3a4a);border:1px solid #1e3a5f;border-radius:12px;padding:24px;margin-bottom:24px}}
  .header h1{{margin:0 0 8px;font-size:1.4em;color:#67e8f9}}
  .meta{{font-size:.85em;color:#94a3b8;margin:4px 0}}
  .atm-badge{{display:inline-block;padding:4px 12px;border-radius:6px;font-weight:bold;font-size:.9em;margin:8px 8px 8px 0;border:1px solid}}
  .stage-badge{{display:inline-block;padding:4px 10px;border-radius:6px;font-size:.8em;border:1px solid #334155;background:#1e293b;color:#94a3b8}}
  .summary{{margin-top:12px;color:#cbd5e1;line-height:1.7;font-size:.9em}}
  h2{{color:#67e8f9;font-size:1em;text-transform:uppercase;letter-spacing:.1em;border-bottom:1px solid #1e3a5f;padding-bottom:6px;margin:24px 0 12px}}
  table{{width:100%;border-collapse:collapse;font-size:.85em;margin-bottom:16px}}
  th{{background:#1e293b;color:#94a3b8;text-align:left;padding:8px 10px;font-weight:600;font-size:.75em;text-transform:uppercase;letter-spacing:.05em}}
  td{{padding:8px 10px;border-bottom:1px solid #1e293b;vertical-align:top;line-height:1.6}}
  tr:hover td{{background:#ffffff08}}
  .tag{{display:inline-block;padding:1px 6px;border-radius:4px;font-size:.75em;font-weight:bold;border:1px solid;margin-right:4px}}
  ul.concerns{{list-style:none;padding:0;margin:0 0 16px}}
  ul.concerns li{{padding:6px 10px;margin:4px 0;border-left:3px solid #f59e0b;background:#f59e0b11;color:#fde68a;border-radius:0 6px 6px 0;font-size:.88em}}
  ul.verbatim{{list-style:none;padding:0;margin:0 0 16px}}
  ul.verbatim li{{padding:8px 12px;margin:6px 0;border-left:3px solid #06b6d4;background:#06b6d411;color:#e2e8f0;border-radius:0 6px 6px 0;font-size:.88em;line-height:1.7}}
  .text-block{{background:#1e293b;border-radius:8px;padding:12px 16px;color:#cbd5e1;font-size:.88em;line-height:1.7;margin-bottom:16px}}
  .footer{{text-align:center;color:#334155;font-size:.75em;margin-top:32px;padding-top:16px;border-top:1px solid #1e293b}}
</style>
</head>
<body>
<div class="header">
  <h1>🎯 路演情报报告</h1>
  {"<p class='meta'>路演场次：" + interviewee + "</p>" if interviewee else ""}
  {"<p class='meta'>引荐方：" + referrer + "</p>" if referrer else ""}
  {"<p class='meta'>生成时间：" + date_str + "</p>" if date_str else ""}
  <div style="margin-top:12px">
    <span class="atm-badge" style="background:{atm_color}22;color:{atm_color};border-color:{atm_color}44">{atm_text}</span>
    <span class="stage-badge">{e(stage_text)}</span>
  </div>
  <p class="summary">{e(report.get('atmosphere_summary',''))}</p>
</div>
{body}
<div class="footer">仓颉 FOS · 路演情报报告 · 内部使用</div>
</body>
</html>"""


@router.post("/jobs/{job_id}/html-report")
def generate_roadshow_html_report(job_id: str) -> dict[str, Any]:
    """生成路演情报 HTML 报告，保存到 data/html_reports/ 并返回路径。"""
    row = db_job_get(job_id)
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")

    report = row.get("edited_report") or row.get("original_report")
    if not report:
        raise HTTPException(404, f"Job {job_id} has no report data")

    # 生成 HTML
    meta = {
        "interviewee": row.get("interviewee", ""),
        "referrer": row.get("referrer", ""),
        "created_at": row.get("created_at", 0.0),
    }
    html_content = _build_roadshow_html(report, meta)

    # 保存到标准位置（与常规报告共享目录）
    output_dir = get_backend_root() / "data" / "html_reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{job_id}.html"
    output_path.write_text(html_content, encoding="utf-8")

    # 持久化路径
    db_job_update(job_id, html_report_path=str(output_path))

    import time as _time  # noqa: PLC0415
    return {
        "ok": True,
        "html_path": str(output_path),
        "generated_at": _time.time(),
    }


@router.get("/jobs/{job_id}/html-report")
def get_roadshow_html_report(job_id: str) -> FileResponse:
    """下载/预览已生成的路演情报 HTML 报告。"""
    report_path = get_backend_root() / "data" / "html_reports" / f"{job_id}.html"
    if not report_path.exists():
        raise HTTPException(404, "HTML report not yet generated. Call POST first.")
    return FileResponse(
        path=str(report_path),
        media_type="text/html",
        filename=f"roadshow_report_{job_id[:8]}.html",
    )
