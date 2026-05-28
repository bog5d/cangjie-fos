"""测试定时反向访谈服务。"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import app


# ── 停滞机构检测 ────────────────────────────────────────────────────────────────

def test_find_stale_returns_old_institutions(monkeypatch):
    """超过3天未更新的机构应被识别为停滞。"""
    from cangjie_fos.services import proactive_interviewer, institution_store
    from cangjie_fos.schemas.institution import InstitutionProfile, PipelineStage, InstitutionThermal

    old_ts = time.time() - 5 * 86400  # 5天前
    recent_ts = time.time() - 1 * 86400  # 1天前

    old_inst = InstitutionProfile(
        institution_id="old-00001", tenant_id="t1", name="停滞机构",
        stage=PipelineStage.DD, thermal=InstitutionThermal.WARM, updated_at=old_ts,
    )
    recent_inst = InstitutionProfile(
        institution_id="new-00002", tenant_id="t1", name="活跃机构",
        stage=PipelineStage.DD, thermal=InstitutionThermal.HOT, updated_at=recent_ts,
    )

    monkeypatch.setattr(
        institution_store, "list_institutions",
        lambda *, tenant_id, limit: [old_inst, recent_inst],
    )

    stale = proactive_interviewer._find_stale_institutions("t1")
    assert len(stale) == 1
    assert stale[0]["name"] == "停滞机构"
    assert stale[0]["days_stale"] >= 4.9


def test_find_stale_returns_empty_when_all_fresh(monkeypatch):
    """所有机构都是最近更新时，停滞列表应为空。"""
    from cangjie_fos.services import proactive_interviewer, institution_store
    from cangjie_fos.schemas.institution import InstitutionProfile, PipelineStage, InstitutionThermal

    recent_ts = time.time() - 1 * 86400
    inst = InstitutionProfile(
        institution_id="new-00001", tenant_id="t1", name="活跃",
        stage=PipelineStage.PITCHED, thermal=InstitutionThermal.HOT, updated_at=recent_ts,
    )
    monkeypatch.setattr(
        institution_store, "list_institutions", lambda *, tenant_id, limit: [inst],
    )

    stale = proactive_interviewer._find_stale_institutions("t1")
    assert stale == []


# ── 追问生成 ────────────────────────────────────────────────────────────────────

def test_generate_questions_dd_stage():
    from cangjie_fos.services.proactive_interviewer import _generate_questions
    stale = [{"name": "红杉", "stage": "dd", "thermal": "warm", "ai_summary": "", "days_stale": 5}]
    qs = _generate_questions(stale)
    assert len(qs) == 1
    assert "红杉" in qs[0]
    assert "尽调" in qs[0]


def test_generate_questions_term_sheet_stage():
    from cangjie_fos.services.proactive_interviewer import _generate_questions
    stale = [{"name": "高瓴", "stage": "term_sheet", "thermal": "hot", "ai_summary": "", "days_stale": 7}]
    qs = _generate_questions(stale)
    assert "TS" in qs[0] or "Term Sheet" in qs[0]


def test_generate_questions_long_stale():
    from cangjie_fos.services.proactive_interviewer import _generate_questions
    stale = [{"name": "IDG", "stage": "pitched", "thermal": "cold", "ai_summary": "", "days_stale": 40}]
    qs = _generate_questions(stale)
    assert "停滞预警" in qs[0]


# ── push_line ────────────────────────────────────────────────────────────────────

def test_push_line_appends_to_queue():
    from cangjie_fos.services.npc_queue import push_line, _LINES
    before_count = len(_LINES)
    line = push_line(role="豆豆", text="测试追问", proactive=True)
    assert len(_LINES) == before_count + 1
    assert line.text == "测试追问"
    assert line.proactive is True


# ── 全流程 ────────────────────────────────────────────────────────────────────────

def test_run_proactive_interview_generates_questions(monkeypatch):
    """有停滞机构时应生成追问并写入队列。"""
    from cangjie_fos.services import proactive_interviewer, institution_store, npc_queue
    from cangjie_fos.schemas.institution import InstitutionProfile, PipelineStage, InstitutionThermal

    old_ts = time.time() - 10 * 86400
    inst = InstitutionProfile(
        institution_id="stale-0001", tenant_id="t1", name="民生证券",
        stage=PipelineStage.DD, thermal=InstitutionThermal.WARM, updated_at=old_ts,
    )
    monkeypatch.setattr(
        institution_store, "list_institutions", lambda *, tenant_id, limit: [inst],
    )

    before_count = len(npc_queue._LINES)
    result = proactive_interviewer.run_proactive_interview("t1")

    assert result["questions_generated"] >= 1
    assert "民生证券" in result["stale_institutions"]
    assert len(npc_queue._LINES) > before_count  # 追问已写入队列


def test_run_proactive_interview_no_stale_skips(monkeypatch):
    """无停滞机构时应静默跳过，不写入任何消息。"""
    from cangjie_fos.services import proactive_interviewer, institution_store, npc_queue
    from cangjie_fos.schemas.institution import InstitutionProfile, PipelineStage, InstitutionThermal

    recent_ts = time.time() - 0.5 * 86400
    inst = InstitutionProfile(
        institution_id="fresh-001x", tenant_id="t1", name="活跃机构",
        stage=PipelineStage.DD, thermal=InstitutionThermal.HOT, updated_at=recent_ts,
    )
    monkeypatch.setattr(
        institution_store, "list_institutions", lambda *, tenant_id, limit: [inst],
    )

    before_count = len(npc_queue._LINES)
    result = proactive_interviewer.run_proactive_interview("t1")

    assert result["questions_generated"] == 0
    assert len(npc_queue._LINES) == before_count


# ── API 端点测试 ────────────────────────────────────────────────────────────────

def test_api_proactive_interview_endpoint(monkeypatch):
    """POST /api/v1/npc/proactive-interview 应返回正确结构。"""
    from cangjie_fos.services import proactive_interviewer

    monkeypatch.setattr(
        proactive_interviewer,
        "run_proactive_interview",
        lambda tenant_id: {"questions_generated": 2, "stale_institutions": ["A", "B"]},
    )

    c = TestClient(app)
    r = c.post("/api/v1/npc/proactive-interview", json={"tenant_id": "t1"})
    assert r.status_code == 200
    body = r.json()
    assert body["questions_generated"] == 2
    assert "A" in body["stale_institutions"]
