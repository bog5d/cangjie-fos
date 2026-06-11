"""需求01·A2 — 覆盖率打分器测试（LLM 全 mock，时长/语速纯计算）。"""
from __future__ import annotations

from cangjie_fos.services import coach_score_service as svc


def _word(text, start, end, idx=0):
    return {"word_index": idx, "text": text, "start_time": start, "end_time": end, "speaker_id": "0"}


_KEY_POINTS = [
    {"point_no": "1", "page_no": 1, "point_text": "商业模式", "weight": "core"},
    {"point_no": "2", "page_no": 1, "point_text": "客户数量", "weight": "normal"},
    {"point_no": "3", "page_no": 2, "point_text": "团队背景", "weight": "minor"},
]


def test_full_coverage(monkeypatch):
    """全部 covered → 覆盖率 100%。"""
    monkeypatch.setattr(svc, "_llm_judge_coverage", lambda kp, t: {
        "1": {"status": "covered", "evidence": "讲了模式"},
        "2": {"status": "covered", "evidence": "30家"},
        "3": {"status": "covered", "evidence": "清华团队"},
    })
    r = svc.score_coverage(_KEY_POINTS, "完整路演转写")
    assert r["coverage_score"] == 100.0
    assert len(r["covered_points"]) == 3
    assert r["missed_points"] == []


def test_weighted_coverage(monkeypatch):
    """漏讲 core(权重3)，命中 normal(2)+minor(1) → 3/6=50%。"""
    monkeypatch.setattr(svc, "_llm_judge_coverage", lambda kp, t: {
        "1": {"status": "missed"},
        "2": {"status": "covered"},
        "3": {"status": "covered"},
    })
    r = svc.score_coverage(_KEY_POINTS, "转写")
    assert r["coverage_score"] == 50.0
    assert len(r["missed_points"]) == 1
    assert r["missed_points"][0]["point_no"] == "1"
    # 漏讲 core 要点应触发警示建议
    assert any("关键要点" in s for s in r["suggestions"])


def test_weak_counts_half(monkeypatch):
    """弱讲计一半分：全 weak → 50%。"""
    monkeypatch.setattr(svc, "_llm_judge_coverage", lambda kp, t: {
        "1": {"status": "weak"}, "2": {"status": "weak"}, "3": {"status": "weak"},
    })
    r = svc.score_coverage(_KEY_POINTS, "转写")
    assert r["coverage_score"] == 50.0
    # weak 计入 covered（命中但不满），不在 missed
    assert len(r["covered_points"]) == 3


def test_delivery_metrics_pure_calc():
    """时长/字数/语速由时间戳纯计算，零 LLM。"""
    words = [
        _word("我", 0.0, 0.5, 0),
        _word("们", 0.5, 1.0, 1),
        _word("做", 1.0, 1.5, 2),
        _word("AI", 1.5, 60.0, 3),
    ]
    m = svc.compute_delivery_metrics(words)
    assert m["duration_sec"] == 60.0
    assert m["word_count"] == 5  # 我+们+做+A+I = 5 字符
    assert m["speech_rate"] == 5.0  # 5字 / 60秒 * 60 = 5 字/分


def test_metrics_empty_words():
    m = svc.compute_delivery_metrics([])
    assert m == {"duration_sec": 0.0, "word_count": 0, "speech_rate": 0.0}


def test_score_with_words_attaches_metrics(monkeypatch):
    """score_coverage 传入 words 时报告带时长/语速。"""
    monkeypatch.setattr(svc, "_llm_judge_coverage", lambda kp, t: {"1": {"status": "covered"}})
    words = [_word("好", 0.0, 30.0, 0)]
    r = svc.score_coverage([_KEY_POINTS[0]], "好", words)
    assert r["duration_sec"] == 30.0
    assert r["word_count"] == 1


def test_no_key_points_returns_zero():
    r = svc.score_coverage([], "随便讲讲")
    assert r["coverage_score"] == 0.0


def test_llm_failure_treated_as_missed(monkeypatch):
    """LLM 判定返回空（失败）→ 全部 missed → 0 分，不崩溃。"""
    monkeypatch.setattr(svc, "_llm_judge_coverage", lambda kp, t: {})
    r = svc.score_coverage(_KEY_POINTS, "转写")
    assert r["coverage_score"] == 0.0
    assert len(r["missed_points"]) == 3
