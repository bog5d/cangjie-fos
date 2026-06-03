"""
TDD：尽调 gk 模式 加密文件密码（UI 收集 + 原样附带，不解密）。

- 扫描结果带 institution_count（供前端布局徽章）。
- session items 富化 is_encrypted / unlock_password（join dd_asset_index）。
- 设置密码端点：POST /api/v1/dd/index/password。
- 导出时把加密文件的密码写入「加密文件密码.txt」附带。
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


# ════════════════════════════════════════════════════════════════════
# 扫描结果带机构数量（布局徽章用）
# ════════════════════════════════════════════════════════════════════

def test_scan_result_reports_institution_count(tmp_path):
    from cangjie_fos.services.dd_index_service import scan_and_index_folder

    for inst in ["瑞源正方", "鼎晖投资", "红杉资本"]:
        d = tmp_path / inst
        d.mkdir()
        (d / f"{inst}.txt").write_text("x", encoding="utf-8")

    with patch("cangjie_fos.services.dd_index_service._llm_summarize",
               return_value="摘要"):
        result = scan_and_index_folder(str(tmp_path), "gk")

    assert result["folder_layout"] == "per_institution"
    assert result["institution_count"] == 3


def test_scan_flat_institution_count_zero(tmp_path):
    from cangjie_fos.services.dd_index_service import scan_and_index_folder

    (tmp_path / "财报.txt").write_text("x", encoding="utf-8")
    with patch("cangjie_fos.services.dd_index_service._llm_summarize",
               return_value="摘要"):
        result = scan_and_index_folder(str(tmp_path), "gk")
    assert result["folder_layout"] == "flat"
    assert result["institution_count"] == 0


# ════════════════════════════════════════════════════════════════════
# session items 富化 is_encrypted / unlock_password
# ════════════════════════════════════════════════════════════════════

def _index_encrypted_file(tmp_path) -> Path:
    """造一个加密文件并入索引，返回路径。"""
    from cangjie_fos.services.dd_index_service import scan_and_index_folder
    enc = tmp_path / "加密财报.xlsx"
    enc.write_bytes(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1encrypted")
    with patch("cangjie_fos.services.dd_index_service._llm_summarize",
               return_value="财报"):
        scan_and_index_folder(str(tmp_path), "gk")
    return enc


def test_items_enriched_with_is_encrypted(client, tmp_path):
    from cangjie_fos.services.dd_match_service import create_match_session
    from cangjie_fos.services.db_base import _connect

    enc = _index_encrypted_file(tmp_path)
    sid = create_match_session("gk", "c.xlsx", str(tmp_path), [
        {"item_no": "1", "category": "财务", "requirement": "财报"},
    ])
    with _connect() as conn:
        conn.execute(
            "UPDATE dd_match_items SET matched_file_path = ?, matched_filename = ?, "
            "confidence = 0.9 WHERE session_id = ?",
            (str(enc), "加密财报.xlsx", sid),
        )

    resp = client.get(f"/api/v1/dd/sessions/{sid}/items")
    assert resp.status_code == 200
    item = resp.json()[0]
    assert item["is_encrypted"] == 1


def test_set_password_endpoint_and_enrichment(client, tmp_path):
    from cangjie_fos.services.dd_match_service import create_match_session
    from cangjie_fos.services.db_base import _connect

    enc = _index_encrypted_file(tmp_path)
    sid = create_match_session("gk", "c.xlsx", str(tmp_path), [
        {"item_no": "1", "category": "财务", "requirement": "财报"},
    ])
    with _connect() as conn:
        conn.execute(
            "UPDATE dd_match_items SET matched_file_path = ?, matched_filename = ?, "
            "confidence = 0.9 WHERE session_id = ?",
            (str(enc), "加密财报.xlsx", sid),
        )

    # 设置密码
    resp = client.post("/api/v1/dd/index/password",
                       json={"file_path": str(enc), "password": "secret123"})
    assert resp.status_code == 200

    # items 富化里带出密码
    item = client.get(f"/api/v1/dd/sessions/{sid}/items").json()[0]
    assert item["unlock_password"] == "secret123"


# ════════════════════════════════════════════════════════════════════
# 导出时附带加密文件密码清单
# ════════════════════════════════════════════════════════════════════

def test_export_writes_password_note(tmp_path):
    from cangjie_fos.services.dd_match_service import create_match_session
    from cangjie_fos.services.dd_export_service import export_by_question
    from cangjie_fos.services.db_base import _connect
    from cangjie_fos.services.dd_index_service import scan_and_index_folder

    enc = tmp_path / "加密财报.xlsx"
    enc.write_bytes(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1encrypted")
    with patch("cangjie_fos.services.dd_index_service._llm_summarize",
               return_value="财报"):
        scan_and_index_folder(str(tmp_path), "gk")
    with _connect() as conn:
        conn.execute(
            "UPDATE dd_asset_index SET unlock_password = ? WHERE file_path = ?",
            ("secret123", str(enc)),
        )

    sid = create_match_session("gk", "c.xlsx", str(tmp_path), [
        {"item_no": "1", "category": "财务", "requirement": "财报"},
    ])
    with _connect() as conn:
        conn.execute(
            "UPDATE dd_match_items SET matched_file_path = ?, matched_filename = ?, "
            "confidence = 0.9 WHERE session_id = ?",
            (str(enc), "加密财报.xlsx", sid),
        )

    out = tmp_path / "导出"
    export_by_question(sid, str(out))

    note = out / "加密文件密码.txt"
    assert note.exists(), "应生成加密文件密码清单"
    body = note.read_text(encoding="utf-8")
    assert "加密财报.xlsx" in body
    assert "secret123" in body
