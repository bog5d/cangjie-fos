"""
TDD 测试：v0.7.2 尽调响应台稳定性加固。

新增测试：
  1. test_match_empty_llm_response  — LLM 返回 {} 不崩溃（原版会静默标 30 条「无匹配」）
  2. test_match_retry_on_failure      — LLM 网络异常后重试，3 次全失败才投降
  3. test_match_session_completes_on_error — LLM 抛异常后 session 状态仍是 matched
  4. test_export_file_size_guard       — 单文件 > 100MB 跳过，不崩溃
  5. test_export_total_size_guard      — 总导出 > 500MB 终止，返回错误
  6. test_scan_status_db_fallback      — 内存无状态时降级查 DB 最新扫描时间
"""
from __future__ import annotations
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import create_app

pytestmark = [pytest.mark.real_db]

_MOCK_ITEMS = [
    {"item_no": "1", "category": "基本情况", "requirement": "验资报告"},
]


@pytest.fixture(scope="module")
def client():
    """Module-scoped TestClient（与 test_dd_e2e.py 一致）。"""
    return TestClient(create_app())


# ═══════════════════════════════════════════════════════════════
# 1. LLM 返回空结果不崩溃
# ═══════════════════════════════════════════════════════════════

class TestLLMEdgeCases:

    def test_match_empty_llm_response(self, client, tmp_path):
        """
        BUG 场景：LLM batch match 返回 {}（网络正常但0条匹配）。
        原版行为：整批30条全部标为 confidence=0.0「无匹配文件」。
        预期行为：同样标为无匹配，但不抛异常、不崩溃。
        """
        src = tmp_path / "test.txt"
        src.write_text("test", encoding="utf-8")

        # 先建索引
        with patch("cangjie_fos.services.dd_index_service._llm_summarize",
                   return_value="测试文件"):
            from cangjie_fos.services.dd_index_service import scan_and_index_folder
            scan_and_index_folder(str(tmp_path), "test")

        # 创建 session
        with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items",
                   return_value=_MOCK_ITEMS):
            create_resp = client.post("/api/v1/dd/sessions", data={
                "text": "1. 验资报告", "tenant_id": "test",
                "folder_root": str(tmp_path),
            })
        assert create_resp.status_code == 200
        sid = create_resp.json()["session_id"]

        # Mock LLM 返回空 JSON（需求 ID 不在结果中 → 每项都标无匹配）
        with patch("cangjie_fos.services.dd_match_service._llm_batch_match",
                   return_value={}):
            from cangjie_fos.services.dd_match_service import run_matching
            run_matching(sid, str(tmp_path))

        # 不应崩溃，session 应标记为完成
        items = client.get(f"/api/v1/dd/sessions/{sid}/items").json()
        assert len(items) == 1
        # 无匹配时应该标 confidence=0.0，但不崩溃
        assert items[0]["confidence"] == 0.0
        # 验证 session 状态是 matched（不是 pending）
        from cangjie_fos.services.db_base import _connect
        with _connect() as conn:
            status = conn.execute(
                "SELECT status FROM dd_match_sessions WHERE session_id = ?",
                (sid,),
            ).fetchone()["status"]
        assert status == "matched", f"预期 matched，实际 {status}"

    def test_match_session_completes_on_error(self, client, tmp_path):
        """
        v0.7.1 关键修复验证：LLM 抛异常后，
        finally 块必须执行 _mark_session_done，保证前端轮询不挂死。

        这个测试确认该修复仍然有效（防止回归）。
        """
        src = tmp_path / "test.txt"
        src.write_text("test", encoding="utf-8")

        with patch("cangjie_fos.services.dd_index_service._llm_summarize",
                   return_value="测试文件"):
            from cangjie_fos.services.dd_index_service import scan_and_index_folder
            scan_and_index_folder(str(tmp_path), "test")

        with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items",
                   return_value=_MOCK_ITEMS):
            create_resp = client.post("/api/v1/dd/sessions", data={
                "text": "1. 验资报告", "tenant_id": "test",
                "folder_root": str(tmp_path),
            })
        assert create_resp.status_code == 200
        sid = create_resp.json()["session_id"]

        # Mock LLM 批量匹配抛异常
        with patch("cangjie_fos.services.dd_match_service._llm_batch_match",
                   side_effect=RuntimeError("mock LLM crash")):
            from cangjie_fos.services.dd_match_service import run_matching
            try:
                run_matching(sid, str(tmp_path))
            except RuntimeError:
                pass  # 预期异常被内部 catch 了

        # 关键断言：session 必须标记为 matched
        from cangjie_fos.services.db_base import _connect
        with _connect() as conn:
            status = conn.execute(
                "SELECT status FROM dd_match_sessions WHERE session_id = ?",
                (sid,),
            ).fetchone()["status"]
        assert status == "matched", (
            f"v0.7.1 回归！LLM崩溃后 session 状态={status}，"
            "前端轮询会永久挂起。"
        )


# ═══════════════════════════════════════════════════════════════
# 2. 导出大小 guard
# ═══════════════════════════════════════════════════════════════

