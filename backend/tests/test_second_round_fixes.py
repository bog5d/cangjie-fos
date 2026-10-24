"""第二轮反馈修复（游梦秋 #1/#2/#3）测试。"""
from __future__ import annotations

import json
import pytest

from cangjie_fos.services import institution_store as store
from cangjie_fos.schemas.institution import InstitutionProfileCreate


# ── #1 豆豆输出补全字段 ───────────────────────────────────────────────────────

def test_institution_detail_includes_all_fields(monkeypatch):
    from cangjie_fos.services import npc_tools

    class FakeInst:
        name = "红杉资本"
        stage = type("S", (), {"value": "dd"})()
        thermal = type("T", (), {"value": "hot"})()
        ai_summary = "关注硬科技"
        concerns = "退出路径"
        preferences = "早期"
        blocker_note = "尽调卡在法务，对方律师休假"
        review_locked = True
        contact_name = "张三"
        contact_title = "合伙人"
        valuation = "2亿"
        deal_size = "3000万"
        probability = 70
        legal_status = "TS草拟中"

    monkeypatch.setattr(
        "cangjie_fos.services.institution_store.find_matching_names",
        lambda *, tenant_id, text: [FakeInst()],
    )
    out = npc_tools.execute_tool("get_institution_detail",
                                 {"institution_name": "红杉"}, tenant_id="t1")
    assert "尽调卡在法务" in out       # 卡点
    assert "已锁定" in out             # 锁定
    assert "张三" in out               # 联系人
    assert "2亿" in out                # 估值
    assert "70%" in out                # 概率
    assert "TS草拟中" in out           # 法务


# ── #2 路演完成后把机构更新入队同步 ──────────────────────────────────────────

@pytest.fixture()
def _iso_inst(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: str(tmp_path / "inst.sqlite"))


def test_roadshow_enqueues_institution_sync(_iso_inst, monkeypatch):
    from cangjie_fos.services.pitch_upload_pipeline import sync_roadshow_institution

    enq = []
    monkeypatch.setattr(
        "cangjie_fos.services.sync_outbox.enqueue_and_try",
        lambda kind, ref: enq.append((kind, ref)),
    )
    ok = sync_roadshow_institution("zt", "红杉资本", {"meeting_atmosphere": "hot"}, "job-1")
    assert ok is True
    # 机构更新应入队同步（以前只推路演报告、不推机构）
    assert any(kind == "institution" for kind, _ in enq)


# ── #3-B pitch 导入不再"存在即跳过" ──────────────────────────────────────────

def _remote(job_id, score, inst="红杉"):
    return {
        "session_id": job_id, "company_id": "zt", "locked_at": "2026-08-06T10:00:00Z",
        "type": "roadshow_intel", "institution": inst, "total_score": score,
        "interviewee": "路演A",
    }


def test_import_updates_prior_remote_shell():
    """上次失败留下的远端空壳，重试能被更新导入（不再永久跳过）。"""
    from cangjie_fos.services.github_sync import _import_remote_pitch
    from cangjie_fos.services.pitch_job_db import _connect

    # 先造一个"远端同步"空壳（模拟上次导入残留）
    with _connect() as conn:
        conn.execute(
            "INSERT INTO pitch_jobs (job_id, tenant_id, status, created_at, original_report, "
            "substatus, institution_id) VALUES ('j1','zt','locked',1.0,'','synced_from_remote','')"
        )
    _import_remote_pitch(_remote("j1", 88))
    with _connect() as conn:
        row = conn.execute("SELECT original_report FROM pitch_jobs WHERE job_id='j1'").fetchone()
    rep = json.loads(row["original_report"])
    assert rep["total_score"] == 88  # 被更新了，不再跳过


def test_import_does_not_clobber_local_edit():
    """用户自己编辑过的本地任务（非远端同步记录）不被远端覆盖。"""
    from cangjie_fos.services.github_sync import _import_remote_pitch
    from cangjie_fos.services.pitch_job_db import _connect

    with _connect() as conn:
        conn.execute(
            "INSERT INTO pitch_jobs (job_id, tenant_id, status, created_at, original_report, "
            "edited_report, substatus, institution_id) "
            "VALUES ('j2','zt','completed',1.0,'{\"total_score\":50}','{\"mine\":1}','','')"
        )
    _import_remote_pitch(_remote("j2", 99))
    with _connect() as conn:
        row = conn.execute("SELECT original_report, edited_report FROM pitch_jobs WHERE job_id='j2'").fetchone()
    # 本地原创任务的报告/编辑未被远端 99 分覆盖
    assert json.loads(row["original_report"])["total_score"] == 50
    assert json.loads(row["edited_report"])["mine"] == 1


def test_import_new_remote_inserts():
    from cangjie_fos.services.github_sync import _import_remote_pitch
    from cangjie_fos.services.pitch_job_db import _connect
    _import_remote_pitch(_remote("j3", 77))
    with _connect() as conn:
        row = conn.execute("SELECT original_report FROM pitch_jobs WHERE job_id='j3'").fetchone()
    assert row is not None
    assert json.loads(row["original_report"])["total_score"] == 77
