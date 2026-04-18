"""Phase 4：Checkpointer 线程恢复、真实大盘扫描、反思结算。"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from starlette.testclient import TestClient

from cangjie_fos.core.checkpointing import reset_checkpointing_for_tests
from cangjie_fos.main import app
from cangjie_fos.services.evolution_store import EvolutionJsonStore
from cangjie_fos.services.npc_chat_graph import export_thread_messages, reset_compiled_npc_graph_for_tests


@pytest.fixture(autouse=True)
def _phase4_paths(monkeypatch, tmp_path):
    root = tmp_path / "fos_backend"
    (root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("cangjie_fos.core.paths.get_backend_root", lambda: root)
    reset_checkpointing_for_tests()
    reset_compiled_npc_graph_for_tests()
    yield
    reset_compiled_npc_graph_for_tests()
    reset_checkpointing_for_tests()


def test_langgraph_thread_checkpoint_restores_history() -> None:
    """同一 thread_id 两次 invoke 后，导出消息应包含多轮 user/assistant。"""
    with patch(
        "cangjie_fos.services.npc_chat_graph._call_llm",
        side_effect=[
            {"messages": [AIMessage(content="R1")]},
            {"messages": [AIMessage(content="R2")]},
        ],
    ):
        reset_compiled_npc_graph_for_tests()
        from cangjie_fos.services.npc_chat_graph import invoke_npc_chat

        tid = "thread-phase4-ut"
        invoke_npc_chat(tenant_id="t-ut", user_message="m1", thread_id=tid)
        invoke_npc_chat(tenant_id="t-ut", user_message="m2", thread_id=tid)
    msgs = export_thread_messages(thread_id=tid)
    roles = [x["role"] for x in msgs]
    assert roles.count("user") >= 2
    assert roles.count("assistant") >= 2


def test_dashboard_reads_asset_index(tmp_path, monkeypatch) -> None:
    fos = tmp_path / ".fos_data"
    fos.mkdir(parents=True, exist_ok=True)
    (fos / "asset_index.json").write_text(
        json.dumps({"assets": [{"filename": "a.pdf", "relative_path": "x", "summary": "s"}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CANGJIE_FSS_DATA_DIR", str(fos))
    room = tmp_path / "room" / "tenant-x"
    room.mkdir(parents=True)
    (room / "f.txt").write_text("x", encoding="utf-8")
    monkeypatch.setenv("CANGJIE_DATA_ROOM_ROOT", str(tmp_path / "room"))
    c = TestClient(app)
    r = c.get("/api/dashboard/status", params={"tenant_id": "tenant-x"})
    assert r.status_code == 200
    assert r.json()["docs_health_pct"] > 0
    assert r.json()["data_room_completeness_pct"] > 0


def test_nightly_settle_marks_pending(tmp_path, monkeypatch) -> None:
    root = tmp_path / "fos_backend"
    (root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("cangjie_fos.core.paths.get_backend_root", lambda: root)
    reset_checkpointing_for_tests()
    reset_compiled_npc_graph_for_tests()
    store = EvolutionJsonStore(base=root / "data" / "evolution")
    from cangjie_fos.schemas.evolution import TextDiffFeedbackRequest

    store.persist_text_diff(
        TextDiffFeedbackRequest(
            tenant_id="z1",
            ai_text="old",
            user_text="new",
            trace_id="t1",
        )
    )
    c = TestClient(app)
    r = c.post("/api/v1/reflection/nightly-settle", json={"tenant_id": "z1"})
    assert r.status_code == 200
    assert r.json().get("processed", 0) >= 1
    gl = root / "data" / "evolution" / "evolution_guidelines.jsonl"
    assert gl.is_file()


def test_pitch_threads_list_and_messages_http() -> None:
    with patch(
        "cangjie_fos.api.routes.pitch.invoke_npc_chat",
        return_value=("ok", "tr1", "th-http-1"),
    ):
        c = TestClient(app)
        r = c.post(
            "/api/pitch/chat",
            json={"tenant_id": "http-tenant", "message": "ping", "thread_id": "th-http-1"},
        )
    assert r.status_code == 200
    lst = c.get("/api/pitch/threads", params={"tenant_id": "http-tenant"})
    assert lst.status_code == 200
    ids = [x["thread_id"] for x in lst.json()]
    assert "th-http-1" in ids
