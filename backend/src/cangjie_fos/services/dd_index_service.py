"""扫描本地文件夹，为每个文件生成 AI 摘要，存入 dd_asset_index 表。"""
from __future__ import annotations
import logging
import os
import re
import uuid
import time
from pathlib import Path
from typing import Callable

from cangjie_fos.services.dd_file_parser import extract_text, SUPPORTED_EXTENSIONS
from cangjie_fos.services.db_base import _connect

logger = logging.getLogger(__name__)

# 超过此数量的文件夹不做 LLM 摘要，只索引文件名+类型，避免几小时的 API 调用
MAX_LLM_SUMMARIZE_FILES = 200

def clean_filename(name: str) -> str:
    """去除文件名中的日期、版本号、噪音词，提升二元组预筛准确率。"""
    name = re.sub(r'\.\w+$', '', name)
    name = re.sub(r'20\d{2}[-年/]\d{0,2}[-月/]?\d{0,2}日?', '', name)
    name = re.sub(r'20\d{2}', '', name)
    name = re.sub(r'[vV]\d+(\.\d+)*', '', name)
    for noise in ['最终版', '终稿', '副本', '扫描件', '盖章版', '签字版', '修订']:
        name = name.replace(noise, '')
    name = re.sub(r'[（(【\[].{0,10}[）)\]】]', '', name)
    return name.strip()


def scan_and_index_folder(
    folder_path: str,
    tenant_id: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict:
    """
    扫描文件夹，对每个支持的文件提取内容并生成摘要，写入 dd_asset_index。
    同步执行，调用方应包装进 BackgroundTask。

    大文件夹优化（v1.1.0）：
    - 文件数 > MAX_LLM_SUMMARIZE_FILES 时跳过 LLM 摘要，只记录文件名。
      匹配引擎的预筛选（prefilter）和 LLM 匹配本身仍可通过文件名工作。
    - progress_callback(done, total) 每处理50个文件回调一次，供前端进度展示。

    返回：{"total": N, "indexed": M, "failed": K, "folder_root": str}
    """
    root = Path(folder_path)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {folder_path}")

    files = [
        f for f in root.rglob("*")
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    total = len(files)
    use_llm = total <= MAX_LLM_SUMMARIZE_FILES
    if not use_llm:
        logger.info(
            "文件夹 %s 含 %d 个文件（>%d），跳过 LLM 摘要，仅索引文件名",
            folder_path, total, MAX_LLM_SUMMARIZE_FILES,
        )

    results = {"total": total, "indexed": 0, "failed": 0, "folder_root": str(root)}

    for i, file_path in enumerate(files):
        try:
            _index_single_file(file_path, str(root), use_llm=use_llm)
            results["indexed"] += 1
        except Exception as e:
            logger.warning("索引失败 %s: %s", file_path.name, e)
            results["failed"] += 1

        # 每 50 个文件汇报一次进度
        if progress_callback and (i + 1) % 50 == 0:
            progress_callback(results["indexed"], total)

    return results


def _index_single_file(file_path: Path, folder_root: str, use_llm: bool = True) -> None:
    text, readable = extract_text(file_path)
    # 只在 use_llm=True 且文件可读时才调用 LLM；否则 summary=None，依靠文件名匹配
    summary = _llm_summarize(file_path.name, text) if (use_llm and readable and text) else None

    now = time.time()
    with _connect() as conn:
        # ── 写入 dd_asset_index（DD 专用索引，用于本次会话匹配）──────────────
        existing = conn.execute(
            "SELECT id FROM dd_asset_index WHERE file_path = ?", (str(file_path),)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE dd_asset_index
                   SET summary = ?, readable = ?, indexed_at = ?
                   WHERE file_path = ?""",
                (summary, 1 if readable else 0, now, str(file_path)),
            )
        else:
            conn.execute(
                """INSERT INTO dd_asset_index
                   (id, folder_root, file_path, filename, file_type, summary, readable, indexed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    folder_root,
                    str(file_path),
                    file_path.name,
                    file_path.suffix.lower(),
                    summary,
                    1 if readable else 0,
                    now,
                ),
            )

        # ── 同步写入共享 assets 表（供轻量匹配器 MatchMaker 读取）────────────
        # 用相对路径作为唯一键；已有更优摘要时不覆盖（CASE WHEN）
        try:
            rel_path = str(file_path.relative_to(Path(folder_root)))
        except ValueError:
            rel_path = file_path.name
        try:
            mtime = str(file_path.stat().st_mtime)
        except OSError:
            mtime = ""
        conn.execute(
            """INSERT INTO assets (filename, relative_path, full_path, last_modified,
                                   summary, tags, scan_dir, indexed_at)
               VALUES (?, ?, ?, ?, ?, '[]', ?, ?)
               ON CONFLICT(relative_path) DO UPDATE SET
                   full_path     = excluded.full_path,
                   last_modified = excluded.last_modified,
                   summary       = CASE WHEN excluded.summary != '' THEN excluded.summary
                                        ELSE assets.summary END,
                   scan_dir      = excluded.scan_dir,
                   indexed_at    = excluded.indexed_at""",
            (file_path.name, rel_path, str(file_path), mtime,
             summary or "", folder_root, now),
        )


def _llm_summarize(filename: str, content: str) -> str:
    """
    调用 LLM 生成文件一句话摘要（20字以内）。

    v0.7.2 改进：使用 dd_llm_client 统一管理 provider 配置 + 重试。
    """
    from cangjie_fos.services.dd_llm_client import get_dd_llm_client, call_with_retry

    client = get_dd_llm_client()
    prompt = (
        f"文件名：{filename}\n"
        f"内容摘录：\n{content[:600]}\n\n"
        "用一句话（20字以内）说明这是什么资料（例如：2023年财务审计报告）："
    )

    def _call():
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=60,
            temperature=0,
        )
        return resp.choices[0].message.content.strip()

    return call_with_retry(_call, max_retries=2)  # 摘要生成重试2次即可


def get_index_by_folder(folder_root: str) -> list[dict]:
    """返回指定文件夹下所有已索引文件。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM dd_asset_index WHERE folder_root = ? ORDER BY indexed_at DESC",
            (folder_root,),
        ).fetchall()
    return [dict(r) for r in rows]
