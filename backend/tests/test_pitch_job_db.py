"""TDD tests for pitch_job_db.py — SQLite persistence layer (Phase 6.4 Task 1).

All tests use tmp_path so they never touch data/pitch_jobs.sqlite.
"""
from __future__ import annotations

import time

import pytest

import cangjie_fos.services.pitch_job_db as _module
from cangjie_fos.services.pitch_job_db import (
    db_job_create,
    db_job_get,
    db_job_list_for_tenant,
    db_job_update,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path):
    """Redirect DB path to a fresh tmp_path for every test."""
    db_file = tmp_path / "pitch_jobs.sqlite"

    monkeypatch.setattr(_module, "_db_path", lambda: str(db_file))
    yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_and_get_round_trip():
    """Create a job and retrieve it; all base fields must be present."""
    db_job_create("job-001", "tenant-A")
    row = db_job_get("job-001")

    assert row is not None
    assert row["job_id"] == "job-001"
    assert row["tenant_id"] == "tenant-A"
    assert row["status"] == "pending"
    assert isinstance(row["created_at"], float)
    assert row["created_at"] > 0


def test_get_returns_none_for_unknown_job():
    """db_job_get must return None for a job_id that was never created."""
    result = db_job_get("does-not-exist")
    assert result is None


def test_update_status():
    """db_job_update should change the status field."""
    db_job_create("job-002", "tenant-A")
    db_job_update("job-002", status="transcribing")
    row = db_job_get("job-002")

    assert row is not None
    assert row["status"] == "transcribing"


def test_update_original_report_dict_serialized_back_to_dict():
    """Passing a dict for original_report stores JSON and returns a dict."""
    report = {"score": 88, "feedback": "Good structure"}
    db_job_create("job-003", "tenant-A")
    db_job_update("job-003", original_report=report)
    row = db_job_get("job-003")

    assert row is not None
    assert isinstance(row["original_report"], dict)
    assert row["original_report"]["score"] == 88
    assert row["original_report"]["feedback"] == "Good structure"


def test_update_edited_report_does_not_affect_original_report():
    """Updating edited_report leaves original_report unchanged."""
    original = {"score": 75, "feedback": "Needs improvement"}
    edited = {"score": 80, "feedback": "Better after edit"}

    db_job_create("job-004", "tenant-A")
    db_job_update("job-004", original_report=original)
    db_job_update("job-004", edited_report=edited)
    row = db_job_get("job-004")

    assert row is not None
    assert row["original_report"]["score"] == 75
    assert row["edited_report"]["score"] == 80


def test_report_alias_only_original_set():
    """When only original_report is set, report == original_report."""
    original = {"score": 70}
    db_job_create("job-005", "tenant-A")
    db_job_update("job-005", original_report=original)
    row = db_job_get("job-005")

    assert row is not None
    assert row["edited_report"] is None
    assert row["report"] == row["original_report"]
    assert row["report"]["score"] == 70


def test_report_alias_with_edited_report_set():
    """When edited_report is set, report == edited_report (not original)."""
    original = {"score": 65}
    edited = {"score": 90}

    db_job_create("job-006", "tenant-A")
    db_job_update("job-006", original_report=original, edited_report=edited)
    row = db_job_get("job-006")

    assert row is not None
    assert row["report"] == row["edited_report"]
    assert row["report"]["score"] == 90


def test_list_for_tenant_ordering_newest_first():
    """db_job_list_for_tenant must return jobs sorted by created_at DESC."""
    db_job_create("job-old", "tenant-B")
    time.sleep(0.01)  # ensure distinct timestamps
    db_job_create("job-new", "tenant-B")

    results = db_job_list_for_tenant("tenant-B")
    assert len(results) == 2
    job_ids = [jid for jid, _ in results]
    assert job_ids[0] == "job-new"
    assert job_ids[1] == "job-old"


def test_list_for_tenant_isolates_tenants():
    """Jobs from other tenants must not appear in the list."""
    db_job_create("job-t1", "tenant-1")
    db_job_create("job-t2", "tenant-2")

    results = db_job_list_for_tenant("tenant-1")
    assert len(results) == 1
    assert results[0][0] == "job-t1"


def test_words_json_round_trip():
    """words_json stored as list → JSON → returns as list."""
    words = [{"word": "hello", "start": 0.0, "end": 0.5}, {"word": "world", "start": 0.6, "end": 1.0}]
    db_job_create("job-007", "tenant-A")
    db_job_update("job-007", words_json=words)
    row = db_job_get("job-007")

    assert row is not None
    assert isinstance(row["words_json"], list)
    assert len(row["words_json"]) == 2
    assert row["words_json"][0]["word"] == "hello"


