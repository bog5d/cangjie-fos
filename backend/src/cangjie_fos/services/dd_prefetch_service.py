"""材料库「预热」：扫描建索引后，后台把全量正文提前抽好（仅文字层）+ 生成 .md，落库缓存。

为什么需要：
  尽调时现场抽正文很慢（几千份）。本服务把「读懂材料」前置——扫描后台一次跑完，
  正文回填 dd_asset_index.content_text，尽调精判直接命中缓存，秒出。

设计（按主理人决策）：
  - 深度=仅文字层：用 extract_full_text（pdfplumber/docx/openpyxl），**不走 OCR/视觉模型**，
    零额外 API 花费、最快。扫描件/加密件读不出 → 标记不可读，留给尽调时按需 OCR/解密兜底。
  - 产物=额外生成 .md：在 md_out_dir 下为每份文档生成对应 .md，便于人工查阅，同时落库。
  - 可中断续传：content_text 已有的文件直接跳过（force=True 可强制重抽）。
  - 进度回调：每 N 个文件回调 (done, total)，供前端进度条。
  - 同步执行，调用方包进 BackgroundTask。

⚠️ md 产物是机密材料的衍生物：md_out_dir 应落在数据目录内、**不得纳入 git / 外发**。
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from cangjie_fos.services.db_base import _connect
from cangjie_fos.services.dd_file_parser import extract_full_text

logger = logging.getLogger(__name__)

# 预热抽取的单文件正文上限（远大于尽调精判的 6000，预热要尽量全）
_PREFETCH_MAX_CHARS = 50_000
_DEFAULT_MD_SUBDIR = "_cangjie_预处理_md"


def default_md_dir(folder_root: str) -> Path:
    """默认 md 输出目录：材料库根目录下的 _cangjie_预处理_md/（集中、显眼、便于整体排除 git）。"""
    return Path(folder_root) / _DEFAULT_MD_SUBDIR


def _write_md(md_dir: Path, folder_root: str, file_path: str, text: str) -> str | None:
    """把抽取出的正文写成 .md，保持相对目录结构。返回 md 路径或 None（失败不阻断）。"""
    try:
        rel = Path(file_path).resolve().relative_to(Path(folder_root).resolve())
    except (ValueError, OSError):
        rel = Path(Path(file_path).name)
    out = md_dir / rel.with_suffix(rel.suffix + ".md")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        header = f"# {Path(file_path).name}\n\n> 源文件：{file_path}\n\n"
        out.write_text(header + (text or ""), encoding="utf-8")
        return str(out)
    except OSError as e:
        logger.warning("写 md 失败 %s: %s", out, e)
        return None


def prefetch_folder(
    folder_root: str,
    md_out_dir: str | None = None,
    force: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict:
    """对 folder_root 已索引的文件做全量文字层预抽取 + 生成 .md + 回填 content_text。

    返回 {"total", "processed", "skipped", "unreadable", "md_dir"}。
    """
    md_dir = Path(md_out_dir) if md_out_dir else default_md_dir(folder_root)

    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT file_path, content_text FROM dd_asset_index WHERE folder_root = ?",
            (folder_root,),
        ).fetchall()]

    total = len(rows)
    processed = skipped = unreadable = 0

    for i, row in enumerate(rows):
        fp = row["file_path"]
        # 续传：已抽过且不强制 → 跳过
        if not force and (row.get("content_text") or "").strip():
            skipped += 1
        else:
            try:
                text, readable = extract_full_text(Path(fp), max_chars=_PREFETCH_MAX_CHARS)
            except Exception as e:  # noqa: BLE001
                logger.warning("预热抽取失败 %s: %s", fp, e)
                text, readable = "", False

            if text and text.strip():
                with _connect() as conn:
                    conn.execute(
                        "UPDATE dd_asset_index SET content_text = ?, readable = 1 WHERE file_path = ?",
                        (text, fp),
                    )
                _write_md(md_dir, folder_root, fp, text)
                processed += 1
            else:
                # 文字层读不出（扫描件/加密件）→ 标记，留给尽调时按需 OCR/解密兜底
                with _connect() as conn:
                    conn.execute(
                        "UPDATE dd_asset_index SET readable = 0 WHERE file_path = ?", (fp,),
                    )
                unreadable += 1

        if progress_callback and ((i + 1) % 20 == 0 or i + 1 == total):
            progress_callback(i + 1, total)

    logger.info("预热完成 %s: 共%d 抽取%d 跳过%d 读不出%d → md=%s",
                folder_root, total, processed, skipped, unreadable, md_dir)
    return {
        "total": total, "processed": processed, "skipped": skipped,
        "unreadable": unreadable, "md_dir": str(md_dir),
    }
