"""扫描本地文件夹，为每个文件生成 AI 摘要，存入 dd_asset_index 表。"""
from __future__ import annotations
import logging
import os
import uuid
import time
from pathlib import Path

from cangjie_fos.services.dd_file_parser import extract_text, SUPPORTED_EXTENSIONS
from cangjie_fos.services.db_base import _connect

logger = logging.getLogger(__name__)


def scan_and_index_folder(folder_path: str, tenant_id: str) -> dict:
    """
    扫描文件夹，对每个支持的文件提取内容并生成摘要，写入 dd_asset_index。
    同步执行，调用方应包装进 BackgroundTask。
    返回：{"total": N, "indexed": M, "failed": K, "folder_root": str}
    """
    root = Path(folder_path)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {folder_path}")

    files = [
        f for f in root.rglob("*")
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    results = {"total": len(files), "indexed": 0, "failed": 0, "folder_root": str(root)}

    for file_path in files:
        try:
            _index_single_file(file_path, str(root))
            results["indexed"] += 1
        except Exception as e:
            logger.warning("索引失败 %s: %s", file_path.name, e)
            results["failed"] += 1

    return results


def _index_single_file(file_path: Path, folder_root: str) -> None:
    text, readable = extract_text(file_path)
    summary = _llm_summarize(file_path.name, text) if readable and text else None

    with _connect() as conn:
        # 用 file_path 做 upsert（同一文件重复扫描不重复插入）
        existing = conn.execute(
            "SELECT id FROM dd_asset_index WHERE file_path = ?", (str(file_path),)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE dd_asset_index
                   SET summary = ?, readable = ?, indexed_at = ?
                   WHERE file_path = ?""",
                (summary, 1 if readable else 0, time.time(), str(file_path)),
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
                    time.time(),
                ),
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
