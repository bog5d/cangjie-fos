"""通用会议纪要 API（非路演场景：高管访谈 / 内部会 / 客户会）。

工作流（单阶段，无需确认发言人）：
  1. POST /api/v1/meeting/start             — 上传录音或文字稿，启动 ASR+纪要（后台），返回 job_id
  2. GET  /api/v1/meeting/jobs/{job_id}/status  — 轮询状态
  3. GET  /api/v1/meeting/jobs/{job_id}/report  — 获取 MeetingMinutesReport
  4. POST/GET /api/v1/meeting/jobs/{job_id}/html-report — 生成/下载 HTML 纪要
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from cangjie_fos.core.paths import get_backend_root, get_audio_dir
from cangjie_fos.schemas.pitch_upload import PitchJobStatus
from cangjie_fos.api.upload_io import stream_upload_to_path
from cangjie_fos.services.pitch_job_db import db_job_get, db_job_update
from cangjie_fos.services.pitch_job_store import job_create, job_update
from cangjie_fos.services.pitch_upload_pipeline import run_meeting_minutes_job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/meeting", tags=["meeting-minutes"])


class MeetingStartResponse(BaseModel):
    job_id: str
    status: str
    message: str


class MeetingJobStatus(BaseModel):
    job_id: str
    status: str
    substatus: str | None = None
    has_report: bool = False
    report: dict | None = None
    created_at: float = 0.0


@router.post("/start", response_model=MeetingStartResponse)
async def meeting_start(
    background_tasks: BackgroundTasks,
    tenant_id: str = Query(..., description="租户 ID"),
    meeting_title: str = Query(default="", description="会议主题（可选）"),
    file: UploadFile | None = None,
    transcript_text: str | None = None,
) -> MeetingStartResponse:
    """上传会议录音或文字稿，启动 ASR + 纪要提炼，返回 job_id。

    - file: 音频文件（mp3/m4a/wav 等）
    - transcript_text: 直接粘贴文字稿（跳过 ASR）
    """
    job_id = str(uuid.uuid4())
    label = meeting_title.strip() or "会议纪要"

    job_create(job_id, tenant_id=tenant_id)
    db_job_update(
        job_id,
        interviewee=label,
        category="06_通用会议纪要",
        is_roadshow=0,
    )

    if file is not None:
        fname = file.filename or f"meeting_{job_id}.mp3"
        suffix = Path(fname).suffix or ".mp3"
        audio_dir = get_audio_dir()
        audio_dir.mkdir(parents=True, exist_ok=True)
        incoming_path = audio_dir / f"{job_id}_incoming{suffix}"
        await stream_upload_to_path(file, incoming_path)

        background_tasks.add_task(
            run_meeting_minutes_job,
            job_id=job_id,
            filename=fname,
            tenant_id=tenant_id,
            meeting_title=label,
            pre_written_path=incoming_path,
        )
        return MeetingStartResponse(
            job_id=job_id,
            status="transcribing",
            message="音频已上传，ASR 转写 + 纪要提炼中，请稍候…",
        )

    if transcript_text and transcript_text.strip():
        # 文字稿路径：跳过 ASR，直接解析为词并走纪要提炼分支
        from cangjie_fos.services.transcript_parser import parse_transcript_to_words  # noqa: PLC0415
        from cangjie_fos.services.pitch_graph_service import PitchGraphService  # noqa: PLC0415

        words = parse_transcript_to_words(transcript_text)

        def _run_text_only() -> None:
            try:
                db_job_update(
                    job_id,
                    status=str(PitchJobStatus.EVALUATING),
                    substatus="正在提炼会议纪要…",
                    words_json=[w.model_dump() for w in words],
                )
                job_update(job_id, status=PitchJobStatus.EVALUATING)
                report, _ = PitchGraphService.run_evaluation_with_state(
                    tenant_id=tenant_id,
                    words=words,
                    model_choice="deepseek",
                    explicit_context={
                        "source": "meeting_minutes",
                        "interviewee": label,
                        "biz_type": "06_通用会议纪要",
                    },
                    trace_id=job_id,
                )
                report_dict = report.model_dump()
                job_update(job_id, status=PitchJobStatus.COMPLETED, report=report_dict)
                db_job_update(
                    job_id,
                    status=str(PitchJobStatus.COMPLETED),
                    original_report=report_dict,
                    substatus=None,
                )
            except Exception as e:  # noqa: BLE001
                logger.exception("meeting_minutes_text_only_failed job_id=%s", job_id)
                db_job_update(job_id, status=str(PitchJobStatus.FAILED),
                              error_summary=str(e), substatus=None)

        background_tasks.add_task(_run_text_only)
        return MeetingStartResponse(
            job_id=job_id,
            status="evaluating",
            message=f"文字稿解析完成（{len(words)} 词），正在提炼纪要…",
        )

    raise HTTPException(400, "必须提供音频文件（file）或文字稿（transcript_text）之一")


@router.get("/jobs/{job_id}/status", response_model=MeetingJobStatus)
def meeting_job_status(job_id: str) -> MeetingJobStatus:
    """轮询 job 状态（前端等待页使用）。"""
    row = db_job_get(job_id)
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")
    return MeetingJobStatus(
        job_id=job_id,
        status=row.get("status", "pending"),
        substatus=row.get("substatus"),
        has_report=bool(row.get("original_report")),
        report=row.get("original_report") if row.get("original_report") else None,
        created_at=row.get("created_at", 0.0),
    )


@router.get("/jobs/{job_id}/report")
def meeting_report(job_id: str) -> dict[str, Any]:
    """获取已完成的会议纪要报告。"""
    row = db_job_get(job_id)
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")
    if row.get("status") != str(PitchJobStatus.COMPLETED):
        raise HTTPException(400, f"Job {job_id} not completed yet (status: {row.get('status')})")
    report = row.get("edited_report") or row.get("original_report")
    if not report:
        raise HTTPException(404, f"Job {job_id} has no report")
    return {
        "job_id": job_id,
        "report": report,
        "interviewee": row.get("interviewee", ""),
        "created_at": row.get("created_at", 0.0),
    }


# ── HTML 报告生成 ──────────────────────────────────────────────────────────────

def _build_minutes_html(report: dict, meta: dict) -> str:
    """根据 MeetingMinutesReport dict 生成自包含 HTML 字符串（纯模板，无音频依赖）。"""
    import html as _html
    from datetime import datetime  # noqa: PLC0415

    def e(v: Any) -> str:
        return _html.escape(str(v or ""), quote=True)

    priority_color = {
        "urgent": "#f43f5e", "normal": "#06b6d4", "optional": "#64748b",
    }

    title = e(meta.get("interviewee", "") or report.get("meeting_title", "") or "会议纪要")
    created_at = meta.get("created_at", 0.0)
    try:
        date_str = datetime.fromtimestamp(float(created_at)).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        date_str = ""

    attendees = report.get("attendees") or []
    attendees_str = "、".join(e(a) for a in attendees) if attendees else ""

    sections: list[str] = []

    key_points = report.get("key_points") or []
    if key_points:
        items = "".join(f"<li>{e(p)}</li>" for p in key_points)
        sections.append(f'<h2>讨论要点</h2><ul class="points">{items}</ul>')

    decisions = report.get("decisions") or []
    if decisions:
        items = "".join(f"<li>✅ {e(d)}</li>" for d in decisions)
        sections.append(f'<h2>会议决议</h2><ul class="decisions">{items}</ul>')

    action_items = report.get("action_items") or []
    if action_items:
        rows = ""
        for a in action_items:
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
            f'<h2>待办行动项 ({len(action_items)})</h2>'
            f'<table><thead><tr><th>优先级</th><th>性质</th><th>行动</th><th>负责方</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
        )

    open_questions = report.get("open_questions") or []
    if open_questions:
        items = "".join(f"<li>⚠ {e(q)}</li>" for q in open_questions)
        sections.append(f'<h2>遗留问题</h2><ul class="concerns">{items}</ul>')

    body = "\n".join(sections)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>会议纪要 — {title}</title>
<style>
  body{{font-family:"PingFang SC","Microsoft YaHei",sans-serif;background:#0d0d1a;color:#e2e8f0;margin:0;padding:24px}}
  .header{{background:linear-gradient(135deg,#0f172a,#1e3a4a);border:1px solid #1e3a5f;border-radius:12px;padding:24px;margin-bottom:24px}}
  .header h1{{margin:0 0 8px;font-size:1.4em;color:#67e8f9}}
  .meta{{font-size:.85em;color:#94a3b8;margin:4px 0}}
  .draft-badge{{display:inline-block;padding:4px 12px;border-radius:6px;font-weight:bold;font-size:.85em;margin:8px 0;border:1px solid #f59e0b44;background:#f59e0b22;color:#fbbf24}}
  .summary{{margin-top:12px;color:#cbd5e1;line-height:1.7;font-size:.9em}}
  h2{{color:#67e8f9;font-size:1em;text-transform:uppercase;letter-spacing:.1em;border-bottom:1px solid #1e3a5f;padding-bottom:6px;margin:24px 0 12px}}
  table{{width:100%;border-collapse:collapse;font-size:.85em;margin-bottom:16px}}
  th{{background:#1e293b;color:#94a3b8;text-align:left;padding:8px 10px;font-weight:600;font-size:.75em;text-transform:uppercase}}
  td{{padding:8px 10px;border-bottom:1px solid #1e293b;vertical-align:top;line-height:1.6}}
  .tag{{display:inline-block;padding:1px 6px;border-radius:4px;font-size:.75em;font-weight:bold;border:1px solid;margin-right:4px}}
  ul.points li{{padding:6px 10px;margin:4px 0;border-left:3px solid #06b6d4;background:#06b6d411;border-radius:0 6px 6px 0;font-size:.88em;line-height:1.7;list-style:none}}
  ul.points{{padding:0;margin:0 0 16px}}
  ul.decisions{{list-style:none;padding:0;margin:0 0 16px}}
  ul.decisions li{{padding:6px 10px;margin:4px 0;border-left:3px solid #10b981;background:#10b98111;color:#a7f3d0;border-radius:0 6px 6px 0;font-size:.88em}}
  ul.concerns{{list-style:none;padding:0;margin:0 0 16px}}
  ul.concerns li{{padding:6px 10px;margin:4px 0;border-left:3px solid #f59e0b;background:#f59e0b11;color:#fde68a;border-radius:0 6px 6px 0;font-size:.88em}}
  .footer{{text-align:center;color:#334155;font-size:.75em;margin-top:32px;padding-top:16px;border-top:1px solid #1e293b}}
</style>
</head>
<body>
<div class="header">
  <h1>📝 会议纪要</h1>
  {"<p class='meta'>会议：" + title + "</p>" if title else ""}
  {"<p class='meta'>参会：" + attendees_str + "</p>" if attendees_str else ""}
  {"<p class='meta'>生成时间：" + date_str + "</p>" if date_str else ""}
  <div class="draft-badge">AI 初稿 · 待人工审核</div>
  <p class="summary">{e(report.get('summary',''))}</p>
</div>
{body}
<div class="footer">仓颉 FOS · 会议纪要 · 内部使用</div>
</body>
</html>"""


