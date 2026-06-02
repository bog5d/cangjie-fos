"""SQLite 每日快照备份：防止单文件损坏/误删导致全部数据丢失。

设计要点：
  - 使用 SQLite 在线备份 API（``sqlite3.Connection.backup``），即使源库正在
    并发写入也能得到一个事务一致的冻结快照，不会复制到写一半的脏页。
  - 快照写入 ``backend/data/backups/``，文件名含 UTC 时间戳（零填充，
    字典序 == 时间序，便于排序和清理）。
  - 自动保留最近 N 份（默认 7），超出的最旧快照删除。
  - 由 main.py lifespan 的 APScheduler 每日凌晨调度（run_daily_backup）。

P0 加固（2026-06）：此前 SQLite 单文件零备份，文件损坏即全部机构/尽调数据
不可恢复。本模块提供最小可用的本地快照能力，零外部依赖。
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from cangjie_fos.core import paths as fos_paths

logger = logging.getLogger(__name__)

_SNAPSHOT_PREFIX = "fos_snapshot_"
_SNAPSHOT_SUFFIX = ".sqlite"


def _active_db_path() -> str:
    """解析当前活动 DB 路径（与 db_base._connect 同源，兼容测试隔离）。

    测试通过 monkeypatch ``pitch_job_db._db_path`` 隔离 DB；此处遵循同样的
    解析顺序，确保备份的是真正在用的那个文件。
    """
    import sys  # noqa: PLC0415
    _pjdb = sys.modules.get("cangjie_fos.services.pitch_job_db")
    if _pjdb is not None and hasattr(_pjdb, "_db_path"):
        return _pjdb._db_path()
    from cangjie_fos.services.db_base import _db_path  # noqa: PLC0415
    return _db_path()


def get_backup_dir() -> Path:
    """返回备份目录（不存在则创建）。"""
    d = fos_paths.get_backend_root() / "data" / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_snapshot(
    db_path: str | None = None,
    backup_dir: Path | None = None,
) -> Path:
    """用 SQLite 在线备份 API 生成一致快照，返回快照路径。

    参数：
        db_path：源 SQLite 路径，默认解析当前活动 DB
        backup_dir：快照输出目录，默认 ``data/backups/``
    """
    src = db_path or _active_db_path()
    dst_dir = backup_dir if backup_dir is not None else get_backup_dir()
    dst_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dst = dst_dir / f"{_SNAPSHOT_PREFIX}{ts}{_SNAPSHOT_SUFFIX}"
    # 同秒内重复调用时追加计数，避免覆盖刚生成的快照
    counter = 1
    while dst.exists():
        dst = dst_dir / f"{_SNAPSHOT_PREFIX}{ts}_{counter}{_SNAPSHOT_SUFFIX}"
        counter += 1

    src_conn = sqlite3.connect(src, timeout=10)
    try:
        dst_conn = sqlite3.connect(str(dst))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()

    logger.info("SQLite 快照已生成: %s", dst)
    return dst


def list_snapshots(backup_dir: Path | None = None) -> list[Path]:
    """返回所有快照路径，按文件名升序（最旧在前）。"""
    d = backup_dir if backup_dir is not None else get_backup_dir()
    if not d.exists():
        return []
    return sorted(
        d.glob(f"{_SNAPSHOT_PREFIX}*{_SNAPSHOT_SUFFIX}"),
        key=lambda p: p.name,
    )


def prune_snapshots(keep: int = 7, backup_dir: Path | None = None) -> list[Path]:
    """删除超出 ``keep`` 数量的最旧快照，返回被删除的路径列表。"""
    snaps = list_snapshots(backup_dir)
    if len(snaps) <= keep:
        return []
    to_delete = snaps[: len(snaps) - keep]  # 最旧的在前
    deleted: list[Path] = []
    for p in to_delete:
        try:
            p.unlink()
            deleted.append(p)
        except OSError as e:
            logger.warning("删除旧快照失败 %s: %s", p, e)
    if deleted:
        logger.info("已清理 %d 份旧快照", len(deleted))
    return deleted


def run_daily_backup(
    keep: int = 7,
    db_path: str | None = None,
    backup_dir: Path | None = None,
) -> Path | None:
    """生成快照 + 清理旧快照。供调度器每日调用。

    返回新快照路径；任何异常都被吞掉并记日志（备份失败不应影响主服务）。
    """
    try:
        snap = create_snapshot(db_path=db_path, backup_dir=backup_dir)
        prune_snapshots(keep=keep, backup_dir=backup_dir)
        return snap
    except Exception as e:  # noqa: BLE001
        logger.error("每日备份失败（非致命）: %s", e)
        return None
