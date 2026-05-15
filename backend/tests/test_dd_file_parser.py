"""Unit tests for dd_file_parser — no LLM, no network."""
from __future__ import annotations
import io
from pathlib import Path
import pytest


def test_extract_txt_file(tmp_path):
    f = tmp_path / "report.txt"
    f.write_text("这是一份财务报告，包含2023年营收数据。", encoding="utf-8")
    from cangjie_fos.services.dd_file_parser import extract_text
    text, readable = extract_text(f)
    assert readable is True
    assert "财务报告" in text


def test_extract_unsupported_file_returns_not_readable(tmp_path):
    f = tmp_path / "image.png"
    f.write_bytes(b"\x89PNG\r\n")
    from cangjie_fos.services.dd_file_parser import extract_text
    text, readable = extract_text(f)
    assert readable is False
    assert text == ""


def test_extract_excel_file(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["序号", "内容"])
    ws.append(["1", "验资报告"])
    ws.append(["2", "营业执照"])
    path = tmp_path / "checklist.xlsx"
    wb.save(str(path))

    from cangjie_fos.services.dd_file_parser import extract_text
    text, readable = extract_text(path)
    assert readable is True
    assert "验资报告" in text


def test_extract_docx_file(tmp_path):
    from docx import Document
    doc = Document()
    doc.add_paragraph("公司架构图说明")
    doc.add_paragraph("组织结构详见附件")
    path = tmp_path / "org.docx"
    doc.save(str(path))

    from cangjie_fos.services.dd_file_parser import extract_text
    text, readable = extract_text(path)
    assert readable is True
    assert "公司架构图" in text


# ── dd_index_service 测试 ────────────────────────────────────

def test_scan_indexes_txt_files(tmp_path):
    (tmp_path / "report.txt").write_text("财务审计报告2023年度", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"\x89PNG")  # 不支持，应记录 readable=0

    from unittest.mock import patch
    from cangjie_fos.services.dd_index_service import scan_and_index_folder, get_index_by_folder

    with patch("cangjie_fos.services.dd_index_service._llm_summarize", return_value="2023年财务审计报告"):
        result = scan_and_index_folder(str(tmp_path), "test")

    assert result["indexed"] == 1   # txt 成功
    # png 不在 SUPPORTED_EXTENSIONS，不进索引
    rows = get_index_by_folder(str(tmp_path))
    assert len(rows) == 1
    assert rows[0]["filename"] == "report.txt"
    assert rows[0]["summary"] == "2023年财务审计报告"
    assert rows[0]["readable"] == 1


def test_scan_invalid_folder_raises():
    from cangjie_fos.services.dd_index_service import scan_and_index_folder
    with pytest.raises(ValueError, match="Not a directory"):
        scan_and_index_folder("/nonexistent/path/xyz", "test")
