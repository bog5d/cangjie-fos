"""BP vs 访谈 口径比对（Part B，吴素最有价值项）测试。"""
from __future__ import annotations

from types import SimpleNamespace

from cangjie_fos.services import consistency_service as cs


def _job(job_id, who, inst, words):
    return {
        "job_id": job_id, "interviewee": who, "institution_id": inst, "status": "completed",
        "words_json": [{"word_index": i, "text": w, "start_time": 0, "end_time": 1, "speaker_id": "0"}
                       for i, w in enumerate(words)],
    }


def test_bp_hard_conflict_detected(monkeypatch):
    """BP 写 800 万、访谈说 8 万 → conflict 硬矛盾。"""
    jobs = [("j1", _job("j1", "波总", "泽天智航", ["创业启动资金8万元"]))]
    monkeypatch.setattr(
        "cangjie_fos.services.pitch_job_db.db_job_list_for_tenant",
        lambda tenant_id, limit=8: jobs,
    )

    def fake_extract(text):
        if "800万" in text:  # BP
            return [{"topic": "创业启动资金", "statement": "启动资金800万元"}]
        return [{"topic": "创业启动资金", "statement": "启动资金8万元"}]
    monkeypatch.setattr(cs, "_llm_extract_claims", fake_extract)
    monkeypatch.setattr(cs, "_llm_judge_bp_vs_interview",
                        lambda t, bp, ivs: {"level": "conflict", "note": "800万 vs 8万，差100倍"})

    r = cs.run_bp_consistency_check("t1", "BP：创业启动资金800万元")
    assert r["bp_topics"] == 1
    assert len(r["hard_conflicts"]) == 1
    assert r["hard_conflicts"][0]["topic"] == "创业启动资金"
    assert r["counts"]["conflict"] == 1


def test_bp_consistent_not_flagged(monkeypatch):
    jobs = [("j1", _job("j1", "波总", "泽天", ["营收一个亿"]))]
    monkeypatch.setattr(
        "cangjie_fos.services.pitch_job_db.db_job_list_for_tenant",
        lambda tenant_id, limit=8: jobs,
    )
    monkeypatch.setattr(cs, "_llm_extract_claims",
                        lambda t: [{"topic": "营收", "statement": "营收约1亿"}])
    monkeypatch.setattr(cs, "_llm_judge_bp_vs_interview",
                        lambda t, bp, ivs: {"level": "consistent", "note": ""})
    r = cs.run_bp_consistency_check("t1", "BP：营收1亿")
    assert r["hard_conflicts"] == []
    assert r["counts"]["consistent"] == 1


def test_bp_topic_not_in_interviews_skipped(monkeypatch):
    """BP 提了但访谈没提的口径不参与比对。"""
    jobs = [("j1", _job("j1", "波总", "泽天", ["随便聊聊"]))]
    monkeypatch.setattr(
        "cangjie_fos.services.pitch_job_db.db_job_list_for_tenant",
        lambda tenant_id, limit=8: jobs,
    )
    monkeypatch.setattr(cs, "_llm_extract_claims",
                        lambda t: [{"topic": "估值", "statement": "估值3亿"}] if "BP" in t else [])
    called = []
    monkeypatch.setattr(cs, "_llm_judge_bp_vs_interview",
                        lambda t, bp, ivs: called.append(1) or {"level": "conflict"})
    r = cs.run_bp_consistency_check("t1", "BP：估值3亿")
    assert r["comparisons"] == []
    assert called == []


def test_bp_empty_text():
    r = cs.run_bp_consistency_check("t1", "")
    assert r["bp_topics"] == 0


def test_bp_check_api(monkeypatch):
    from fastapi.testclient import TestClient
    from cangjie_fos.main import create_app

    monkeypatch.setattr(
        "cangjie_fos.api.routes.consistency.run_bp_consistency_check",
        lambda tenant_id, bp_text, limit=8: {"bp_topics": 2, "hard_conflicts": [{"topic": "资金"}],
                                             "comparisons": [], "counts": {}, "checked_interviews": [],
                                             "note": "ok"},
    )
    with TestClient(create_app()) as c:
        r = c.post("/api/v1/consistency/bp-check",
                   json={"tenant_id": "t1", "bp_text": "BP正文..."})
        assert r.status_code == 200
        assert r.json()["bp_topics"] == 2
