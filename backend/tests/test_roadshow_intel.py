"""路演情报分析模块测试（Phase 7）

验证：
1. RoadshowIntelReport schema 可正常序列化/反序列化
2. category=='01_机构路演' 时走 intel 分支（不走 LangGraph）
3. 其他 category 仍走 LangGraph 分支（保持现有行为）
4. run_roadshow_intel_analysis LLM mock 端到端
5. pitch_graph_service 分支路由逻辑（mock LLM，验证 report_type）
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch

# ── schema 层测试 ─────────────────────────────────────────────────────────────

def test_roadshow_intel_report_schema_minimal():
    """最小合法 RoadshowIntelReport 可以通过 Pydantic 验证。"""
    from cangjie_fos.engine.schema import RoadshowIntelReport
    r = RoadshowIntelReport(
        meeting_atmosphere="warm",
        atmosphere_summary="会议氛围正常，对方表现出一定兴趣。",
    )
    assert r.report_type == "roadshow_intel"
    assert r.meeting_atmosphere == "warm"
    assert r.key_questions == []
    assert r.next_actions == []


def test_roadshow_intel_report_schema_full():
    """完整字段的 RoadshowIntelReport 可以正常序列化为 JSON 并反序列化。"""
    from cangjie_fos.engine.schema import RoadshowIntelReport, IntelQuestion, IntelSignal, IntelAction
    r = RoadshowIntelReport(
        meeting_atmosphere="hot",
        meeting_stage="deep_discussion",
        atmosphere_summary="对方表现出强烈投资兴趣，主动追问尽调时间表。",
        key_questions=[
            IntelQuestion(
                speaker_id="A",
                verbatim="你们的退出路径是什么？",
                underlying_concern="担心流动性风险",
                priority="high",
            )
        ],
        interest_signals=[
            IntelSignal(
                speaker_id="A",
                verbatim="这个赛道我们一直在看，你们是少数有真实收入的",
                signal_type="positive",
                interpretation="对项目商业化阶段认可",
            )
        ],
        hidden_concerns=["对GP团队的行业资源有隐性质疑"],
        key_verbatim_moments=["「我们的合伙人会亲自来看一次」"],
        institution_update="新川基金偏好有真实ARR的项目，决策周期约6周",
        next_actions=[
            IntelAction(
                source="commitment",
                actor="对方",
                action="下周安排合伙人会议",
                priority="urgent",
            )
        ],
    )
    dumped = r.model_dump()
    assert dumped["report_type"] == "roadshow_intel"
    assert dumped["meeting_atmosphere"] == "hot"
    assert dumped["key_questions"][0]["priority"] == "high"

    # 反序列化
    r2 = RoadshowIntelReport.model_validate(dumped)
    assert r2.meeting_stage == "deep_discussion"
    assert len(r2.next_actions) == 1


def test_roadshow_intel_report_json_round_trip():
    """通过 JSON 字符串的序列化 → 反序列化循环。"""
    from cangjie_fos.engine.schema import RoadshowIntelReport
    r = RoadshowIntelReport(
        meeting_atmosphere="cold",
        atmosphere_summary="兴趣不足，对方频繁看手机。",
    )
    raw = r.model_dump_json()
    r2 = RoadshowIntelReport.model_validate_json(raw)
    assert r2.meeting_atmosphere == "cold"
    assert r2.report_type == "roadshow_intel"


# ── run_roadshow_intel_analysis 端到端（mock LLM）────────────────────────────

def _make_mock_llm_response(payload: dict) -> MagicMock:
    """构造 openai ChatCompletion mock。"""
    msg = MagicMock()
    msg.content = json.dumps(payload, ensure_ascii=False)
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_run_roadshow_intel_analysis_success():
    """mock LLM，验证 run_roadshow_intel_analysis 返回合法 RoadshowIntelReport。"""
    from cangjie_fos.engine.coach.llm_judge import run_roadshow_intel_analysis

    payload = {
        "report_type": "roadshow_intel",
        "meeting_atmosphere": "warm",
        "meeting_stage": "first_contact",
        "atmosphere_summary": "初次见面，气氛融洽，对方问了2个核心问题。",
        "key_questions": [
            {
                "speaker_id": "A",
                "verbatim": "你们的营收规模是多少？",
                "underlying_concern": "关心商业化进展",
                "priority": "high",
            }
        ],
        "interest_signals": [],
        "hidden_concerns": [],
        "key_verbatim_moments": ["「这个方向我们有布局」"],
        "institution_update": "",
        "next_actions": [],
    }

    words = [
        {"word_index": 0, "text": "你们的营收规模是多少？", "start_time": 0, "end_time": 2, "speaker_id": "A"},
        {"word_index": 1, "text": "目前ARR约500万", "start_time": 3, "end_time": 5, "speaker_id": "B"},
    ]

    mock_resp = _make_mock_llm_response(payload)

    with patch("cangjie_fos.engine.coach.llm_judge._evaluation._make_client") as mock_client_fn, \
         patch("cangjie_fos.engine.coach.llm_judge._roadshow.run_with_backoff") as mock_backoff:
        mock_client = MagicMock()
        mock_client_fn.return_value = (mock_client, "deepseek-chat")
        mock_backoff.return_value = mock_resp

        result = run_roadshow_intel_analysis(
            words,
            model_choice="deepseek",
            explicit_context={"biz_type": "01_机构路演", "recording_label": "test"},
        )

    assert result.report_type == "roadshow_intel"
    assert result.meeting_atmosphere == "warm"
    assert len(result.key_questions) == 1
    assert result.key_questions[0].underlying_concern == "关心商业化进展"


def test_run_roadshow_intel_analysis_llm_parse_failure_graceful():
    """LLM 返回非法 JSON 时，降级为最小合法报告，不抛异常。"""
    from cangjie_fos.engine.coach.llm_judge import run_roadshow_intel_analysis

    msg = MagicMock()
    msg.content = "这不是JSON！"
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]

    with patch("cangjie_fos.engine.coach.llm_judge._evaluation._make_client") as mock_client_fn, \
         patch("cangjie_fos.engine.coach.llm_judge._roadshow.run_with_backoff") as mock_backoff:
        mock_client = MagicMock()
        mock_client_fn.return_value = (mock_client, "deepseek-chat")
        mock_backoff.return_value = resp

        result = run_roadshow_intel_analysis([], model_choice="deepseek")

    # 降级报告：report_type 仍为 roadshow_intel，atmosphere 默认 warm
    assert result.report_type == "roadshow_intel"
    assert "AI 解析失败" in result.atmosphere_summary


# ── PitchGraphService 分支路由测试 ────────────────────────────────────────────

def test_pitch_graph_service_routes_roadshow_to_intel():
    """category=='01_机构路演' 时应调用 run_roadshow_intel_analysis，不调用 LangGraph。"""
    from cangjie_fos.services.pitch_graph_service import PitchGraphService
    from cangjie_fos.engine.schema import RoadshowIntelReport

    fake_report = RoadshowIntelReport(
        meeting_atmosphere="hot",
        atmosphere_summary="积极信号明显。",
    )

    with patch("cangjie_fos.services.pitch_graph_service.run_roadshow_intel_analysis") as mock_intel, \
         patch("cangjie_fos.services.pitch_graph_service.run_pitch_evaluation_via_langgraph_with_state") as mock_lg:
        mock_intel.return_value = fake_report

        report, excerpt = PitchGraphService.run_evaluation_with_state(
            tenant_id="t1",
            words=[],
            model_choice="deepseek",
            explicit_context={"biz_type": "01_机构路演"},
        )

    mock_intel.assert_called_once()
    mock_lg.assert_not_called()
    assert report.report_type == "roadshow_intel"
    assert excerpt == {}


def test_pitch_graph_service_routes_other_to_langgraph():
    """category!='01_机构路演' 时应调用 LangGraph，不调用 roadshow_intel。"""
    from cangjie_fos.services.pitch_graph_service import PitchGraphService
    from cangjie_fos.engine.schema import AnalysisReport, SceneAnalysis

    fake_report = AnalysisReport(
        scene_analysis=SceneAnalysis(scene_type="高管访谈", speaker_roles="高管 vs 投资人"),
        total_score=80,
        risk_points=[],
    )

    with patch("cangjie_fos.services.pitch_graph_service.run_roadshow_intel_analysis") as mock_intel, \
         patch("cangjie_fos.services.pitch_graph_service.run_pitch_evaluation_via_langgraph_with_state") as mock_lg:
        mock_lg.return_value = (fake_report, {"asset_hits": []})

        report, excerpt = PitchGraphService.run_evaluation_with_state(
            tenant_id="t1",
            words=[],
            model_choice="deepseek",
            explicit_context={"biz_type": "02_高管访谈"},
        )

    mock_intel.assert_not_called()
    mock_lg.assert_called_once()
    assert report.total_score == 80


def test_pitch_graph_service_no_category_routes_to_langgraph():
    """explicit_context 为 None 时默认走 LangGraph。"""
    from cangjie_fos.services.pitch_graph_service import PitchGraphService
    from cangjie_fos.engine.schema import AnalysisReport, SceneAnalysis

    fake_report = AnalysisReport(
        scene_analysis=SceneAnalysis(scene_type="未知", speaker_roles="未指定"),
        total_score=70,
        risk_points=[],
    )

    with patch("cangjie_fos.services.pitch_graph_service.run_roadshow_intel_analysis") as mock_intel, \
         patch("cangjie_fos.services.pitch_graph_service.run_pitch_evaluation_via_langgraph_with_state") as mock_lg:
        mock_lg.return_value = (fake_report, {})

        PitchGraphService.run_evaluation_with_state(
            tenant_id="t1",
            words=[],
            explicit_context=None,
        )

    mock_intel.assert_not_called()
    mock_lg.assert_called_once()
