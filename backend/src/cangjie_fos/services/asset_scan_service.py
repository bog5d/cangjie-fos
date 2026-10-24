"""向上扫描服务：在 FOS 后端直接扫描资料目录，结果写入 SQLite。"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cangjie_fos.services.pitch_job_db import (
    db_asset_upsert,
    db_assets_clear,
    db_assets_list,
    db_scan_config_get,
    db_scan_config_set,
)

logger = logging.getLogger(__name__)

_SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", ".pytest_cache"}
_SKIP_EXTS = {".tmp", ".lnk", ".ds_store", ".thumbdb", ".bak", ".log", ".pyc"}


def get_scan_config() -> dict[str, Any]:
    """返回当前扫描配置，若未配置返回默认值。"""
    cfg = db_scan_config_get()
    if cfg is None:
        return {"scan_dir": "", "auto_scan": False, "configured": False}
    return {**cfg, "configured": True}


def save_scan_config(scan_dir: str, auto_scan: bool = False) -> dict[str, Any]:
    """保存扫描配置，返回保存后的配置。"""
    db_scan_config_set(scan_dir=scan_dir.strip(), auto_scan=auto_scan)
    return get_scan_config()


def run_scan(scan_dir: str | None = None) -> dict[str, Any]:
    """扫描目录并将结果写入 assets 表。

    scan_dir 为 None 时从已保存配置读取。
    返回 { scanned, indexed, scan_dir, duration_ms, scanned_at }。
    """
    if scan_dir is None:
        cfg = db_scan_config_get()
        scan_dir = (cfg or {}).get("scan_dir", "")

    scan_dir = (scan_dir or "").strip()
    if not scan_dir:
        return {
            "ok": False,
            "error": "scan_dir_empty",
            "message": "未配置扫描目录，请先设置 scan_dir",
        }

    root = Path(scan_dir)
    if not root.is_dir():
        return {
            "ok": False,
            "error": "scan_dir_not_found",
            "message": f"目录不存在: {scan_dir}",
        }

    t0 = time.monotonic()
    scanned = 0
    indexed = 0
    db_assets_clear()

    try:
        for dirpath, dirnames, filenames in os.walk(str(root)):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
            for fname in filenames:
                suffix = Path(fname).suffix.casefold()
                if suffix in _SKIP_EXTS:
                    continue
                scanned += 1
                fpath = Path(dirpath) / fname
                try:
                    rel = str(fpath.relative_to(root)).replace("\\", "/")
                    mtime = datetime.fromtimestamp(fpath.stat().st_mtime, tz=timezone.utc).strftime(
                        "%Y-%m-%d"
                    )
                    db_asset_upsert(
                        filename=fname,
                        relative_path=rel,
                        full_path=str(fpath),
                        last_modified=mtime,
                        summary="",
                        tags=[],
                        scan_dir=scan_dir,
                    )
                    indexed += 1
                except Exception:
                    logger.debug("skip file %s", fpath, exc_info=True)
    except Exception:
        logger.exception("scan failed for dir=%s", scan_dir)
        return {"ok": False, "error": "scan_error", "message": "扫描时发生异常，请查看日志"}

    duration_ms = int((time.monotonic() - t0) * 1000)
    scanned_at = datetime.now(tz=timezone.utc).isoformat()
    logger.info("scan done dir=%s scanned=%d indexed=%d ms=%d", scan_dir, scanned, indexed, duration_ms)

    return {
        "ok": True,
        "scanned": scanned,
        "indexed": indexed,
        "scan_dir": scan_dir,
        "duration_ms": duration_ms,
        "scanned_at": scanned_at,
    }


def get_scan_status() -> dict[str, Any]:
    """返回最近一次扫描状态（从 assets 表推断）。"""
    assets = db_assets_list(limit=1)
    if not assets:
        return {"indexed": 0, "last_scan": None, "scan_dir": ""}
    latest = assets[0]
    all_assets = db_assets_list(limit=2000)
    return {
        "indexed": len(all_assets),
        "last_scan": datetime.fromtimestamp(latest["indexed_at"], tz=timezone.utc).isoformat()
        if latest.get("indexed_at")
        else None,
        "scan_dir": latest.get("scan_dir", ""),
    }
