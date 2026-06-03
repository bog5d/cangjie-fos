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

    def test_update_item_extra_files_json(self, client, tmp_path):
        """F2 多文件：PATCH extra_files_json 应持久化，items 读回一致。"""
        import json
        with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items",
                   return_value=_MOCK_ITEMS):
            create_resp = client.post("/api/v1/dd/sessions", data={
                "text": "dummy", "tenant_id": "test", "folder_root": str(tmp_path),
            })
        sid = create_resp.json()["session_id"]
        item_id = client.get(f"/api/v1/dd/sessions/{sid}/items").json()[0]["id"]

        extra = json.dumps([{"file_path": "/a/2022.pdf", "filename": "2022.pdf"}])
        resp = client.patch(f"/api/v1/dd/sessions/{sid}/items/{item_id}",
                            json={"extra_files_json": extra})
        assert resp.status_code == 200

        reread = client.get(f"/api/v1/dd/sessions/{sid}/items").json()
        target = next(i for i in reread if i["id"] == item_id)
        assert json.loads(target["extra_files_json"])[0]["filename"] == "2022.pdf"


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


_MOCK_ITEMS_GH = [
    {"item_no": "1", "category": "基本情况", "requirement": "营业执照"},
]


class TestDDGitHubSync:
    """导出后触发 GitHub 同步。"""

    def test_export_triggers_github_push(self, client, tmp_path, monkeypatch):
        """export 成功后应调用 push_dd_session。"""
        push_calls: list[str] = []

        def mock_push(session_id: str) -> bool:
            push_calls.append(session_id)
            return True

        monkeypatch.setattr(
            "cangjie_fos.api.routes.dd_response.push_dd_session",
            mock_push,
        )

        with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items",
                   return_value=_MOCK_ITEMS_GH):
            resp = client.post(
                "/api/v1/dd/sessions",
                data={"tenant_id": "gh_test", "folder_root": "/tmp", "text": "1. 营业执照"},
                files={},
            )
        session_id = resp.json()["session_id"]

        export_resp = client.post(
            f"/api/v1/dd/sessions/{session_id}/export",
            json={"output_dir": str(tmp_path)},
        )
        assert export_resp.status_code == 200
        # BackgroundTask 在 TestClient 中同步执行
        assert session_id in push_calls


class TestFlywheel:
    """Step 1 验证：DD 确认写入 match_outcomes 学习飞轮。"""

    def test_bulk_confirm_writes_match_outcomes(self, client, tmp_path):
        """bulk-confirm 后 match_outcomes 表应有对应记录。"""
        src = tmp_path / "验资报告.pdf"
        src.write_bytes(b"fake")

        with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items",
                   return_value=_MOCK_ITEMS):
            resp = client.post("/api/v1/dd/sessions", data={
                "text": "dummy", "tenant_id": "fw_test", "folder_root": str(tmp_path),
                "institution_name": "飞轮测试机构",
            })
        sid = resp.json()["session_id"]
        items = client.get(f"/api/v1/dd/sessions/{sid}/items").json()

        # 设置文件路径 + 高置信度
        from cangjie_fos.services.db_base import _connect
        with _connect() as conn:
            conn.execute(
                "UPDATE dd_match_items SET matched_file_path = ?, matched_filename = ?, confidence = 0.95 WHERE id = ?",
                (str(src), "验资报告.pdf", items[0]["id"]),
            )

        confirm_resp = client.post(
            f"/api/v1/dd/sessions/{sid}/items/bulk-confirm?min_confidence=0.8"
        )
        assert confirm_resp.status_code == 200

        # BackgroundTask 在 TestClient 中同步执行，检查 match_outcomes 写入
        with _connect() as conn:
            rows = conn.execute(
                "SELECT was_selected FROM match_outcomes WHERE session_id = ?", (sid,)
            ).fetchall()
        assert len(rows) >= 1
        assert any(r[0] == 1 for r in rows)

    def test_individual_confirm_writes_match_outcomes(self, client, tmp_path):
        """PATCH user_confirmed=True 后 match_outcomes 应有记录。"""
        src = tmp_path / "审计报告.pdf"
        src.write_bytes(b"fake")

        with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items",
                   return_value=[{"item_no": "1", "category": "财务", "requirement": "审计报告"}]):
            resp = client.post("/api/v1/dd/sessions", data={
                "text": "dummy", "tenant_id": "fw2", "folder_root": str(tmp_path),
                "institution_name": "单项确认机构",
            })
        sid = resp.json()["session_id"]
        items = client.get(f"/api/v1/dd/sessions/{sid}/items").json()
        item_id = items[0]["id"]

        from cangjie_fos.services.db_base import _connect
        with _connect() as conn:
            conn.execute(
                "UPDATE dd_match_items SET matched_file_path = ?, matched_filename = ? WHERE id = ?",
                (str(src), "审计报告.pdf", item_id),
            )

        resp = client.patch(f"/api/v1/dd/sessions/{sid}/items/{item_id}",
                            json={"user_confirmed": True})
        assert resp.status_code == 200

        with _connect() as conn:
            row = conn.execute(
                "SELECT institution FROM match_outcomes WHERE session_id = ?", (sid,)
            ).fetchone()
        assert row is not None
        assert row[0] == "单项确认机构"


