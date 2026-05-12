"""记忆与建议持久化层：executive_memories + nightly_suggestions。

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


# ─────────────────────────────────────────────────────────────────
# nightly_suggestions — 夜间自动进化建议
# ─────────────────────────────────────────────────────────────────

def db_nightly_suggestion_insert(
    *,
    id: str,
    tenant_id: str,
    type: str,
    content: str,
    asset_id: str | None = None,
    priority: int = 5,
) -> None:
    """Insert a nightly suggestion record."""
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO nightly_suggestions
                    (id, tenant_id, created_at, type, content, asset_id, priority)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (id, tenant_id, time.time(), type, content, asset_id, priority),
            )
            conn.commit()
        finally:
            conn.close()


def db_nightly_suggestion_list_pending(
    tenant_id: str, *, limit: int = 3, max_priority: int = 5
) -> list[dict[str, Any]]:
    """Return unconsumed suggestions for a tenant with priority <= max_priority."""
    conn = _connect()
    try:
        cur = conn.execute(
            """SELECT * FROM nightly_suggestions
               WHERE tenant_id = ? AND consumed_at IS NULL AND priority <= ?
               ORDER BY priority ASC, created_at ASC LIMIT ?""",
            (tenant_id, max_priority, max(1, min(int(limit), 20))),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def db_nightly_suggestion_mark_consumed(suggestion_id: str) -> None:
    """Mark a nightly suggestion as consumed."""
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE nightly_suggestions SET consumed_at = ? WHERE id = ?",
                (time.time(), suggestion_id),
            )
            conn.commit()
        finally:
            conn.close()
