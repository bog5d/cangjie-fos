"""DD-V1 快照冻结测试（A4a · G-A4a-2）。

判据对应：**A4-2** 两侧快照逐件 sha256 相等；``snapshot_id`` 与冻结时刻已记录；改动可检出。

红线：
- sha256 一律**现场算**（复用 ``dd_v1_agent_result_service``，不重写 sha 计算）；
- ``snapshot_id`` 一律取 ``ar.snapshot_id()``（同一份口径，不另造）。
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_agent_result_service as ar
from cangjie_fos.services import dd_v1_snapshot_freeze_service as fz

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "dd-v1-fos71-a4"
MATERIAL = FIXTURE / "material"


def _meta():
    return json.loads((MATERIAL / "meta.json").read_text("utf-8"))


def _freeze(tmp_path, name="frozen"):
    return fz.freeze_snapshot(MATERIAL, _meta(), tmp_path / name)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_manifest_records_snapshot_id_frozen_at_and_per_file_sha(tmp_path):
    man = _freeze(tmp_path)
    assert man["snapshot_id"].startswith("snap-")
    assert man["frozen_at"]
    assert len(man["files"]) == 8
    for entry in man["files"]:
        assert set(entry) == {"file_id", "relative_path", "sha256"}
        assert _sha(tmp_path / "frozen" / entry["relative_path"]) == entry["sha256"]
    assert (tmp_path / "frozen" / "snapshot.json").is_file()


def test_snapshot_id_reuses_agent_result_service(tmp_path):
    """复用同一份口径：不得另造 snapshot_id。"""
    man = _freeze(tmp_path)
    snap = ar.load_snapshot(tmp_path / "frozen", _meta())
    assert man["snapshot_id"] == ar.snapshot_id(snap)


def test_frozen_dir_is_readonly(tmp_path):
    _freeze(tmp_path)
    assert (tmp_path / "frozen").stat().st_mode & 0o777 == 0o555


def test_verify_frozen_detects_modified_file(tmp_path):
    man = _freeze(tmp_path)
    victim = tmp_path / "frozen" / man["files"][0]["relative_path"]
    fz.make_writable(tmp_path / "frozen")
    victim.write_text(victim.read_text("utf-8") + "改动\n", "utf-8")
    out = fz.verify_frozen(tmp_path / "frozen", man)
    assert out["ok"] is False
    assert any(c["kind"] == "MODIFIED" for c in out["changed"])


def test_verify_frozen_detects_missing_file(tmp_path):
    man = _freeze(tmp_path)
    fz.make_writable(tmp_path / "frozen")
    (tmp_path / "frozen" / man["files"][0]["relative_path"]).unlink()
    out = fz.verify_frozen(tmp_path / "frozen", man)
    assert out["ok"] is False
    assert any(c["kind"] == "MISSING" for c in out["changed"])


def test_verify_frozen_detects_extra_file(tmp_path):
    man = _freeze(tmp_path)
    fz.make_writable(tmp_path / "frozen")
    (tmp_path / "frozen" / "偷偷加进来的.txt").write_text("x", "utf-8")
    out = fz.verify_frozen(tmp_path / "frozen", man)
    assert out["ok"] is False
    assert any(c["kind"] == "EXTRA" for c in out["changed"])


def test_two_sides_are_byte_identical(tmp_path):
    _freeze(tmp_path, "examiner")
    _freeze(tmp_path, "grader")
    out = fz.compare_snapshots(tmp_path / "examiner", tmp_path / "grader", _meta())
    assert out["ok"] is True and out["mismatched"] == []
    assert out["snapshot_id_a"] == out["snapshot_id_b"]


def test_compare_snapshots_detects_difference(tmp_path):
    _freeze(tmp_path, "examiner")
    _freeze(tmp_path, "grader")
    fz.make_writable(tmp_path / "grader")
    man = json.loads((tmp_path / "grader" / "snapshot.json").read_text("utf-8"))
    victim = tmp_path / "grader" / man["files"][0]["relative_path"]
    victim.write_text(victim.read_text("utf-8") + "改动\n", "utf-8")
    out = fz.compare_snapshots(tmp_path / "examiner", tmp_path / "grader", _meta())
    assert out["ok"] is False
    assert out["mismatched"][0]["kind"] == "SHA_MISMATCH"


def test_freeze_refuses_dir_inside_source(tmp_path):
    with pytest.raises(fz.FreezeError, match="FREEZE_DIR_INSIDE_SOURCE"):
        fz.freeze_snapshot(MATERIAL, _meta(), MATERIAL / "frozen")


def test_freeze_is_repeatable_over_readonly_dir(tmp_path):
    _freeze(tmp_path)
    man2 = fz.freeze_snapshot(MATERIAL, _meta(), tmp_path / "frozen")
    assert man2["files"] and man2["snapshot_id"].startswith("snap-")


def test_sha_is_computed_on_site_not_trusted_from_metadata(tmp_path):
    """元数据里没有 sha 字段 ⇒ 清单里的 sha 只能来自现场计算。"""
    meta = _meta()
    assert all("sha256" not in m for m in meta)
    man = _freeze(tmp_path)
    entry = man["files"][0]
    assert entry["sha256"] == _sha(tmp_path / "frozen" / entry["relative_path"])