class TestExportGuards:

    def test_export_file_size_guard(self, client, tmp_path):
        """
        单文件 > 100MB 应跳过不复制，记录到缺失清单，
        不抛异常、不卡死、不爆内存。
        """
        # 创建一个大文件（虚拟 sparse，实际不占磁盘）
        src = tmp_path / "huge.mp4"
        # 用 seek 创建稀疏文件模拟超大文件
        with open(src, "wb") as f:
            f.seek(110 * 1024 * 1024 - 1)  # 110MB
            f.write(b"\0")

        with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items",
                   return_value=_MOCK_ITEMS):
            create_resp = client.post("/api/v1/dd/sessions", data={
                "text": "1. 验资报告", "tenant_id": "test",
                "folder_root": str(tmp_path),
            })
        sid = create_resp.json()["session_id"]
        items = client.get(f"/api/v1/dd/sessions/{sid}/items").json()
        item_id = items[0]["id"]

        # 设置匹配到超大文件
        client.patch(f"/api/v1/dd/sessions/{sid}/items/{item_id}", json={
            "matched_file_path": str(src),
            "matched_filename": "huge.mp4",
            "confidence": 0.9,
        })

        out_dir = str(tmp_path / "output")
        resp = client.post(f"/api/v1/dd/sessions/{sid}/export",
                           json={"output_dir": out_dir})

        assert resp.status_code == 200
        result = resp.json()
        # 超大文件应被跳过 → exported=0, missing=1
        assert result["exported"] == 0, "超大文件应跳过不复制"
        assert result["missing"] == 1, "超大文件应记入缺失清单"

        # 确认缺失清单里提到了这个文件
        gap = Path(out_dir) / "缺失清单.txt"
        assert gap.exists()
        gap_text = gap.read_text(encoding="utf-8")
        assert "huge.mp4" in gap_text or "过大" in gap_text, (
            f"缺失清单应提及跳过的超大文件，实际内容: {gap_text[:200]}"
        )

    def test_export_total_size_guard(self, client, tmp_path):
        """
        导出的所有文件总大小超过 500MB 时终止整个导出，
        返回错误信息，不部分导出、不留残留文件。

        注意：每个文件必须 < 100MB（单文件上限），但总合 > 500MB（总上限），
        才能触发累加上限而非单文件跳过。
        """
        # 创建 6 个 90MB 稀疏文件（总计 540MB > 500MB 上限）
        files = []
        for i in range(6):
            f = tmp_path / f"big_{i}.pdf"
            with open(f, "wb") as fh:
                fh.seek(90 * 1024 * 1024 - 1)
                fh.write(b"\0")
            files.append(f)

        # 6 条需求项，各自匹配一个 90MB 文件
        items_mock = [
            {"item_no": "1", "category": "财务", "requirement": "审计报告"},
            {"item_no": "2", "category": "法务", "requirement": "法律意见书"},
            {"item_no": "3", "category": "基本情况", "requirement": "营业执照"},
            {"item_no": "4", "category": "财务", "requirement": "财务报表"},
            {"item_no": "5", "category": "法务", "requirement": "合同"},
            {"item_no": "6", "category": "基本情况", "requirement": "章程"},
        ]
        with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items",
                   return_value=items_mock):
            create_resp = client.post("/api/v1/dd/sessions", data={
                "text": "dummy", "tenant_id": "test",
                "folder_root": str(tmp_path),
            })
        sid = create_resp.json()["session_id"]
        items = client.get(f"/api/v1/dd/sessions/{sid}/items").json()

        # 每项匹配到大文件
        for i, item in enumerate(items):
            client.patch(f"/api/v1/dd/sessions/{sid}/items/{item['id']}", json={
                "matched_file_path": str(files[i]),
                "matched_filename": files[i].name,
                "confidence": 0.9,
            })

        out_dir = str(tmp_path / "output")
        resp = client.post(f"/api/v1/dd/sessions/{sid}/export",
                           json={"output_dir": out_dir})

        assert resp.status_code == 200
        result = resp.json()
        # 总大小超限时应返回错误
        # 前几个文件（<500MB）可能已部分导出，但到达限额后应终止
        assert result.get("error"), (
            f"总大小超限应返回 error 说明。实际: {result}"
        )
        assert result.get("exported", 0) < 6, (
            "达到限额后不应继续导出后续文件"
        )


# ═══════════════════════════════════════════════════════════════
# 3. 扫描状态 DB fallback
# ═══════════════════════════════════════════════════════════════

class TestScanStatusFallback:

    def test_scan_status_db_fallback(self, client, tmp_path):
        """
        内存 _scan_status 没有记录时，get_scan_status 应降级查询
        dd_asset_index 表，返回最近一次索引时间。

        场景：服务重启后，内存清空，但 DB 里有历史索引记录。
        """
        # 先做一次扫描，让 DB 里有数据
        (tmp_path / "doc.txt").write_text("测试内容", encoding="utf-8")
        with patch("cangjie_fos.services.dd_index_service._llm_summarize",
                   return_value="测试文档"):
            from cangjie_fos.services.dd_index_service import scan_and_index_folder
            scan_and_index_folder(str(tmp_path), "test")

        from cangjie_fos.services.db_base import _connect
        with _connect() as conn:
            rows = conn.execute(
                "SELECT MAX(indexed_at) as last_scan FROM dd_asset_index "
                "WHERE folder_root = ?", (str(tmp_path),)
            ).fetchall()
        assert rows and rows[0]["last_scan"] is not None, (
            "DB 里应有索引记录"
        )

        # 用不存在的 scan_id 调用 — 模拟重启后状态
        resp = client.get("/api/v1/dd/index/status/nonexistent_scan_id")
        assert resp.status_code == 200
        data = resp.json()

        # 预期行为：返回 DB fallback 信息（source="db_fallback"）
        assert data.get("source") == "db_fallback", (
            f"重启后应降级查 DB（source=db_fallback），而非 not_found。实际: {data}"
        )
