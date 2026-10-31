"""DD-V1 **考场数据面并发锁** 的回归测试。

★ **本轮实测踩出来的坑**：两个进程同时跑同一场考试 ⇒ 后一个炸在
  ``shutil.rmtree`` 的「Directory not empty」（另一个进程正在往里写）⇒
  报出来的是**看不懂的 rmtree 栈**，而不是「这一场正被别人占着」。

★ 判据钉的是**性质**：
  ① 同一考场被别的进程占着 ⇒ **报人话**（``EXAM_PLANE_BUSY``），不是 rmtree 栈；
  ② 同一个进程**重复**跑同一场 ⇒ **不得自己把自己挡住**；
  ③ 持锁进程**被杀** ⇒ 锁**不残留**（下一个能拿到）；
  ④ 锁文件**必须在数据面外面** —— 放里面会被 rmtree 一起删掉 ⇒ 锁形同虚设。
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import dd_v1_exam_suite as suite  # noqa: E402

HOLDER = textwrap.dedent(
    """
    import fcntl, os, sys, time
    path = sys.argv[1]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    h = open(path, "a+")
    fcntl.flock(h.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    print("locked", flush=True)
    time.sleep(120)
    """
)


@pytest.fixture()
def plane(tmp_path, monkeypatch):
    """把数据面指到临时目录，并清掉进程级锁注册表。"""
    p = tmp_path / "plane"
    monkeypatch.setattr(suite, "PLANE", p)
    suite._PLANE_LOCKS.clear()
    yield p
    suite._PLANE_LOCKS.clear()


def _holder(plane: Path, exam: str) -> subprocess.Popen:
    lock_path = plane / ".locks" / f"{exam}.lock"
    proc = subprocess.Popen([sys.executable, "-c", HOLDER, str(lock_path)],
                            stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "locked", "持锁进程没起来"
    return proc


def test_busy_reports_human_readable_error(plane):
    """★ 核心：被占用时**报人话**，不是 rmtree 栈。"""
    proc = _holder(plane, "A")
    try:
        with pytest.raises(SystemExit) as exc:
            suite._prepare_plane("A", reset=True)
        assert "EXAM_PLANE_BUSY" in str(exc.value), str(exc.value)
        assert "rmtree" not in str(exc.value)
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_same_process_can_run_same_exam_twice(plane):
    """★ 同一进程重复跑同一场**不得自锁**（否则第二次调用自己把自己挡住）。"""
    suite._prepare_plane("B", reset=True)
    suite._prepare_plane("B", reset=True)
    assert (plane / "B" / "data").is_dir()


def test_lock_not_left_behind_after_holder_is_killed(plane):
    """★ 持锁进程被杀 ⇒ 锁**不残留** ⇒ 下一个能正常拿到。"""
    proc = _holder(plane, "C")
    proc.kill()
    proc.wait(timeout=10)
    time.sleep(0.2)
    suite._prepare_plane("C", reset=True)   # 不得抛 BUSY
    assert (plane / "C" / "runs").is_dir()


def test_lock_file_lives_outside_the_plane_dir(plane):
    """★ 锁文件必须在数据面**外面** —— 放里面会被 rmtree 删掉 ⇒ 锁形同虚设。"""
    suite._prepare_plane("D", reset=True)
    assert (plane / ".locks" / "D.lock").exists()
    assert not (plane / "D" / ".locks").exists()
    # 复位（reset=True）之后锁文件仍在 ⇒ 复位没有把锁删掉
    suite._prepare_plane("D", reset=True)
    assert (plane / ".locks" / "D.lock").exists()


# ── Windows 兼容性（★ 交接包要在 Windows 上跑） ─────────────────────────

#: 只封 ``fcntl``（**不封 msvcrt**）⇒ subprocess 自身在 POSIX 上不 import msvcrt，
#: 所以这个模拟**不会**打断解释器自身。
FCNTL_BLOCKED_SIM = textwrap.dedent(
    """
    import sys
    class Blocker:
        def find_spec(self, name, path=None, target=None):
            if name == "fcntl":
                raise ImportError("blocked on purpose: " + name)
            return None
    sys.meta_path.insert(0, Blocker())
    sys.path.insert(0, {tools!r})
    import dd_v1_exam_suite as s
    print("IMPORT_OK", s.LOCK_BACKEND)
    """
)


def test_module_imports_without_posix_only_fcntl(tmp_path):
    """★ **`fcntl` 在 Windows 上不存在** ⇒ 直接 import 会 ImportError
    ⇒ 整个考试台在 Windows 上起不来。

    ⇒ 这里把 ``fcntl`` **封掉**再 import：能 import ⇒ 模块**没有**平台专属硬依赖；
      且 ``LOCK_BACKEND`` 必须如实报 ``none``（**降级要说出来，不假装有保护**）。
    """
    code = FCNTL_BLOCKED_SIM.format(tools=str(REPO / "tools"))
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, timeout=120)
    assert proc.returncode == 0, f"封掉 fcntl 后 import 失败：\n{proc.stderr}"
    assert "IMPORT_OK none" in proc.stdout, proc.stdout


class _FakeMsvcrt:
    """最小 msvcrt 替身：记下 ``locking()`` 的调用（**按字节区间**语义）。"""

    LK_NBLCK = 1
    LK_UNLCK = 2

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []
        self.locked: set[int] = set()

    def locking(self, fd: int, mode: int, nbytes: int) -> None:
        self.calls.append((mode, nbytes))
        if mode == self.LK_NBLCK:
            if fd in self.locked:
                raise OSError("already locked")
            self.locked.add(fd)
        else:
            self.locked.discard(fd)


def test_windows_branch_uses_byte_range_lock(monkeypatch, tmp_path):
    """★ Windows 分支（``msvcrt``）必须**按字节区间**锁，且**占用时报 False**
    （⇒ 上层报 ``EXAM_PLANE_BUSY``），**不得抛异常**。"""
    fake = _FakeMsvcrt()
    monkeypatch.setattr(suite, "_fcntl", None)
    monkeypatch.setattr(suite, "_msvcrt", fake)
    h = (tmp_path / "x.lock").open("a+", encoding="utf-8")
    try:
        assert suite._lock_exclusive(h) is True
        assert fake.calls[0] == (fake.LK_NBLCK, 1), fake.calls
        # ★ 同一 fd 再锁一次 ⇒ **被占** ⇒ 返回 False（不是抛异常）
        assert suite._lock_exclusive(h) is False
        suite._unlock_exclusive(h)
        assert fake.calls[-1] == (fake.LK_UNLCK, 1), fake.calls
        # 解锁后可再拿
        assert suite._lock_exclusive(h) is True
    finally:
        h.close()


def test_lock_backend_is_reported_and_not_silently_faked(plane):
    """★ 锁后端必须**如实**报出来（复核者要能判断「这次有没有锁在起作用」）。"""
    assert suite.LOCK_BACKEND in ("fcntl", "msvcrt", "none")
    assert suite.LOCK_BACKEND == "none" or suite.LOCK_BACKEND == "fcntl", (
        "本机是 POSIX ⇒ 应当走 fcntl")
