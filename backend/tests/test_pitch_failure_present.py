"""pitch_failure_present：错误摘要与 Raw JSON 隔离。"""
from __future__ import annotations

from cangjie_fos.services.pitch_failure_present import (
    CODE_ASR_VENDOR,
    job_failure_update_kwargs,
    normalize_pitch_failure,
    resolve_stored_job_errors,
)


def test_normalize_raw_json_aliyun_like() -> None:
    raw = (
        '{"request_id":"abc-123","output":{"message":"Throttling.User",'
        '"status":"Failed"},"status":"Failed"}'
    )
    n = normalize_pitch_failure(raw, job_id="deadbeef0001")
    assert "{" not in (n["error_summary"] or "")
    assert "request_id" not in (n["error_summary"] or "").lower()
    assert n["error_detail"] is not None
    assert "request_id" in n["error_detail"]


def test_normalize_plain_message() -> None:
    n = normalize_pitch_failure("磁盘空间不足", job_id="x")
    assert "磁盘" in (n["error_summary"] or "")


def test_job_failure_update_kwargs_sets_legacy_error_to_summary() -> None:
    kw = job_failure_update_kwargs(ValueError("boom"), job_id="jidjidjidjid")
    assert kw["error_summary"] is not None
    assert kw["error"] == kw["error_summary"]
    assert "boom" in kw["error_summary"]


def test_resolve_stored_prefers_error_summary() -> None:
    row = {"error_summary": "人话", "error_detail": "D", "error_code": "X", "error": "legacy"}
    r = resolve_stored_job_errors(row, "jid")
    assert r["error_summary"] == "人话"
    assert r["error"] == "人话"


def test_resolve_stored_legacy_json_row() -> None:
    import json

    raw = json.dumps({"request_id": "rid", "output": {"message": "限流"}})
    row = {"error": raw}
    r = resolve_stored_job_errors(row, "abcdef123456")
    assert r["error_summary"] is not None
    assert "{" not in r["error_summary"]
    assert r["error_code"] in (CODE_ASR_VENDOR, "UNKNOWN")
