"""上传任务内存态（后续可换 Redis/DB）。"""
from __future__ import annotations

import threading
import time
from typing import Any

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


def job_update(job_id: str, **kwargs: Any) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)


def job_get(job_id: str) -> dict[str, Any] | None:
    with _lock:
        return _jobs.get(job_id)


def job_list_for_tenant(tenant_id: str, *, limit: int = 50) -> list[tuple[str, dict[str, Any]]]:
    """按创建时间倒序返回 (job_id, row)，供 Task Rail / 管理端列举。"""
    lim = max(1, min(int(limit), 200))
    with _lock:
        pairs = [(jid, row) for jid, row in _jobs.items() if row.get("tenant_id") == tenant_id]
    pairs.sort(key=lambda p: float(p[1].get("created_at") or 0.0), reverse=True)
    return pairs[:lim]
