"""全局限流：长任务并发槽位（commit / upload 时 try_reserve，任务结束 release）。"""
from __future__ import annotations

import os
import threading

_lock = threading.Lock()
_in_use: int = 0


def _capacity() -> int:
    raw = (os.getenv("CANGJIE_MAX_CONCURRENT_JOBS") or "2").strip()
    try:
        return max(1, min(64, int(raw)))
    except ValueError:
        return 2


def try_reserve_jobs(n: int) -> bool:
    """同时占用 n 个槽；成功返回 True。与 release_job_slot 成对使用（每结束一个任务 release 一次）。"""
    global _in_use
    if n <= 0:
        return True
    cap = _capacity()
    with _lock:
        if _in_use + n > cap:
            return False
        _in_use += n
        return True


def release_job_slot() -> bool:
    """释放一个槽。"""
    global _in_use
    with _lock:
        if _in_use <= 0:
            return False
        _in_use -= 1
        return True


def queue_snapshot() -> dict[str, int]:
    with _lock:
        cap = _capacity()
        return {"in_use": _in_use, "capacity": cap, "available": max(0, cap - _in_use)}
