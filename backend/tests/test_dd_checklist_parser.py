"""Tests for dd_checklist_parser — all LLM calls mocked."""
from __future__ import annotations
from unittest.mock import patch
import pytest


_MOCK_ITEMS = [
    {"item_no": "1", "category": "基本情况", "requirement": "实收资本验资报告"},
    {"item_no": "2", "category": "基本情况", "requirement": "营业执照"},
]


def _fake_llm_extract(raw_text: str) -> list[dict]:
    return _MOCK_ITEMS


def test_parse_text_input():
    from cangjie_fos.services.dd_checklist_parser import parse_checklist
    with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items", side_effect=_fake_llm_extract):
        result = parse_checklist("1. 验资报告\n2. 营业执照", "text")
    assert len(result) == 2
    assert result[0]["requirement"] == "实收资本验资报告"
    assert result[0]["item_no"] == "1"


def test_parse_excel_file(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["序号", "内容"])
    ws.append(["1", "实收资本验资报告"])
    ws.append(["2", "营业执照"])
    path = tmp_path / "dd.xlsx"
    wb.save(str(path))

    from cangjie_fos.services.dd_checklist_parser import parse_checklist
    with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items", side_effect=_fake_llm_extract):
        result = parse_checklist(str(path), "excel")
    assert len(result) == 2


def test_parse_word_file(tmp_path):
    from docx import Document
    doc = Document()
    doc.add_paragraph("一、基本情况")
    doc.add_paragraph("1. 实收资本验资报告")
    doc.add_paragraph("2. 营业执照")
    path = tmp_path / "dd.docx"
    doc.save(str(path))

    from cangjie_fos.services.dd_checklist_parser import parse_checklist
    with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items", side_effect=_fake_llm_extract):
        result = parse_checklist(str(path), "word")
    assert len(result) == 2


def test_items_have_required_fields():
    from cangjie_fos.services.dd_checklist_parser import parse_checklist
    with patch("cangjie_fos.services.dd_checklist_parser._llm_extract_items", side_effect=_fake_llm_extract):
        result = parse_checklist("任意文字", "text")
    for item in result:
        assert "item_no" in item
        assert "category" in item
        assert "requirement" in item
        assert item["requirement"]  # 非空


# ── dd_match_service 测试 ────────────────────────────────────

def test_create_match_session_stores_items():
    from cangjie_fos.services.dd_match_service import create_match_session, get_session_items
    items = [
        {"item_no": "1", "category": "基本情况", "requirement": "验资报告"},
        {"item_no": "2", "category": "财务", "requirement": "审计报告"},
    ]
    session_id = create_match_session("test_tenant", "测试清单.xlsx", "/some/folder", items)
    assert session_id

    stored = get_session_items(session_id)
    assert len(stored) == 2
    assert stored[0]["requirement"] == "验资报告"
    assert stored[1]["category"] == "财务"


def test_run_matching_updates_confidence():
    from cangjie_fos.services.dd_match_service import create_match_session, run_matching, get_session_items
    from unittest.mock import patch

    items = [{"item_no": "1", "category": "基本情况", "requirement": "验资报告"}]
    session_id = create_match_session("test_tenant", "test.xlsx", "/folder", items)

    fake_index = [{"file_path": "/folder/验资.pdf", "filename": "验资.pdf", "summary": "验资报告"}]

    def fake_batch_match(items, file_list_text, index_rows):
        return {items[0]["id"]: {"file_path": "/folder/验资.pdf", "filename": "验资.pdf",
                                  "confidence": 0.92, "reason": "文件名匹配"}}

    with patch("cangjie_fos.services.dd_match_service._llm_batch_match", side_effect=fake_batch_match):
        with patch("cangjie_fos.services.dd_match_service._get_index_for_folder", return_value=fake_index):
            run_matching(session_id, "/folder")

    result = get_session_items(session_id)
    assert result[0]["confidence"] == pytest.approx(0.92)
    assert result[0]["matched_filename"] == "验资.pdf"


# ── dd_export_service 测试 ────────────────────────────────────

def test_export_creates_folder_and_copies_files(tmp_path):
    from cangjie_fos.services.dd_match_service import create_match_session, get_session_items
    from cangjie_fos.services.dd_export_service import export_to_folder
    from cangjie_fos.services.db_base import _connect
    from pathlib import Path

    # 准备真实文件
    src = tmp_path / "验资报告.pdf"
    src.write_bytes(b"fake pdf")

    items = [
        {"item_no": "1", "category": "基本情况", "requirement": "验资报告"},
        {"item_no": "2", "category": "基本情况", "requirement": "军工四证"},
    ]
    session_id = create_match_session("test", "dd.xlsx", str(tmp_path), items)

    # 手动给 item 1 设置匹配结果，item 2 标记 user_skipped
    stored = get_session_items(session_id)
    item1_id, item2_id = stored[0]["id"], stored[1]["id"]
    with _connect() as conn:
        conn.execute(
            "UPDATE dd_match_items SET matched_file_path=?, matched_filename=?, confidence=? WHERE id=?",
            (str(src), "验资报告.pdf", 0.95, item1_id),
        )
        conn.execute("UPDATE dd_match_items SET user_skipped=1 WHERE id=?", (item2_id,))

    out_dir = str(tmp_path / "output")
    result = export_to_folder(session_id, out_dir)

    assert result["exported"] == 1
    assert result["missing"] == 1

    # 文件被复制进去
    copied = list(Path(out_dir).rglob("*验资报告.pdf"))
    assert len(copied) == 1

    # 缺失清单生成
    gap = Path(out_dir) / "缺失清单.txt"
    assert gap.exists()
    assert "军工四证" in gap.read_text(encoding="utf-8")
