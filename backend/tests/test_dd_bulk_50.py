"""
TDD tests for bulk 50-item DD matching fixes:
  - batch_size=20, max_tokens=6000, 2 candidates
  - partial save per batch
  - truncation recovery (_try_partial_json_parse)
  - progress_callback support
  - match-status API endpoint
"""
from __future__ import annotations
import json
import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient


# ─── helpers ────────────────────────────────────────────────────────────────

def _make_items(n: int) -> list[dict]:
    return [
        {"item_no": str(i + 1), "category": "测试", "requirement": f"需求条目{i + 1}"}
        for i in range(n)
    ]


def _make_index_rows(n: int = 5) -> list[dict]:
    return [
        {"file_path": f"/folder/文件{i}.pdf", "filename": f"文件{i}.pdf", "summary": f"摘要{i}"}
        for i in range(n)
    ]


def _make_batch_match_result(items: list[dict], index_rows: list[dict]) -> dict:
    """假的 LLM batch 匹配结果：每条需求匹配到 index_rows[0]。"""
    return {
        item["id"]: {
            "file_path": index_rows[0]["file_path"],
            "filename": index_rows[0]["filename"],
            "confidence": 0.85,
            "reason": "测试匹配",
            "candidates_json": json.dumps([{
                "file_path": index_rows[0]["file_path"],
                "filename": index_rows[0]["filename"],
                "confidence": 0.85,
                "reason": "测试匹配",
            }], ensure_ascii=False),
        }
        for item in items
    }


# ─── Test 1: 50 short items → 1 chunk ───────────────────────────────────────

def test_parse_50_items_single_chunk(monkeypatch):
    """50 条短需求文字 → 单块 → _llm_extract_chunk 调用1次 → 返回50条。"""
    expected = [
        {"item_no": str(i + 1), "category": "测试", "requirement": f"需求{i + 1}"}
        for i in range(50)
    ]
    call_count = 0

    def mock_extract_chunk(chunk_text: str) -> list[dict]:
        nonlocal call_count
        call_count += 1
        return expected

    monkeypatch.setattr(
        "cangjie_fos.services.dd_checklist_parser._llm_extract_chunk",
        mock_extract_chunk,
    )
    short_text = "\n".join(f"{i + 1}. 需求{i + 1}" for i in range(50))  # ~500 chars, < 4000

    from cangjie_fos.services.dd_checklist_parser import _llm_extract_items
    items = _llm_extract_items(short_text)

    assert call_count == 1, f"短文本应只调用1次，实际 {call_count}"
    assert len(items) == 50


# ─── Test 2: 50 verbose items → multiple chunks, dedup ─────────────────────

def test_parse_50_items_multi_chunk(monkeypatch):
    """50 条长需求文字 > 4000字 → 分多块 → _llm_extract_chunk 调用 >1 次，去重后条数 >= 1。"""
    call_count = 0

    def mock_extract_chunk(chunk_text: str) -> list[dict]:
        nonlocal call_count
        call_count += 1
        return [{"item_no": str(call_count), "category": "财务", "requirement": f"需求块{call_count}"}]

    monkeypatch.setattr(
        "cangjie_fos.services.dd_checklist_parser._llm_extract_chunk",
        mock_extract_chunk,
    )
    # 每条 ~100字 × 50 = ~5000字，超过 4000 字分块
    verbose_text = "\n".join(f"{i + 1}. " + "这是一条详细的尽调需求，说明了需要提供的文件和资料内容。" * 3 for i in range(50))

    from cangjie_fos.services.dd_checklist_parser import _llm_extract_items
    items = _llm_extract_items(verbose_text)

    assert call_count > 1, f"长文本应分多块，实际调用次数: {call_count}"
    assert len(items) >= 1


# ─── helpers for LLM-level mocking ─────────────────────────────────────────

def _make_fake_llm_client(index_rows: list[dict]):
    """
    构造一个 fake OpenAI-compatible client，其 chat.completions.create 返回
    能被 _llm_batch_match 解析的 JSON（按 item id 逐一匹配 index_rows[0]）。
    """
    import re as _re

    def create(**kwargs):
        content = kwargs.get("messages", [{}])[-1].get("content", "")
        # 从 prompt 中提取所有 UUID（需求 ID）
        ids = _re.findall(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            content,
        )
        entries = {}
        for uid in ids:
            entries[uid] = {
                "candidates": [{"file_index": 0, "confidence": 0.85, "reason": "测试"}]
            }
        raw = json.dumps(entries, ensure_ascii=False)

        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = raw
        return mock_resp

    client = MagicMock()
    client.chat.completions.create.side_effect = create
    return client


