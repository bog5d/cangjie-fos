"""P0：War Room 漏斗与 Dashboard 内 funnel 同源契约（REFACTOR_PLAN 步骤 5）。"""
from __future__ import annotations

from starlette.testclient import TestClient

from cangjie_fos.main import app as global_app


def test_war_room_funnel_matches_dashboard_funnel_payload() -> None:
    """同一 tenant_id 下 HTTP 响应中 funnel 字段应与 war-room 路由完全一致。"""
    c = TestClient(global_app)
    tenant_id = "p0-funnel-parity-tenant"
    r_wr = c.get("/api/war-room/funnel", params={"tenant_id": tenant_id})
    r_dash = c.get("/api/dashboard/status", params={"tenant_id": tenant_id})
    assert r_wr.status_code == 200
    assert r_dash.status_code == 200
    body_dash = r_dash.json()
    assert body_dash["funnel"] == r_wr.json()
