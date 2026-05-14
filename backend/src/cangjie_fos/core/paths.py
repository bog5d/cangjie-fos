"""路径解析：迁移源 `AI_Pitch_Coach` 与本地数据目录。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from cangjie_fos.core.config import settings


def get_pitch_coach_root() -> Path:
    """定位 `AI_Pitch_Coach` 根目录（含 `src/`）。"""
    # 须优先读当前 os.environ：`lifespan` 内 `hydrate_pitch_coach_env` 会合并
    # backend/.env 到环境变量，但 `settings` 在 import 时已固化为旧值，仅靠 settings
    # 会忽略 .env 中的 CANGJIE_PITCH_COACH_ROOT。
    env = (os.getenv("CANGJIE_PITCH_COACH_ROOT") or "").strip()
    if env:
        return Path(env).resolve()
    if settings.pitch_coach_root:
        return Path(settings.pitch_coach_root).resolve()
    # backend/src/cangjie_fos/core/paths.py → parents[5] == AI_Workspaces
    here = Path(__file__).resolve()
    workspace = here.parents[5]
    return (workspace / "AI_Pitch_Coach").resolve()


def get_backend_root() -> Path:
    """`backend/` 目录（含 pyproject.toml）。"""
    return Path(__file__).resolve().parents[3]


def get_monorepo_root() -> Path:
    """`CangJie_FOS/` 根目录。"""
    return get_backend_root().parent


def get_frontend_dist_dir() -> Path:
    """Vite 构建产物 `frontend/dist`（Phase 2 静态伺服）。"""
    return get_monorepo_root() / "frontend" / "dist"


def get_langgraph_sqlite_path() -> Path:
    """NPC LangGraph Checkpointer 落盘路径。"""
    return get_backend_root() / "data" / "langgraph_npc.sqlite"


def get_fos_bridge_data_dir() -> Path:
    """与 FSS `asset_bridge_fss` 对齐：工作区根下 `.fos_data`（可用 CANGJIE_FSS_DATA_DIR 覆盖）。"""
    import os

    override = os.getenv("CANGJIE_FSS_DATA_DIR", "").strip()
    if override:
        return Path(override).resolve()
    return get_monorepo_root().parent / ".fos_data"


def get_data_room_root() -> Path:
    """资料室根目录（按 tenant 分子目录扫描）。"""
    import os

    override = os.getenv("CANGJIE_DATA_ROOM_ROOT", "").strip()
    if override:
        return Path(override).resolve()
    return get_backend_root() / "data" / "data_room"


def get_evolution_data_dir() -> Path:
    """进化记录落盘目录（SPEC：JSON/SQLite 之前先 JSON 文件）。"""
    if settings.evolution_data_dir:
        p = Path(settings.evolution_data_dir).resolve()
    else:
        p = get_backend_root() / "data" / "evolution"
    p.mkdir(parents=True, exist_ok=True)
    return p


def hydrate_pitch_coach_env() -> None:
    """
    仅为「尚未出现在 os.environ 中的键」补全 Coach/FOS 两侧 `.env`，供 ASR/评估热路径调用。

    - 背景：`transcriber` 默认只 `load_dotenv(Coach 根/.env)`，FOS 常在 `backend/.env` 配置 DashScope。
    - 不在 pytest 内注入：避免覆盖用例里 `monkeypatch.delenv` 的离线断言。
    - 合并顺序：Coach 先、backend 后；**同键以 backend 为准**，但仅当该键在环境中仍为空时才写入。
    """
    if os.getenv("PYTEST_CURRENT_TEST") or (os.getenv("CI", "").lower() in {"1", "true", "yes"}):
        return
    try:
        from dotenv import dotenv_values
    except ImportError:
        return
    coach = get_pitch_coach_root()
    backend = get_backend_root()
    merged: dict[str, str] = {}
    for p in (coach / ".env", backend / ".env"):
        if not p.is_file():
            continue
        raw = dotenv_values(p)
        for k, v in raw.items():
            if k and v is not None and str(v).strip():
                merged[str(k)] = str(v).strip()
    for k, v in merged.items():
        if not str(os.environ.get(k, "")).strip():
            os.environ[k] = v


def ensure_pitch_coach_import_path() -> Path | None:
    """
    将 Pitch_Coach `src` 置于 sys.path 首位（向后兼容保留）。

    engine/ 子包已包含所有核心模块，本函数不再是必须调用路径。
    若 AI_Pitch_Coach 不存在（单仓库部署），记录警告并返回 None 而非崩溃。
    """
    import logging
    root = get_pitch_coach_root()
    src = root / "src"
    if not src.is_dir():
        logging.getLogger(__name__).warning(
            "AI_Pitch_Coach src 不存在（%s），跳过 sys.path 注入。"
            "engine/ 子包已覆盖核心功能，通常无影响。",
            src,
        )
        return None
    s_src = str(src)
    s_root = str(root)
    if s_root not in sys.path:
        sys.path.insert(0, s_root)
    if s_src not in sys.path:
        sys.path.insert(0, s_src)
    return root


def ensure_pitch_coach_runtime() -> Path:
    """sys.path + 合并 .env；仅在「要走真实 Coach ASR/评估」的入口调用。"""
    root = ensure_pitch_coach_import_path()
    hydrate_pitch_coach_env()
    return root
