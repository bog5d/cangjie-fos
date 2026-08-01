"""跨录音口径一致性对比（F1）测试。"""
from __future__ import annotations

import pytest

from cangjie_fos.services import consistency_service as cs


def _job(job_id, interviewee, institution, words):
    return {
        "job_id": job_id, "interviewee": interviewee, "institution_id": institution,
        "status": "completed",
        "words_json": [{"word_index": i, "text": w, "start_time": 0, "end_time": 1, "speaker_id": "0"}
                       for i, w in enumerate(words)],
    }


def test_flags_inconsistency_across_two_sources(monkeypatch):
    jobs = [
        ("j1", _job("j1", "张总", "红杉", ["我们毛利率60%"])),
        ("j2", _job("j2", "李总", "高瓴", ["毛利率大概40%"])),
    ]
    monkeypatch.setattr(
        "cangjie_fos.services.pitch_job_db.db_job_list_for_tenant",
        lambda tenant_id, limit=8: jobs,
    )
    # 每场抽出一个"毛利率"声明
    def fake_extract(transcript):
        if "60%" in transcript:
            return [{"topic": "毛利率", "statement": "毛利率60%"}]
        return [{"topic": "毛利率", "statement": "毛利率40%"}]
    monkeypatch.setattr(cs, "_llm_extract_claims", fake_extract)
    monkeypatch.setattr(cs, "_llm_judge_conflict",
                        lambda topic, stmts: {"conflict": True, "note": "60% vs 40% 对不上"})

    result = cs.run_consistency_check("t1")
    assert len(result["checked_sources"]) == 2
    incons = result["inconsistencies"]
    assert len(incons) == 1
    assert incons[0]["topic"] == "毛利率"
    assert incons[0]["verdict"] == "inconsistent"
    assert len(incons[0]["entries"]) == 2


def test_consistent_topic_not_flagged(monkeypatch):
    jobs = [
        ("j1", _job("j1", "张总", "红杉", ["营收1个亿"])),
        ("j2", _job("j2", "张总", "高瓴", ["营收一个亿"])),
    ]
    monkeypatch.setattr(
        "cangjie_fos.services.pitch_job_db.db_job_list_for_tenant",
        lambda tenant_id, limit=8: jobs,
    )
    monkeypatch.setattr(cs, "_llm_extract_claims",
                        lambda t: [{"topic": "营收", "statement": "营收约1亿"}])
    monkeypatch.setattr(cs, "_llm_judge_conflict",
                        lambda topic, stmts: {"conflict": False, "note": ""})
    result = cs.run_consistency_check("t1")
    assert result["inconsistencies"] == []


def test_single_source_topic_not_compared(monkeypatch):
    """只有一场提到的指标不参与对比。"""
    jobs = [("j1", _job("j1", "张总", "红杉", ["估值3亿"]))]
    monkeypatch.setattr(
        "cangjie_fos.services.pitch_job_db.db_job_list_for_tenant",
        lambda tenant_id, limit=8: jobs,
    )
    monkeypatch.setattr(cs, "_llm_extract_claims",
                        lambda t: [{"topic": "估值", "statement": "估值3亿"}])
    called = []
    monkeypatch.setattr(cs, "_llm_judge_conflict",
                        lambda topic, stmts: called.append(1) or {"conflict": True})
    result = cs.run_consistency_check("t1")
    assert result["inconsistencies"] == []
    assert called == []  # 单来源不触发判定


def test_no_recordings(monkeypatch):
    monkeypatch.setattr(
        "cangjie_fos.services.pitch_job_db.db_job_list_for_tenant",
        lambda tenant_id, limit=8: [],
    )
    result = cs.run_consistency_check("t1")
    assert result["checked_sources"] == []
    assert "没有可对比" in result["note"]


def test_judge_failure_degrades_to_review(monkeypatch):
    jobs = [
        ("j1", _job("j1", "张总", "红杉", ["客户500家"])),
        ("j2", _job("j2", "李总", "高瓴", ["客户300家"])),
    ]
    monkeypatch.setattr(
        "cangjie_fos.services.pitch_job_db.db_job_list_for_tenant",
        lambda tenant_id, limit=8: jobs,
    )
    monkeypatch.setattr(cs, "_llm_extract_claims",
                        lambda t: [{"topic": "客户数", "statement": "客户很多"}])

    def _boom(topic, stmts):
        raise RuntimeError("LLM down")
    monkeypatch.setattr(cs, "_llm_judge_conflict", _boom)
    result = cs.run_consistency_check("t1")
    # 判定不可用 → 仍以"待核对"抛出，不静默吞掉
    assert len(result["inconsistencies"]) == 1
    assert result["inconsistencies"][0]["verdict"] == "review"
