"""NPC 会话线程索引（与 LangGraph thread_id 对齐，SQLite）。"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from cangjie_fos.core import paths as fos_paths


def _db_path() -> Path:
    return fos_paths.get_backend_root() / "data" / "npc_threads.sqlite"


def _conn() -> sqlite3.Connection:
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(p), check_same_thread=False)
    c.execute(
        """CREATE TABLE IF NOT EXISTS npc_threads (
            thread_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            preview TEXT,
            updated_at REAL NOT NULL
        )"""
    )
    c.commit()
    return c


def upsert_thread(*, thread_id: str, tenant_id: str, preview: str) -> None:
    now = time.time()
    with _conn() as c:
        c.execute(
            """INSERT INTO npc_threads (thread_id, tenant_id, preview, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(thread_id) DO UPDATE SET
                 tenant_id=excluded.tenant_id,
                 preview=excluded.preview,
                 updated_at=excluded.updated_at""",
            (thread_id, tenant_id, preview[:200], now),
        )
        c.commit()


def list_threads(*, tenant_id: str, limit: int = 50) -> list[dict]:
    with _conn() as c:
        cur = c.execute(
            """SELECT thread_id, tenant_id, preview, updated_at FROM npc_threads
               WHERE tenant_id = ? ORDER BY updated_at DESC LIMIT ?""",
            (tenant_id, limit),
        )
        rows = cur.fetchall()
    return [
        {
            "thread_id": r[0],
            "tenant_id": r[1],
            "preview": r[2],
            "updated_at": r[3],
        }
        for r in rows
    ]
