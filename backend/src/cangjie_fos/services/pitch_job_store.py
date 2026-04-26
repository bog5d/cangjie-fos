"""上传任务内存态（后续可换 Redis/DB）。"""
from __future__ import annotations

import json as _json
import threading
import time
from typing import Any

# SQLite 回退路径中需要反序列化的 JSON 字符串列
_DB_JSON_COLS: frozenset[str] = frozenset({"warnings"})

from cangjie_fos.schemas.pitch_upload import PitchJobStatus

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def job_create(job_id: str, tenant_id: str, **extra: Any) -> None:
    with _lock:
        row: dict[str, Any] = {
            "tenant_id": tenant_id,
            "status": PitchJobStatus.PENDING,
            "report": None,
            "error": None,
            "error_summary": None,
            "error_detail": None,
            "error_code": None,
            "exp_delta": 0,
            "exp_reason": "",
            "created_at": time.time(),
        }
        row.update(extra)
        _jobs[job_id] = row

    # Also persist to SQLite (best-effort; in-memory remains authoritative for now)
    try:
        from cangjie_fos.services.pitch_job_db import db_job_create
        db_job_create(job_id, tenant_id, **{k: v for k, v in row.items() if k != "tenant_id"})
    except Exception:
        pass


def job_update(job_id: str, **kwargs: Any) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)


def job_get(job_id: str) -> dict[str, Any] | None:
    with _lock:
        return _jobs.get(job_id)


def job_list_for_tenant(tenant_id: str, *, limit: int = 50) -> list[tuple[str, dict[str, Any]]]:
    """按创建时间倒序返回 (job_id, row)，供 Task Rail / 管理端列举。
    内存不为空时优先用内存；内存为空时（如刚重启）兜底读 SQLite。
    """
    lim = max(1, min(int(limit), 200))
    with _lock:
        pairs = [(jid, row) for jid, row in _jobs.items() if row.get("tenant_id") == tenant_id]

    if not pairs:
        # 内存 store 为空（服务刚重启），兜底从 SQLite 加载
        try:
            from cangjie_fos.services.pitch_job_db import _connect  # noqa: PLC0415
            conn = _connect()
            try:
                cur = conn.execute(
                    "SELECT job_id, tenant_id, status, created_at, exp_delta, exp_reason, "
                    "error_summary, error_detail, error_code, html_report_path, warnings, substatus, "
                    "CASE WHEN original_report IS NOT NULL THEN 1 ELSE 0 END as has_report_flag "
                    "FROM pitch_jobs WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
                    (tenant_id, lim),
                )
                rows = cur.fetchall()
            finally:
                conn.close()
            db_pairs: list[tuple[str, dict[str, Any]]] = []
            for r in rows:
                d = dict(r)
                jid = d.pop("job_id")
                # Deserialize JSON string columns (SQLite stores them as raw JSON text)
                for col in _DB_JSON_COLS:
                    if isinstance(d.get(col), str):
                        try:
                            d[col] = _json.loads(d[col])
                        except Exception:
                            d[col] = None
                # Reconstruct minimal memory-store shape
                d["report"] = None  # full report not loaded here (avoid memory pressure)
                d["error"] = d.get("error_summary")
                db_pairs.append((jid, d))
            return db_pairs
        except Exception:  # noqa: BLE001
            pass

    pairs.sort(key=lambda p: float(p[1].get("created_at") or 0.0), reverse=True)
    return pairs[:lim]
