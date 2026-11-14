"""回归测试：只读体检命令**不得**改写 ``backend/uv.lock``。

## 为什么有这条测试（实测事故）

DD-V1 的门禁证据里有一个硬字段 ``git_dirty``，它回答的是
「**测的代码**是否等于 HEAD 的代码」。证据目录（``.audit/``）被有意豁免，
但**代码/测试/配置**的未提交变更会被算成 dirty ⇒ **证据当场失效**。

而 ``tools/doctor.py``（交接单里让刘江先跑的那条体检命令）原先写的是：

    uv run --extra dev python -c "import cangjie_fos"

``uv run`` **不带** ``--frozen`` 时会**重新解析依赖并改写** ``backend/uv.lock``。
实测一次 doctor 检查就把锁文件改了 **1793 行**（引入 ``pyproject.toml`` 里
**根本没声明**的 accelerate / torch 等一整串包）⇒ 工作区变脏 ⇒
「跑门禁之前先跑 doctor」这一步会把**门禁证据的溯源自证**直接打掉。

⇒ 处置：doctor 的两处 uv 调用（``uv run`` 与 ``uv sync``）一律加 ``--frozen``；
本测试把它钉住，防止以后有人「顺手清理参数」时又放回去。

## 本测试断言两件事

1. **静态**：``tools/doctor.py`` 里**每一处** ``uv run`` / ``uv sync`` 调用都带 ``--frozen``；
2. **行为**：真跑一次 ``check_deps(fix=False)``，``backend/uv.lock`` 的 sha256 **一字不变**。
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCTOR = REPO_ROOT / "tools" / "doctor.py"
UV_LOCK = REPO_ROOT / "backend" / "uv.lock"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _uv_invocations() -> list[list[str]]:
    """从 doctor.py 源码里抽出所有 ``uv`` 子命令调用（argv 列表字面量）。

    ★ 只取**会解析/安装依赖**的子命令（``run`` / ``sync`` / ``add`` / ``lock``）：
      ``uv --version`` 这类纯只读调用**不会**碰锁文件，不该被本测试当成违规。
    """
    src = DOCTOR.read_text(encoding="utf-8")
    out: list[list[str]] = []
    for match in re.finditer(r"\[\s*\"uv\"(?P<rest>[^\]]*)\]", src, re.DOTALL):
        args = re.findall(r"\"([^\"]*)\"", match.group(0))
        if any(arg in ("run", "sync", "add", "lock", "pip") for arg in args[1:]):
            out.append(args)
    return out


def test_doctor_uv_calls_are_frozen():
    """静态断言：每一处 uv 调用都带 ``--frozen``。"""
    calls = _uv_invocations()
    assert calls, "未在 doctor.py 里找到 uv 调用——源码结构变了，请同步本测试"
    for argv in calls:
        assert "--frozen" in argv, (
            f"doctor.py 的 uv 调用缺 --frozen：{argv}。"
            "不带 --frozen 会重写 backend/uv.lock ⇒ 弄脏工作区 ⇒ 门禁证据的 git_dirty 自证失效。"
        )


@pytest.mark.skipif(not shutil.which("uv"), reason="本机未装 uv")
def test_doctor_check_deps_does_not_touch_uv_lock():
    """行为断言：跑一次 doctor 的依赖体检，锁文件的 sha256 一字不变。"""
    if not UV_LOCK.is_file():
        pytest.skip("backend/uv.lock 不存在")

    before = _sha256(UV_LOCK)
    proc = subprocess.run(
        [sys.executable, str(DOCTOR)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=600,
    )
    after = _sha256(UV_LOCK)
    assert before == after, (
        "doctor.py 跑完以后 backend/uv.lock 变了 ⇒ 只读体检命令污染了工作区。"
        "（doctor 的 uv 调用必须带 --frozen）"
    )
    # ★ doctor 的退出码在本机通常非 0（缺 .env / node_modules）⇒ 那**不是**本测试的判据。
    assert proc.returncode in (0, 1), f"doctor.py 异常退出：rc={proc.returncode}"
