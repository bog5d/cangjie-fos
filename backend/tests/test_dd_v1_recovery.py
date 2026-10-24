"""DD-V1 崩溃恢复与规模基线（WP1 补强）。

补 WP1 首轮 Evidence 中自陈的两个缺口：
1. 「未验证断点在**真实进程被 SIGKILL 后**的恢复」——首轮只用异常模拟，本文件用真子进程 + SIGKILL。
2. 「未做性能基线」——本文件给出可复跑的规模基线。

这些是 **工程证据**，不是终局业务效果证据：
材料能不能被正确匹配仍属 WP3/WP6，本文件不改变 Goal Contract 的 outcome 计分。
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_manifest_service as mf

_REPO = Path(__file__).resolve().parents[2]
_TOOLS = _REPO / "tools"


# ── 披露策略夹具（WP7）─────────────────────────────────────────────────────
# WP3–WP6 时期的用例用 `sensitivity="PUBLIC"` 绕过 Gate，那正是二值判定的漏洞：
# 任意非空值都放行。WP7 改为版本化策略后，未知等级一律不可外发，
# 因此本文件统一在**已知策略**下运行。
import json as _json
from pathlib import Path as _Path

_TEST_POLICY = {
    "policy_version": "test-v1",
    "default_level": "RESTRICTED",
    "levels": {
        "PUBLIC": {"externally_sendable": True, "requires_review": True},
        "INTERNAL": {"externally_sendable": False, "requires_review": True},
        "CONFIDENTIAL": {"externally_sendable": False, "requires_review": True},
        "RESTRICTED": {"externally_sendable": False, "requires_review": True},
    },
    "rules": [],
}


def _enable_test_policy(monkeypatch, tmp_path) -> None:
    p = _Path(tmp_path) / "_policy.json"
    p.write_text(_json.dumps(_TEST_POLICY, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("CANGJIE_DD_V1_POLICY", str(p))


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    db = tmp_path / "_dp" / "manifest.sqlite"
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    _enable_test_policy(monkeypatch, tmp_path)
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path: Path):
    return tmp_path / "_dp" / "manifest.sqlite"


def _make_library(tmp_path: Path, n_subjects: int, n_files: int) -> Path:
    """造一个多主体材料库：每主体若干同名文件，mtime 拉开。"""
    root = tmp_path / "materials"
    for s in range(n_subjects):
        d = root / f"主体{s:02d}"
        d.mkdir(parents=True)
        for i in range(n_files):
            f = d / f"审计报告{i:03d}.txt"
            f.write_text(f"主体{s} 第{i}份审计报告正文。" * 40, encoding="utf-8")
            os.utime(f, (1_700_000_000 + s * 86400 + i,) * 2)
    return root


# ── 1. 真实 SIGKILL 崩溃恢复 ───────────────────────────────────────────────
def _child_env(tmp_path: Path) -> dict:
    env = dict(os.environ)
    env["CANGJIE_DD_V1_DATA_DIR"] = str(tmp_path / "_plane")
    env["PYTHONPATH"] = str(_REPO / "backend" / "src")
    return env


def test_sigkill_mid_scan_leaves_resumable_run_and_recovers(tmp_path):
    """真子进程跑到一半被 SIGKILL → 必须能查到断点并完整恢复。

    这是「恢复的是工作，不是状态」的最小可验证形态：
    恢复后 Manifest 里必须真的多出剩余文件，而不只是 run 状态翻绿。
    做法刻意做成**确定性**而非赛跑：子进程入库到第 30 份时写下哨兵文件并放慢，
    父进程等到哨兵出现才发 SIGKILL——避免「扫描太快、还没来得及杀就跑完了」的竞态。
    """
    n_subjects, n_files = 6, 40           # 240 份
    root = _make_library(tmp_path, n_subjects, n_files)
    db = _db(tmp_path)
    total_expected = n_subjects * n_files
    sentinel = tmp_path / "sentinel"

    mf.register_library("lib1", str(root), authorized_by="波总", db_path=db)

    driver = tmp_path / "child.py"
    driver.write_text(
        "import sys, os, time\n"
        "from cangjie_fos.services import dd_v1_manifest_service as mf\n"
        "orig = mf._upsert_file\n"
        "cnt = [0]\n"
        "def patched(*a, **kw):\n"
        "    orig(*a, **kw)\n"
        "    cnt[0] += 1\n"
        "    if cnt[0] == 30:\n"
        "        open(sys.argv[2], 'w').write('x')\n"
        "    time.sleep(0.03)\n"
        "mf._upsert_file = patched\n"
        "mf.build_manifest('lib1', mode='full', db_path=sys.argv[1],"
        " lease_owner='child', lease_seconds=1)\n",
        encoding="utf-8",
    )

    proc = subprocess.Popen(
        [sys.executable, str(driver), str(db), str(sentinel)],
        env=_child_env(tmp_path),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # 哨兵出现 = 确定已入库 30 份且进程仍在运行
    deadline = time.time() + 30
    while time.time() < deadline and not sentinel.exists():
        if proc.poll() is not None:
            break
        time.sleep(0.01)
    assert sentinel.exists(), "子进程未到达哨兵点，无法验证中途崩溃"

    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=10)
    assert proc.returncode != 0, "被 SIGKILL 的进程应非零退出"

    # 崩溃后：已入库一部分，但远未完成
    partial = mf.manifest_summary("lib1", db_path=db)["total"]
    assert 0 < partial < total_expected, f"应在中途（已入库 {partial}/{total_expected}）"

    # 崩溃后 run 应仍是 running（孤儿租约），这是恢复入口
    run = mf.find_resumable_run("lib1", db_path=db)
    assert run is not None, "崩溃后应留下可发现的 running 运行"
    assert run["processed"] > 0, "运行记录应持久化已处理计数"

    # 租约未过期时，他人不得抢跑（围栏语义）
    with pytest.raises(RuntimeError, match="持有"):
        mf.build_manifest("lib1", resume_run_id=run["run_id"],
                          lease_owner="thief", db_path=db)

    # 租约过期后，续跑者接管并把剩余文件补齐。
    # 轮询等待真实过期，而非固定 sleep——子进程在哨兵之后仍可能再刷新一次租约。
    deadline = time.time() + 30
    while time.time() < deadline:
        cur = mf.get_run(run["run_id"], db_path=db)
        if cur and cur["lease_expires_at"] <= time.time():
            break
        time.sleep(0.05)
    else:
        pytest.fail("租约迟迟未过期，恢复路径不可用")

    resumed = mf.build_manifest("lib1", resume_run_id=run["run_id"],
                                lease_owner="rescuer", db_path=db)
    assert resumed["status"] == mf.RUN_COMPLETED

    final = mf.manifest_summary("lib1", db_path=db)["total"]
    assert final == total_expected, \
        f"恢复后应补齐到 {total_expected}，实际 {final}"


def test_crash_does_not_duplicate_or_lose_same_name_files(tmp_path):
    """崩溃前后反复扫描，同名跨主体文件既不重复也不丢失。"""
    root = _make_library(tmp_path, 3, 5)    # 15 份
    db = _db(tmp_path)
    mf.register_library("lib1", str(root), authorized_by="波总", db_path=db)

    mf.build_manifest("lib1", mode="full", db_path=db)
    first = {r["file_id"] for r in mf.list_manifest("lib1", db_path=db)}

    # 模拟再来一轮中断
    driver = tmp_path / "child2.py"
    driver.write_text(
        "import sys\n"
        "from cangjie_fos.services import dd_v1_manifest_service as mf\n"
        "mf.build_manifest('lib1', mode='full', db_path=sys.argv[1], lease_seconds=1)\n",
        encoding="utf-8",
    )
    proc = subprocess.Popen([sys.executable, str(driver), str(db)],
                            env=_child_env(tmp_path),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.05)
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=10)

    # 轮询等租约真正过期，避免固定 sleep 的竞态
    deadline = time.time() + 30
    while time.time() < deadline:
        r = mf.find_resumable_run("lib1", db_path=db)
        if r and r["lease_expires_at"] <= time.time():
            break
        time.sleep(0.05)

    mf.build_manifest("lib1", mode="full", db_path=db)
    second = {r["file_id"] for r in mf.list_manifest("lib1", db_path=db)}

    assert first == second, "崩溃恢复后文件集合应完全一致（既不重复也不丢失）"
    assert len(second) == 15


# ── 2. 规模基线（工程性能，非业务效果）─────────────────────────────────────
@pytest.mark.parametrize("n_subjects,n_files", [(20, 25), (40, 25)])
def test_scale_baseline(tmp_path, n_subjects, n_files, capsys):
    """规模基线：记录扫描耗时与吞吐。

    **这不是业务效果证据**，仅用于回归对比与容量预估。
    阈值刻意宽松（只卡灾难性退化），避免把机器性能差异误判为回归。
    """
    root = _make_library(tmp_path, n_subjects, n_files)
    db = _db(tmp_path)
    total = n_subjects * n_files
    mf.register_library("lib1", str(root), authorized_by="波总", db_path=db)

    t0 = time.perf_counter()
    res = mf.build_manifest("lib1", mode="full", db_path=db)
    full_s = time.perf_counter() - t0

    t1 = time.perf_counter()
    inc = mf.build_manifest("lib1", mode="incremental", db_path=db)
    inc_s = time.perf_counter() - t1

    assert res["added"] == total
    assert inc["added"] == 0 and inc["unchanged"] == total

    # WAL 模式下近期写入可能仍在 -wal 里，只量主库会严重低估，8 B/份 之类是测量假象
    db_size = sum(
        Path(str(db) + suffix).stat().st_size
        for suffix in ("", "-wal", "-shm")
        if Path(str(db) + suffix).exists()
    )
    with capsys.disabled():
        per_file = db_size / total
        print(f"\n[scale] {total} 份 | 全量 {full_s:.2f}s "
              f"({total / max(full_s, 1e-6):.0f} 份/s) | "
              f"增量 {inc_s:.2f}s ({total / max(inc_s, 1e-6):.0f} 份/s) | "
              f"库 {db_size / 1024:.0f} KB ({per_file:.0f} B/份) | "
              f"外推 1万份≈{per_file * 10000 / 1024 / 1024:.0f} MB, "
              f"10万份≈{per_file * 100000 / 1024 / 1024:.0f} MB")

    # 增量必须显著快于全量：mtime 快跳生效
    assert inc_s < full_s, "增量扫描应快于全量（size+mtime 快跳未生效？）"
    # 每份记录的库占用上限。实测约 4.7 KB/份（64B content_hash + 32B file_id +
    # 多列路径/时间 + 3 个索引），外推 10 万份约 470 MB；超过 8 KB/份说明
    # Schema 出现意外膨胀，属回归。
    assert db_size / total < 8192, f"每份占用 {db_size / total:.0f} B 过大"


def test_cli_entrypoint_runs_without_llm_key(tmp_path):
    """CLI 入口必须无需任何 LLM key 即可跑通——这是监工/刘江的独立复核路径。"""
    env = _child_env(tmp_path)
    env.pop("OPENAI_API_KEY", None)
    env.pop("DASHSCOPE_API_KEY", None)

    r = subprocess.run(
        [sys.executable, str(_TOOLS / "dd_v1_manifest.py"), "selftest"],
        env=env, capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, f"CLI selftest 失败：{r.stderr[-500:]}"
    data = json.loads(r.stdout)
    assert data["selftest"] == "PASS"
    assert all(c["结果"] == "PASS" for c in data["checks"])


def test_cli_refuses_unregistered_library(tmp_path):
    """CLI 层同样不得绕过授权闸。"""
    env = _child_env(tmp_path)
    r = subprocess.run(
        [sys.executable, str(_TOOLS / "dd_v1_manifest.py"), "build",
         "--library", "nope", "--mode", "full"],
        env=env, capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 1
    assert "PERMISSION_DENIED" in r.stderr
