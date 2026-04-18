"""兼容 Phase 1 命名：Watchdog 入口已迁移至 file_watchdog（Phase 5）。"""
from __future__ import annotations

from pathlib import Path

from cangjie_fos.events.file_watchdog import (
    is_file_watchdog_running as is_watchdog_running,
    start_file_watchdog,
    stop_file_watchdog,
)


def start_watchdog_stub(path: Path | str | None = None) -> None:  # noqa: ARG001
    """旧 API：path 已忽略，监听目录固定为 ``data_room/incoming``。"""
    start_file_watchdog()


def stop_watchdog_stub() -> None:
    stop_file_watchdog()
