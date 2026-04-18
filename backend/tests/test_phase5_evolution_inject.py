"""Phase 5：evolution_guidelines 注入离线 NPC 回复。"""
from __future__ import annotations

import json

import pytest

from cangjie_fos.core.checkpointing import reset_checkpointing_for_tests
from cangjie_fos.services.evolution_guidelines_loader import load_recent_guidelines_for_prompt
from cangjie_fos.services.npc_chat_graph import invoke_npc_chat, reset_compiled_npc_graph_for_tests


@pytest.fixture(autouse=True)
def _ckpt(monkeypatch, tmp_path):
    root = tmp_path / "fos_backend"
    (root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("cangjie_fos.core.paths.get_backend_root", lambda: root)
    reset_checkpointing_for_tests()
    reset_compiled_npc_graph_for_tests()
    yield
    reset_compiled_npc_graph_for_tests()
    reset_checkpointing_for_tests()


def test_guidelines_loader_filters_tenant(tmp_path, monkeypatch) -> None:
    root = tmp_path / "fos_backend"
    (root / "data" / "evolution").mkdir(parents=True, exist_ok=True)
    fp = root / "data" / "evolution" / "evolution_guidelines.jsonl"
    fp.write_text(
        json.dumps({"tenant_scope": "other", "text": "skip"}) + "\n"
        + json.dumps({"tenant_scope": "mine", "text": "KEEP_LINE"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("cangjie_fos.core.paths.get_backend_root", lambda: root)
    blob = load_recent_guidelines_for_prompt(tenant_id="mine")
    assert "KEEP_LINE" in blob
    assert "skip" not in blob


def test_offline_npc_reply_contains_guideline_phrase(monkeypatch, tmp_path) -> None:
    root = tmp_path / "fos_backend"
    (root / "data" / "evolution").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("cangjie_fos.core.paths.get_backend_root", lambda: root)
    monkeypatch.setattr(
        "cangjie_fos.services.npc_chat_graph.build_tenant_context_block",
        lambda **kwargs: "[stub-tenant-ctx]",
    )
    (root / "data" / "evolution" / "evolution_guidelines.jsonl").write_text(
        json.dumps({"tenant_scope": "t-ev", "text": "PH5_EVOLUTION_UNIQUE_MARKER"}) + "\n",
        encoding="utf-8",
    )
    reset_compiled_npc_graph_for_tests()
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reply, _, _ = invoke_npc_chat(tenant_id="t-ev", user_message="你好", thread_id="th-ev-1")
    assert "PH5_EVOLUTION_UNIQUE_MARKER" in reply
