"""Phase 6：离线 NPC 将战前机构档案拼入上下文。"""
from __future__ import annotations

import pytest

from cangjie_fos.core.checkpointing import reset_checkpointing_for_tests
from cangjie_fos.schemas.institution import InstitutionProfileCreate, PipelineStage
from cangjie_fos.services.institution_store import create_institution
from cangjie_fos.services.npc_chat_graph import invoke_npc_chat, reset_compiled_npc_graph_for_tests


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    root = tmp_path / "fos_backend"
    (root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("cangjie_fos.core.paths.get_backend_root", lambda: root)
    reset_checkpointing_for_tests()
    reset_compiled_npc_graph_for_tests()
    monkeypatch.setattr(
        "cangjie_fos.services.npc_chat_graph.build_tenant_context_block",
        lambda **kwargs: "[ctx]",
    )
    yield
    reset_compiled_npc_graph_for_tests()
    reset_checkpointing_for_tests()


def test_offline_reply_includes_institution_concerns(monkeypatch) -> None:
    create_institution(
        InstitutionProfileCreate(
            tenant_id="npc-p6",
            name="红杉资本",
            stage=PipelineStage.DD,
            concerns="PH6_CONCERN_MARKER",
            preferences="硬科技",
        )
    )
    reset_compiled_npc_graph_for_tests()
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reply, _, _ = invoke_npc_chat(
        tenant_id="npc-p6",
        user_message="明天我要去见红杉资本，有什么要注意？",
        thread_id="th-pre-1",
    )
    assert "PH6_CONCERN_MARKER" in reply
