"""DD-V1 单写者写入守卫（``tools/dd_v1_write_guard.py``）的回归测试。

★ **判据**：守卫必须把「失租仍写」「双写交错」变成**机器拒绝**，而不是靠人记得住。
★ 本文件**真跑 git**：用本地 bare 仓当远端，真提交、真推送、真分叉 ——
  不 mock 掉 git，否则测的就不是守卫而是 mock。

覆盖：
- 租约四种拒绝态（不存在 / 已释放 / 已过期 / holder 不是我）+ 文档非法；
- 有效租约 ⇒ 放行；
- **外部写入检测**：远端被另一写者推进后 ⇒ 拒绝推送（且远端一个字节都不变）；
- 失租时推送 ⇒ 远端 tip **不动**（证明守卫不是「先推了再说」）；
- 正常快进 ⇒ 远端 tip 正好等于我的 commit。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import dd_v1_write_guard as guard  # noqa: E402

HOLDER = "cloud-ddv1:test-instance"
OTHER = "mac-mini-old-minimax"


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, f"git {' '.join(args)} 失败: {proc.stderr}"
    return proc.stdout.strip()


def _write_lease(path: Path, *, holder: str = HOLDER, ttl_s: float = 180.0,
                 heartbeat_at: datetime | None = None, released: bool = False,
                 generation: int = 1, schema: str = guard.LEASE_SCHEMA) -> Path:
    """按 **GM 真实落盘格式**写租约：``{"schema": ..., "lease": {...}}``。

    ★ 刻意与 ``gm.continuity_v2.lease.LeaseStore._write_lease_unlocked`` 同构 ——
      守卫若按平铺格式读，会在**真实租约文件**上误判为非法（这正是本用例存在的理由）。
    """
    hb = heartbeat_at or datetime.now(timezone.utc)
    doc = {
        "schema": schema,
        "lease": {
            "holder": holder,
            "generation": generation,
            "ttl_s": ttl_s,
            "acquired_at": hb.isoformat(),
            "heartbeat_at": hb.isoformat(),
            "released": released,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _commit(repo: Path, filename: str, content: str, message: str) -> str:
    (repo / filename).write_text(content, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def arena(tmp_path: Path):
    """真远端（bare）＋ 我的克隆 ＋ 另一个写者的克隆。"""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)

    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "-q", str(seed)], check=True)
    _git(seed, "config", "user.email", "seed@example.invalid")
    _git(seed, "config", "user.name", "seed")
    _commit(seed, "README.md", "seed\n", "init")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-q", "origin", "HEAD:refs/heads/feature")

    mine = tmp_path / "mine"
    subprocess.run(["git", "clone", "-q", str(remote), str(mine)], check=True)
    _git(mine, "config", "user.email", "me@example.invalid")
    _git(mine, "config", "user.name", "me")
    _git(mine, "checkout", "-q", "-B", "feature", "origin/feature")

    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True)
    _git(other, "config", "user.email", "other@example.invalid")
    _git(other, "config", "user.name", "other")
    _git(other, "checkout", "-q", "-B", "feature", "origin/feature")

    return {
        "remote": remote,
        "mine": mine,
        "other": other,
        "lease": tmp_path / "state" / "lease.json",
    }


# ── 租约判定：四种拒绝态 + 非法文档 + 放行 ──────────────────────────────

def test_missing_lease_refuses(tmp_path: Path):
    ok, code, _ = guard.check_lease(tmp_path / "nope.json", HOLDER)
    assert ok is False
    assert code == guard.RC_NO_LEASE


def test_released_lease_refuses(tmp_path: Path):
    p = _write_lease(tmp_path / "l.json", released=True)
    ok, code, _ = guard.check_lease(p, HOLDER)
    assert ok is False
    assert code == guard.RC_LEASE_RELEASED


def test_expired_lease_refuses(tmp_path: Path):
    old = datetime.now(timezone.utc) - timedelta(seconds=600)
    p = _write_lease(tmp_path / "l.json", ttl_s=180.0, heartbeat_at=old)
    ok, code, detail = guard.check_lease(p, HOLDER)
    assert ok is False
    assert code == guard.RC_LEASE_EXPIRED
    assert detail["expired_by_s"] > 0


def test_holder_mismatch_refuses(tmp_path: Path):
    p = _write_lease(tmp_path / "l.json", holder=OTHER)
    ok, code, _ = guard.check_lease(p, HOLDER)
    assert ok is False
    assert code == guard.RC_HOLDER_MISMATCH


def test_corrupt_lease_refuses(tmp_path: Path):
    p = _write_lease(tmp_path / "l.json", schema="something.else")
    ok, code, _ = guard.check_lease(p, HOLDER)
    assert ok is False
    assert code == guard.RC_LEASE_CORRUPT


def test_naive_timestamp_lease_refuses(tmp_path: Path):
    """naive 时间戳必须被拒（否则本地时区会把新旧混算）。"""
    p = tmp_path / "l.json"
    p.write_text(
        json.dumps(
            {
                "schema": guard.LEASE_SCHEMA,
                "lease": {
                    "holder": HOLDER,
                    "generation": 1,
                    "ttl_s": 180.0,
                    "acquired_at": "2026-10-30T00:00:00",
                    "heartbeat_at": "2026-10-30T00:00:00",
                    "released": False,
                },
            }
        ),
        encoding="utf-8",
    )
    ok, code, _ = guard.check_lease(p, HOLDER)
    assert ok is False
    assert code == guard.RC_LEASE_CORRUPT


def test_flat_lease_document_refuses(tmp_path: Path):
    """**平铺**格式（不是 GM 落盘格式）必须被拒 —— 不接受「猜格式」。"""
    p = tmp_path / "l.json"
    p.write_text(
        json.dumps(
            {
                "schema": guard.LEASE_SCHEMA,
                "holder": HOLDER,
                "generation": 1,
                "ttl_s": 180.0,
                "acquired_at": datetime.now(timezone.utc).isoformat(),
                "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "released": False,
            }
        ),
        encoding="utf-8",
    )
    ok, code, _ = guard.check_lease(p, HOLDER)
    assert ok is False
    assert code == guard.RC_LEASE_CORRUPT


def test_valid_lease_allows(tmp_path: Path):
    p = _write_lease(tmp_path / "l.json")
    ok, code, _ = guard.check_lease(p, HOLDER)
    assert ok is True
    assert code == guard.RC_WRITE_ACCEPTED


# ── 外部写检测 ─────────────────────────────────────────────────────────

def test_external_write_detected_refuses_push(arena):
    """远端被另一写者推进 ⇒ 我的推送被拒（**且远端不被我改动**）。"""
    _write_lease(arena["lease"])
    mine, other = arena["mine"], arena["other"]

    _commit(other, "other.txt", "other\n", "other writer")
    _git(other, "push", "-q", "origin", "HEAD:refs/heads/feature")
    tip_before = guard.remote_tip(mine, "feature")

    _commit(mine, "mine.txt", "mine\n", "my commit")
    res = guard.guarded_push(mine, "feature", arena["lease"], HOLDER)

    assert res["ok"] is False
    assert res["reason_code"] == guard.RC_EXTERNAL_WRITE
    assert res["pushed"] is False
    assert guard.remote_tip(mine, "feature") == tip_before, "被拒的推送不得改动远端"


def test_no_external_write_allows_push(arena):
    _write_lease(arena["lease"])
    mine = arena["mine"]
    _commit(mine, "mine.txt", "mine\n", "my commit")
    res = guard.preflight(mine, "feature", arena["lease"], HOLDER)
    assert res["ok"] is True
    assert res["action"] == "ALLOWED"


def test_unreachable_remote_refuses(tmp_path: Path):
    """远端读不到 ⇒ 无法证明「没有外部写入」⇒ fail-closed。"""
    p = _write_lease(tmp_path / "l.json")
    repo = tmp_path / "no-remote"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _git(repo, "config", "user.email", "x@example.invalid")
    _git(repo, "config", "user.name", "x")
    _commit(repo, "a.txt", "a\n", "init")
    res = guard.preflight(repo, "feature", p, HOLDER)
    assert res["ok"] is False
    assert res["reason_code"] == guard.RC_EXTERNAL_WRITE


# ── 推送行为 ───────────────────────────────────────────────────────────

def test_guarded_push_advances_remote(arena):
    """正常快进：远端 tip 正好变成我的 commit。"""
    _write_lease(arena["lease"])
    mine = arena["mine"]
    head = _commit(mine, "mine.txt", "mine\n", "my commit")

    res = guard.guarded_push(mine, "feature", arena["lease"], HOLDER)
    assert res["ok"] is True, res
    assert res["pushed"] is True
    assert res["remote_tip_after"] == head
    assert guard.remote_tip(mine, "feature") == head


def test_push_without_lease_does_not_touch_remote(arena):
    """失租 ⇒ 远端一个字节都不动。"""
    mine = arena["mine"]
    head = _commit(mine, "mine.txt", "mine\n", "my commit")
    tip_before = guard.remote_tip(mine, "feature")

    res = guard.guarded_push(mine, "feature", arena["lease"], HOLDER)
    assert res["ok"] is False
    assert res["pushed"] is False
    assert res["reason_code"] == guard.RC_NO_LEASE
    assert guard.remote_tip(mine, "feature") == tip_before
    # 本地提交仍在（守卫只拦远端写，不毁本地工作）
    assert _git(mine, "rev-parse", "HEAD") == head


def test_expired_lease_does_not_touch_remote(arena):
    """过期租约 ⇒ 远端不动（与「不存在」同一处置）。"""
    old = datetime.now(timezone.utc) - timedelta(seconds=600)
    _write_lease(arena["lease"], ttl_s=180.0, heartbeat_at=old)
    mine = arena["mine"]
    _commit(mine, "mine.txt", "mine\n", "my commit")
    tip_before = guard.remote_tip(mine, "feature")

    res = guard.guarded_push(mine, "feature", arena["lease"], HOLDER)
    assert res["ok"] is False
    assert res["reason_code"] == guard.RC_LEASE_EXPIRED
    assert guard.remote_tip(mine, "feature") == tip_before


def test_push_writes_audit(arena, tmp_path: Path):
    """每次判定都留 append-only 审计。"""
    _write_lease(arena["lease"])
    mine = arena["mine"]
    _commit(mine, "mine.txt", "mine\n", "my commit")
    audit = tmp_path / "audit.jsonl"
    guard.guarded_push(mine, "feature", arena["lease"], HOLDER, audit_path=audit)
    lines = [json.loads(x) for x in audit.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert lines and lines[-1]["action"] == "PUSHED"
