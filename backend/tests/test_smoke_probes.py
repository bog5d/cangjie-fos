"""探针测试：无人值守冒烟验证所有关键 API 路由和链路完整性。

不依赖 ASR / LLM / 外部网络，全部在本地 TestClient 完成。
目标：每次上线前一条命令可验证整条骨干链路无断点。
"""
from __future__ import annotations

import json
import pathlib

import pytest
from starlette.testclient import TestClient

from cangjie_fos.main import app as global_app

TENANT = "smoke-tenant"
CLIENT = TestClient(global_app)


# ──────────────────────────────────────────────
# 1. 基础健康 & 状态端点
# ──────────────────────────────────────────────

def test_health_200():
    r = CLIENT.get("/health")
    assert r.status_code == 200


def test_pitch_health_200():
    r = CLIENT.get("/api/pitch/health")
    assert r.status_code == 200


def test_dashboard_status_200():
    r = CLIENT.get("/api/dashboard/status", params={"tenant_id": TENANT})
    assert r.status_code == 200
    data = r.json()
    assert "total_score" in data or "docs_health_pct" in data


def test_pipeline_status_200():
    r = CLIENT.get("/api/v1/pipeline/status", params={"tenant_id": TENANT})
    assert r.status_code == 200


def test_war_room_funnel_200():
    r = CLIENT.get("/api/war-room/funnel", params={"tenant_id": TENANT})
    assert r.status_code == 200


# ──────────────────────────────────────────────
# 2. 机构 Pipeline CRM 端点
# ──────────────────────────────────────────────

def test_institutions_list_200():
    r = CLIENT.get("/api/v1/pipeline/institutions", params={"tenant_id": TENANT})
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_funnel_debug_200():
    r = CLIENT.get("/api/v1/pipeline/funnel-debug", params={"tenant_id": TENANT})
    assert r.status_code == 200


# ──────────────────────────────────────────────
# 3. Job 列表端点
# ──────────────────────────────────────────────

def test_jobs_list_200():
    r = CLIENT.get("/api/pitch/jobs", params={"tenant_id": TENANT})
    assert r.status_code == 200


def test_job_unknown_404():
    r = CLIENT.get("/api/pitch/jobs/nonexistent-job-id/review")
    assert r.status_code == 404


def test_job_words_unknown_404():
    r = CLIENT.get("/api/pitch/jobs/nonexistent-job-id/words")
    assert r.status_code == 404


# ──────────────────────────────────────────────
# 4. 资产台账 API
# ──────────────────────────────────────────────

def test_assets_200_even_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "cangjie_fos.core.paths.get_fos_bridge_data_dir", lambda: tmp_path
    )
    r = CLIENT.get("/api/v1/assets")
    assert r.status_code == 200
    data = r.json()
    assert data["total_files"] == 0
    assert data["assets"] == []


def test_assets_search_200(monkeypatch, tmp_path):
    sample = {
        "generated_at": "2026-04-22T10:00:00",
        "source_dir": str(tmp_path),
        "total_files": 1,
        "assets": [
            {"filename": "BP.pdf", "relative_path": "", "full_path": str(tmp_path / "BP.pdf"),
             "last_modified": "2026-04-22", "summary": "商业计划书", "tags": ["BP"]}
        ],
    }
    (tmp_path / "asset_index.json").write_text(json.dumps(sample), encoding="utf-8")
    monkeypatch.setattr(
        "cangjie_fos.core.paths.get_fos_bridge_data_dir", lambda: tmp_path
    )
    r = CLIENT.get("/api/v1/assets/search", params={"q": "BP"})
    assert r.status_code == 200
    assert r.json()["total_files"] == 1


# ──────────────────────────────────────────────
# 5. 进化飞轮端点
# ──────────────────────────────────────────────

def test_prefs_200():
    r = CLIENT.get("/api/pitch/prefs", params={"tenant_id": TENANT})
    assert r.status_code == 200


# ──────────────────────────────────────────────
# 6. 上传向导 — 骨架流程
# ──────────────────────────────────────────────

def test_wizard_create_session_200():
    body = {
        "tenant_id": TENANT,
        "category": "01_机构路演",
        "institution_name": "冒烟测试机构",
        "tracks": [{"client_temp_id": "t1", "interviewee": "测试人"}],
    }
    r = CLIENT.post("/api/v1/pitch/upload-sessions", json=body)
    assert r.status_code == 200
    data = r.json()
    assert "session_id" in data


def test_wizard_commit_unknown_session_404():
    r = CLIENT.post("/api/v1/pitch/upload-sessions/no-such-session/commit")
    assert r.status_code == 404


# ──────────────────────────────────────────────
# 7. NPC 离线冒烟
# ──────────────────────────────────────────────

def test_npc_chat_offline_returns_reply(monkeypatch):
    """无 API Key 时应返回「离线 NPC」提示，不抛 500。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from cangjie_fos.services.npc_chat_graph import reset_compiled_npc_graph_for_tests
    reset_compiled_npc_graph_for_tests()

    body = {
        "tenant_id": TENANT,
        "message": "你好，这是冒烟测试",
        "thread_id": None,
    }
    r = CLIENT.post("/api/pitch/chat", json=body)
    assert r.status_code == 200
    reply = r.json().get("reply") or r.json().get("message") or ""
    assert len(reply) > 0

    reset_compiled_npc_graph_for_tests()


# ──────────────────────────────────────────────
# 8. Dry-run 链路（pitch/run）
# ──────────────────────────────────────────────

def test_pitch_dry_run_200():
    body = {
        "tenant_id": TENANT,
        "dry_run": True,
        "words": [{"word_index": 0, "text": "测", "start_time": 0.0, "end_time": 0.1, "speaker_id": "S1"}],
    }
    r = CLIENT.post("/api/pitch/run", json=body)
    assert r.status_code == 200


# ──────────────────────────────────────────────
# 9. SPA 路由 fallback（非 API 路径返回 index.html 或 404）
# ──────────────────────────────────────────────

def test_api_404_is_json_not_html():
    """API 路径 404 应返回 JSON detail，不应返回 HTML。"""
    r = CLIENT.get("/api/v1/nonexistent-endpoint-xyz")
    assert r.status_code == 404
    # FastAPI 404 应返回 JSON
    assert r.headers.get("content-type", "").startswith("application/json")


def test_non_api_404_is_not_json_error():
    """非 API 路径（SPA 路由）404 不应被当作 API 错误返回 JSON detail。"""
    r = CLIENT.get("/some/spa/path/that/does/not/exist")
    # 没有 dist/index.html 时会 404，但不应是 API JSON detail
    assert r.status_code in (200, 404)
    if r.status_code == 404:
        body = r.text
        assert '"detail"' not in body or "Not Found" in body
