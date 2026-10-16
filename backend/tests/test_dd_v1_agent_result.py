"""cangjie-fos#71 WP01：Agent 结果契约的确定性校验（不调用模型）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_agent_result_service as ar

FX = Path(__file__).parent / "fixtures" / "dd_v1_fos71"
SNAP = FX / "snapshot"
META = json.loads((FX / "meta.json").read_text("utf-8"))
OBS = json.loads((FX / "obligations.json").read_text("utf-8"))
SCHEMA = Path(ar.__file__).with_name("dd_v1_agent_result.v1.schema.json")


def _snap():
    return ar.load_snapshot(SNAP, META)


def _result(oid="S1-O1", item="S1", verdict="MATCH", fid="F001", **over):
    s = _snap()
    cands = []
    if fid:
        f = s[fid]
        cands = [{"file_id": fid, "relative_path": f.relative_path, "sha256": f.sha256,
                  "locator": "UNKNOWN", "entity": f.entity, "period": f.period, "match_reason": "r"}]
    r = {"item_id": item, "obligation_id": oid, "agent_id": "t", "provider": "test",
         "model_id_or_unknown": "UNKNOWN", "prompt_version": ar.PROMPT_VERSION,
         "source_snapshot_id": ar.snapshot_id(s), "candidate_files": cands,
         "proposed_verdict": verdict, "confidence_or_uncertain": 0.9, "abstain_reason": None,
         "warnings": [], "elapsed": "UNKNOWN", "token_usage_or_UNKNOWN": "UNKNOWN"}
    r.update(over)
    return r


def _run(results):
    return ar.validate_agent_output(json.dumps({"results": results}), SNAP, META, OBS)


def test_fixtures_are_marked_synthetic():
    for p in SNAP.iterdir():
        assert "SYNTHETIC" in p.read_text("utf-8")


def test_schema_fields_match_validator():
    s = json.loads(SCHEMA.read_text("utf-8"))
    item = s["properties"]["results"]["items"]
    assert tuple(item["required"]) == ar.RESULT_FIELDS
    assert tuple(item["properties"]["candidate_files"]["items"]["required"]) == ar.CANDIDATE_FIELDS
    assert set(item["properties"]["proposed_verdict"]["enum"]) == set(ar.ALLOWED_VERDICTS)


def test_packet_is_deterministic_and_marks_excerpt_untrusted():
    a = ar.build_task_packet(SNAP, META, OBS)
    b = ar.build_task_packet(SNAP, META, OBS)
    assert a == b
    assert all("untrusted_excerpt" in f for f in a["files"])
    assert "不可信" in a["instructions"]


def test_valid_match_is_accepted_but_only_as_suggestion():
    rep = _run([_result()])
    assert rep.mode == "AGENT_SUGGESTION"
    assert rep.accepted[0]["review_required"] is True
    assert rep.accepted[0]["approved"] is False


@pytest.mark.parametrize("bad", ["approved", "DELIVERABLE"])
def test_model_cannot_set_approved(bad):
    rep = _run([_result(verdict=bad)])
    assert "FORBIDDEN_VERDICT" in rep.rejected[0]["errors"]
    assert rep.mode == "RULE_ONLY"


def test_fabricated_file_rejected():
    r = _result()
    r["candidate_files"][0]["file_id"] = "F999"
    assert "CANDIDATE_0_NOT_IN_SNAPSHOT" in _run([r]).rejected[0]["errors"]


def test_fabricated_path_and_sha_rejected():
    r = _result()
    r["candidate_files"][0]["relative_path"] = "/etc/passwd"
    r["candidate_files"][0]["sha256"] = "0" * 64
    errs = _run([r]).rejected[0]["errors"]
    assert "CANDIDATE_0_PATH_MISMATCH" in errs and "CANDIDATE_0_SHA_MISMATCH" in errs


def test_wrong_entity_match_rejected():
    errs = _run([_result(fid="F003")]).rejected[0]["errors"]
    assert "CANDIDATE_0_ENTITY_MISMATCH" in errs


def test_wrong_period_match_rejected():
    errs = _run([_result(fid="F002")]).rejected[0]["errors"]
    assert "CANDIDATE_0_PERIOD_MISMATCH" in errs


def test_wrong_period_as_outdated_is_allowed():
    assert _run([_result(fid="F002", verdict="OUTDATED")]).mode == "AGENT_SUGGESTION"


def test_missing_requires_abstain_reason():
    bad = _result(oid="S3-O1", item="S3", verdict="MISSING", fid=None)
    assert "ABSTAIN_WITHOUT_REASON" in _run([bad]).rejected[0]["errors"]
    ok = _result(oid="S3-O1", item="S3", verdict="MISSING", fid=None, abstain_reason="快照无社保证明")
    assert _run([ok]).mode == "AGENT_SUGGESTION"


def test_match_without_evidence_rejected():
    assert "MATCH_WITHOUT_EVIDENCE" in _run([_result(fid=None)]).rejected[0]["errors"]


def test_snapshot_mismatch_rejected():
    assert "SNAPSHOT_MISMATCH" in _run([_result(source_snapshot_id="snap-x")]).rejected[0]["errors"]


def test_bad_confidence_rejected():
    assert "INVALID_CONFIDENCE" in _run([_result(confidence_or_uncertain=7)]).rejected[0]["errors"]


@pytest.mark.parametrize("raw,reason", [
    (None, "EMPTY_OUTPUT"), ("", "EMPTY_OUTPUT"), ("not json", "INVALID_JSON"), ("[]", "NO_RESULTS_ARRAY"),
])
def test_unparseable_output_degrades_to_rule_only(raw, reason):
    rep = ar.validate_agent_output(raw, SNAP, META, OBS)
    assert rep.mode == "RULE_ONLY" and rep.degrade_reason.startswith(reason)


def test_call_failure_degrades_with_reason():
    rep = ar.validate_agent_output(None, SNAP, META, OBS, call_error="TIMEOUT_180S")
    assert rep.mode == "RULE_ONLY" and rep.degrade_reason == "AGENT_CALL_FAILED:TIMEOUT_180S"


def test_tampered_snapshot_file_detected(tmp_path):
    import shutil
    d = tmp_path / "snap"
    shutil.copytree(SNAP, d)
    r = _result()  # sha 来自原快照
    (d / "F001_shili_audit_2024.txt").write_text("tampered", encoding="utf-8")
    rep = ar.validate_agent_output(json.dumps({"results": [r]}), d, META, OBS)
    errs = rep.rejected[0]["errors"]
    assert "SNAPSHOT_MISMATCH" in errs and "CANDIDATE_0_SHA_MISMATCH" in errs


def test_module_has_no_model_client_imports():
    src = Path(ar.__file__).read_text("utf-8")
    for bad in ("openai", "dd_llm_client", "httpx", "requests", "anthropic"):
        assert f"import {bad}" not in src and f"from {bad}" not in src


# ---- 独立复核 N1–N3 回归 ----

def _full():
    return [
        _result(),
        _result(oid="S2-O1", item="S2", fid="F004"),
        _result(oid="S3-O1", item="S3", verdict="MISSING", fid=None, abstain_reason="无"),
    ]


def test_full_coverage_has_no_degrade_reason():
    rep = _run(_full())
    assert rep.mode == "AGENT_SUGGESTION" and len(rep.accepted) == 3
    assert rep.uncovered == [] and rep.degrade_reason is None


def test_n1_unknown_result_field_rejected():
    errs = _run([_result(extra="x")]).rejected[0]["errors"]
    assert "UNKNOWN_FIELDS:extra" in errs


def test_n1_unknown_candidate_field_rejected():
    r = _result()
    r["candidate_files"][0]["approved"] = True
    assert "CANDIDATE_0_UNKNOWN_FIELDS" in _run([r]).rejected[0]["errors"]


def test_n1_unknown_top_level_field_degrades():
    raw = json.dumps({"results": _full(), "approved": True})
    rep = ar.validate_agent_output(raw, SNAP, META, OBS)
    assert rep.mode == "RULE_ONLY" and rep.degrade_reason.startswith("UNKNOWN_TOP_LEVEL_FIELDS")


@pytest.mark.parametrize("verdict,code", [("MISSING", "MISSING_WITH_CANDIDATES"), ("UNCERTAIN", "UNCERTAIN_WITH_CANDIDATES")])
def test_n2_abstain_with_candidates_rejected(verdict, code):
    r = _result(oid="S3-O1", item="S3", verdict=verdict, fid="F001", abstain_reason="x")
    assert code in _run([r]).rejected[0]["errors"]


def test_n2_duplicate_obligation_rejected():
    rep = _run(_full() + [_result()])
    dup = [x for x in rep.rejected if "DUPLICATE_OBLIGATION" in x["errors"]]
    assert len(dup) == 2  # 两条 S1-O1 都拒，不挑一条当真


def test_n2_incomplete_coverage_reported():
    rep = _run([_result()])
    assert rep.uncovered == ["S2-O1", "S3-O1"]
    assert rep.degrade_reason == "INCOMPLETE_COVERAGE:S2-O1,S3-O1"
    assert rep.to_dict()["uncovered_obligations"] == ["S2-O1", "S3-O1"]


def test_n2_item_id_mismatch_rejected():
    assert "ITEM_ID_MISMATCH" in _run([_result(item="S2")]).rejected[0]["errors"]


@pytest.mark.parametrize("verdict", ["PARTIAL", "OUTDATED"])
def test_n3_wrong_entity_rejected_for_partial_and_outdated(verdict):
    errs = _run([_result(fid="F003", verdict=verdict)]).rejected[0]["errors"]
    assert "CANDIDATE_0_ENTITY_MISMATCH" in errs


def test_n3_partial_wrong_period_rejected():
    assert "CANDIDATE_0_PERIOD_MISMATCH" in _run([_result(fid="F002", verdict="PARTIAL")]).rejected[0]["errors"]


def test_n3_outdated_with_current_period_rejected():
    errs = _run([_result(fid="F001", verdict="OUTDATED")]).rejected[0]["errors"]
    assert "CANDIDATE_0_OUTDATED_BUT_PERIOD_MATCHES" in errs
