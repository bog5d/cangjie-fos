"""v1.11.1 多端补漏：v1.10.0 的跨源情报随机构档案跨端流通（push 附带 + pull 合并）。

- push_institution 把 institution_intel 附进 payload
- _merge_institution_from_cloud 按子键 updated_at 新者覆盖合并情报
- 陈旧远端情报不覆盖本地更新的情报
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from cangjie_fos.schemas.institution import (
    InstitutionProfile,
    InstitutionThermal,
    PipelineStage,
)
from cangjie_fos.services import github_sync
from cangjie_fos.services.institution_store import (
    get_institution_intel_by_name,
    merge_institution_intel,
    upsert_institution,
)


@pytest.fixture(autouse=True)
def _isolate_institutions(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "cangjie_fos.services.institution_store._db_path",
        lambda: str(tmp_path / "test_inst.sqlite"),
    )


def _seed_institution(name: str, iid: str = "inst-0000-0001", tenant: str = "t1") -> None:
    upsert_institution(InstitutionProfile(
        institution_id=iid, tenant_id=tenant, name=name,
        stage=PipelineStage.PITCHED, thermal=InstitutionThermal.WARM,
        updated_at=time.time(),
    ))


def test_push_institution_attaches_intel():
    _seed_institution("推送情报机构", iid="inst-push-0001")
    merge_institution_intel(tenant_id="t1", name="推送情报机构",
                            patch={"dd": {"gaps": ["审计报告"], "updated_at": time.time()}})

    captured = {}

    def fake_put(path, content, message):
        captured["payload"] = content
        return True

    with patch.object(github_sync, "is_configured", return_value=True), \
         patch.object(github_sync, "_put_file", side_effect=fake_put), \
         patch.object(github_sync, "_cfg", return_value={"tenant": "t1", "repo": "x/y", "token": "t"}):
        ok = github_sync.push_institution("inst-push-0001")

    assert ok is True
    assert captured["payload"]["intel_notes"]["dd"]["gaps"] == ["审计报告"]


def test_pull_merges_remote_intel():
    """远端情报（较新）应被合并进本地侧表。"""
    _seed_institution("拉取情报机构", iid="inst-pull-0001")
    data = {
        "institution_id": "inst-pull-0001",
        "tenant_id": "t1",
        "name": "拉取情报机构",
        "updated_at": 0,  # 里程碑不更新，但情报应独立合并
        "intel_notes": {"roadshow": {"key_questions": [{"verbatim": "毛利率?"}], "updated_at": time.time()}},
    }
    github_sync._merge_institution_from_cloud(data)
    notes = get_institution_intel_by_name("拉取情报机构")
    assert notes["roadshow"]["key_questions"][0]["verbatim"] == "毛利率?"


def test_stale_remote_intel_does_not_clobber_local():
    """本地情报较新时，陈旧远端情报不得覆盖。"""
    _seed_institution("防覆盖机构", iid="inst-guard-0001")
    now = time.time()
    merge_institution_intel(tenant_id="t1", name="防覆盖机构",
                            patch={"dd": {"gaps": ["本地新缺口"], "updated_at": now}})
    data = {
        "institution_id": "inst-guard-0001",
        "tenant_id": "t1",
        "name": "防覆盖机构",
        "updated_at": 0,
        "intel_notes": {"dd": {"gaps": ["远端旧缺口"], "updated_at": now - 1000}},
    }
    github_sync._merge_institution_from_cloud(data)
    notes = get_institution_intel_by_name("防覆盖机构")
    assert notes["dd"]["gaps"] == ["本地新缺口"], "陈旧远端不应覆盖较新本地情报"