def test_audio_path_storage():
    """audio_path should be stored and retrieved as a plain string."""
    db_job_create("job-008", "tenant-A")
    db_job_update("job-008", audio_path="/tmp/uploads/audio_abc.wav")
    row = db_job_get("job-008")

    assert row is not None
    assert row["audio_path"] == "/tmp/uploads/audio_abc.wav"


def test_create_with_extra_kwargs():
    """db_job_create accepts status, exp_delta, exp_reason via **extra."""
    db_job_create("job-009", "tenant-A", status="evaluating", exp_delta=10, exp_reason="bonus")
    row = db_job_get("job-009")

    assert row is not None
    assert row["status"] == "evaluating"
    assert row["exp_delta"] == 10
    assert row["exp_reason"] == "bonus"


def test_list_for_tenant_returns_dicts():
    """Each item returned by list_for_tenant is a (str, dict) tuple."""
    db_job_create("job-010", "tenant-C")
    results = db_job_list_for_tenant("tenant-C")

    assert len(results) == 1
    job_id, row = results[0]
    assert isinstance(job_id, str)
    assert isinstance(row, dict)
    assert "report" in row  # alias key must be present


def test_update_ignores_unknown_kwargs():
    """db_job_update must silently ignore kwargs not in _WRITABLE_COLS."""
    db_job_create("job-011", "tenant-A")
    # This should not raise even though 'unknown_field' is not a column
    db_job_update("job-011", status="completed", unknown_field="ignored")
    row = db_job_get("job-011")
    assert row is not None
    assert row["status"] == "completed"


# ---------------------------------------------------------------------------
# Task 1 — Phase 2 新表测试
# ---------------------------------------------------------------------------

from cangjie_fos.services.pitch_job_db import (  # noqa: E402
    db_exec_memory_insert,
    db_exec_memory_list,
    db_exec_memory_delete,
    db_material_contribution_upsert,
    db_material_contributions_list,
    db_material_match_insert,
    db_material_matches_list,
)


def test_exec_memory_insert_and_list():
    db_exec_memory_insert(
        company_id="co-A", tag="risk", uuid="uuid-1",
        raw_text="内容A", refined_text="精炼A",
    )
    rows = db_exec_memory_list("co-A")
    assert len(rows) == 1
    assert rows[0]["uuid"] == "uuid-1"
    assert rows[0]["refined_text"] == "精炼A"


def test_exec_memory_delete():
    db_exec_memory_insert(company_id="co-B", tag="risk", uuid="uuid-2", raw_text="X")
    db_exec_memory_delete("uuid-2")
    rows = db_exec_memory_list("co-B")
    assert rows == []


def test_exec_memory_idempotent_insert():
    """同一 uuid 重复插入不抛异常（IGNORE）。"""
    db_exec_memory_insert(company_id="co-C", tag="t", uuid="uuid-3", raw_text="Y")
    db_exec_memory_insert(company_id="co-C", tag="t", uuid="uuid-3", raw_text="Y")
    assert len(db_exec_memory_list("co-C")) == 1


def test_material_contribution_upsert_and_list():
    db_material_contribution_upsert("file.pptx", "docs/file.pptx", tags=["pitch"], usage_count_delta=1)
    rows = db_material_contributions_list()
    assert any(r["asset_filename"] == "file.pptx" for r in rows)
    # 再次 upsert 累加
    db_material_contribution_upsert("file.pptx", "docs/file.pptx", usage_count_delta=2)
    rows2 = db_material_contributions_list()
    match = next(r for r in rows2 if r["asset_filename"] == "file.pptx")
    assert match["usage_count"] == 3


