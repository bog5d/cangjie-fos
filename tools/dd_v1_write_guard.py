#!/usr/bin/env python3
"""DD-V1 **单写者写入守卫**（最小必要的写入校验机制）。

**为什么需要它**：DD-V1 的交付面是**一串堆叠分支**（PR#86 → PR#87 → PR#88），
同一时刻只允许**一个施工者**写。历史事故形态有两个：

1. **失租仍写**：旧施工者会话恢复后继续推，覆盖新持有者的成果；
2. **双写交错**：两个施工者各自 push，同一分支上出现互相不可见的提交。

本工具把「失租不写 / 外写不盖」变成**机器判定**，不靠人记得住：

- **租约校验**：读 GM 自己的租约文档（``gm.continuity_v2.lease.v1``），
  校验「存在 ∧ 未 released ∧ 未过期 ∧ holder 是我」；
  任一条不成立 ⇒ **拒绝写入**（fail-closed），reason code 沿用 GM 词汇
  （``FENCING_NO_LEASE`` / ``FENCING_LEASE_EXPIRED`` / ``FENCING_LEASE_RELEASED`` /
  ``FENCING_HOLDER_MISMATCH``）。
- **外部写检测**：推送前读远端分支 tip，判定它是否是我本地 HEAD 的祖先；
  不是 ⇒ **远端有我不知道的提交** ⇒ 拒绝推送（而不是让 git 报一个难懂的
  non-fast-forward），并如实报出分叉点。
- **只快进**：``git push`` **不带** ``--force``／``--force-with-lease``；
  推送后核「远端新 tip == 我这次的 commit sha」，不一致即判失败。

★ **本工具不调度、不派工、不持有权威状态**：它只是 GM 租约的**消费侧执行者**，
真正的租约权威仍是 GM 的 ``LeaseStore``（写在那台机器的状态根上）。
★ **不复制 GM 的判定语义**：租约文档格式与过期规则直接对齐
  ``gm.continuity_v2.lease``（schema 常量 + ``heartbeat_at + ttl_s``），语义相同。

**用法**::

    python tools/dd_v1_write_guard.py preflight --branch feat/xxx \\
        --lease /path/to/lease.json --holder cloud-ddv1:<instance>
    python tools/dd_v1_write_guard.py push --branch feat/xxx \\
        --lease /path/to/lease.json --holder cloud-ddv1:<instance>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

#: GM 租约文档的 schema（与 ``gm.continuity_v2.lease.LEASE_SCHEMA`` 逐字一致）。
LEASE_SCHEMA = "gm.continuity_v2.lease.v1"

# ── reason code（沿用 GM 词汇，便于直接落审计） ──────────────────────────
RC_NO_LEASE = "FENCING_NO_LEASE"
RC_LEASE_EXPIRED = "FENCING_LEASE_EXPIRED"
RC_LEASE_RELEASED = "FENCING_LEASE_RELEASED"
RC_HOLDER_MISMATCH = "FENCING_HOLDER_MISMATCH"
RC_WRITE_ACCEPTED = "FENCING_WRITE_ACCEPTED"
RC_EXTERNAL_WRITE = "FENCING_EXTERNAL_WRITE_DETECTED"
RC_PUSH_REJECTED = "FENCING_PUSH_REJECTED"
#: 推送**可能已落地**但复核读不到远端（传输层抖动）—— 与「不一致」是两回事，
#: **不得混为一谈**：前者是「不可验证」，后者是「验证为否」。
RC_PUSH_UNVERIFIED = "FENCING_PUSH_UNVERIFIED"

#: 租约文档结构非法（读得出来但字段不对）—— 同样 fail-closed。
RC_LEASE_CORRUPT = "FENCING_LEASE_CORRUPT"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw: Any) -> datetime | None:
    """只接受带时区的 ISO-8601；naive 一律拒绝（避免本地时区把新旧混算）。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return None if ts.tzinfo is None else ts.astimezone(timezone.utc)


