#!/usr/bin/env python3
"""仓颉 FOS 一键诊断修复脚本。
用法：python tools/doctor.py [--fix]
不带 --fix：只诊断，输出报告
带 --fix：自动修复可修复项
"""
from __future__ import annotations

import argparse
import platform
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

# Windows 终端 UTF-8 输出
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass


def _project_root() -> Path:
    return Path(__file__).parent.parent


def _is_windows() -> bool:
    return platform.system() == "Windows"


# ── 各项检查 ────────────────────────────────────────────────────────────────

def check_python() -> tuple[bool, str, list[str]]:
    vi = sys.version_info
    ver = f"Python {vi.major}.{vi.minor}.{vi.micro}"
    if vi >= (3, 10):
        return True, ver, []
    return False, f"{ver}（需要 ≥ 3.10）", [
        "请安装 Python 3.10 或更高版本",
        "下载：https://www.python.org/downloads/",
        "安装时必须勾选 'Add Python to PATH'",
    ]


def check_uv() -> tuple[bool, str, list[str]]:
    if shutil.which("uv"):
        r = subprocess.run(["uv", "--version"], capture_output=True, text=True)
        return True, r.stdout.strip() or "uv", []
    return False, "uv 未安装", [
        "Windows:  powershell -c \"irm https://astral.sh/uv/install.ps1 | iex\"",
        "Mac/Linux: curl -LsSf https://astral.sh/uv | sh",
    ]


def check_deps(fix: bool) -> tuple[bool, str, list[str]]:
    if not shutil.which("uv"):
        return False, "uv 未找到，跳过依赖检查", []
    backend = _project_root() / "backend"
    r = subprocess.run(
        ["uv", "run", "--extra", "dev", "python", "-c", "import cangjie_fos"],
        capture_output=True, text=True, cwd=str(backend),
    )
    if r.returncode == 0:
        return True, "依赖已安装", []
    if not fix:
        return False, "依赖未安装", ["运行：cd backend && uv sync --extra dev"]
    print("    → 运行: uv sync --extra dev")
    r2 = subprocess.run(["uv", "sync", "--extra", "dev"], cwd=str(backend))
    if r2.returncode == 0:
        return True, "依赖安装完成", []
    return False, "依赖安装失败", ["手动运行：cd backend && uv sync --extra dev"]


def check_port(fix: bool) -> tuple[bool, str, list[str]]:
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=1):
            pass
        in_use = True
    except (ConnectionRefusedError, OSError):
        in_use = False

    if not in_use:
        return True, "端口 8000 空闲", []
    if not fix:
        return False, "端口 8000 已被占用", ["运行 --fix 可自动释放"]

    if _is_windows():
        r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
        pid = None
        for line in r.stdout.splitlines():
            if ":8000 " in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    pid = parts[-1]
                    break
        if pid:
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
            return True, f"已终止占用端口的进程 PID={pid}", []
    else:
        r = subprocess.run(["lsof", "-ti", ":8000"], capture_output=True, text=True)
        pid = r.stdout.strip()
        if pid:
            subprocess.run(["kill", "-9", pid])
            return True, f"已终止占用端口的进程 PID={pid}", []

    return False, "无法自动释放端口 8000", ["手动关闭占用端口的进程后重试"]


def check_data_dir(fix: bool) -> tuple[bool, str, list[str]]:
    root = _project_root()
    audio = root / "backend" / "data" / "audio"
    reports = root / "backend" / "data" / "html_reports"
    if audio.exists() and reports.exists():
        return True, "data/ 目录已存在", []
    if fix:
        audio.mkdir(parents=True, exist_ok=True)
        reports.mkdir(parents=True, exist_ok=True)
        return True, "data/ 目录已创建", []
    return False, "data/ 目录不存在", ["运行 --fix 自动创建"]


def check_ffmpeg() -> tuple[bool, str, list[str]]:
    if shutil.which("ffmpeg"):
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
        first = (r.stdout or "ffmpeg").splitlines()[0][:60]
        return True, first, []
    system = platform.system()
    hints = ["请下载：https://ffmpeg.org/download.html"]
    if system == "Windows":
        hints.append("Windows 推荐：winget install ffmpeg")
    elif system == "Darwin":
        hints.append("Mac 推荐：brew install ffmpeg")
    else:
        hints.append("Linux 推荐：sudo apt install ffmpeg")
    return False, "FFmpeg 未找到（语音转写将不可用）", hints