class TestDDScanSyncToAssets:
    """Step 3 验证：DD 扫描同步写入 assets 共享表。"""

    def test_scan_writes_to_assets_table(self, client, tmp_path):
        """扫描完成后 assets 表中应能查到被扫描的文件。"""
        (tmp_path / "营业执照.txt").write_text("营业执照原件", encoding="utf-8")
        (tmp_path / "财务报告.txt").write_text("2023年财务报告", encoding="utf-8")

        with patch("cangjie_fos.services.dd_index_service._llm_summarize", return_value="测试摘要"):
            from cangjie_fos.services.dd_index_service import scan_and_index_folder
            result = scan_and_index_folder(str(tmp_path), "test_sync")

        assert result["indexed"] == 2

        from cangjie_fos.services.db_base import _connect
        with _connect() as conn:
            rows = conn.execute(
                "SELECT filename, summary FROM assets WHERE scan_dir = ?", (str(tmp_path),)
            ).fetchall()
        filenames = {r[0] for r in rows}
        assert "营业执照.txt" in filenames
        assert "财务报告.txt" in filenames
        # 摘要应被写入
        assert any(r[1] == "测试摘要" for r in rows)

    def test_scan_upserts_existing_asset(self, client, tmp_path):
        """重复扫描同一文件不应创建重复记录（upsert 幂等）。"""
        f = tmp_path / "合同.txt"
        f.write_text("合同正文", encoding="utf-8")

        with patch("cangjie_fos.services.dd_index_service._llm_summarize", return_value="合同摘要"):
            from cangjie_fos.services.dd_index_service import scan_and_index_folder
            scan_and_index_folder(str(tmp_path), "t_upsert")
            scan_and_index_folder(str(tmp_path), "t_upsert")

        from cangjie_fos.services.db_base import _connect
        with _connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM assets WHERE filename = '合同.txt' AND scan_dir = ?",
                (str(tmp_path),),
            ).fetchone()[0]
        assert count == 1  # 不应重复


_TEMPLATE_TEXT = """一、基本信息
1、项目名称：
公司总资产人民币【 】万元，净资产人民币【 】万元。
三、核心能力分析（不少于500字）
"""

_PI_ITEMS = [
    {"item_no": "1", "category": "一、基本信息", "requirement": "项目名称", "field_kind": "field"},
    {"item_no": "2", "category": "一、基本信息",
     "requirement": "公司总资产人民币【 】万元，净资产人民币【 】万元。（第1/2个空格）",
     "field_kind": "blank"},
    {"item_no": "3", "category": "一、基本信息",
     "requirement": "公司总资产人民币【 】万元，净资产人民币【 】万元。（第2/2个空格）",
     "field_kind": "blank"},
    {"item_no": "4", "category": "三、核心能力分析（不少于500字）",
     "requirement": "三、核心能力分析（不少于500字）",
     "field_kind": "narrative"},
]


