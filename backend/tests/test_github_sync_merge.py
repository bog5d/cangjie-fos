"""机构数据跨端同步 Pull 端字段合并（游梦秋 #01）测试。

Push 端 model_dump 全字段都推；本测试确保 Pull 端把 stage/thermal/画像/卡点/锁
等字段也合并回本地，而不是只合 9 个里程碑字段。
"""
from __future__ import annotations

import pytest

from cangjie_fos.services import institution_store as store
from cangjie_fos.schemas.institution import InstitutionProfileCreate
from cangjie_fos.services.github_sync import _merge_institution_from_cloud


@pytest.fixture(autouse=True)
def _isolate_institutions_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "inst.sqlite"
    monkeypatch.setattr(store, "_db_path", lambda: str(dbfile))


def test_pull_merges_stage_blocker_lock_and_profile():
    # 本地建一家（旧时间戳）
    p = store.create_institution(InstitutionProfileCreate(tenant_id="zt", name="红杉资本"))
    store.update_institution(tenant_id="zt", institution_id=p.institution_id, )  # touch

    # 云端推来的完整档案（更新时间更晚），带上以前 Pull 漏合的字段
    cloud = {
        "institution_id": p.institution_id,
        "tenant_id": "zt",
        "name": "红杉资本",
        "updated_at": 9_999_999_999.0,  # 远大于本地
        "stage": "dd",
        "thermal": "hot",
        "blocker_note": "尽调卡在法务，对方律师休假",
        "review_locked": True,
        "contact_name": "张三",
        "valuation": "2亿",
        "probability": 70,
        "ai_summary": "关注估值偏高、退出路径",
        # 里程碑也带上
        "nda_signed": True,
    }
    _merge_institution_from_cloud(cloud)

    after = store.get_by_id(institution_id=p.institution_id)
    assert after.stage.value == "dd"
    assert after.thermal.value == "hot"
    assert after.blocker_note == "尽调卡在法务，对方律师休假"
    assert after.review_locked is True
    assert after.contact_name == "张三"
    assert after.valuation == "2亿"
    assert after.probability == 70
    assert "估值偏高" in after.ai_summary
    assert after.nda_signed is True


def test_pull_does_not_overwrite_newer_local():
    """本地更新（时间戳更晚）时，陈旧云端不覆盖。"""
    import time
    p = store.create_institution(InstitutionProfileCreate(tenant_id="zt", name="高瓴"))
    store.update_institution(tenant_id="zt", institution_id=p.institution_id,
                             blocker_note="本地最新卡点")
    cloud = {
        "institution_id": p.institution_id, "tenant_id": "zt", "name": "高瓴",
        "updated_at": 1.0,  # 很旧
        "blocker_note": "陈旧云端卡点",
    }
    _merge_institution_from_cloud(cloud)
    after = store.get_by_id(institution_id=p.institution_id)
    assert after.blocker_note == "本地最新卡点"  # 未被旧云端覆盖


def test_db_startup_safety_returns_abs_path():
    """启动数据安全动作不崩，返回绝对路径（游梦秋 #02 定位手段）。"""
    import os
    from cangjie_fos.services.db_base import startup_db_safety
    path = startup_db_safety()
    assert os.path.isabs(path)
