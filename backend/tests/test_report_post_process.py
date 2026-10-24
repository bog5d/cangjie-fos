"""Unit tests for report_post_process.expand_risk_original_text."""
from __future__ import annotations

import pytest

from cangjie_fos.services.report_post_process import (
    _reconstruct_segment,
    _words_to_lookup,
    expand_risk_original_text,
)


def _make_word(idx: int, text: str, speaker: str = "A") -> dict:
    return {"word_index": idx, "text": text, "speaker_id": speaker}


def _make_words(*pairs: tuple[int, str, str]) -> list[dict]:
    return [_make_word(i, t, s) for i, t, s in pairs]


# --- _words_to_lookup ---

def test_lookup_uses_word_index() -> None:
    words = [{"word_index": 10, "text": "hello", "speaker_id": "A"}]
    lu = _words_to_lookup(words)
    assert 10 in lu
    assert lu[10]["text"] == "hello"


def test_lookup_falls_back_to_list_position() -> None:
    words = [{"text": "a"}, {"text": "b"}]
    lu = _words_to_lookup(words)
    assert lu[0]["text"] == "a"
    assert lu[1]["text"] == "b"


# --- _reconstruct_segment ---

def test_reconstruct_single_speaker() -> None:
    words = _make_words((0, "你好", "A"), (1, "世界", "A"))
    lu = _words_to_lookup(words)
    result = _reconstruct_segment(lu, 0, 1)
    assert result == "你好 世界"
    assert "[A]" not in result  # single speaker → no prefix (默认剥前缀)


def test_reconstruct_single_speaker_can_keep_label() -> None:
    words = _make_words((0, "你好", "A"), (1, "世界", "A"))
    lu = _words_to_lookup(words)
    result = _reconstruct_segment(lu, 0, 1, strip_single_speaker_prefix=False)
    assert "[A]" in result


def test_reconstruct_multi_speaker() -> None:
    words = _make_words((0, "问题", "A"), (1, "回答", "B"))
    lu = _words_to_lookup(words)
    result = _reconstruct_segment(lu, 0, 1)
    assert "[A]" in result
    assert "[B]" in result
    assert "问题" in result
    assert "回答" in result


def test_reconstruct_empty_range() -> None:
    lu = _words_to_lookup(_make_words((5, "x", "A")))
    assert _reconstruct_segment(lu, 0, 3) == ""


def test_reconstruct_inverted_range() -> None:
    lu = _words_to_lookup(_make_words((0, "x", "A")))
    assert _reconstruct_segment(lu, 5, 3) == ""


def test_reconstruct_skips_empty_text() -> None:
    words = [
        {"word_index": 0, "text": "", "speaker_id": "A"},
        {"word_index": 1, "text": "内容", "speaker_id": "A"},
    ]
    lu = _words_to_lookup(words)
    result = _reconstruct_segment(lu, 0, 1)
    assert result == "内容"


# --- expand_risk_original_text ---

def _make_report(risk_points: list[dict]) -> dict:
    return {"total_score": 80, "risk_points": risk_points}


def test_expand_replaces_shorter_original() -> None:
    words = _make_words(
        (0, "这", "A"), (1, "是", "A"), (2, "一段", "A"),
        (3, "很长", "A"), (4, "的", "A"), (5, "原文实录", "A"),
    )
    rp = {
        "start_word_index": 0,
        "end_word_index": 5,
        "original_text": "摘录",  # very short → ratio will exceed 1.2
        "description": "test risk",
    }
    report = _make_report([rp])
    expand_risk_original_text(report, words)
    assert report["risk_points"][0]["original_text"] != "摘录"
    assert "原文实录" in report["risk_points"][0]["original_text"]


def test_expand_keeps_longer_original() -> None:
    words = _make_words((0, "短", "A"))
    rp = {
        "start_word_index": 0,
        "end_word_index": 0,
        "original_text": "这是一段已经很长的原文，比重建结果长得多，不应该被替换掉",
    }
    report = _make_report([rp])
    original = rp["original_text"]
    expand_risk_original_text(report, words)
    assert report["risk_points"][0]["original_text"] == original


def test_expand_replaces_when_original_empty() -> None:
    words = _make_words((0, "内容", "A"))
    rp = {"start_word_index": 0, "end_word_index": 0, "original_text": ""}
    report = _make_report([rp])
    expand_risk_original_text(report, words)
    out = report["risk_points"][0]["original_text"]
    assert "内容" in out
    assert "[A]" in out  # HITL 风险点保留单说话人标签


def test_expand_skips_missing_indices() -> None:
    words = _make_words((0, "x", "A"))
    rp = {"original_text": "保持不变", "description": "no indices"}
    report = _make_report([rp])
    expand_risk_original_text(report, words)
    assert report["risk_points"][0]["original_text"] == "保持不变"


def test_expand_empty_words_noop() -> None:
    rp = {"start_word_index": 0, "end_word_index": 1, "original_text": "原"}
    report = _make_report([rp])
    expand_risk_original_text(report, [])
    assert report["risk_points"][0]["original_text"] == "原"


def test_expand_returns_same_dict() -> None:
    report = _make_report([])
    result = expand_risk_original_text(report, [])
    assert result is report


def test_expand_non_dict_report_noop() -> None:
    result = expand_risk_original_text("not a dict", [{"word_index": 0, "text": "x"}])  # type: ignore[arg-type]
    assert result == "not a dict"
