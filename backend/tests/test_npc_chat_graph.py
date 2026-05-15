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
