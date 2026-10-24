"""Watchdog 状态查询（SPEC A3 / A7）。"""
from __future__ import annotations

from fastapi import APIRouter

from cangjie_fos.events.file_watchdog import is_file_watchdog_running as is_watchdog_running

router = APIRouter()


@router.get("/watch/status")
def watch_status() -> dict[str, bool]:
    return {"watchdog_running": is_watchdog_running()}