def check_sqlite(fix: bool) -> tuple[bool, str, list[str]]:
    try:
        fd, tmp = tempfile.mkstemp(suffix=".sqlite")
        import os
        os.close(fd)
        conn = sqlite3.connect(tmp)
        conn.execute("CREATE TABLE _t (id INTEGER PRIMARY KEY)")
        conn.close()
        Path(tmp).unlink(missing_ok=True)
        return True, "SQLite 可写", []
    except Exception as e:  # noqa: BLE001
        hints = [f"错误：{e}"]
        if fix:
            try:
                du = shutil.disk_usage(str(_project_root()))
                hints.append(f"磁盘剩余：{du.free // (1024 * 1024)} MB")
            except Exception:  # noqa: BLE001
                pass
        return False, "SQLite 不可写", hints


def check_env(fix: bool) -> tuple[bool, str, list[str]]:
    root = _project_root()
    env_file = root / "backend" / ".env"
    example = root / "backend" / ".env.example"
    if env_file.exists():
        return True, "backend/.env 存在", []
    if fix and example.exists():
        shutil.copy2(str(example), str(env_file))
        return True, "已从 .env.example 复制 .env，请填写 API 密钥", [
            "编辑 backend/.env，填写 SILICONFLOW_API_KEY 和 DEEPSEEK_API_KEY",
        ]
    hints = []
    if example.exists():
        hints.append("运行 --fix 自动从 .env.example 复制")
    else:
        hints.append("运行「填写API密钥_双击我.bat」创建 backend/.env")
    return False, "backend/.env 不存在（API 密钥未配置）", hints


def check_node_modules(fix: bool) -> tuple[bool, str, list[str]]:
    nm = _project_root() / "frontend" / "node_modules"
    if nm.exists():
        return True, "frontend/node_modules 存在", []
    if not fix:
        return False, "前端依赖未安装", ["运行：cd frontend && npm ci"]
    print("    → 运行: npm ci")
    r = subprocess.run(["npm", "ci"], cwd=str(_project_root() / "frontend"))
    if r.returncode == 0:
        return True, "前端依赖安装完成", []
    return False, "npm ci 失败，请检查 Node.js 是否已安装", [
        "下载 Node.js 18+：https://nodejs.org/",
        "然后运行：cd frontend && npm ci",
    ]


# ── 主流程 ──────────────────────────────────────────────────────────────────

_CHECKS: list[tuple[str, bool]] = [
    ("Python 版本", False),
    ("uv 包管理器", False),
    ("Python 依赖", True),
    ("端口 8000", True),
    ("data/ 目录", True),
    ("FFmpeg", False),
    ("SQLite 可写", True),
    (".env 配置", True),
    ("前端 node_modules", True),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="仓颉 FOS 诊断修复脚本",
        epilog="不带 --fix 仅输出诊断报告；带 --fix 自动修复可修复项",
    )
    parser.add_argument("--fix", action="store_true", help="自动修复可修复项")
    args = parser.parse_args()
    fix: bool = args.fix

    print()
    print("=" * 52)
    print(f"  仓颉 FOS — 系统诊断{'（自动修复模式）' if fix else ''}")
    print("=" * 52)
    print()

    results = [
        check_python(),
        check_uv(),
        check_deps(fix),
        check_port(fix),
        check_data_dir(fix),
        check_ffmpeg(),
        check_sqlite(fix),
        check_env(fix),
        check_node_modules(fix),
    ]

    fail = 0
    for (ok, msg, hints), (label, _fixable) in zip(results, _CHECKS):
        icon = "✅" if ok else "❌"
        print(f"[{icon}] {label}: {msg}")
        for h in hints:
            print(f"    → {h}")
        if not ok:
            fail += 1

    print()
    print("=" * 52)
    if fail == 0:
        print("✅ 所有检查通过！系统就绪。")
        print("   运行：cd backend && uv run uvicorn cangjie_fos.main:app --host 0.0.0.0 --port 8000")
    else:
        suffix = "已尝试自动修复，部分项可能仍需手动操作。" if fix else "运行 python tools/doctor.py --fix 可自动修复部分问题。"
        print(f"❌ 发现 {fail} 个问题。{suffix}")
    print("=" * 52)
    print()

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
