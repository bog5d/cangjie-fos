"""测试群聊情报摄入服务和 API 端点。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import app


# ── 服务层测试 ──────────────────────────────────────────────────────────────

def test_ingest_empty_text_returns_empty():
    from cangjie_fos.services.chat_log_ingestor import ingest_chat_log
    result = ingest_chat_log("   ", tenant_id="t1", persist=False)
    assert result["institution_updates"] == []
    assert result["followup_items"] == []
    assert result["persisted"] is False


def test_ingest_extracts_institution_updates(monkeypatch):
    """LLM 返回机构更新时，结果应正确透传。"""
    from cangjie_fos.services import chat_log_ingestor

    fake_result = {
        "institution_updates": [
            {"name": "红杉资本", "stage": "dd", "thermal": "warm", "note": "底稿已确认"},
        ],
        "followup_items": [],
        "summary": "红杉进入尽调",
    }
    monkeypatch.setattr(chat_log_ingestor, "_llm_extract_from_chat", lambda text: fake_result)

    result = chat_log_ingestor.ingest_chat_log("群聊内容", tenant_id="t1", persist=False)
    assert len(result["institution_updates"]) == 1
    assert result["institution_updates"][0]["name"] == "红杉资本"
    assert result["institution_updates"][0]["stage"] == "dd"
    assert result["summary"] == "红杉进入尽调"
    assert result["persisted"] is False


def test_ingest_extracts_followup_items(monkeypatch):
    """LLM 返回行动项时，结果应正确透传。"""
    from cangjie_fos.services import chat_log_ingestor

    fake_result = {
        "institution_updates": [],
        "followup_items": [
            {"actor": "我方", "action": "催民生法务进度", "priority": "high", "institution": "民生证券"},
            {"actor": "对方", "action": "反馈 TS 意见", "priority": "normal", "institution": "高瓴"},
        ],
        "summary": "两条跟进事项",
    }
    monkeypatch.setattr(chat_log_ingestor, "_llm_extract_from_chat", lambda text: fake_result)

    result = chat_log_ingestor.ingest_chat_log("群聊内容", tenant_id="t1", persist=False)
    assert len(result["followup_items"]) == 2
    assert result["followup_items"][0]["action"] == "催民生法务进度"
    assert result["followup_items"][0]["priority"] == "high"


def test_ingest_persist_writes_followups(monkeypatch):
    """persist=True 时应调用 db_follow_up_insert 写入行动项。"""
    from cangjie_fos.services import chat_log_ingestor, pitch_job_db

    fake_result = {
        "institution_updates": [],
        "followup_items": [
            {"actor": "我方", "action": "发尽调清单", "priority": "high", "institution": "红杉"},
        ],
        "summary": "待发送",
    }
    monkeypatch.setattr(chat_log_ingestor, "_llm_extract_from_chat", lambda text: fake_result)

    inserted = []
    def fake_insert(*, tenant_id, job_id, institution_id, actor, action, priority, source):
        inserted.append({"action": action, "institution_id": institution_id, "source": source})
        return "fake-id"

    monkeypatch.setattr(pitch_job_db, "db_follow_up_insert", fake_insert)

    chat_log_ingestor.ingest_chat_log("群聊", tenant_id="t1", persist=True)
    assert len(inserted) == 1
    assert inserted[0]["action"] == "发尽调清单"
    assert inserted[0]["source"] == "chat_log"


def test_ingest_persist_updates_institution(monkeypatch):
    """persist=True 时，已存在的机构应被更新 AI 摘要。"""
    from cangjie_fos.services import chat_log_ingestor, institution_store
    from cangjie_fos.schemas.institution import InstitutionProfile, PipelineStage, InstitutionThermal

    fake_result = {
        "institution_updates": [
            {"name": "红杉资本", "stage": "dd", "thermal": "hot", "note": "估值谈妥"},
        ],
        "followup_items": [],
        "summary": "进展顺利",
    }
    monkeypatch.setattr(chat_log_ingestor, "_llm_extract_from_chat", lambda text: fake_result)

    fake_inst = InstitutionProfile(
        institution_id="inst-001",
        tenant_id="t1",
        name="红杉资本",
        stage=PipelineStage.PITCHED,
        thermal=InstitutionThermal.WARM,
        ai_summary="",
    )
    monkeypatch.setattr(institution_store, "get_by_name", lambda *, tenant_id, name: fake_inst)

    patched = {}
    def fake_update(inst_id, update):
        patched["inst_id"] = inst_id
        patched["stage"] = update.stage
        patched["ai_summary"] = update.ai_summary

    monkeypatch.setattr(institution_store, "update_institution", fake_update)

    chat_log_ingestor.ingest_chat_log("群聊", tenant_id="t1", persist=True)
    assert patched["inst_id"] == "inst-001"
    assert patched["stage"] == "dd"
    assert "估值谈妥" in patched["ai_summary"]


# ── API 端点测试 ────────────────────────────────────────────────────────────

def test_api_ingest_empty_text_returns_400():
    c = TestClient(app)
    r = c.post("/api/v1/npc/ingest-chat-log", json={"raw_text": "  ", "tenant_id": "t1"})
    assert r.status_code == 400


def test_api_ingest_missing_tenant_returns_422():
    c = TestClient(app)
    r = c.post("/api/v1/npc/ingest-chat-log", json={"raw_text": "有内容"})
    assert r.status_code == 422


def test_api_ingest_returns_correct_shape(monkeypatch):
    """API 正常流：应返回三个 key。"""
    from cangjie_fos.services import chat_log_ingestor

    fake_result = {
        "institution_updates": [{"name": "高瓴", "stage": "term_sheet", "thermal": "hot", "note": "TS 在谈"}],
        "followup_items": [{"actor": "我方", "action": "催签署", "priority": "high", "institution": "高瓴"}],
        "summary": "TS 推进中",
    }
    monkeypatch.setattr(chat_log_ingestor, "_llm_extract_from_chat", lambda text: fake_result)
    # persist=False 避免真实 DB 操作
    c = TestClient(app)
    r = c.post(
        "/api/v1/npc/ingest-chat-log",
        json={"raw_text": "高瓴说 TS 没问题，明天签", "tenant_id": "t1", "persist": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert "institution_updates" in body
    assert "followup_items" in body
    assert "summary" in body
    assert body["institution_updates"][0]["name"] == "高瓴"