def read_lease(path: str | Path) -> dict[str, Any] | None:
    """读租约文档。文件不存在 ⇒ ``None``（调用方判 ``FENCING_NO_LEASE``）。"""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def check_lease(
    lease_path: str | Path,
    expected_holder: str,
    now: datetime | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """租约判定。返回 ``(是否放行, reason_code, 详情)``。

    ★ **fail-closed**：读不到、字段非法、已过期、已释放、holder 不是我 —— 一律拒绝。
    """
    now = now or _now()
    detail: dict[str, Any] = {"expected_holder": expected_holder}

    doc = read_lease(lease_path)
    if doc is None:
        return False, RC_NO_LEASE, {**detail, "lease_path": str(lease_path)}

    schema = doc.get("schema")
    # ★ GM 的落盘格式是**嵌套**的：``{"schema": ..., "lease": {holder, generation, ...}}``
    #   （见 ``gm.continuity_v2.lease.LeaseStore._write_lease_unlocked``）。
    #   这里**逐字对齐**该格式，不按平铺猜。
    rec = doc.get("lease")
    if not isinstance(rec, dict):
        return False, RC_LEASE_CORRUPT, {**detail, "schema": schema}

    holder = rec.get("holder")
    generation = rec.get("generation")
    ttl_s = rec.get("ttl_s")
    heartbeat_at = _parse_ts(rec.get("heartbeat_at"))
    released = rec.get("released")

    detail.update(
        {
            "schema": schema,
            "holder": holder,
            "generation": generation,
            "ttl_s": ttl_s,
            "heartbeat_at": rec.get("heartbeat_at"),
            "released": released,
        }
    )

    if schema != LEASE_SCHEMA:
        return False, RC_LEASE_CORRUPT, detail
    if not isinstance(holder, str) or not holder.strip():
        return False, RC_LEASE_CORRUPT, detail
    if isinstance(generation, bool) or not isinstance(generation, int):
        return False, RC_LEASE_CORRUPT, detail
    if isinstance(ttl_s, bool) or not isinstance(ttl_s, (int, float)) or ttl_s <= 0:
        return False, RC_LEASE_CORRUPT, detail
    if heartbeat_at is None:
        return False, RC_LEASE_CORRUPT, detail

    # 已释放的租约**永不**新鲜（TTL 归零不足以表达「交出去了」）。
    if released is True:
        return False, RC_LEASE_RELEASED, detail
    if now - heartbeat_at > timedelta(seconds=float(ttl_s)):
        return False, RC_LEASE_EXPIRED, {
            **detail,
            "expired_by_s": round((now - heartbeat_at).total_seconds() - float(ttl_s), 3),
        }
    if holder != expected_holder:
        return False, RC_HOLDER_MISMATCH, detail

    return True, RC_WRITE_ACCEPTED, detail


def _git(repo: str | Path, *args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _git_retry(
    repo: str | Path, *args: str, attempts: int = 3
) -> tuple[int, str, str]:
    """只读 git 命令**重试**。

    ★ 沙箱里 git over HTTPS 是**间歇性**通道（TLS 握手会被腰斩）。
      ★ **一次失败不等于「远端没有」** —— 必须重试到命中或用尽次数，
        且**读不到**与**读到「没有」**在结论上要分开（fail-closed ≠ 误判）。
    """
    rc, out, err = 1, "", ""
    for attempt in range(attempts):
        rc, out, err = _git(repo, *args)
        if rc == 0:
            return rc, out, err
        if attempt + 1 < attempts:
            time.sleep(0.8 * (attempt + 1))
    return rc, out, err


def remote_tip(repo: str | Path, branch: str) -> str | None:
    """读远端分支 tip。读不到（网络/权限/分支不存在）⇒ ``None``。"""
    rc, out, _ = _git_retry(repo, "ls-remote", "origin", f"refs/heads/{branch}")
    if rc != 0 or not out:
        return None
    parts = out.split()
    return parts[0] if parts else None


def is_ancestor(repo: str | Path, ancestor: str, descendant: str) -> bool:
    """``ancestor`` 是否是 ``descendant`` 的祖先（= 推 ``descendant`` 是快进）。"""
    rc, _, _ = _git(repo, "merge-base", "--is-ancestor", ancestor, descendant)
    return rc == 0


def local_head(repo: str | Path) -> str | None:
    rc, out, _ = _git(repo, "rev-parse", "HEAD")
    return out if rc == 0 and out else None


def preflight(
    repo: str | Path,
    branch: str,
    lease_path: str | Path,
    expected_holder: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """推送前判定。**不写任何远端。**

    返回 ``{"ok": bool, "reason_code": str, ...}``。
    """
    now = now or _now()
    ok, code, detail = check_lease(lease_path, expected_holder, now)

    head = local_head(repo)
    tip = remote_tip(repo, branch)
    verdict: dict[str, Any] = {
        "ok": ok,
        "reason_code": code,
        "branch": branch,
        "repo": str(repo),
        "local_head": head,
        "remote_tip": tip,
        "lease": detail,
        "checked_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
    }

    if not ok:
        verdict["action"] = "REFUSED_NO_WRITE"
        return verdict

    if tip is None:
        # 远端读不到 ⇒ 无法证明「远端没有别人的提交」⇒ fail-closed。
        verdict.update(
            {
                "ok": False,
                "reason_code": RC_EXTERNAL_WRITE,
                "action": "REFUSED_NO_WRITE",
                "detail": "远端 tip 不可得（读不到分支）⇒ 无法证明无外部写入，拒绝推送",
            }
        )
        return verdict

    if head and head != tip and not is_ancestor(repo, tip, head):
        verdict.update(
            {
                "ok": False,
                "reason_code": RC_EXTERNAL_WRITE,
                "action": "REFUSED_NO_WRITE",
                "detail": (
                    f"远端 tip {tip} 不是本地 HEAD {head} 的祖先 ⇒ "
                    "远端存在我未包含的提交（外部写入者），拒绝快进推送"
                ),
            }
        )
        return verdict

    verdict["action"] = "ALLOWED"
    verdict["fast_forward"] = bool(head and head != tip)
    return verdict


def guarded_push(
    repo: str | Path,
    branch: str,
    lease_path: str | Path,
    expected_holder: str,
    now: datetime | None = None,
    remote: str = "origin",
    audit_path: str | Path | None = None,
) -> dict[str, Any]:
    """受保护推送：**先判租约，再判外部写，最后才推**，推完核 tip。

    ★ 推送**永不**带 force / force-with-lease。
    """
    now = now or _now()
    pf = preflight(repo, branch, lease_path, expected_holder, now)
    if not pf.get("ok"):
        pf["pushed"] = False
        _append_audit(audit_path, pf)
        return pf

    head = pf["local_head"]
    rc, out, err = _git(repo, "push", remote, f"HEAD:refs/heads/{branch}")
    result = {
        **pf,
        "pushed": rc == 0,
        "push_rc": rc,
        "push_stdout": out[-2000:],
        "push_stderr": err[-2000:],
    }
    if rc != 0:
        # ★ 传输层失败（TLS 抖动等）**不等于**「没推上去」—— 可能已落地。
        #   先读远端 tip 判事实，再决定要不要**重推同一 commit**（幂等）。
        tip_now = remote_tip(repo, branch)
        if tip_now == head:
            result.update(
                {
                    "ok": True,
                    "pushed": True,
                    "action": "PUSHED",
                    "detail": "push 返回非零，但远端 tip 已等于我的 commit ⇒ 实际已落地（传输层报错）",
                }
            )
            _append_audit(audit_path, result)
            return result
        result.update(
            {
                "ok": False,
                "reason_code": RC_PUSH_REJECTED,
                "action": "REFUSED_NO_WRITE",
                "remote_tip_now": tip_now,
                "detail": "推送失败且远端 tip 不等于我的 commit ⇒ 未落地（需人工核对）",
            }
        )
        _append_audit(audit_path, result)
        return result

    tip_after = remote_tip(repo, branch)
    result["remote_tip_after"] = tip_after
    if tip_after is None:
        # ★ **读不到 ≠ 不一致**：只能判「不可验证」，不得谎称「不一致」。
        result.update(
            {
                "ok": False,
                "reason_code": RC_PUSH_UNVERIFIED,
                "action": "PUSHED_BUT_UNVERIFIED",
                "detail": (
                    "推送返回成功，但复核时远端 tip **读不到**（通道抖动/权限）"
                    "⇒ 判「不可验证」，需另路现读核实（不得写成「不一致」）"
                ),
            }
        )
    elif tip_after != head:
        result.update(
            {
                "ok": False,
                "reason_code": RC_PUSH_REJECTED,
                "action": "PUSHED_BUT_TIP_MISMATCH",
                "detail": f"推送后远端 tip {tip_after} != 我的 commit {head}",
            }
        )
    else:
        result["action"] = "PUSHED"
    _append_audit(audit_path, result)
    return result


def _append_audit(audit_path: str | Path | None, doc: dict[str, Any]) -> None:
    """append-only 审计（判定与结果都留痕）。"""
    if audit_path is None:
        return
    p = Path(audit_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(doc, ensure_ascii=False, sort_keys=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DD-V1 单写者写入守卫")
    ap.add_argument("action", choices=["preflight", "push"])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--branch", required=True)
    ap.add_argument("--lease", required=True, help="GM 租约文档路径")
    ap.add_argument("--holder", required=True, help="期望的租约持有者")
    ap.add_argument("--audit", default=None, help="append-only 审计文件路径")
    ap.add_argument("--remote", default="origin")
    args = ap.parse_args(argv)

    if args.action == "preflight":
        res = preflight(args.repo, args.branch, args.lease, args.holder)
    else:
        res = guarded_push(
            args.repo,
            args.branch,
            args.lease,
            args.holder,
            remote=args.remote,
            audit_path=args.audit,
        )
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
