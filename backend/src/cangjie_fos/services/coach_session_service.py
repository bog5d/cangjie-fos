"""
需求01·A3 — 路演教练会话编排（多轮 + 进步曲线）。

create_session：读 BP → 提炼要点 → 落 coaching_sessions
submit_round：录音 → ASR → 覆盖率打分 → 落 coaching_rounds
get_progress_curve：历轮覆盖率序列（进步曲线数据源）

ASR 通过 _transcribe（可 monkeypatch）注入，测试无需真实音频。
"""
from __future__ import annotations

import json
import logging
import time
import uuid

from cangjie_fos.services.db_base import _connect
from cangjie_fos.services.coach_keypoint_service import extract_key_points
from cangjie_fos.services.coach_score_service import score_coverage

logger = logging.getLogger(__name__)


def create_session(
    tenant_id: str,
    bp_text: str,
    title: str = "",
    mode: str = "coach",
    bp_doc_path: str = "",
) -> dict:
    """提炼 BP 要点并创建教练会话。返回 {session_id, key_points, count}。"""
    key_points = extract_key_points(bp_text)
    if not key_points:
        raise ValueError("未能从 BP 提炼出任何要点，请检查逐字稿内容")

    session_id = str(uuid.uuid4())
    with _connect() as conn:
        conn.execute(
            """INSERT INTO coaching_sessions
               (session_id, tenant_id, mode, title, bp_doc_path, key_points_json, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'ready', ?)""",
            (session_id, tenant_id, mode, title, bp_doc_path,
             json.dumps(key_points, ensure_ascii=False), time.time()),
        )
    return {"session_id": session_id, "key_points": key_points, "count": len(key_points)}


def get_session(session_id: str) -> dict | None:
    """读取会话（含解析后的要点清单）。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM coaching_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    data["key_points"] = json.loads(data.get("key_points_json") or "[]")
    return data


def _transcribe(audio_path: str) -> list:
    """ASR 注入点（测试 monkeypatch 此函数返回 TranscriptionWord 列表）。"""
    from cangjie_fos.engine.transcriber import transcribe_audio  # noqa: PLC0415
    return transcribe_audio(audio_path)


def submit_round(session_id: str, audio_path: str) -> dict:
    """提交一遍录音：ASR → 覆盖率打分 → 落库为新一轮。返回该轮报告。"""
    session = get_session(session_id)
    if not session:
        raise ValueError(f"会话 {session_id} 不存在")
    key_points = session["key_points"]

    words = _transcribe(audio_path)
    transcript = "".join(
        (w.get("text") if isinstance(w, dict) else getattr(w, "text", "")) or ""
        for w in words
    )
    report = score_coverage(key_points, transcript, words)

    round_no = _next_round_no(session_id)
    round_id = str(uuid.uuid4())
    with _connect() as conn:
        conn.execute(
            """INSERT INTO coaching_rounds
               (round_id, session_id, round_no, audio_path, transcript_text,
                coverage_score, covered_points_json, missed_points_json, feedback_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (round_id, session_id, round_no, audio_path, transcript,
             report["coverage_score"],
             json.dumps(report["covered_points"], ensure_ascii=False),
             json.dumps(report["missed_points"], ensure_ascii=False),
             json.dumps({
                 "suggestions": report["suggestions"],
                 "duration_sec": report["duration_sec"],
                 "speech_rate": report["speech_rate"],
                 "word_count": report["word_count"],
             }, ensure_ascii=False),
             time.time()),
        )
        conn.execute(
            "UPDATE coaching_sessions SET status = 'in_progress' WHERE session_id = ?",
            (session_id,),
        )
    return {"round_id": round_id, "round_no": round_no, **report}


def _next_round_no(session_id: str) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT MAX(round_no) AS m FROM coaching_rounds WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return (row["m"] or 0) + 1


def list_rounds(session_id: str) -> list[dict]:
    """返回该会话所有轮次（按轮序），含解析后的要点/反馈。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM coaching_rounds WHERE session_id = ? ORDER BY round_no",
            (session_id,),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        d["covered_points"] = json.loads(d.get("covered_points_json") or "[]")
        d["missed_points"] = json.loads(d.get("missed_points_json") or "[]")
        d["feedback"] = json.loads(d.get("feedback_json") or "{}")
        out.append(d)
    return out


def get_progress_curve(session_id: str) -> dict:
    """进步曲线：历轮覆盖率序列 + 趋势。"""
    rounds = list_rounds(session_id)
    points = [
        {"round_no": r["round_no"], "coverage_score": r["coverage_score"]}
        for r in rounds
    ]
    delta = 0.0
    if len(points) >= 2:
        delta = round((points[-1]["coverage_score"] or 0) - (points[0]["coverage_score"] or 0), 1)
    return {
        "session_id": session_id,
        "rounds": points,
        "best_score": max((p["coverage_score"] or 0 for p in points), default=0.0),
        "improvement": delta,
    }
