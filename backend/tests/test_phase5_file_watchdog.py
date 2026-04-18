"""Phase 5：incoming 文件 -> Job + 资料室落盘。"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from cangjie_fos.events.file_watchdog import (
    incoming_root,
    process_incoming_file_path,
    start_file_watchdog,
    stop_file_watchdog,
)
from cangjie_fos.schemas.pitch_upload import PitchJobStatus
from cangjie_fos.services.pitch_job_store import job_get


def test_incoming_root_under_data_room(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("cangjie_fos.core.paths.get_data_room_root", lambda: tmp_path / "dr")
    assert incoming_root() == tmp_path / "dr" / "incoming"


def test_process_incoming_document_copies_and_completes_job(monkeypatch, tmp_path) -> None:
    root_dr = tmp_path / "dr"
    monkeypatch.setattr("cangjie_fos.core.paths.get_data_room_root", lambda: root_dr)
    inc = root_dr / "incoming" / "acme"
    inc.mkdir(parents=True, exist_ok=True)
    src = inc / "bp.txt"
    src.write_text("deck", encoding="utf-8")
    jid = process_incoming_file_path(src)
    assert jid
    time.sleep(0.55)
    row = job_get(jid)
    assert row is not None
    assert row["status"] == PitchJobStatus.COMPLETED
    assert (root_dr / "acme" / "bp.txt").is_file()


def test_process_incoming_root_file_uses_default_tenant(monkeypatch, tmp_path) -> None:
    root_dr = tmp_path / "dr"
    monkeypatch.setattr("cangjie_fos.core.paths.get_data_room_root", lambda: root_dr)
    monkeypatch.setenv("CANGJIE_WATCHDOG_DEFAULT_TENANT", "def-tenant")
    inc = root_dr / "incoming"
    inc.mkdir(parents=True, exist_ok=True)
    f = inc / "solo.txt"
    f.write_text("x", encoding="utf-8")
    jid = process_incoming_file_path(f)
    assert jid
    time.sleep(0.55)
    assert (root_dr / "def-tenant" / "solo.txt").is_file()


def test_process_incoming_ignores_outside_incoming(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("cangjie_fos.core.paths.get_data_room_root", lambda: tmp_path / "dr")
    other = tmp_path / "outside.txt"
    other.write_text("x", encoding="utf-8")
    assert process_incoming_file_path(other) is None


def test_watchdog_start_stop_idempotent(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("cangjie_fos.core.paths.get_data_room_root", lambda: tmp_path / "dr")
    start_file_watchdog()
    start_file_watchdog()
    stop_file_watchdog()
    stop_file_watchdog()
