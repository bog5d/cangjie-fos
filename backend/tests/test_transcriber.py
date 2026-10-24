"""transcriber.py 单元测试 — 重点覆盖 _map_aliyun_paraformer_to_schema 的段落下坠逻辑。

Bug #1: 录音片段不完整 — 当 Paraformer 返回的句子缺词级时间戳时，
整句被静默丢弃，导致转写输出缺失段落。

运行: uv run --extra dev pytest tests/test_transcriber.py -v
"""
from __future__ import annotations

import pytest
from cangjie_fos.engine.transcriber import _map_aliyun_paraformer_to_schema


# ── 构造 Paraformer 风格响应 JSON ────────────────────────────────

def _make_paraformer_response(sentences: list[dict]) -> dict:
    """构造标准的 Paraformer 转写结果 JSON 结构。"""
    return {
        "transcripts": [
            {
                "sentences": sentences,
            }
        ]
    }


def _sentence_with_words(
    begin_ms: int,
    end_ms: int,
    words_data: list[tuple[int, int, str]],
    *,
    text: str = "",
    speaker_id: str = "spk_0",
) -> dict:
    """构造一个句子，其每个词都有 begin_time/end_time。"""
    return {
        "begin_time": begin_ms,
        "end_time": end_ms,
        "text": text or " ".join(w[2] for w in words_data),
        "speaker_id": speaker_id,
        "words": [
            {"begin_time": bt, "end_time": et, "text": txt}
            for bt, et, txt in words_data
        ],
    }


def _sentence_without_word_times(
    begin_ms: int,
    end_ms: int,
    *,
    text: str = "这是一句没有词级时间戳的话。",
    speaker_id: str = "spk_1",
) -> dict:
    """构造一个句子，有句子级时间戳但词级缺 begin_time/end_time。"""
    return {
        "begin_time": begin_ms,
        "end_time": end_ms,
        "text": text,
        "speaker_id": speaker_id,
        "words": [
            {"text": "这是"},
            {"text": "一句"},
            {"text": "没有词级时间戳的话"},
        ],
    }


def _sentence_with_mixed_word_times(
    begin_ms: int,
    end_ms: int,
    *,
    text: str = "部分词有时间戳部分没有。",
    speaker_id: str = "spk_2",
) -> dict:
    """构造一个句子，部分词有时间戳，部分没有。"""
    return {
        "begin_time": begin_ms,
        "end_time": end_ms,
        "text": text,
        "speaker_id": speaker_id,
        "words": [
            {"begin_time": begin_ms, "end_time": begin_ms + 500, "text": "部分"},
            {"begin_time": begin_ms + 500, "end_time": begin_ms + 1000, "text": "词有"},
            {"text": "时间戳"},  # 缺时间戳
            {"begin_time": begin_ms + 1200, "end_time": end_ms, "text": "部分没有"},
        ],
    }


# ── 测试 ──────────────────────────────────────────────────────────


class TestMapAliyunParaformerBasic:
    """基础场景：词级数据完整时是否正常工作。"""

    def test_single_sentence_with_full_word_times(self):
        """一个句子所有词都有 begin_time/end_time → 应全部产出。"""
        result = _make_paraformer_response([
            _sentence_with_words(0, 3000, [
                (0, 1000, "你好"),
                (1000, 2000, "世界"),
                (2000, 3000, "。"),
            ]),
        ])
        words = _map_aliyun_paraformer_to_schema(result)
        assert len(words) == 3
        assert words[0].text == "你好"
        assert words[0].start_time == 0.0
        assert words[0].end_time == 1.0

    def test_sentence_terminal_punct_appended(self):
        """句末标点应追加到最后一个词。"""
        result = _make_paraformer_response([
            _sentence_with_words(0, 2000, [
                (0, 1000, "你好"),
                (1000, 2000, "世界"),
            ], text="你好世界。"),
        ])
        words = _map_aliyun_paraformer_to_schema(result)
        assert len(words) == 2
        assert words[1].text == "世界。"

    def test_empty_sentences_returns_empty(self):
        """空句子列表应返回空。"""
        result = _make_paraformer_response([])
        with pytest.raises(ValueError, match="未找到带 begin_time"):
            _map_aliyun_paraformer_to_schema(result)


