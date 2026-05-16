"""E2E 测试：尽调响应台 API（所有 LLM 调用 mock）。"""
from __future__ import annotations
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import create_app

pytestmark = [pytest.mark.real_db]

_MOCK_ITEMS = [
    {"item_no": "1", "category": "基本情况", "requirement": "验资报告"},
    {"item_no": "2", "category": "财务", "requirement": "审计报告"},
]


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


class TestIndexEndpoints:

    def test_start_scan_returns_scan_id(self, client, tmp_path):
        (tmp_path / "report.txt").write_text("财务报告", encoding="utf-8")
        with patch("cangjie_fos.services.dd_index_service._llm_summarize", return_value="财务报告"):
            resp = client.post("/api/v1/dd/index", json={
                "folder_path": str(tmp_path), "tenant_id": "test"
            })
        assert resp.status_code == 200
        assert "scan_id" in resp.json()

    def test_list_index_after_scan(self, client, tmp_path):
        (tmp_path / "audit.txt").write_text("2023年度审计报告", encoding="utf-8")
        with patch("cangjie_fos.services.dd_index_service._llm_summarize", return_value="审计报告"):
            from cangjie_fos.services.dd_index_service import scan_and_index_folder
            scan_and_index_folder(str(tmp_path), "test")

        resp = client.get("/api/v1/dd/index", params={"folder_root": str(tmp_path)})
        assert resp.status_code == 200
        files = resp.json()
        assert any(f["filename"] == "audit.txt" for f in files)


class TestSessionEndpoints:

    def test_create_session_from_text(self, client, tmp_path):
        with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items",
                   return_value=_MOCK_ITEMS):
            resp = client.post("/api/v1/dd/sessions", data={
                "text": "1. 验资报告\n2. 审计报告",
                "tenant_id": "test",
                "folder_root": str(tmp_path),
            })
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert data["count"] == 2

    def test_get_session_items(self, client, tmp_path):
        with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items",
                   return_value=_MOCK_ITEMS):
            create_resp = client.post("/api/v1/dd/sessions", data={
                "text": "dummy", "tenant_id": "test", "folder_root": str(tmp_path),
            })
        sid = create_resp.json()["session_id"]

        resp = client.get(f"/api/v1/dd/sessions/{sid}/items")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 2
        assert items[0]["requirement"] == "验资报告"

    def test_get_unknown_session_returns_404(self, client):
        resp = client.get("/api/v1/dd/sessions/nonexistent-id/items")
        assert resp.status_code == 404

    def test_update_item_user_confirmed(self, client, tmp_path):
        with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items",
                   return_value=_MOCK_ITEMS):
            create_resp = client.post("/api/v1/dd/sessions", data={
                "text": "dummy", "tenant_id": "test", "folder_root": str(tmp_path),
            })
        sid = create_resp.json()["session_id"]
        items = client.get(f"/api/v1/dd/sessions/{sid}/items").json()
        item_id = items[0]["id"]

        resp = client.patch(f"/api/v1/dd/sessions/{sid}/items/{item_id}",
                            json={"user_confirmed": True, "confidence": 0.95})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestExportEndpoint:

    def test_export_creates_files_and_gap_report(self, client, tmp_path):
        # 准备真实文件
        src = tmp_path / "验资报告.pdf"
        src.write_bytes(b"fake")

        with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items",
                   return_value=_MOCK_ITEMS):
            create_resp = client.post("/api/v1/dd/sessions", data={
                "text": "dummy", "tenant_id": "test", "folder_root": str(tmp_path),
            })
        sid = create_resp.json()["session_id"]
        items = client.get(f"/api/v1/dd/sessions/{sid}/items").json()

        # item 1：手动设置匹配到真实文件
        client.patch(f"/api/v1/dd/sessions/{sid}/items/{items[0]['id']}", json={
            "matched_file_path": str(src),
            "matched_filename": "验资报告.pdf",
            "confidence": 0.95,
        })
        # item 2：标记缺失
        client.patch(f"/api/v1/dd/sessions/{sid}/items/{items[1]['id']}", json={"user_skipped": True})

        out_dir = str(tmp_path / "output")
        resp = client.post(f"/api/v1/dd/sessions/{sid}/export", json={"output_dir": out_dir})
        assert resp.status_code == 200
        result = resp.json()
        assert result["exported"] == 1
        assert result["missing"] == 1

        # 确认文件被复制
        assert list(Path(out_dir).rglob("*验资报告.pdf"))
        # 确认缺失清单
        gap = Path(out_dir) / "缺失清单.txt"
        assert gap.exists()
        assert "审计报告" in gap.read_text(encoding="utf-8")


