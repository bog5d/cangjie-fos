"""离线暂存 + 自动补传（sync outbox）测试。

核心保证：网不好时改动进本地队列不丢；网好了 flush 把积压全部补传。
"""
from __future__ import annotations

import pytest

from cangjie_fos.services import sync_outbox as ob


def test_enqueue_and_dedup():
    ob.enqueue("institution", "inst-1")
    ob.enqueue("institution", "inst-1")  # 同实体重复 → 只留一条
    ob.enqueue("roadshow", "job-1")
    pend = {(p["kind"], p["ref_id"]) for p in ob.list_pending()}
    assert ("institution", "inst-1") in pend
    assert ("roadshow", "job-1") in pend
    assert ob.pending_count() == 2  # 去重后 2 条


def test_unknown_kind_ignored():
    before = ob.pending_count()
    ob.enqueue("bogus", "x")
    ob.enqueue("institution", "")  # 空 ref
    assert ob.pending_count() == before


def test_flush_drains_on_success(monkeypatch):
    ob.enqueue("institution", "inst-A")
    ob.enqueue("dd_session", "sess-A")
    monkeypatch.setattr("cangjie_fos.services.github_sync.is_configured", lambda: True)
    monkeypatch.setattr("cangjie_fos.services.github_sync.push_institution", lambda rid: True)
    monkeypatch.setattr("cangjie_fos.services.github_sync.push_dd_session", lambda rid: True)

    res = ob.flush()
    assert res["flushed"] == 2
    assert res["remaining"] == 0
    assert ob.pending_count() == 0


def test_flush_keeps_failed(monkeypatch):
    """离线（push 失败）→ 队列保留，不丢。"""
    ob.enqueue("institution", "inst-B")
    monkeypatch.setattr("cangjie_fos.services.github_sync.is_configured", lambda: True)
    monkeypatch.setattr("cangjie_fos.services.github_sync.push_institution", lambda rid: False)

    res = ob.flush()
    assert res["flushed"] == 0
    assert res["remaining"] == 1
    assert ob.pending_count() == 1  # 还在，等下次补传
    rec = next(p for p in ob.list_pending() if p["ref_id"] == "inst-B")
    assert rec["attempts"] == 1


def test_flush_recovers_when_network_back(monkeypatch):
    """先离线（失败留队），后网好（成功补传清空）——完整的暂存→补传闭环。"""
    ob.enqueue("roadshow", "job-B")
    monkeypatch.setattr("cangjie_fos.services.github_sync.is_configured", lambda: True)

    # 第一轮：网坏
    monkeypatch.setattr("cangjie_fos.services.github_sync.push_roadshow_report", lambda rid: False)
    assert ob.flush()["remaining"] == 1

    # 第二轮：网好 → 补传成功
    monkeypatch.setattr("cangjie_fos.services.github_sync.push_roadshow_report", lambda rid: True)
    res = ob.flush()
    assert res["flushed"] == 1
    assert ob.pending_count() == 0


def test_flush_skips_when_unconfigured(monkeypatch):
    """未配 token → 不清空、直接返回 skipped（等配好再补传）。"""
    ob.enqueue("institution", "inst-C")
    monkeypatch.setattr("cangjie_fos.services.github_sync.is_configured", lambda: False)
    res = ob.flush()
    assert res["skipped"] is True
    assert ob.pending_count() == 1  # 数据不丢


def test_enqueue_and_try_online(monkeypatch):
    """在线时 enqueue_and_try 立即补传成功，不留积压。"""
    monkeypatch.setattr("cangjie_fos.services.github_sync.is_configured", lambda: True)
    monkeypatch.setattr("cangjie_fos.services.github_sync.push_institution", lambda rid: True)
    ob.enqueue_and_try("institution", "inst-D")
    assert ob.pending_count() == 0


def test_pending_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    from cangjie_fos.main import create_app
    ob.enqueue("institution", "inst-E")
    with TestClient(create_app()) as c:
        r = c.get("/api/sync/pending")
        assert r.status_code == 200
        assert r.json()["pending"] >= 1