def test_material_match_insert_and_list():
    db_material_match_insert("inst-1", "file.pptx", "docs/file.pptx", score=0.9)
    rows = db_material_matches_list("inst-1")
    assert len(rows) == 1
    assert rows[0]["score"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# db_institution_pitch_stats
# ---------------------------------------------------------------------------

def test_institution_pitch_stats_from_jobs_table(_isolated_db) -> None:
    """db_institution_pitch_stats returns counts from pitch_jobs.institution_id."""
    import uuid
    from cangjie_fos.services.pitch_job_db import db_institution_pitch_stats, db_job_bind_institution

    # Create two completed jobs bound to the same institution
    jid1, jid2 = str(uuid.uuid4()), str(uuid.uuid4())
    for jid in (jid1, jid2):
        db_job_create(jid, "t-stats", filename="a.mp3")
        db_job_update(jid, status="completed")
        db_job_bind_institution(jid, "红杉资本")

    # One job for a different institution
    jid3 = str(uuid.uuid4())
    db_job_create(jid3, "t-stats", filename="b.mp3")
    db_job_update(jid3, status="completed")
    db_job_bind_institution(jid3, "高瓴资本")

    stats = db_institution_pitch_stats("t-stats")
    names = {s["institution"]: s for s in stats}

    assert "红杉资本" in names
    assert names["红杉资本"]["pitch_count"] == 2
    assert names["高瓴资本"]["pitch_count"] == 1
    assert names["红杉资本"]["last_pitch_at"] is not None


def test_institution_pitch_stats_from_participants(_isolated_db) -> None:
    """db_institution_pitch_stats also counts via job_participants.institution."""
    import uuid
    from cangjie_fos.services.pitch_job_db import (
        db_institution_pitch_stats,
        db_participants_save,
    )

    # Job without explicit institution_id binding but with participant data
    jid = str(uuid.uuid4())
    db_job_create(jid, "t-part", filename="c.mp3")
    db_job_update(jid, status="completed")
    db_participants_save(
        job_id=jid,
        tenant_id="t-part",
        confirmed_by="commander",
        participants=[
            {
                "speaker_id": "S1",
                "real_name": "张三",
                "institution": "IDG资本",
                "role": "GP执行",
                "title": "合伙人",
            }
        ],
    )

    stats = db_institution_pitch_stats("t-part")
    names = {s["institution"]: s for s in stats}
    assert "IDG资本" in names
    assert names["IDG资本"]["pitch_count"] >= 1


def test_institution_pitch_stats_empty_tenant(_isolated_db) -> None:
    """Returns empty list for tenant with no completed jobs."""
    from cangjie_fos.services.pitch_job_db import db_institution_pitch_stats

    stats = db_institution_pitch_stats("no-such-tenant")
    assert stats == []


# ---------------------------------------------------------------------------
# State Machine — VALID_TRANSITIONS + db_job_transition
# ---------------------------------------------------------------------------

def test_valid_transition_pending_to_transcribing():
    """pending → transcribing is a legal transition."""
    from cangjie_fos.services.pitch_job_db import db_job_transition, VALID_TRANSITIONS
    db_job_create("sm-001", "tenant-A")
    db_job_transition("sm-001", "transcribing")
    row = db_job_get("sm-001")
    assert row["status"] == "transcribing"


def test_valid_transition_chain():
    """Full happy-path chain: pending → transcribing → evaluating → completed."""
    from cangjie_fos.services.pitch_job_db import db_job_transition
    db_job_create("sm-chain", "tenant-A")
    db_job_transition("sm-chain", "transcribing")
    db_job_transition("sm-chain", "evaluating")
    db_job_transition("sm-chain", "completed")
    row = db_job_get("sm-chain")
    assert row["status"] == "completed"


def test_invalid_transition_raises():
    """pending → completed is NOT in VALID_TRANSITIONS, must raise InvalidTransitionError."""
    from cangjie_fos.services.pitch_job_db import db_job_transition, InvalidTransitionError
    db_job_create("sm-bad", "tenant-A")
    with pytest.raises(InvalidTransitionError):
        db_job_transition("sm-bad", "completed")


def test_transition_nonexistent_job_raises():
    """Transitioning a job that doesn't exist must raise KeyError."""
    from cangjie_fos.services.pitch_job_db import db_job_transition
    with pytest.raises(KeyError):
        db_job_transition("no-such-job", "transcribing")


def test_transition_with_extra_fields():
    """db_job_transition accepts extra kwargs forwarded to db_job_update."""
    from cangjie_fos.services.pitch_job_db import db_job_transition
    db_job_create("sm-extra", "tenant-A")
    db_job_transition("sm-extra", "transcribing", substatus="正在转写…")
    row = db_job_get("sm-extra")
    assert row["status"] == "transcribing"
    assert row["substatus"] == "正在转写…"


def test_db_job_update_bypasses_state_machine():
    """db_job_update (无校验) allows arbitrary status jumps — backward compat."""
    db_job_create("sm-bypass", "tenant-A")
    db_job_update("sm-bypass", status="completed")
    row = db_job_get("sm-bypass")
    assert row["status"] == "completed"


def test_valid_transitions_covers_all_states():
    """VALID_TRANSITIONS should have an entry for every known status string."""
    from cangjie_fos.services.pitch_job_db import VALID_TRANSITIONS
    known_states = {"pending", "transcribing", "awaiting_speakers",
                    "resuming_analysis", "evaluating", "completed", "failed"}
    assert set(VALID_TRANSITIONS.keys()) == known_states
