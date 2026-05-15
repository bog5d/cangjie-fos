"""从 PDF/Word/Excel/txt 文件中提取文字内容（纯工具函数，无 IO 副作用）。"""
from __future__ import annotations
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".md"}


def extract_text(file_path: Path, max_chars: int = 800) -> tuple[str, bool]:
    """
    从文件提取文字内容。
    返回 (text, readable)。readable=False 表示无法读取（加密/图片 PDF/不支持格式）。
    """
    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        return "", False
    try:
        if suffix == ".pdf":
            return _extract_pdf(file_path, max_chars), True
        elif suffix in (".docx", ".doc"):
            return _extract_docx(file_path, max_chars), True
        elif suffix in (".xlsx", ".xls"):
            return _extract_excel(file_path, max_chars), True
        elif suffix in (".txt", ".md"):
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            return text[:max_chars], True
    except Exception as e:
        logger.warning("无法读取文件 %s: %s", file_path.name, e)
    return "", False


def _extract_pdf(path: Path, max_chars: int) -> str:
    import pdfplumber
    texts: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages[:3]:  # 只读前3页，够摘要用
            t = page.extract_text() or ""
            texts.append(t)
            if sum(len(x) for x in texts) >= max_chars:
                break
    return " ".join(texts)[:max_chars]


def _extract_docx(path: Path, max_chars: int) -> str:
    from docx import Document
    doc = Document(str(path))
    parts: list[str] = []
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text.strip())
    # 也读表格内容
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return " ".join(parts)[:max_chars]


def _extract_excel(path: Path, max_chars: int) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb.active
    rows: list[str] = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        cells = [str(c).strip() for c in row if c is not None and str(c).strip() not in ("", "None")]
        if cells:
            rows.append(f"行{i + 1}: " + " | ".join(cells))
        if i >= 30:  # 只读前30行
            break
    wb.close()
    return "\n".join(rows)[:max_chars]
