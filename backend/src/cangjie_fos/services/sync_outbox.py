"""离线暂存 + 自动补传（durable sync outbox）。

背景：团队保持分布式部署（每人各跑前后端），GitHub 仓库当数据中枢。原来的推送是
"动作完成→后台直接 push"，网一断就滞留在本地、不会自动补传（长时间断网必丢同步）。

改法：**每次改动只往本地 outbox 入队**（永不因网络失败而丢），
  - 在线：入队后立刻尝试补传一次 → 秒同步；
  - 离线：补传失败就留在队列里，由定时 flusher（每几分钟）+ 启动时各扫一遍，
          网一恢复就把积压的全部补传上去。
拉取（pull）本就有：登录 + 每 10 分钟 + 手动，且已合并全字段。

去重：同一实体重复改只留一条（补传时读的是当前 DB 最新状态，push 一次即最新）。
"""
from __future__ import annotations

import logging
import time

from cangjie_fos.services.db_base import _connect

logger = logging.getLogger(__name__)

# 支持的实体类型 → 对应的推送函数（懒加载，避免循环导入）
_KINDS = {"institution", "roadshow", "dd_session"}
_MAX_ATTEMPTS_LOG = 20  # 仅用于日志提示，不丢弃（网久不好也不丢数据）


def _ensure_table() -> None:
    with _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS sync_outbox (
                kind        TEXT NOT NULL,
                ref_id      TEXT NOT NULL,
                enqueued_at REAL NOT NULL,
                attempts    INTEGER NOT NULL DEFAULT 0,
                last_error  TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (kind, ref_id)
            )"""
        )


def enqueue(kind: str, ref_id: str) -> None:
    """把一条待同步改动入队（同 kind+ref_id 去重，刷新入队时间）。"""
    if kind not in _KINDS or not ref_id:
        return
    _ensure_table()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO sync_outbox (kind, ref_id, enqueued_at, attempts, last_error)
               VALUES (?, ?, ?, 0, '')
               ON CONFLICT(kind, ref_id) DO UPDATE SET enqueued_at=excluded.enqueued_at""",
            (kind, ref_id, time.time()),
        )


def list_pending() -> list[dict]:
    _ensure_table()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT kind, ref_id, enqueued_at, attempts, last_error FROM sync_outbox "
            "ORDER BY enqueued_at"
        ).fetchall()
    return [dict(r) for r in rows]


def pending_count() -> int:
    _ensure_table()
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0]


def _push_one(kind: str, ref_id: str) -> bool:
    """按 kind 调对应推送函数。返回是否成功。"""
    from cangjie_fos.services import github_sync  # noqa: PLC0415
    try:
        if kind == "institution":
            return github_sync.push_institution(ref_id)
        if kind == "roadshow":
            return github_sync.push_roadshow_report(ref_id)
        if kind == "dd_session":
            return github_sync.push_dd_session(ref_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("outbox 推送异常 %s/%s: %s", kind, ref_id, e)
        return False
    return False


def _mark_done(kind: str, ref_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM sync_outbox WHERE kind=? AND ref_id=?", (kind, ref_id))


def _mark_failed(kind: str, ref_id: str, err: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE sync_outbox SET attempts=attempts+1, last_error=? WHERE kind=? AND ref_id=?",
            (err[:200], kind, ref_id),
        )


def flush() -> dict:
    """把 outbox 里所有待同步项尽力补传。成功的移除，失败的保留待下次。

    未配置 GitHub token（is_configured=False）→ 不清空、直接返回（等配好再补传）。
    返回 {"flushed": n, "remaining": m, "skipped": bool}。
    """
    from cangjie_fos.services import github_sync  # noqa: PLC0415
    if not github_sync.is_configured():
        return {"flushed": 0, "remaining": pending_count(), "skipped": True}

    flushed = 0
    for item in list_pending():
        kind, ref_id = item["kind"], item["ref_id"]
        if _push_one(kind, ref_id):
            _mark_done(kind, ref_id)
            flushed += 1
        else:
            _mark_failed(kind, ref_id, "push 失败（网络/Token）")
            if item["attempts"] + 1 in (5, _MAX_ATTEMPTS_LOG):
                logger.warning("outbox 项 %s/%s 已重试 %d 次仍未成功（数据未丢，继续排队）",
                               kind, ref_id, item["attempts"] + 1)
    remaining = pending_count()
    if flushed:
        logger.info("outbox 补传成功 %d 条，剩余 %d 条", flushed, remaining)
    return {"flushed": flushed, "remaining": remaining, "skipped": False}


def enqueue_and_try(kind: str, ref_id: str) -> None:
    """动作完成后调用：先入队（保证不丢），再尽力立即补传一次（在线则秒同步）。

    替代原来的"后台直接 push"——网好一样即时，网坏也不丢、待 flusher 补传。
    """
    enqueue(kind, ref_id)
    try:
        flush()
    except Exception as e:  # noqa: BLE001
        logger.warning("即时补传失败（已入队，稍后重试）%s/%s: %s", kind, ref_id, e)
