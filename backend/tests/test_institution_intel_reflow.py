"""v1.10.0 数据回流：尽调缺口 + 路演细分情报 → 机构情报侧表 → 机构简报。

覆盖：
- merge_institution_intel 按子键合并、幂等、不互相覆盖
- get_institution_intel_by_name 读取
- 尽调台确认后 DD 缺口回流到 institution_intel
- 路演分析后 key_questions/interest_signals 回流
- /briefing 端点合入侧表情报
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import app as global_app
from cangjie_fos.services.institution_store import (
    get_institution_intel_by_name,
    merge_institution_intel,
)


@pytest.fixture(autouse=True)
def _isolate_institutions(tmp_path, monkeypatch):
    """institutions.sqlite 不在全局 autouse 隔离范围内，这里单独重定向到临时库。"""
    monkeypatch.setattr(
        "cangjie_fos.services.institution_store._db_path",
        lambda: str(tmp_path / "test_inst.sqlite"),
    )


# ─── 1. 侧表合并语义 ──────────────────────────────────────────────────────────

def test_merge_intel_creates_and_reads():
    merge_institution_intel(tenant_id="t1", name="测试机构A", patch={"dd": {"gaps": ["审计报告"]}})
    notes = get_institution_intel_by_name("测试机构A")
    assert notes["dd"]["gaps"] == ["审计报告"]


def test_merge_intel_subkeys_coexist():
    """dd 与 roadshow 两个子键独立合并，互不覆盖。"""
    merge_institution_intel(tenant_id="t1", name="机构B", patch={"dd": {"total": 5}})
    merge_institution_intel(tenant_id="t1", name="机构B", patch={"roadshow": {"key_questions": [{"verbatim": "毛利率?"}]}})
    notes = get_institution_intel_by_name("机构B")
    assert notes["dd"]["total"] == 5
    assert notes["roadshow"]["key_questions"][0]["verbatim"] == "毛利率?"


def test_merge_intel_same_subkey_overwrites():
    """同一子键再次写入 = 覆盖（幂等，重复确认不堆积）。"""
    merge_institution_intel(tenant_id="t1", name="机构C", patch={"dd": {"gaps": ["a"]}})
    merge_institution_intel(tenant_id="t1", name="机构C", patch={"dd": {"gaps": ["a", "b"]}})
    notes = get_institution_intel_by_name("机构C")
    assert notes["dd"]["gaps"] == ["a", "b"]


def test_get_intel_empty_when_absent():
    assert get_institution_intel_by_name("从未出现过的机构") == {}


# ─── 2. 尽调缺口回流 ──────────────────────────────────────────────────────────

def test_dd_confirm_reflows_gaps_to_intel(tmp_path):
    """尽调台确认后，未满足的清单项作为 gaps 回流到机构情报侧表。"""
    src = tmp_path / "已确认.pdf"
    src.write_bytes(b"x")
    with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items",
               return_value=[
                   {"item_no": "1", "category": "财务", "requirement": "审计报告"},
                   {"item_no": "2", "category": "法务", "requirement": "公司章程"},
               ]):
        with TestClient(global_app) as client:
            resp = client.post("/api/v1/dd/sessions", data={
                "text": "dummy", "tenant_id": "ddx", "folder_root": str(tmp_path),
                "institution_name": "缺口回流机构",
            })
            sid = resp.json()["session_id"]
            items = client.get(f"/api/v1/dd/sessions/{sid}/items").json()

            from cangjie_fos.services.db_base import _connect
            # item0 确认有文件；item1 故意留空 → 应成为缺口
            with _connect() as conn:
                conn.execute(
                    "UPDATE dd_match_items SET matched_file_path = ?, matched_filename = ? WHERE id = ?",
                    (str(src), "已确认.pdf", items[0]["id"]),
                )
            client.patch(f"/api/v1/dd/sessions/{sid}/items/{items[0]['id']}",
                         json={"user_confirmed": True})

    notes = get_institution_intel_by_name("缺口回流机构")
    assert notes.get("dd") is not None
    assert "公司章程" in notes["dd"]["gaps"]      # 未确认项 → 缺口
    assert notes["dd"]["confirmed"] >= 1


# ─── 3. 路演细分情报回流 ──────────────────────────────────────────────────────

def test_roadshow_intel_bits_extracts_questions_signals():
    report = SimpleNamespace(
        key_questions=[SimpleNamespace(verbatim="毛利率多少?", underlying_concern="盈利能力")],
        interest_signals=[SimpleNamespace(verbatim="想看看数据", interpretation="正向信号")],
    )
    from cangjie_fos.services.institution_intel_extract import _roadshow_intel_bits
    bits = _roadshow_intel_bits(report)
    assert bits["key_questions"][0]["concern"] == "盈利能力"
    assert bits["interest_signals"][0]["interpretation"] == "正向信号"


def test_roadshow_intel_bits_none_for_plain_report():
    """普通评分报告（无 key_questions/interest_signals）不应误触发回流。"""
    from cangjie_fos.services.institution_intel_extract import _roadshow_intel_bits
    assert _roadshow_intel_bits(SimpleNamespace(score=88)) is None


def test_extract_persist_reflows_roadshow_intel():
    """extract_and_persist 在路演报告下，把细分情报写入侧表。"""
    from cangjie_fos.services.institution_intel_extract import extract_and_persist_institution_intel
    report = SimpleNamespace(
        key_questions=[SimpleNamespace(verbatim="客户集中度?", underlying_concern="大客户风险")],
        interest_signals=[],
    )
    # 让 _llm_extract 直接给出机构名，避免依赖真实 LLM
    with patch("cangjie_fos.services.institution_intel_extract._llm_extract",
               return_value=[{"name": "路演情报机构", "stage": "pitched", "thermal": "warm",
                              "preferences": "p", "concerns": "c", "ai_summary": "s"}]):
        extract_and_persist_institution_intel(
            tenant_id="rsx", words=[], report=report, trace_id="job1", explicit_context={},
        )
    notes = get_institution_intel_by_name("路演情报机构")
    assert notes["roadshow"]["key_questions"][0]["verbatim"] == "客户集中度?"


# ─── 4. /briefing 端点合入侧表 ────────────────────────────────────────────────

def test_briefing_includes_intel():
    """/briefing 即便无 match_sessions 历史，只要侧表有情报也应展示。"""
    merge_institution_intel(tenant_id="t1", name="简报机构",
                            patch={"dd": {"checklist": "A轮清单", "total": 3, "confirmed": 1, "gaps": ["流水"]}})
    with TestClient(global_app) as client:
        r = client.get("/api/v1/institutions/简报机构/briefing")
    assert r.status_code == 200
    body = r.json()
    assert body["has_history"] is True
    assert body["dd_summary"]["gaps"] == ["流水"]
    assert body["dd_summary"]["checklist"] == "A轮清单"