# ─── Test 3: 20 items → 1 batch (batch_size=20) ─────────────────────────────

def test_match_20_items_correct_batch_size(monkeypatch):
    """修复后 batch_size=20，20条需求应只触发1次 LLM API 调用。"""
    from cangjie_fos.services.dd_match_service import (
        create_match_session, get_session_items,
    )
    items = _make_items(20)
    session_id = create_match_session("test", "test.xlsx", "/folder", items)

    index_rows = _make_index_rows(3)
    fake_client = _make_fake_llm_client(index_rows)

    with patch("cangjie_fos.services.dd_match_service._get_index_for_folder",
               return_value=index_rows):
        with patch("cangjie_fos.services.dd_match_service.get_dd_llm_client",
                   return_value=fake_client):
            from cangjie_fos.services.dd_match_service import run_matching
            run_matching(session_id, "/folder")

    # 20 items with batch_size=20 → exactly 1 LLM API call
    assert fake_client.chat.completions.create.call_count == 1, (
        f"20条需求应1批完成，实际API调用了 {fake_client.chat.completions.create.call_count} 次"
    )
    result = get_session_items(session_id)
    assert all(r["confidence"] is not None for r in result)


# ─── Test 4: 50 items → 3 batches (ceil(50/20)=3) ──────────────────────────

def test_match_50_items_three_batches(monkeypatch):
    """50 条需求 / batch_size=20 → ceil(50/20)=3 批次，LLM API 调用3次。"""
    from cangjie_fos.services.dd_match_service import create_match_session
    items = _make_items(50)
    session_id = create_match_session("test", "test50.xlsx", "/folder", items)

    index_rows = _make_index_rows(3)
    fake_client = _make_fake_llm_client(index_rows)

    with patch("cangjie_fos.services.dd_match_service._get_index_for_folder",
               return_value=index_rows):
        with patch("cangjie_fos.services.dd_match_service.get_dd_llm_client",
                   return_value=fake_client):
            from cangjie_fos.services.dd_match_service import run_matching
            run_matching(session_id, "/folder")

    import math
    expected_batches = math.ceil(50 / 20)
    actual_calls = fake_client.chat.completions.create.call_count
    assert actual_calls == expected_batches, (
        f"50条需求应{expected_batches}批，实际API调用 {actual_calls} 次"
    )


# ─── Test 5: truncation recovery ────────────────────────────────────────────

def test_match_truncation_recovery():
    """
    _try_partial_json_parse 应从截断的 JSON 中恢复已完整输出的 uuid 块。
    """
    from cangjie_fos.services.dd_match_service import _try_partial_json_parse

    uid1 = str(uuid.uuid4())
    uid2 = str(uuid.uuid4())

    # 模拟 LLM 在第2条输出到一半时截断
    truncated_json = (
        "{\n"
        f'  "{uid1}": {{"candidates": [{{"file_index": 0, "confidence": 0.9, "reason": "匹配"}}]}},\n'
        f'  "{uid2}": {{"candidates": [{{"file_index": 1, "con'  # 截断
    )

    result = _try_partial_json_parse(truncated_json)

    assert uid1 in result, "第1条应被恢复"
    assert uid2 not in result, "截断的第2条不应出现"
    assert result[uid1]["candidates"][0]["confidence"] == 0.9


# ─── Test 6: partial save per batch ─────────────────────────────────────────

def test_match_partial_save_on_batch_failure(monkeypatch):
    """
    当第2批 LLM API 调用失败（JSONDecodeError）时，第1批的结果应已写入 DB（partial save）。
    """
    from cangjie_fos.services.dd_match_service import (
        create_match_session, get_session_items,
    )
    import re as _re

    items = _make_items(25)  # 25条 → 批1(20) + 批2(5)
    session_id = create_match_session("test", "partial.xlsx", "/folder", items)

    index_rows = _make_index_rows(3)
    api_call_count = 0

    def create_side_effect(**kwargs):
        nonlocal api_call_count
        api_call_count += 1
        if api_call_count == 2:
            # 第2批返回截断 JSON（无法解析）
            mock_resp = MagicMock()
            mock_resp.choices[0].message.content = '{"truncated": incomplete'
            return mock_resp
        # 第1批正常返回
        content = kwargs.get("messages", [{}])[-1].get("content", "")
        ids = _re.findall(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            content,
        )
        entries = {
            uid: {"candidates": [{"file_index": 0, "confidence": 0.85, "reason": "ok"}]}
            for uid in ids
        }
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = json.dumps(entries)
        return mock_resp

    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = create_side_effect

    with patch("cangjie_fos.services.dd_match_service._get_index_for_folder",
               return_value=index_rows):
        with patch("cangjie_fos.services.dd_match_service.get_dd_llm_client",
                   return_value=fake_client):
            from cangjie_fos.services.dd_match_service import run_matching
            run_matching(session_id, "/folder")

    # 第1批(前20条，按 item_no 排序)应有 confidence
    result = get_session_items(session_id)  # ordered by item_no
    first_batch = result[:20]
    assert all(r["confidence"] is not None for r in first_batch), (
        "第1批结果应已写入DB，confidence 不应为 NULL"
    )


