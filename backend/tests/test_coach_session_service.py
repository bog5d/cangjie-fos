"""需求01·A3 — 教练会话编排测试（DB 隔离 + ASR/LLM mock）。"""
from __future__ import annotations

import pytest

from cangjie_fos.services import coach_keypoint_service as kp_svc
from cangjie_fos.services import coach_score_service as score_svc
from cangjie_fos.services import coach_session_service as sess_svc


_FAKE_POINTS = [
    {"page_no": 1, "point_text": "商业模式是 SaaS 订阅", "weight": "core"},
    {"page_no": 1, "point_text": "已有 30 家客户", "weight": "normal"},
]


def _word(text, start, end, idx=0):
    return {"word_index": idx, "text": text, "start_time": start, "end_time": end, "speaker_id": "0"}


@pytest.fixture()
def patched(monkeypatch):
    """统一打桩：要点提炼 + ASR + 覆盖率判定。"""
    monkeypatch.setattr(kp_svc, "_llm_extract_keypoints_chunk", lambda chunk: [dict(p) for p in _FAKE_POINTS])
    monkeypatch.setattr(sess_svc, "_transcribe", lambda path: [_word("我们做SaaS订阅", 0.0, 30.0, 0)])
    monkeypatch.setattr(score_svc, "_llm_judge_coverage", lambda kp, t: {
        "1": {"status": "covered"}, "2": {"status": "missed"},
    })


def test_create_session_extracts_points(patched):
    result = sess_svc.create_session("zt", "BP逐字稿……", title="A轮路演")
    assert result["count"] == 2
    assert result["session_id"]
    got = sess_svc.get_session(result["session_id"])
    assert got["title"] == "A轮路演"
    assert len(got["key_points"]) == 2


def test_create_session_no_points_raises(monkeypatch):
    monkeypatch.setattr(kp_svc, "_llm_extract_keypoints_chunk", lambda chunk: [])
    with pytest.raises(ValueError):
        sess_svc.create_session("zt", "空洞内容")


def test_submit_round_scores_and_persists(patched):
    sid = sess_svc.create_session("zt", "BP……")["session_id"]
    report = sess_svc.submit_round(sid, "/fake/audio.wav")
    assert report["round_no"] == 1
    # core 命中(权重3) + normal 漏(权重2) → 3/5 = 60%
    assert report["coverage_score"] == 60.0
    assert report["duration_sec"] == 30.0  # 来自 mock 时间戳
    rounds = sess_svc.list_rounds(sid)
    assert len(rounds) == 1
    assert rounds[0]["coverage_score"] == 60.0


def test_multi_round_increments(patched):
    sid = sess_svc.create_session("zt", "BP……")["session_id"]
    sess_svc.submit_round(sid, "/a.wav")
    r2 = sess_svc.submit_round(sid, "/b.wav")
    assert r2["round_no"] == 2
    assert len(sess_svc.list_rounds(sid)) == 2


def test_progress_curve(patched, monkeypatch):
    sid = sess_svc.create_session("zt", "BP……")["session_id"]
    # 第一轮 60%
    sess_svc.submit_round(sid, "/a.wav")
    # 第二轮全命中 100%
    monkeypatch.setattr(score_svc, "_llm_judge_coverage", lambda kp, t: {
        "1": {"status": "covered"}, "2": {"status": "covered"},
    })
    sess_svc.submit_round(sid, "/b.wav")

    curve = sess_svc.get_progress_curve(sid)
    assert len(curve["rounds"]) == 2
    assert curve["rounds"][0]["coverage_score"] == 60.0
    assert curve["rounds"][1]["coverage_score"] == 100.0
    assert curve["best_score"] == 100.0
    assert curve["improvement"] == 40.0  # 100 - 60


def test_submit_round_unknown_session_raises(patched):
    with pytest.raises(ValueError):
        sess_svc.submit_round("nonexistent", "/x.wav")
