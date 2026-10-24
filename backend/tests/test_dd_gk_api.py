"""
TDD：尽调 gk 模式 API 端点 — F2（按问题导出）+ F4（问答草稿）。

- POST /api/v1/dd/sessions/{id}/export-by-question
- POST /api/v1/dd/qa/extract
- GET  /api/v1/dd/qa/draft
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def _seed_session(tmp_path):
    from cangjie_fos.services.dd_match_service import create_match_session
    from cangjie_fos.services.db_base import _connect

    f1 = tmp_path / "2024财报.txt"; f1.write_text("财报", encoding="utf-8")
    sid = create_match_session("gk", "c.xlsx", str(tmp_path), [
        {"item_no": "1", "category": "基本", "requirement": "近三年财务报表"},
    ])
    with _connect() as conn:
        conn.execute(
            "UPDATE dd_match_items SET matched_file_path = ?, matched_filename = ?, "
            "confidence = 0.9 WHERE session_id = ?",
            (str(f1), "2024财报.txt", sid),
        )
    return sid


def test_export_by_question_endpoint(client, tmp_path):
    """F2：按问题导出端点建立问题文件夹并落文件。"""
    sid = _seed_session(tmp_path)
    out = tmp_path / "导出"
    resp = client.post(f"/api/v1/dd/sessions/{sid}/export-by-question",
                       json={"output_dir": str(out)})
    assert resp.status_code == 200
    assert resp.json()["exported"] == 1
    folders = [p.name for p in out.iterdir() if p.is_dir()]
    assert any("财务报表" in f for f in folders)


def test_qa_extract_endpoint(client, tmp_path):
    """F4：扒取端点触发问答提取并落表。"""
    doc = tmp_path / "补充尽调资料.txt"
    doc.write_text("问：团队规模？答：50人。", encoding="utf-8")

    with patch("cangjie_fos.services.dd_qa_service._llm_extract_qa",
               return_value=[{"question": "团队规模？", "answer": "50人",
                              "confidence": 0.9}]):
        resp = client.post("/api/v1/dd/qa/extract",
                          json={"folder_root": str(tmp_path), "tenant_id": "gk"})
    assert resp.status_code == 200
    assert resp.json()["extracted"] == 1


def test_qa_draft_endpoint(client, tmp_path):
    """F4：草稿端点对命中历史问答返回带答案的草稿。"""
    from cangjie_fos.services.dd_qa_service import _persist_qa_pair

    _persist_qa_pair("gk", str(tmp_path), "补充.txt",
                     "公司团队规模有多大？", "核心团队50人", "", 0.9)

    resp = client.get("/api/v1/dd/qa/draft", params={
        "requirement": "请说明团队规模", "folder_root": str(tmp_path),
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is True
    assert "50人" in body["answer"]
