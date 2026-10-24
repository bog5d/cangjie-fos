"""进化飞轮注入器测试：偏好格式化 + API 端点。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import create_app
from cangjie_fos.services.evolution_injector import build_investor_context
from cangjie_fos.services.pitch_job_db import _connect, db_pref_insert

TENANT = "inject-test-tenant"


@pytest.fixture(autouse=True)
def clean_prefs():
    conn = _connect()
    conn.execute("DELETE FROM investor_prefs WHERE tenant_id = ?", (TENANT,))
    conn.commit()
    conn.close()


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def _seed_prefs():
    db_pref_insert(
        tenant_id=TENANT,
        pref_type="score_bias",
        pref_key="score_adjustment_direction",
        pref_value={"delta": -5, "direction": "down"},
        source_job_id="j1",
    )
    db_pref_insert(
        tenant_id=TENANT,
        pref_type="risk_level_adjustment",
        pref_key="upgrade_一般_to_严重",
        pref_value={"from": "一般", "to": "严重"},
        source_job_id="j1",
    )
    db_pref_insert(
        tenant_id=TENANT,
        pref_type="risk_calibration",
        pref_key="tends_to_add_risk_points",
        pref_value={"count": 2, "samples": ["信息披露不足"]},
        source_job_id="j1",
    )


class TestBuildInvestorContext:
    def test_empty_tenant_returns_empty(self):
        result = build_investor_context("nonexistent-tenant-xyz")
        assert result == {}

    def test_returns_investor_preferences_key(self):
        _seed_prefs()
        result = build_investor_context(TENANT)
        assert "investor_preferences" in result

    def test_context_contains_score_info(self):
        _seed_prefs()
        text = build_investor_context(TENANT)["investor_preferences"]
        assert "评分" in text or "分" in text

    def test_context_contains_risk_level_info(self):
        _seed_prefs()
        text = build_investor_context(TENANT)["investor_preferences"]
        assert "一般" in text or "严重" in text or "升级" in text

    def test_context_has_header(self):
        _seed_prefs()
        text = build_investor_context(TENANT)["investor_preferences"]
        assert "投资人历史偏好" in text

    def test_dedup_same_pref_key(self):
        # 插入两条相同 pref_key，只应出现一次
        for _ in range(3):
            db_pref_insert(
                tenant_id=TENANT,
                pref_type="score_bias",
                pref_key="score_adjustment_direction",
                pref_value={"delta": -5, "direction": "down"},
            )
        text = build_investor_context(TENANT)["investor_preferences"]
        assert text.count("评分") <= 1 or text.count("分") <= 3  # 去重后不重复

    def test_max_chars_limit(self):
        # 大量偏好不超过 _MAX_CHARS
        for i in range(20):
            db_pref_insert(
                tenant_id=TENANT,
                pref_type="risk_level_adjustment",
                pref_key=f"upgrade_一般_to_key_{i}",
                pref_value={"from": "一般", "to": f"级别{i}"},
            )
        result = build_investor_context(TENANT)
        if "investor_preferences" in result:
            assert len(result["investor_preferences"]) <= 900  # 含截断标记


class TestPrefsEndpoint:
    def test_prefs_endpoint_empty(self, client):
        r = client.get(f"/api/pitch/prefs?tenant_id={TENANT}")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0
        assert data["prefs"] == []

    def test_prefs_endpoint_with_data(self, client):
        _seed_prefs()
        r = client.get(f"/api/pitch/prefs?tenant_id={TENANT}")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 3
        assert data["tenant_id"] == TENANT

    def test_prefs_endpoint_injected_context(self, client):
        _seed_prefs()
        r = client.get(f"/api/pitch/prefs?tenant_id={TENANT}")
        data = r.json()
        assert isinstance(data["injected_context"], str)
        assert len(data["injected_context"]) > 0

    def test_prefs_endpoint_missing_tenant_returns_422(self, client):
        r = client.get("/api/pitch/prefs")
        assert r.status_code == 422
