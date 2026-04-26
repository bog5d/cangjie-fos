"""启动前依赖检查 — 在服务接收请求前验证所有运行时依赖。"""
from __future__ import annotations

import importlib
import logging

logger = logging.getLogger(__name__)

# (import_name, pip_package, 用途说明)
_REQUIRED: list[tuple[str, str, str]] = [
    ("pandas",          "pandas",          "QA文档解析 (document_reader)"),
    ("docx",            "python-docx",     "Word文档读取 (document_reader)"),
    ("openai",          "openai",          "LLM调用"),
    ("jinja2",          "jinja2",          "HTML报告渲染"),
    ("imageio_ffmpeg",  "imageio-ffmpeg",  "音频切片"),
    ("fastapi",         "fastapi",         "Web框架"),
    ("pydantic",        "pydantic",        "数据校验"),
]

# 可选依赖 — 缺失只警告不阻断启动
_OPTIONAL: list[tuple[str, str, str]] = [
    ("dashscope",  "dashscope",   "阿里云 ASR（转写）"),
    ("watchdog",   "watchdog",    "文件监听（enable_watchdog=true时需要）"),
]


def run_preflight(*, strict: bool = True) -> list[str]:
    """
    检查所有依赖。
    strict=True 时有缺失直接抛 RuntimeError（用于生产启动）。
    返回缺失的必选包列表。
    """
    missing_required: list[str] = []
    missing_optional: list[str] = []

    for import_name, pip_name, reason in _REQUIRED:
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing_required.append(f"  uv add {pip_name:<20}  # {reason}")

    for import_name, pip_name, reason in _OPTIONAL:
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing_optional.append(f"  uv add {pip_name:<20}  # {reason}")

    if missing_optional:
        logger.warning(
            "可选依赖缺失（功能降级）:\n%s", "\n".join(missing_optional)
        )

    if missing_required:
        msg = "启动检查发现缺失依赖，请先安装后再启动:\n\n" + "\n".join(missing_required)
        if strict:
            raise RuntimeError(msg)
        logger.error(msg)

    if not missing_required:
        logger.info("preflight OK — 所有必选依赖已就绪")

    return missing_required
