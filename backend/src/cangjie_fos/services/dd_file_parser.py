"""从 PDF/Word/Excel/txt 文件中提取文字内容（纯工具函数，无 IO 副作用）。"""
from __future__ import annotations
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".md"}

# 全文抽取时 PDF 最多遍历的页数（安全帽，防扫描件/超大 PDF 把索引拖死）
_FULL_MAX_PAGES = 80


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


def extract_full_text(file_path: Path, max_chars: int = 6000) -> tuple[str, bool]:
    """提取文件「全文」内容（供精判节点逐条核对正文），上限 max_chars。

    与 extract_text 的区别：
      - extract_text 只读前 3 页 / 800 字，够生成 20 字摘要即可；
      - extract_full_text 读全部页 / 默认 6000 字，供 LLM 精判核对内容是否满足需求。

    返回 (text, readable)。readable=False 表示加密/图片型 PDF/不支持格式
    （此类文件正文读不出，精判会自动跳过，仍可靠文件名+摘要参与粗筛）。

    注：本函数只做「文字层」快速抽取（pdfplumber 等）。扫描件/图片型 PDF 读不出字、
    加密文件读不了——这些「死角」由 dd_content_extractor.extract_for_verify 在精判节点
    按需补齐（解密 + MarkItDown + 图片 OCR），见 v1.17.0。本函数保持轻量，不引入重依赖。
    """
    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        return "", False
    try:
        if suffix == ".pdf":
            # 页数安全帽：扫描件/纯图片 PDF 每页抽不出字、永远到不了 max_chars，
            # 若不限页会把上千页全遍历一遍，索引时卡死。最多看 _FULL_MAX_PAGES 页。
            return _extract_pdf(file_path, max_chars, max_pages=_FULL_MAX_PAGES), True
        elif suffix in (".docx", ".doc"):
            return _extract_docx(file_path, max_chars), True
        elif suffix in (".xlsx", ".xls"):
            return _extract_excel(file_path, max_chars, max_rows=200), True
        elif suffix in (".txt", ".md"):
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            return text[:max_chars], True
    except Exception as e:
        logger.warning("无法读取文件全文 %s: %s", file_path.name, e)
    return "", False


def _extract_pdf(path: Path, max_chars: int, max_pages: int | None = 3) -> str:
    """保留**页码**前缀（``[第N页]``），供 locator 指到具体页。

    WP-R1 改动。此前把各页直接拼接、无页码，模型给的 locator 只能标 UNKNOWN，
    人工无法回原文核对——这正是「引用可追溯」的要求所不允许的。
    """
    import pdfplumber
    texts: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        total = len(pdf.pages)
        pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
        for n, page in enumerate(pages, 1):
            t = page.extract_text() or ""
            if t.strip():
                texts.append(f"[第{n}页] " + t.strip())
            if sum(len(x) for x in texts) >= max_chars:
                break
        if total > len(pages):
            texts.append(f"[共{total}页，本次只读前{len(pages)}页]")
    return "\n".join(texts)[:max_chars]


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


def _cell_ref(col_idx: int, row_idx: int) -> str:
    """1-based 单元格地址，如 B7。供模型与人工核对数字出处。"""
    s, col = "", col_idx + 1
    while col:
        col, rem = divmod(col - 1, 26)
        s = chr(65 + rem) + s
    return f"{s}{row_idx}"


def _extract_excel(path: Path, max_chars: int, max_rows: int = 30,
                   max_sheets: int = 8) -> str:
    """遍历**全部工作表**，保留表名与单元格地址。

    WP-R1 改动。此前只取 ``wb.active`` 活动表、``values_only`` 丢地址、
    行上限 30（调用方默认）⇒ 华西《盈利预测_2026-2030.xlsx》(233 个数字单元格)
    与《研发费用辅助账》(1521 个单元格) 这类**多表预测/台账**几乎读不到内容，
    正是报告点名的 19 份未收录材料的主要形态。

    保留 ``表名!单元格=值`` 形式，满足「Excel 应保留工作表、单元格及数字来源」。
    """
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    out: list[str] = []
    for ws in wb.worksheets[:max_sheets]:
        rows: list[str] = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            cells = []
            for j, c in enumerate(row):
                if c is None or str(c).strip() in ("", "None"):
                    continue
                cells.append(f"{_cell_ref(j, i + 1)}={str(c).strip()}")
            if cells:
                rows.append(" ".join(cells))
            if i >= max_rows:
                rows.append(f"...（{ws.title} 表第 {max_rows + 1} 行后省略，共 {ws.max_row} 行）")
                break
        if rows:
            out.append(f"【工作表】{ws.title}\n" + "\n".join(rows))
        if sum(len(x) for x in out) >= max_chars:
            break
    wb.close()
    return "\n".join(out)[:max_chars]