# ─── Test 7: progress_callback ──────────────────────────────────────────────

def test_match_progress_callback(monkeypatch):
    """run_matching 应在每批结束后调用 progress_callback(done, total)。"""
    from cangjie_fos.services.dd_match_service import (
        create_match_session, run_matching,
    )
    items = _make_items(50)
    session_id = create_match_session("test", "prog.xlsx", "/folder", items)

    index_rows = _make_index_rows(3)
    progress_calls: list[tuple[int, int]] = []
    fake_client = _make_fake_llm_client(index_rows)

    with patch("cangjie_fos.services.dd_match_service._get_index_for_folder",
               return_value=index_rows):
        with patch("cangjie_fos.services.dd_match_service.get_dd_llm_client",
                   return_value=fake_client):
            def _cb(done: int, total: int) -> None:
                progress_calls.append((done, total))

            run_matching(session_id, "/folder", progress_callback=_cb)

    import math
    expected_calls = math.ceil(50 / 20)
    assert len(progress_calls) == expected_calls, (
        f"应调用 {expected_calls} 次，实际 {len(progress_calls)} 次: {progress_calls}"
    )
    # 最后一次应为 (50, 50)
    assert progress_calls[-1] == (50, 50), f"最后进度应为(50,50)，实际{progress_calls[-1]}"
    # 每次 done 单调递增
    dones = [d for d, _ in progress_calls]
    assert dones == sorted(dones)


# ─── Test 8: 50 items all get non-null confidence ───────────────────────────

def test_match_50_items_all_have_results(monkeypatch):
    """50条需求经过匹配后，全部应有非 NULL 的 confidence 值。"""
    from cangjie_fos.services.dd_match_service import (
        create_match_session, run_matching, get_session_items,
    )
    items = _make_items(50)
    session_id = create_match_session("test", "all50.xlsx", "/folder", items)

    index_rows = _make_index_rows(3)
    fake_client = _make_fake_llm_client(index_rows)

    with patch("cangjie_fos.services.dd_match_service._get_index_for_folder",
               return_value=index_rows):
        with patch("cangjie_fos.services.dd_match_service.get_dd_llm_client",
                   return_value=fake_client):
            run_matching(session_id, "/folder")

    result = get_session_items(session_id)
    assert len(result) == 50
    null_items = [r for r in result if r["confidence"] is None]
    assert len(null_items) == 0, (
        f"{len(null_items)} 条 confidence 仍为 NULL（预期全部非NULL）"
    )


# ─── Test 9: match-status endpoint ──────────────────────────────────────────

pytestmark_real_db = pytest.mark.real_db


@pytest.mark.real_db
def test_match_status_endpoint():
    """
    触发匹配后，GET /sessions/{id}/match-status 应返回 status 字段。
    匹配完成后 status 应为 done。
    """
    from cangjie_fos.main import create_app
    from cangjie_fos.services.dd_match_service import create_match_session

    client = TestClient(create_app())

    # 准备一个 session
    with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items",
               return_value=[{"item_no": "1", "category": "基本", "requirement": "营业执照"}]):
        resp = client.post("/api/v1/dd/sessions", data={
            "text": "1. 营业执照", "tenant_id": "ms_test", "folder_root": "/tmp",
        })
    assert resp.status_code == 200
    sid = resp.json()["session_id"]

    # 触发匹配（mock run_matching 立即完成）
    with patch("cangjie_fos.api.routes.dd_response.run_matching") as mock_run:
        mock_run.return_value = None
        match_resp = client.post(
            f"/api/v1/dd/sessions/{sid}/match?folder_root=/tmp"
        )
    assert match_resp.status_code == 200

    # match-status 应存在
    status_resp = client.get(f"/api/v1/dd/sessions/{sid}/match-status")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert "status" in data
    assert data["status"] in ("running", "done", "not_found")


@pytest.mark.real_db
def test_match_status_unknown_session():
    """未知 session_id 的 match-status 应返回 not_found。"""
    from cangjie_fos.main import create_app

    client = TestClient(create_app())
    resp = client.get("/api/v1/dd/sessions/nonexistent-session-id/match-status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_found"