class TestPostInvestmentScenario:
    """投后场景：create_session 支持 scenario=post_investment，可填充并导出初稿。"""

    def test_create_pi_session_from_text(self, client, tmp_path):
        """scenario=post_investment 应解析模板待填项，不走 dd_checklist_parser。"""
        resp = client.post("/api/v1/dd/sessions", data={
            "text": _TEMPLATE_TEXT,
            "tenant_id": "pi_test",
            "folder_root": str(tmp_path),
            "scenario": "post_investment",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["scenario"] == "post_investment"
        assert data["count"] >= 2  # 至少有空格项

    def test_pi_session_has_field_kind(self, client, tmp_path):
        """投后 session 的 items 应有 field_kind 字段。"""
        resp = client.post("/api/v1/dd/sessions", data={
            "text": _TEMPLATE_TEXT,
            "tenant_id": "pi_fk",
            "folder_root": str(tmp_path),
            "scenario": "post_investment",
        })
        sid = resp.json()["session_id"]
        items = client.get(f"/api/v1/dd/sessions/{sid}/items").json()
        assert any(i.get("field_kind") for i in items)

    def test_pi_session_in_list_with_scenario(self, client, tmp_path):
        """list sessions 应包含 scenario 字段。"""
        client.post("/api/v1/dd/sessions", data={
            "text": _TEMPLATE_TEXT,
            "tenant_id": "pi_list",
            "folder_root": str(tmp_path),
            "scenario": "post_investment",
        })
        sessions = client.get("/api/v1/dd/sessions?tenant_id=pi_list").json()
        assert any(s.get("scenario") == "post_investment" for s in sessions)

    def test_export_report_fills_blanks(self, client, tmp_path):
        """export-report 应用 draft_answer 填充模板，生成初稿文件。"""
        resp = client.post("/api/v1/dd/sessions", data={
            "text": _TEMPLATE_TEXT,
            "tenant_id": "pi_exp",
            "folder_root": str(tmp_path),
            "scenario": "post_investment",
        })
        sid = resp.json()["session_id"]

        # 手动写入 draft_answer 模拟填充结果
        from cangjie_fos.services.db_base import _connect
        with _connect() as conn:
            blank_items = conn.execute(
                "SELECT id FROM dd_match_items WHERE session_id = ? AND field_kind = 'blank'",
                (sid,),
            ).fetchall()
            for i, row in enumerate(blank_items):
                conn.execute(
                    "UPDATE dd_match_items SET draft_answer = ? WHERE id = ?",
                    (f"测试值{i + 1}", row[0]),
                )

        output_file = str(tmp_path / "季报初稿.txt")
        resp2 = client.post(f"/api/v1/dd/sessions/{sid}/export-report",
                            json={"output_path": output_file})
        assert resp2.status_code == 200
        result = resp2.json()
        assert result["ok"] is True
        assert result["filled"] >= 1
        assert (tmp_path / "季报初稿.txt").exists()

        content = (tmp_path / "季报初稿.txt").read_text(encoding="utf-8")
        assert "测试值1" in content

    def test_draft_fill_runs_after_matching(self, client, tmp_path):
        """投后场景触发 match 后，fill service 自动运行（mock LLM）。"""
        # 创建索引文件
        (tmp_path / "财务报告.txt").write_text("总资产5000万元，净资产3000万元", encoding="utf-8")
        with patch("cangjie_fos.services.dd_index_service._llm_summarize",
                   return_value="总资产5000万元，净资产3000万元"):
            from cangjie_fos.services.dd_index_service import scan_and_index_folder
            scan_and_index_folder(str(tmp_path), "pi_fill")

        resp = client.post("/api/v1/dd/sessions", data={
            "text": _TEMPLATE_TEXT,
            "tenant_id": "pi_fill",
            "folder_root": str(tmp_path),
            "scenario": "post_investment",
        })
        sid = resp.json()["session_id"]

        fill_calls: list = []

        def mock_fill(session_id: str) -> None:
            fill_calls.append(session_id)

        with patch("cangjie_fos.api.routes.dd_response.run_draft_fill", side_effect=mock_fill), \
             patch("cangjie_fos.services.dd_match_service._llm_batch_match", return_value={}):
            client.post(
                f"/api/v1/dd/sessions/{sid}/match?folder_root={str(tmp_path)}"
            )

        assert sid in fill_calls