@router.post("/jobs/{job_id}/html-report")
def generate_meeting_html_report(job_id: str) -> dict[str, Any]:
    """生成会议纪要 HTML，保存到 data/html_reports/ 并返回路径。"""
    row = db_job_get(job_id)
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")
    report = row.get("edited_report") or row.get("original_report")
    if not report:
        raise HTTPException(404, f"Job {job_id} has no report data")

    meta = {
        "interviewee": row.get("interviewee", ""),
        "created_at": row.get("created_at", 0.0),
    }
    html_content = _build_minutes_html(report, meta)

    output_dir = get_backend_root() / "data" / "html_reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{job_id}.html"
    output_path.write_text(html_content, encoding="utf-8")
    db_job_update(job_id, html_report_path=str(output_path))

    import time as _time  # noqa: PLC0415
    return {"ok": True, "html_path": str(output_path), "generated_at": _time.time()}


@router.get("/jobs/{job_id}/html-report")
def get_meeting_html_report(job_id: str) -> FileResponse:
    """下载/预览已生成的会议纪要 HTML。"""
    report_path = get_backend_root() / "data" / "html_reports" / f"{job_id}.html"
    if not report_path.exists():
        raise HTTPException(404, "HTML report not yet generated. Call POST first.")
    return FileResponse(
        path=str(report_path),
        media_type="text/html",
        filename=f"meeting_minutes_{job_id[:8]}.html",
    )
