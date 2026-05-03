"""wiki_extractor LLM 提炼引擎测试（全 mock LLM，不发真实请求）。"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from cangjie_fos.services.wiki_extractor import (
    extract_entities_from_text,
    parse_extraction_response,
    ENTITY_TYPES,
)


# ── parse_extraction_response（纯函数，无 mock）─────────────────────────────

def test_parse_valid_json_returns_entities():
    raw_json = json.dumps({
        "entities": [
            {
                "name": "红杉资本",
                "type": "institution",
                "new_facts": ["对团队稳定性有担忧"],
                "current_status": "谈判中",
                "timeline_event": {"date": "2026-04-15", "event": "二轮会议"},
            }
        ],
        "relationships": [
            {
                "source": "红杉资本",
                "target": "团队稳定性",
                "relationship": "concerned_about",
                "context": "追问团队构成",
            }
        ],
    })
    result = parse_extraction_response(raw_json)
    assert len(result["entities"]) == 1
    assert result["entities"][0]["name"] == "红杉资本"
    assert result["entities"][0]["type"] == "institution"
    assert len(result["relationships"]) == 1


def test_parse_invalid_json_returns_empty():
    result = parse_extraction_response("这不是 JSON { broken")
    assert result == {"entities": [], "relationships": []}


def test_parse_missing_keys_fills_defaults():
    raw_json = json.dumps({"entities": [{"name": "水导激光", "type": "technology"}]})
    result = parse_extraction_response(raw_json)
    entity = result["entities"][0]
    assert entity["new_facts"] == []
    assert entity["current_status"] == ""
    assert entity["timeline_event"] is None


def test_parse_unknown_entity_type_excluded():
    raw_json = json.dumps({
        "entities": [{"name": "奇怪的东西", "type": "alien", "new_facts": []}],
        "relationships": [],
    })
    result = parse_extraction_response(raw_json)
    assert result["entities"] == []


def test_entity_types_set_contains_expected():
    for t in ("institution", "technology", "risk", "person", "concept", "event"):
        assert t in ENTITY_TYPES


# ── extract_entities_from_text（mock LLM）──────────────────────────────────

def _mock_openai_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    return resp


def test_extract_calls_llm_and_returns_parsed_result():
    fake_llm_output = json.dumps({
        "entities": [
            {
                "name": "红杉资本",
                "type": "institution",
                "new_facts": ["要求补充期权方案"],
                "current_status": "待定",
                "timeline_event": {"date": "2026-04-28", "event": "要求期权方案"},
            }
        ],
        "relationships": [],
    })

    with patch("cangjie_fos.services.wiki_extractor.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_openai_response(fake_llm_output)

        result = extract_entities_from_text(
            text="红杉资本今天要求我们补充期权绑定方案，这是一段足够长的文本用于测试",
            source_type="pitch_recording",
        )

    assert len(result["entities"]) == 1
    assert result["entities"][0]["name"] == "红杉资本"
    mock_client.chat.completions.create.assert_called_once()


def test_extract_llm_returns_malformed_json_gracefully():
    """LLM 返回垃圾时，不抛异常，返回空结果。"""
    with patch("cangjie_fos.services.wiki_extractor.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "对不起，我不懂这个问题。"
        )
        result = extract_entities_from_text(text="任意足够长的文本内容用于测试边界情况处理", source_type="manual_note")

    assert result == {"entities": [], "relationships": []}


def test_extract_short_text_skipped():
    """文本过短（< 20 字符）时直接返回空，不调 LLM。"""
    with patch("cangjie_fos.services.wiki_extractor.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        result = extract_entities_from_text(text="太短", source_type="pitch_recording")

    MockOpenAI.assert_not_called()
    assert result == {"entities": [], "relationships": []}
