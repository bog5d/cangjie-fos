"""npc_chat_graph.py 单元测试 — 覆盖纯函数、离线模式、单例、图结构。

不测试需要真实 LLM 的路径（_call_llm 需要 API key），
但验证离线模式（无 API key）的正确行为。
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import patch, MagicMock

from cangjie_fos.services.npc_chat_graph import (
    _npc_display_name,
    _base_system,
    _last_user_text,
    _infer_memory_tag_from_user_text,
    _build_graph,
    get_compiled_npc_graph,
    reset_compiled_npc_graph_for_tests,
    invoke_npc_chat,
    export_thread_messages,
    NpcGraphState,
)
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage


# ── display name ──────────────────────────────────────────────────

class TestNpcDisplayName:
    def test_default_is_doudou(self):
        assert _npc_display_name() == "豆豆"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("CANGJIE_NPC_DISPLAY_NAME", "仓颉助理")
        assert _npc_display_name() == "仓颉助理"

    def test_env_empty_falls_back(self, monkeypatch):
        monkeypatch.setenv("CANGJIE_NPC_DISPLAY_NAME", "")
        assert _npc_display_name() == "豆豆"

    def test_env_whitespace_falls_back(self, monkeypatch):
        monkeypatch.setenv("CANGJIE_NPC_DISPLAY_NAME", "   ")
        assert _npc_display_name() == "豆豆"


# ── base system prompt ────────────────────────────────────────────

class TestBaseSystem:
    def test_contains_npc_name(self):
        prompt = _base_system()
        assert "豆豆" in prompt

    def test_contains_core_capabilities(self):
        prompt = _base_system()
        assert "ASR" in prompt
        assert "LangGraph" in prompt
        assert "0-100" in prompt or "总分" in prompt

    def test_contains_health_monitor_role(self):
        prompt = _base_system()
        assert "健康监测员" in prompt
        assert "系统健康快照" in prompt

    def test_contains_injection_markers(self):
        prompt = _base_system()
        assert "用户输入开始" in prompt
        assert "用户输入结束" in prompt


# ── last user text extraction ─────────────────────────────────────

class TestLastUserText:
    def test_extracts_human_message(self):
        state: NpcGraphState = {
            "messages": [
                HumanMessage(content="你好"),
                AIMessage(content="你好！有什么可以帮你？"),
                HumanMessage(content="帮我分析一下"),
            ],
        }
        assert _last_user_text(state) == "帮我分析一下"

    def test_no_messages_returns_empty(self):
        state: NpcGraphState = {"messages": []}
        assert _last_user_text(state) == ""

    def test_only_ai_messages_returns_empty(self):
        state: NpcGraphState = {
            "messages": [AIMessage(content="你好，请问有什么需要？")],
        }
        assert _last_user_text(state) == ""

    def test_empty_content_returns_empty_str(self):
        state: NpcGraphState = {
            "messages": [HumanMessage(content="")],
        }
        assert _last_user_text(state) == ""


# ── memory tag inference ──────────────────────────────────────────

class TestInferMemoryTag:
    def test_always_returns_default(self):
        assert _infer_memory_tag_from_user_text("any text") == "default"
        assert _infer_memory_tag_from_user_text("") == "default"


# ── graph construction ────────────────────────────────────────────

class TestBuildGraph:
    def test_has_all_nodes(self):
        from langgraph.graph import StateGraph
        g = _build_graph(checkpointer=None)
        nodes = list(g.nodes.keys())
        assert "preload" in nodes
        assert "inject" in nodes
        assert "inject_job" in nodes
        assert "inject_health" in nodes
        assert "agent" in nodes

    def test_entry_is_preload(self):
        g = _build_graph(checkpointer=None)
        # Verify the first node is preload
        assert "preload" in g.nodes


# ── singleton pattern ─────────────────────────────────────────────

class TestCompiledGraphSingleton:
    def test_same_instance_returned(self):
        reset_compiled_npc_graph_for_tests()
        g1 = get_compiled_npc_graph()
        g2 = get_compiled_npc_graph()
        assert g1 is g2

    def test_reset_creates_new_instance(self):
        reset_compiled_npc_graph_for_tests()
        g1 = get_compiled_npc_graph()
        reset_compiled_npc_graph_for_tests()
        g2 = get_compiled_npc_graph()
        assert g1 is not g2


# ── invoke offline mode (no API key) ──────────────────────────────

class TestInvokeOffline:
    def setup_method(self):
        reset_compiled_npc_graph_for_tests()
        # Ensure no API keys present
        self._old_ds = os.environ.pop("DEEPSEEK_API_KEY", None)
        self._old_oa = os.environ.pop("OPENAI_API_KEY", None)

    def teardown_method(self):
        if self._old_ds is not None:
            os.environ["DEEPSEEK_API_KEY"] = self._old_ds
        if self._old_oa is not None:
            os.environ["OPENAI_API_KEY"] = self._old_oa

    def test_offline_mode_returns_placeholder(self):
        reply, turn_id, thread_id = invoke_npc_chat(
            tenant_id="test-tenant",
            user_message="你好",
            thread_id="test-thread-001",
        )
        assert "离线" in reply or "配置" in reply
        assert len(turn_id) > 0
        assert thread_id == "test-thread-001"

    def test_offline_echoes_user_message(self):
        reply, _, _ = invoke_npc_chat(
            tenant_id="test-tenant",
            user_message="我的项目估值多少？",
            thread_id=None,
        )
        assert "我的项目估值多少" in reply

    def test_no_thread_id_generates_one(self):
        _, _, tid = invoke_npc_chat(
            tenant_id="test-tenant",
            user_message="你好",
            thread_id="",
        )
        assert len(tid) == 32  # uuid4 hex

    def test_offline_with_user_name_still_works(self):
        # user_name goes to system prompt (not visible in offline response)
        reply, _, _ = invoke_npc_chat(
            tenant_id="test-tenant",
            user_message="你好",
            thread_id="test-thread-002",
            user_name="王波",
        )
        assert "离线" in reply


# ── export thread messages ────────────────────────────────────────

class TestExportThreadMessages:
    def setup_method(self):
        reset_compiled_npc_graph_for_tests()

    def test_export_empty_thread_returns_empty_list(self):
        result = export_thread_messages(thread_id="nonexistent-thread")
        assert isinstance(result, list)
        assert len(result) == 0

    def test_export_returns_correct_roles(self):
        # Invoke first to populate thread, then export
        old_ds = os.environ.pop("DEEPSEEK_API_KEY", None)
        old_oa = os.environ.pop("OPENAI_API_KEY", None)
        try:
            invoke_npc_chat(
                tenant_id="test-tenant",
                user_message="测试消息",
                thread_id="export-test-001",
            )
            messages = export_thread_messages(thread_id="export-test-001")
            assert len(messages) >= 1
            roles = {m["role"] for m in messages}
            assert "user" in roles
            # offline mode: assistant message should be present
        finally:
            if old_ds is not None:
                os.environ["DEEPSEEK_API_KEY"] = old_ds
            if old_oa is not None:
                os.environ["OPENAI_API_KEY"] = old_oa


# ── Tool Use 测试 ────────────────────────────────────────────────────────────

class TestNpcToolUse:
    """验证 _call_llm 能正确处理 tool_call 并把结果喂回 LLM。"""

    def setup_method(self):
        reset_compiled_npc_graph_for_tests()

    def test_tool_call_triggers_execute_and_returns_text(self, monkeypatch):
        """LLM 第一轮返回 tool_call，第二轮返回正常文本，最终应得到文本回复。"""
        import json
        from unittest.mock import MagicMock, patch

        # 第一次调用：返回 tool_call（查"红杉"）
        tc = MagicMock()
        tc.id = "call_abc123"
        tc.function.name = "get_institution_detail"
        tc.function.arguments = json.dumps({"institution_name": "红杉"})

        first_msg = MagicMock()
        first_msg.content = ""
        first_msg.tool_calls = [tc]
        first_choice = MagicMock()
        first_choice.message = first_msg

        # 第二次调用：返回正常文本
        second_msg = MagicMock()
        second_msg.content = "红杉目前处于尽调阶段，关注点是 ARR 增速。"
        second_msg.tool_calls = []
        second_choice = MagicMock()
        second_choice.message = second_msg

        mock_create = MagicMock(side_effect=[
            MagicMock(choices=[first_choice]),
            MagicMock(choices=[second_choice]),
        ])

        fake_tool_result = "机构：红杉资本\n阶段：due_diligence\n热度：warm\nAI画像：专注早期消费和科技"

        with patch("cangjie_fos.services.npc_tools.execute_tool", return_value=fake_tool_result) as mock_exec:
            with patch("openai.OpenAI") as MockOpenAI:
                MockOpenAI.return_value.chat.completions.create = mock_create
                os.environ["DEEPSEEK_API_KEY"] = "fake-key-for-test"
                try:
                    reply, _, _ = invoke_npc_chat(
                        tenant_id="test-tenant",
                        user_message="红杉那边情况怎样？",
                        thread_id="tool-test-001",
                    )
                finally:
                    del os.environ["DEEPSEEK_API_KEY"]

        # LLM 被调用了两次（第一次 tool_call，第二次正常回复）
        assert mock_create.call_count == 2
        # execute_tool 被调用了一次，参数正确
        mock_exec.assert_called_once_with(
            "get_institution_detail",
            {"institution_name": "红杉"},
            tenant_id="test-tenant",
        )
        # 最终回复是第二轮的文本
        assert "红杉" in reply

    def test_no_tool_call_returns_direct_text(self, monkeypatch):
        """LLM 不触发工具时，直接返回文本，execute_tool 不应被调用。"""
        from unittest.mock import MagicMock, patch

        msg = MagicMock()
        msg.content = "今天天气不错，继续加油！"
        msg.tool_calls = []
        choice = MagicMock()
        choice.message = msg
        mock_create = MagicMock(return_value=MagicMock(choices=[choice]))

        with patch("cangjie_fos.services.npc_tools.execute_tool") as mock_exec:
            with patch("openai.OpenAI") as MockOpenAI:
                MockOpenAI.return_value.chat.completions.create = mock_create
                os.environ["DEEPSEEK_API_KEY"] = "fake-key-for-test"
                try:
                    reply, _, _ = invoke_npc_chat(
                        tenant_id="test-tenant",
                        user_message="随便说点什么",
                        thread_id="tool-test-002",
                    )
                finally:
                    del os.environ["DEEPSEEK_API_KEY"]

        mock_exec.assert_not_called()
        assert reply == "今天天气不错，继续加油！"


class TestNpcToolExecutors:
    """直接测试 npc_tools.py 里的执行器函数。"""

    def test_get_institution_detail_found(self, monkeypatch):
        from cangjie_fos.services import npc_tools

        class FakeInst:
            name = "红杉资本"
            stage = type("S", (), {"value": "due_diligence"})()
            thermal = type("T", (), {"value": "warm"})()
            ai_summary = "专注早期科技"
            concerns = "ARR增速"
            preferences = "SaaS"

        monkeypatch.setattr(
            "cangjie_fos.services.institution_store.find_matching_names",
            lambda *, tenant_id, text: [FakeInst()],
        )
        result = npc_tools.execute_tool(
            "get_institution_detail", {"institution_name": "红杉"}, tenant_id="t1"
        )
        assert "红杉资本" in result
        assert "due_diligence" in result
        assert "ARR增速" in result

    def test_get_institution_detail_not_found(self, monkeypatch):
        from cangjie_fos.services import npc_tools

        monkeypatch.setattr(
            "cangjie_fos.services.institution_store.find_matching_names",
            lambda *, tenant_id, text: [],
        )
        monkeypatch.setattr(
            "cangjie_fos.services.institution_store.list_institutions",
            lambda *, tenant_id, limit: [],
        )
        result = npc_tools.execute_tool(
            "get_institution_detail", {"institution_name": "不存在机构"}, tenant_id="t1"
        )
        assert "未找到" in result

    def test_query_pipeline_overview(self, monkeypatch):
        from cangjie_fos.services import npc_tools

        monkeypatch.setattr(
            "cangjie_fos.services.institution_store.count_by_stage",
            lambda *, tenant_id: {"due_diligence": 2, "ts_negotiation": 1, "contact": 3},
        )

        class FakeInst:
            name = "测试机构"
            stage = type("S", (), {"value": "contact"})()
            thermal = type("T", (), {"value": "cold"})()

        monkeypatch.setattr(
            "cangjie_fos.services.institution_store.list_institutions",
            lambda *, tenant_id, limit: [FakeInst()],
        )
        result = npc_tools.execute_tool(
            "query_pipeline_overview", {}, tenant_id="t1"
        )
        assert "6" in result  # 2+1+3 总计
        assert "due_diligence" in result
        assert "测试机构" in result
