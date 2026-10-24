"""记忆持久化层：executive_memories。

所有写操作通过 db_base._write_lock 序列化，连接由 db_base._connect 管理。
"""
from __future__ import annotations

import time
from typing import Any

from cangjie_fos.services.db_base import _connect, _write_lock


# ─────────────────────────────────────────────────────────────────
# executive_memories — 高管/机构记忆库
# ─────────────────────────────────────────────────────────────────

def db_exec_memory_insert(
    *,
    company_id: str,
    tag: str,
    uuid: str,
    raw_text: str,
    refined_text: str | None = None,
    weight: float = 1.0,
    source_job_id: str | None = None,
) -> None:
    """Insert an executive memory entry (idempotent: ignore duplicate uuid)."""
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO executive_memories
                    (company_id, tag, uuid, raw_text, refined_text, weight, created_at, source_job_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (company_id, tag, uuid, raw_text, refined_text, weight, time.time(), source_job_id),
            )
            conn.commit()
        finally:
            conn.close()


def db_exec_memory_list(
    company_id: str, *, tag: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    """Return executive memories for a company, optionally filtered by tag."""
    conn = _connect()
    try:
        if tag:
            cur = conn.execute(
                "SELECT * FROM executive_memories WHERE company_id = ? AND tag = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (company_id, tag, max(1, min(int(limit), 500))),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM executive_memories WHERE company_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (company_id, max(1, min(int(limit), 500))),
            )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def db_exec_memory_delete(uuid: str) -> None:
    """Delete an executive memory entry by uuid."""
    with _write_lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM executive_memories WHERE uuid = ?", (uuid,))
            conn.commit()
        finally:
            conn.close()


