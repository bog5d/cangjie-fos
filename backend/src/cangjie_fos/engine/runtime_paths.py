"""FOS 内嵌版路径解析（原 FSS runtime_paths，适配 FOS backend/ 布局）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def get_project_root() -> Path:
    """FOS context：backend/ 目录（含 pyproject.toml）。"""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    # backend/src/cangjie_fos/engine/runtime_paths.py → parents[3] = backend/
    return Path(__file__).resolve().parents[3]


def get_writable_app_root() -> Path:
    """FOS context：backend/data/ 可写数据目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return get_project_root() / "data"


def get_resource_path(relative_path: str) -> str:
    rel = (relative_path or ".").replace("/", os.sep).strip()
    root = get_project_root()
    if not rel or rel == ".":
        return str(root)
    return str(root / rel)


def get_memory_root() -> Path:
    """优先读 MEMORY_ROOT 环境变量；否则 backend/data/.executive_memory。"""
    override = os.environ.get("MEMORY_ROOT", "").strip()
    if override:
        return Path(override)
    return get_writable_app_root() / ".executive_memory"


def get_asr_cache_root() -> Path:
    """优先读 CACHE_ROOT 环境变量；否则 backend/data/.asr_cache。"""
    override = os.environ.get("CACHE_ROOT", "").strip()
    if override:
        return Path(override)
    return get_writable_app_root() / ".asr_cache"