_MOCK_ITEMS_2 = [
    {"item_no": "1", "category": "基本情况", "requirement": "验资报告"},
    {"item_no": "2", "category": "基本情况", "requirement": "营业执照"},
]

_MOCK_ITEMS_3 = [
    {"item_no": "1", "category": "基本情况", "requirement": "营业执照"},
]


class TestDDSessionList:
    """Session 历史列表 API 测试。"""

    def test_list_sessions_returns_recent(self, client):
        """GET /api/v1/dd/sessions 应返回已创建的 session。"""
        with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items",
                   return_value=_MOCK_ITEMS_2):
            resp = client.post(
                "/api/v1/dd/sessions",
                data={"tenant_id": "t1", "folder_root": "/tmp", "text": "1. 验资报告\n2. 营业执照"},
                files={},
            )
        assert resp.status_code == 200

        list_resp = client.get("/api/v1/dd/sessions?tenant_id=t1")
        assert list_resp.status_code == 200
        sessions = list_resp.json()
        assert isinstance(sessions, list)
        assert len(sessions) >= 1
        assert "session_id" in sessions[0]
        assert "item_count" in sessions[0]

    def test_bulk_confirm_high_confidence_items(self, client):
        """POST bulk-confirm 应将置信度 >= 阈值的项设为已确认。"""
        with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items",
                   return_value=_MOCK_ITEMS_2):
            resp = client.post(
                "/api/v1/dd/sessions",
                data={"tenant_id": "t2", "folder_root": "/tmp", "text": "1. 审计报告\n2. 营业执照"},
                files={},
            )
        session_id = resp.json()["session_id"]

        from cangjie_fos.services.db_base import _connect
        with _connect() as conn:
            items = conn.execute(
                "SELECT id FROM dd_match_items WHERE session_id = ?",
                (session_id,)
            ).fetchall()
            for row in items:
                conn.execute(
                    "UPDATE dd_match_items SET confidence = 0.9 WHERE id = ?",
                    (row[0],)
                )

        confirm_resp = client.post(
            f"/api/v1/dd/sessions/{session_id}/items/bulk-confirm?min_confidence=0.8"
        )
        assert confirm_resp.status_code == 200
        data = confirm_resp.json()
        assert data["ok"] is True
        assert data["confirmed_count"] == 2

    def test_create_session_with_institution_name_updates_stage(self, client, monkeypatch):
        """创建 session 时若指定机构名，且该机构存在，应自动更新其 Pipeline 阶段为 dd。"""
        from cangjie_fos.services.institution_store import create_institution
        from cangjie_fos.schemas.institution import InstitutionProfileCreate, PipelineStage, InstitutionThermal
        create_institution(InstitutionProfileCreate(
            tenant_id="t3",
            name="高瓴资本",
            stage=PipelineStage.PITCHED,
            thermal=InstitutionThermal.WARM,
        ))

        with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items",
                   return_value=_MOCK_ITEMS_3):
            resp = client.post(
                "/api/v1/dd/sessions",
                data={
                    "tenant_id": "t3",
                    "folder_root": "/tmp",
                    "text": "1. 营业执照",
                    "institution_name": "高瓴资本",
                },
                files={},
            )
        assert resp.status_code == 200

        from cangjie_fos.services.institution_store import list_institutions
        institutions = list_institutions(tenant_id="t3")
        gaoling = next((i for i in institutions if i.name == "高瓴资本"), None)
        assert gaoling is not None
        assert gaoling.stage == PipelineStage.DD
