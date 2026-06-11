"""
需求01 — 路演 AI 教练 & 答疑 AI 审问 API。

教练（mode=coach）：
  POST /api/v1/coaching/sessions            上传/粘贴 BP → 提炼要点，建会话
  POST /api/v1/coaching/sessions/{id}/rounds 上传录音 → ASR → 覆盖率打分（多轮）
  GET  /api/v1/coaching/sessions/{id}/rounds 历轮明细
  GET  /api/v1/coaching/sessions/{id}/progress 进步曲线

审问（mode=qa）：
  POST /api/v1/coaching/qa/questions        出题（历史迁移 + AI 生成，去重）
  POST /api/v1/coaching/qa/grade            评估一次答疑回答（可选录音转写）
"""
from __future__ import annotations

import logging
import os
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from cangjie_fos.api.upload_io import stream_upload_to_path
from cangjie_fos.core.paths import get_audio_dir
from cangjie_fos.services.coach_session_service import (
    create_session,
    get_session,
    get_progress_curve,
    list_rounds,
    submit_round,
)
from cangjie_fos.services.qa_examiner_service import generate_questions, upsert_question_bank
from cangjie_fos.services.qa_grader_service import grade_answer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/coaching", tags=["coaching"])


# ── 教练：建会话 ──────────────────────────────────────────────
@router.post("/sessions")
async def create_coaching_session(
    file: UploadFile | None = File(None),
    bp_text: str | None = Form(None),
    tenant_id: str = Form("default"),
    title: str = Form(""),
):
    """上传 BP 文件或粘贴逐字稿，提炼要点并创建教练会话。"""
    text = bp_text or ""
    if file and file.filename:
        from cangjie_fos.engine.document_reader import extract_text_from_files  # noqa: PLC0415
        content = await file.read()

        class _Wrap:
            def __init__(self, name: str, data: bytes):
                self.name = name
                self._data = data
            def getvalue(self) -> bytes:
                return self._data

        text = extract_text_from_files([_Wrap(file.filename, content)])

    if not text.strip():
        raise HTTPException(400, "必须提供 BP 文件或逐字稿文字")

    try:
        result = create_session(tenant_id, text, title=title, mode="coach")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return result


@router.get("/sessions/{session_id}")
def get_coaching_session(session_id: str):
    """获取会话详情（含要点清单）。"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, f"会话 {session_id} 不存在")
    return session


# ── 教练：提交一遍录音 ────────────────────────────────────────
@router.post("/sessions/{session_id}/rounds")
async def submit_coaching_round(
    session_id: str,
    file: UploadFile = File(...),
):
    """上传一遍路演录音 → ASR → 覆盖率打分，记为新一轮。"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, f"会话 {session_id} 不存在")

    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    audio_path = Path(get_audio_dir()) / f"coach_{uuid.uuid4().hex}{suffix}"
    await stream_upload_to_path(file, audio_path)

    try:
        report = submit_round(session_id, str(audio_path))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        logger.error("教练打分失败 session=%s: %s", session_id, e)
        raise HTTPException(500, f"打分失败：{e}")
    return report


@router.get("/sessions/{session_id}/rounds")
def get_coaching_rounds(session_id: str):
    """历轮明细。"""
    if not get_session(session_id):
        raise HTTPException(404, f"会话 {session_id} 不存在")
    return list_rounds(session_id)


@router.get("/sessions/{session_id}/progress")
def get_coaching_progress(session_id: str):
    """进步曲线（历轮覆盖率序列）。"""
    if not get_session(session_id):
        raise HTTPException(404, f"会话 {session_id} 不存在")
    return get_progress_curve(session_id)


# ── 审问：出题 ────────────────────────────────────────────────
class QuestionGenRequest(BaseModel):
    material: str
    tenant_id: str = "default"
    sector: str = ""
    round_stage: str = ""
    limit: int = 12


@router.post("/qa/questions")
def gen_qa_questions(req: QuestionGenRequest):
    """生成压力测试问题（历史迁移 + AI 生成，去重）。"""
    questions = generate_questions(
        req.material, tenant_id=req.tenant_id,
        sector=req.sector, round_stage=req.round_stage, limit=req.limit,
    )
    if not questions:
        raise HTTPException(400, "未能生成任何问题，请检查材料内容")
    return {"questions": questions, "count": len(questions)}


# ── 审问：评分（可选录音）──────────────────────────────────────
class GradeRequest(BaseModel):
    question: str
    answer_points: list[str] = []
    transcript: str = ""
    # 沉淀回写参数（可选）
    tenant_id: str = "default"
    sector: str = ""
    round_stage: str = ""
    category: str = "业务"
    persist: bool = True


@router.post("/qa/grade")
def grade_qa_answer(req: GradeRequest):
    """评估一次答疑回答（文字转写）。persist=True 时把问题沉淀回可复用库。"""
    result = grade_answer(req.question, req.answer_points, req.transcript)
    if req.persist and req.question.strip():
        try:
            upsert_question_bank(
                tenant_id=req.tenant_id,
                question_text=req.question.strip(),
                answer_points=req.answer_points,
                category=req.category,
                sector=req.sector,
                round_stage=req.round_stage,
                source="real",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("问题沉淀回写失败（不影响评分）: %s", e)
    return result


@router.post("/qa/grade-audio")
async def grade_qa_answer_audio(
    file: UploadFile = File(...),
    question: str = Form(...),
    answer_points_json: str = Form("[]"),
    tenant_id: str = Form("default"),
):
    """上传录音回答 → ASR → 评分。"""
    import json  # noqa: PLC0415
    try:
        answer_points = json.loads(answer_points_json)
    except json.JSONDecodeError:
        answer_points = []

    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    audio_path = Path(get_audio_dir()) / f"qa_{uuid.uuid4().hex}{suffix}"
    await stream_upload_to_path(file, audio_path)

    from cangjie_fos.services.coach_session_service import _transcribe  # noqa: PLC0415
    words = _transcribe(str(audio_path))
    transcript = "".join(
        (w.get("text") if isinstance(w, dict) else getattr(w, "text", "")) or ""
        for w in words
    )
    result = grade_answer(question, answer_points, transcript)
    result["transcript"] = transcript
    return result