class TestMapAliyunParaformerBug1:
    """Bug #1 场景：缺词级时间戳时的段落下坠。"""

    def test_sentence_without_word_times_not_dropped(self):
        """句子有 begin_time/end_time 但词级缺时间戳 → 不应静默丢弃整句。

        这是 Bug #1 的核心场景。Paraformer 可能在词级不返回时间戳，
        但句子级仍有 begin_time/end_time 可用作兜底。
        """
        result = _make_paraformer_response([
            _sentence_without_word_times(1000, 5000, text="这是第一句。"),
        ])
        words = _map_aliyun_paraformer_to_schema(result)
        # 当前行为：返回 0 词（整句被丢弃）
        # 期望行为：返回至少 1 词（用句子级时间戳兜底）
        assert len(words) >= 1, (
            f"Bug #1: 句子缺词级时间戳时被静默丢弃，"
            f"预期至少产出 1 个词，实际 {len(words)} 个"
        )

    def test_sentence_fallback_uses_sentence_level_times(self):
        """句子级时间戳兜底时应正确映射。"""
        result = _make_paraformer_response([
            _sentence_without_word_times(2000, 7000, text="兜底测试。"),
        ])
        words = _map_aliyun_paraformer_to_schema(result)
        assert len(words) >= 1
        if len(words) == 1:
            w = words[0]
            # 毫秒 → 秒：2000ms → 2.0s, 7000ms → 7.0s
            assert w.start_time == pytest.approx(2.0)
            assert w.end_time == pytest.approx(7.0)
            assert "兜底测试" in w.text

    def test_mixed_sentences_some_with_some_without(self):
        """混合场景：一个句子有词级时间戳，另一个没有。"""
        result = _make_paraformer_response([
            _sentence_with_words(0, 3000, [
                (0, 1500, "有词级"),
                (1500, 3000, "时间戳"),
            ], text="有词级时间戳。"),
            _sentence_without_word_times(3000, 6000, text="缺词级时间戳。"),
        ])
        words = _map_aliyun_paraformer_to_schema(result)
        assert len(words) >= 3, (
            f"混合场景：预期 ≥3 词（2 正常词 + ≥1 兜底词），实际 {len(words)}"
        )

    def test_mixed_words_within_sentence_not_dropped(self):
        """句中部分词缺时间戳 → 不应丢弃该词。"""
        result = _make_paraformer_response([
            _sentence_with_mixed_word_times(0, 3000, text="部分词有时间戳部分没有。"),
        ])
        words = _map_aliyun_paraformer_to_schema(result)
        # 当前行为：只返回 3 个词（"时间戳" 被丢弃）
        # 期望行为：返回 4 个词（全部保留）
        assert len(words) >= 3, (
            f"句中缺时间戳的词不应被丢弃，预期 ≥3 词，实际 {len(words)}"
        )

    def test_multiple_speakers_retained(self):
        """多说话人场景，所有句子的 speaker_id 应正确保留。"""
        result = _make_paraformer_response([
            _sentence_with_words(0, 2000, [
                (0, 1000, "投资人"),
                (1000, 2000, "说"),
            ], text="投资人说。", speaker_id="speaker_0"),
            _sentence_without_word_times(2000, 4000, text="创始人回应。", speaker_id="speaker_1"),
        ])
        words = _map_aliyun_paraformer_to_schema(result)
        speaker_ids = set(w.speaker_id for w in words)
        assert "speaker_0" in speaker_ids, "speaker_0 应保留"
        assert "speaker_1" in speaker_ids, "speaker_1 应保留"


class TestWordOrderAndIndices:
    """词序与索引的正确性。"""

    def test_word_indices_sequential(self):
        """word_index 应自增且连续。"""
        result = _make_paraformer_response([
            _sentence_with_words(0, 2000, [
                (0, 1000, "A"),
                (1000, 2000, "B"),
            ]),
            _sentence_with_words(2000, 4000, [
                (2000, 3000, "C"),
                (3000, 4000, "D"),
            ]),
        ])
        words = _map_aliyun_paraformer_to_schema(result)
        indices = [w.word_index for w in words]
        assert indices == [0, 1, 2, 3]

    def test_start_end_times_increasing(self):
        """start_time 应单调递增。"""
        result = _make_paraformer_response([
            _sentence_with_words(1000, 5000, [
                (1000, 2000, "词1"),
                (2000, 3000, "词2"),
                (3000, 4000, "词3"),
            ]),
        ])
        words = _map_aliyun_paraformer_to_schema(result)
        for i in range(1, len(words)):
            assert words[i].start_time >= words[i - 1].start_time
