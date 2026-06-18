"""材料库预热（提前全量文字层抽取 + 生成 .md + 回填 content_text）测试。

确定性、不依赖 LLM/网络：用真实 txt/docx 验证抽取落库、md 生成、续传跳过、进度回调、读不出标记。
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from cangjie_fos.services import dd_prefetch_service as pf
from cangjie_fos.services.db_base import _connect


def _index_file(folder_root: str, file_path: str, content_text=None, readable=1):
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_asset_index
               (id, folder_root, file_path, filename, file_type, summary,
                readable, indexed_at, content_text)
               VALUES (?, ?, ?, ?, ?, 's', ?, ?, ?)""",
            (str(uuid.uuid4()), folder_root, file_path, Path(file_path).name,
             Path(file_path).suffix.lower(), readable, time.time(), content_text),
        )


def _get_content(file_path: str):
    with _connect() as conn:
        row = conn.execute(
            "SELECT content_text, readable FROM dd_asset_index WHERE file_path = ?",
            (file_path,),
        ).fetchone()
    return (row["content_text"], row["readable"]) if row else (None, None)


def test_prefetch_extracts_fills_and_writes_md(tmp_path):
    folder = tmp_path / "lib"
    folder.mkdir()
    f = folder / "审计报告.txt"
    f.write_text("审计报告 标准无保留意见 2023年度", encoding="utf-8")
    _index_file(str(folder), str(f), content_text=None)

    md_dir = tmp_path / "md_out"
    result = pf.prefetch_folder(str(folder), md_out_dir=str(md_dir))

    assert result["total"] == 1 and result["processed"] == 1
    text, readable = _get_content(str(f))
    assert "审计报告" in text and readable == 1            # 回填落库
    md_files = list(md_dir.rglob("*.md"))
    assert len(md_files) == 1                              # 生成了 .md
    assert "审计报告" in md_files[0].read_text(encoding="utf-8")


def test_prefetch_resumable_skips_already_extracted(tmp_path):
    folder = tmp_path / "lib"
    folder.mkdir()
    f = folder / "a.txt"
    f.write_text("新内容", encoding="utf-8")
    _index_file(str(folder), str(f), content_text="已抽取过的旧正文")  # 已有缓存

    result = pf.prefetch_folder(str(folder), md_out_dir=str(tmp_path / "md"))
    assert result["skipped"] == 1 and result["processed"] == 0
    text, _ = _get_content(str(f))
    assert text == "已抽取过的旧正文"                       # 续传未覆盖


def test_prefetch_force_reextracts(tmp_path):
    folder = tmp_path / "lib"
    folder.mkdir()
    f = folder / "a.txt"
    f.write_text("最新正文内容", encoding="utf-8")
    _index_file(str(folder), str(f), content_text="旧的")

    pf.prefetch_folder(str(folder), md_out_dir=str(tmp_path / "md"), force=True)
    text, _ = _get_content(str(f))
    assert "最新正文内容" in text                           # force 强制重抽


def test_prefetch_marks_unreadable(tmp_path):
    """文字层读不出（不存在/空）→ 标记 readable=0，不崩（留给尽调按需 OCR 兜底）。"""
    folder = tmp_path / "lib"
    folder.mkdir()
    missing = folder / "缺失.pdf"   # 没真正创建文件
    _index_file(str(folder), str(missing), content_text=None, readable=1)

    result = pf.prefetch_folder(str(folder), md_out_dir=str(tmp_path / "md"))
    assert result["unreadable"] == 1
    _, readable = _get_content(str(missing))
    assert readable == 0


def test_prefetch_progress_callback(tmp_path):
    folder = tmp_path / "lib"
    folder.mkdir()
    for i in range(3):
        f = folder / f"f{i}.txt"
        f.write_text(f"文件{i}正文", encoding="utf-8")
        _index_file(str(folder), str(f))
    seen: list[tuple] = []
    pf.prefetch_folder(str(folder), md_out_dir=str(tmp_path / "md"),
                       progress_callback=lambda d, t: seen.append((d, t)))
    assert seen and seen[-1] == (3, 3)                     # 末次回调到达总数
