"""LangGraph SqliteSaver 生命周期（Phase 4 SPEC A1）。"""
from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from typing import Any

from cangjie_fos.core.paths import get_langgraph_sqlite_path

logger = logging.getLogger(__name__)

_ctx: AbstractContextManager[Any] | None = None
_saver: Any | None = None


def get_sqlite_checkpointer():
    """返回已打开的 SqliteSaver（长连接）。优先由 FastAPI lifespan 初始化。"""
    global _ctx, _saver
    if _saver is not None:
        return _saver
    from langgraph.checkpoint.sqlite import SqliteSaver

    path = get_langgraph_sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # sqlite3.connect 需要裸文件路径，不能用 SQLAlchemy 的 sqlite:/// URI。
    conn_target = str(path.resolve())
    logger.info("langgraph_sqlite_checkpointer_init path=%s", conn_target)
    _ctx = SqliteSaver.from_conn_string(conn_target)
    _saver = _ctx.__enter__()
    return _saver


def shutdown_checkpointer() -> None:
    global _ctx, _saver
    if _ctx is not None:
        try:
            _ctx.__exit__(None, None, None)
        except Exception as e:  # noqa: BLE001
            logger.warning("checkpointer_shutdown: %s", e)
    _ctx = None
    _saver = None


def reset_checkpointing_for_tests() -> None:
    """测试隔离：关闭 saver 并清空全局引用。"""
    shutdown_checkpointer()
