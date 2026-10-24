"""Tests for tools/doctor.py — 命令行诊断脚本。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _doctor_path() -> str:
    return str(Path(__file__).parent.parent.parent / "tools" / "doctor.py")


def test_doctor_script_exits_zero():
    """不带 --fix 的诊断模式应以 0 退出（本机环境全部检查应通过）。"""
    r = subprocess.run(
        [sys.executable, _doctor_path()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert r.returncode == 0, f"doctor.py 退出码非 0\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"


def test_doctor_script_output_contains_python():
    """输出中应包含 'Python' 字样。"""
    r = subprocess.run(
        [sys.executable, _doctor_path()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert "Python" in r.stdout, f"输出中未找到 'Python'：\n{r.stdout}"
