"""参与人身份确认模块测试（Phase 6.6）"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CANGJIE_DATA_ROOT", str(tmp_path))
    from cangjie_fos.main import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


def _make_job(client: TestClient, tenant_id: str = "t1") -> str:
    """在 DB 中直接插入一个 completed job，返回 job_id。"""
    import time, uuid, json
    from cangjie_fos.services.pitch_job_db import db_job_create, db_job_update

    job_id = str(uuid.uuid4())
    db_job_create(job_id, tenant_id, status="completed")
    # 写入 words_json 供 speaker-summary 使用
    words = [
        {"word_index": 0, "text": "你们的商业模式是什么？", "start_time": 0, "end_time": 2, "speaker_id": "A"},
        {"word_index": 1, "text": "我们是SaaS订阅模式", "start_time": 3, "end_time": 5, "speaker_id": "B"},
        {"word_index": 2, "text": "那你们的客单价呢？", "start_time": 6, "end_time": 8, "speaker_id": "A"},
        {"word_index": 3, "text": "平均年费50万", "start_time": 9, "end_time": 10, "speaker_id": "B"},
        {"word_index": 4, "text": "毛利率是多少？", "start_time": 11, "end_time": 12, "speaker_id": "A"},
    ]
    db_job_update(job_id, original_report={"total_score": 80}, words_json=words)
    return job_id


# ── speaker-summary ──────────────────────────────────────────────────────────

def test_speaker_summary_returns_speakers(client):
    job_id = _make_job(client)
    r = client.get(f"/api/v1/pitch/jobs/{job_id}/speaker-summary")
    assert r.status_code == 200
    data = r.json()
    sids = {s["speaker_id"] for s in data}
    assert "A" in sids
    assert "B" in sids


def test_speaker_summary_has_sample_lines(client):
    job_id = _make_job(client)
    r = client.get(f"/api/v1/pitch/jobs/{job_id}/speaker-summary")
    speakers = {s["speaker_id"]: s for s in r.json()}
    assert len(speakers["A"]["sample_lines"]) >= 1
    assert "商业模式" in speakers["A"]["sample_lines"][0]


def test_speaker_summary_404_on_unknown(client):
    r = client.get("/api/v1/pitch/jobs/no-such-job/speaker-summary")
    assert r.status_code == 404


# ── confirm participants ──────────────────────────────────────────────────────

def test_confirm_participants_success(client):
    job_id = _make_job(client)
    r = client.post(
        f"/api/v1/pitch/jobs/{job_id}/participants",
        json={
            "confirmed_by": "王总",
            "participants": [
                {"speaker_id": "A", "real_name": "李局长", "institution": "新川基金", "role": "LP投资方", "title": "招商局长"},
                {"speaker_id": "B", "real_name": "张伟", "institution": "新川基金", "role": "GP执行", "title": "管理合伙人"},
            ],
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["confirmed"] == 2


def test_confirm_marks_job_confirmed(client):
    job_id = _make_job(client)
    client.post(
        f"/api/v1/pitch/jobs/{job_id}/participants",
        json={"participants": [{"speaker_id": "A", "role": "其他"}]},
    )
    # job list should show participants_confirmed=True
    from cangjie_fos.services.pitch_job_db import db_job_get
    row = db_job_get(job_id)
    assert row["participants_confirmed"] == 1


def test_get_participants_after_confirm(client):
    job_id = _make_job(client)
    client.post(
        f"/api/v1/pitch/jobs/{job_id}/participants",
        json={
            "confirmed_by": "测试用户",
            "participants": [
                {"speaker_id": "A", "real_name": "李总", "institution": "新川基金", "role": "GP执行"},
            ],
        },
    )
    r = client.get(f"/api/v1/pitch/jobs/{job_id}/participants")
    assert r.status_code == 200
    parts = r.json()
    assert len(parts) == 1
    assert parts[0]["speaker_id"] == "A"
    assert parts[0]["institution"] == "新川基金"
    assert parts[0]["role"] == "GP执行"


def test_confirm_idempotent_overwrite(client):
    """重复 POST 应覆盖旧数据，不出现重复行。"""
    job_id = _make_job(client)
    for name in ["旧名字", "新名字"]:
        client.post(
            f"/api/v1/pitch/jobs/{job_id}/participants",
            json={"participants": [{"speaker_id": "A", "real_name": name, "role": "其他"}]},
        )
    r = client.get(f"/api/v1/pitch/jobs/{job_id}/participants")
    parts = r.json()
    assert len(parts) == 1
    assert parts[0]["real_name"] == "新名字"


def test_confirm_404_on_unknown_job(client):
    r = client.post(
        "/api/v1/pitch/jobs/no-such/participants",
        json={"participants": [{"speaker_id": "A", "role": "其他"}]},
    )
    assert r.status_code == 404


def test_invalid_role_defaults_to_other(client):
    """非法角色值自动回退为「其他」。"""
    job_id = _make_job(client)
    client.post(
        f"/api/v1/pitch/jobs/{job_id}/participants",
        json={"participants": [{"speaker_id": "A", "role": "随便乱填"}]},
    )
    parts = client.get(f"/api/v1/pitch/jobs/{job_id}/participants").json()
    assert parts[0]["role"] == "其他"


def test_valid_roles_endpoint(client):
    r = client.get("/api/v1/pitch/participants/valid-roles")
    assert r.status_code == 200
    roles = r.json()
    assert "GP执行" in roles
    assert "LP投资方" in roles


# ── job list includes participants_confirmed ──────────────────────────────────

def test_job_list_includes_confirmed_flag(client):
    job_id = _make_job(client, "t-flag")
    # 未确认时应为 False
    r = client.get("/api/pitch/jobs", params={"tenant_id": "t-flag"})
    assert r.status_code == 200
    rows = r.json()
    row = next((x for x in rows if x["job_id"] == job_id), None)
    assert row is not None
    assert row["participants_confirmed"] is False

    # 确认后应为 True
    client.post(
        f"/api/v1/pitch/jobs/{job_id}/participants",
        json={"participants": [{"speaker_id": "A", "role": "其他"}]},
    )
    r2 = client.get("/api/pitch/jobs", params={"tenant_id": "t-flag"})
    row2 = next((x for x in r2.json() if x["job_id"] == job_id), None)
    assert row2["participants_confirmed"] is True
