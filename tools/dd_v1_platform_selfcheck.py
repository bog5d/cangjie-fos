#!/usr/bin/env python3
"""DD-V1 **平台自检 / 一键复跑**（Windows 真机交接的关键路径工具）。

★ **为什么需要它**：交接包原本给的是**分步命令**（7 步，含 PowerShell 手工搬文件）。
  手工搬运在 Windows 上最容易漏文件 ⇒ 门禁找不到运行清单 ⇒ 复核判不出 R10。
  ⇒ 本工具把「环境预检 → 跑测试 → 跑三场考试 → 门禁判定 → 覆盖率 →
  **产物哈希清单** → 一屏摘要」收成**一条命令**，并**把失败原因与下一步写清楚**。

★ **三条硬纪律**：
1. **不覆盖任何人的成果**：全部产物落在**自己的输出目录**（默认
   ``.audit/platform-selfcheck/<时间戳>/``），**不写**仓内 ``.audit/gate-runs/``
   ⇒ 刘江在真机上跑，**不会**把施工者的证据面覆盖掉。
2. **证据自带哈希**：产出的每个文件都进 ``SHA256SUMS``（**不含自身**）
   ⇒ 复核方能独立验证「他交上来的结果没被改过」。
3. **平台信息进证据**：运行清单里记 **OS 版本 / 架构 / Python 实现**
   ⇒ R10「Windows 真机」有**可核**的形态，而不是靠一句「我在 Windows 上跑的」。

**用法**::

    # 0) 只做环境预检（不跑考试）
    python tools/dd_v1_platform_selfcheck.py preflight

    # 1) 一键全量复跑（CI 口径的全量 pytest ＋ 三场考试 ＋ 门禁 ＋ 覆盖率）
    python tools/dd_v1_platform_selfcheck.py run --out .audit/platform-selfcheck/win

    # 2) 缩减复跑（只跑 L1/L2/L3 ＋ 三场考试；摘要里会**明确标注**「非全量」）
    python tools/dd_v1_platform_selfcheck.py run --steps quick --out <dir>

    # 3) 独立验证某次复跑的产物完整性
    python tools/dd_v1_platform_selfcheck.py verify --out <dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SUITE = "dd_v1_exam_suite"
CST = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ── 步骤执行 ────────────────────────────────────────────────────────────

def run_step(
    name: str,
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 3600,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """跑一步，**如实**记下 rc / 耗时 / 输出尾部。

    ★ 失败**不抛异常**：返回结构化结果，由调用方决定停在哪一步、怎么报。
    """
    t0 = time.time()
    full_env = {**os.environ, **(env or {})}
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd or REPO),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=full_env,
        )
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        rc = 124
        out = exc.stdout or ""
        err = (exc.stderr or "") + f"\n[TIMEOUT] 超过 {timeout}s 未完成"
        timed_out = True
    except OSError as exc:
        rc, out, err, timed_out = 127, "", f"[OSERROR] {exc}", False
    return {
        "name": name,
        "cmd": cmd,
        "rc": rc,
        "ok": rc == 0,
        "timed_out": timed_out,
        "elapsed_s": round(time.time() - t0, 2),
        "stdout_tail": out[-4000:],
        "stderr_tail": err[-4000:],
    }


# ── 环境预检 ────────────────────────────────────────────────────────────

def preflight() -> dict[str, Any]:
    """环境预检 —— 每项都**真跑一次**，不靠猜。"""
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, *, fatal: bool = True) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "fatal": fatal})

    # Python 版本
    v = sys.version_info
    add("python>=3.11", v >= (3, 11), f"{platform.python_implementation()} {sys.version.split()[0]}")

    # git 可用 + 当前提交
    git_sha = ""
    try:
        p = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                           capture_output=True, text=True, encoding="utf-8")
        git_sha = p.stdout.strip()
        add("git 可用", p.returncode == 0, git_sha or "git rev-parse 失败")
    except OSError as exc:
        add("git 可用", False, f"git 不可用：{exc}")

    # 后端依赖是否装齐（用真正会被 import 的模块探）
    missing: list[str] = []
    probe = """
import importlib, sys
mods = ["pytest", "pydantic", "fastapi", "httpx"]
bad = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception:
        bad.append(m)
sys.exit(1 if bad else 0)
"""
    p = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                       cwd=str(REPO / "backend"))
    if p.returncode != 0:
        missing = ["pytest/pydantic/fastapi/httpx 之一缺失"]
    add("backend 依赖", not missing, "齐备" if not missing else "缺：" + "、".join(missing))

    # 数据面可写（隔离考场目录在仓库之外）
    plane = Path(os.environ.get("DDV1_EXAM_PLANE")
                 or (Path.home() / ".cangjie-ddv1-exams"))
    try:
        plane.mkdir(parents=True, exist_ok=True)
        probe_file = plane / ".write_probe"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink()
        add("数据面可写", True, str(plane))
    except OSError as exc:
        add("数据面可写", False, f"{plane} 不可写：{exc}")

    # 磁盘余量（考试产物 + JUnit XML 不小）
    try:
        usage = shutil.disk_usage(REPO)
        free_mb = usage.free // (1024 * 1024)
        add("磁盘余量 ≥ 500MB", free_mb >= 500, f"{free_mb} MB")
    except OSError as exc:
        add("磁盘余量 ≥ 500MB", False, f"读不到：{exc}", fatal=False)

    return {
        "checked_at": now_iso(),
        "environment": {
            "platform": sys.platform,
            "platform_release": platform.platform(),
            "platform_version": platform.version(),
            "os_name": platform.system(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "python_implementation": platform.python_implementation(),
            "python_version_full": sys.version.replace("\n", " "),
            "git_sha": git_sha,
            "repo": str(REPO),
        },
        "checks": checks,
        "ok": all(c["ok"] for c in checks if c["fatal"]),
    }


# ── 证据包 ──────────────────────────────────────────────────────────────

def write_sha256sums(root: Path) -> Path:
    """给 ``root`` 下**全部文件**（除 ``SHA256SUMS`` 自己）写哈希清单。"""
    sums = root / "SHA256SUMS"
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    lines = [f"{sha256(p)}  {p.relative_to(root).as_posix()}" for p in files]
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sums


def verify_sha256sums(root: Path) -> dict[str, Any]:
    """独立复算 ``SHA256SUMS``（**只读**）。"""
    sums = root / "SHA256SUMS"
    out: dict[str, Any] = {"root": str(root), "present": sums.is_file(),
                           "checked": 0, "bad": [], "missing": [], "ok": False}
    if not out["present"]:
        out["error"] = "SHA256SUMS_MISSING"
        return out
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, rel = line.partition("  ")
        rel = rel.strip()
        target = root / rel
        out["checked"] += 1
        if not target.is_file():
            out["missing"].append(rel)
        elif sha256(target) != digest.strip():
            out["bad"].append(rel)
    out["ok"] = not out["bad"] and not out["missing"]
    return out


# ── 一键复跑 ────────────────────────────────────────────────────────────

def one_shot(out_dir: Path, *, steps: str = "full", keep_going: bool = False) -> dict[str, Any]:
    py = sys.executable
    suite = REPO / "tools" / f"{SUITE}.py"
    out_dir = out_dir.resolve()
    steps_dir = out_dir / "steps"
    gate_dir = out_dir / "gate-runs"
    steps_dir.mkdir(parents=True, exist_ok=True)
    gate_dir.mkdir(parents=True, exist_ok=True)

    pf = preflight()
    record: dict[str, Any] = {
        "schema_version": "dd_v1_platform_selfcheck.v1",
        "started_at": now_iso(),
        "mode": steps,
        "out_dir": str(out_dir),
        "preflight": pf,
        "steps": [],
        "exam_artifacts": [],
        "verdict": "FAIL",
        "failed_step": None,
        "next_action": None,
    }

    if not pf["ok"]:
        bad = [c["name"] for c in pf["checks"] if not c["ok"] and c["fatal"]]
        record["failed_step"] = "preflight"
        record["next_action"] = (
            "环境预检未通过：" + "、".join(bad)
            + "。先按 `复跑命令.md` 第 0 步装好环境（backend 目录 `pip install -e \".[dev]\"`），再重跑。"
        )
        _finalize(record, out_dir)
        return record

    plane = os.environ.get("DDV1_EXAM_PLANE") or str(Path.home() / ".cangjie-ddv1-exams")
    env = {"DDV1_EXAM_PLANE": plane}

    plan: list[tuple[str, list[str], Path]] = []
    l123 = [
        "tests/test_dd_v1_exam_suite_l1.py",
        "tests/test_dd_v1_exam_suite_l2.py",
        "tests/test_dd_v1_model_participation_l3.py",
    ]
    for exam in ("A", "B", "C"):
        plan.append((
            f"考试 {exam}（RULE_ONLY）",
            [py, str(suite), "run", "--exam", exam, "--run-mode", "RULE_ONLY",
             "--out", str(gate_dir / exam)],
            REPO,
        ))
    if steps == "full":
        # ★ `pytest-report` **自己就跑 pytest**（还带代理口径处理与 JUnit XML 落盘）
        #   ⇒ 不再单独跑一遍全量（避免重复劳动与两套口径）。
        plan.append((
            "G1 机读报告（内部跑全量 pytest · CI 口径 · 排除 doctor）",
            [py, str(suite), "pytest-report", "--out", str(gate_dir / "g1_pytest.json"),
             "--tests", "tests/"],
            REPO,
        ))
    else:
        plan.append((
            "G1 机读报告（★ 缩减口径：只跑 L1/L2/L3，**非全量**）",
            [py, str(suite), "pytest-report", "--out", str(gate_dir / "g1_pytest.json"),
             "--tests", *l123],
            REPO,
        ))
    plan.append((
        "门禁判定 G1—G8",
        [py, str(suite), "gate", "--runs", str(gate_dir), "--out", str(gate_dir / "门禁报告.json")],
        REPO,
    ))
    plan.append((
        "覆盖率报告",
        [py, str(suite), "coverage", "--runs", str(gate_dir),
         "--out", str(gate_dir / "覆盖率报告.json")],
        REPO,
    ))

    for name, cmd, cwd in plan:
        res = run_step(name, cmd, cwd=cwd, env=env)
        res["stdout_file"] = f"steps/{len(record['steps']) + 1:02d}-{name}.stdout.txt"
        res["stderr_file"] = f"steps/{len(record['steps']) + 1:02d}-{name}.stderr.txt"
        (out_dir / res["stdout_file"]).write_text(res.pop("stdout_tail") or "", encoding="utf-8")
        (out_dir / res["stderr_file"]).write_text(res.pop("stderr_tail") or "", encoding="utf-8")
        record["steps"].append(res)
        if not res["ok"] and not keep_going:
            record["failed_step"] = name
            record["next_action"] = (
                f"步骤「{name}」失败（rc={res['rc']}"
                + ("，超时" if res.get("timed_out") else "")
                + "）。完整输出见 "
                + f"`{res['stdout_file']}` / `{res['stderr_file']}`。"
                + "★ 请把这两个文件连同本摘要一起回给施工者；**不要**自行改判据。"
            )
            break

    # 收集考试产物（供 R10 复核者核「哪台机器跑的、跑出什么」）
    for exam in ("A", "B", "C"):
        mf = gate_dir / exam / "运行清单.json"
        if mf.is_file():
            try:
                m = json.loads(mf.read_text(encoding="utf-8"))
                env_blk = m.get("environment") or {}
                res_blk = m.get("results") or {}
                scores_blk = res_blk.get("scores") or {}
                record["exam_artifacts"].append({
                    "exam": exam,
                    "manifest": str(mf.relative_to(out_dir)),
                    "run_id": m.get("run_id"),
                    "git_sha": m.get("git_sha"),
                    "platform": env_blk.get("platform"),
                    "platform_release": env_blk.get("platform_release"),
                    "os_name": env_blk.get("os_name"),
                    "machine": env_blk.get("machine"),
                    "python": env_blk.get("python"),
                    # ★ 总分在 ``results.scores.total_score``（不是 ``results.total_score``）
                    "total_score": scores_blk.get("total_score"),
                    "score_name": ((res_blk.get("score_split") or {}).get("score_name")),
                    "status": res_blk.get("status"),
                    "examined_mode": ((res_blk.get("run_provenance") or {}).get("examinee_mode")
                                      or (m.get("model") or {}).get("examinee_mode")),
                    "execution_path": ((res_blk.get("run_provenance") or {}).get("execution_path")
                                       or (m.get("model") or {}).get("execution_path")),
                    "participated": (m.get("model") or {}).get("participated"),
                })
            except (OSError, ValueError) as exc:
                record["exam_artifacts"].append({"exam": exam, "error": str(exc)})

    # 门禁读数
    gate_report = gate_dir / "门禁报告.json"
    if gate_report.is_file():
        try:
            g = json.loads(gate_report.read_text(encoding="utf-8"))
            record["gate"] = {
                "status": g.get("status"),
                "failed_key_gates": g.get("failed_key_gates"),
                "reviewer_verdict": g.get("reviewer_verdict"),
                "gates": {k: v.get("status") for k, v in (g.get("gates") or {}).items()},
            }
        except (OSError, ValueError) as exc:
            record["gate"] = {"error": str(exc)}

    if record["failed_step"] is None:
        gate = record.get("gate") or {}
        if gate.get("status") == "PASS":
            record["verdict"] = "PASS"
            record["next_action"] = (
                "本机复跑全绿。把整个输出目录（含 `SHA256SUMS` 与 `selfcheck.json`）"
                "交给施工者/复核者；对方用 `verify --out <目录>` 独立复算即可。"
            )
        else:
            record["verdict"] = "FAIL"
            failed = gate.get("failed_key_gates") or []
            extra = ""
            if record.get("mode") == "quick":
                extra = ("★ 本次是**缩减复跑**（G1 只覆盖 L1/L2/L3，**不是全量**）"
                         "⇒ G1 的用例数天然偏小，**不得**据此判断全量健康度。")
            record["next_action"] = (
                "复跑本身**跑完了**，但门禁未全绿（failed_key_gates="
                + json.dumps(failed, ensure_ascii=False)
                + "）。★ 这**不等于**复跑出错：G6 只认独立复核 `PASS`"
                "（amendment A7/A8）⇒ 在独立复核给出 PASS 之前，"
                "**预期就是 FAIL**。" + extra
                + "请把整个输出目录交回。"
            )
    _finalize(record, out_dir)
    return record


def _finalize(record: dict[str, Any], out_dir: Path) -> None:
    """收尾：写摘要 ＋ 产物哈希清单 ＋ 一屏输出。"""
    record["finished_at"] = now_iso()
    record["sha256sums"] = "SHA256SUMS"
    (out_dir / "selfcheck.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_sha256sums(out_dir)
    print(render_summary(record))


def render_summary(record: dict[str, Any]) -> str:
    env = (record.get("preflight") or {}).get("environment") or {}
    lines = [
        "【DD-V1 平台自检 · 一键复跑】",
        f"平台      : {env.get('os_name')} {env.get('platform_release')}（{env.get('platform')} / {env.get('machine')}）",
        f"Python    : {env.get('python')}（{env.get('python_implementation')}）",
        f"提交      : {env.get('git_sha')}",
        f"模式      : {record.get('mode')}" + ("（★ 缩减复跑，**非全量**）" if record.get("mode") == "quick" else "（全量）"),
        f"输出目录  : {record.get('out_dir')}",
        "",
        "步骤：",
    ]
    for s in record.get("steps") or []:
        mark = "✅" if s.get("ok") else "❌"
        lines.append(f"  {mark} {s.get('name')}  rc={s.get('rc')}  {s.get('elapsed_s')}s")
    pf = (record.get("preflight") or {}).get("checks") or []
    if any(not c["ok"] for c in pf):
        lines.append("  预检：")
        for c in pf:
            lines.append(f"    {'✅' if c['ok'] else '❌'} {c['name']} —— {c['detail']}")
    art = record.get("exam_artifacts") or []
    if art:
        lines.append("")
        lines.append("考试产物：")
        for a in art:
            lines.append(
                f"  {a.get('exam')}: run_id={a.get('run_id')} 平台={a.get('platform')}"
                f"（{a.get('platform_release')}） 总分={a.get('total_score')}"
                f" 模式={a.get('examined_mode')} 状态={a.get('status')}"
            )
    gate = record.get("gate") or {}
    if gate:
        lines.append("")
        lines.append(f"门禁：status={gate.get('status')}  failed_key_gates="
                     f"{json.dumps(gate.get('failed_key_gates'), ensure_ascii=False)}")
        lines.append("  逐门：" + "  ".join(
            f"{k}={v}" for k, v in sorted((gate.get("gates") or {}).items())
        ))
    lines.append("")
    lines.append(f"结论：{record.get('verdict')}")
    if record.get("next_action"):
        lines.append("下一步：" + record["next_action"])
    lines.append("")
    lines.append("★ 本目录已生成 `SHA256SUMS`（含全部产物哈希，不含自身）"
                 "⇒ 交接前请用 `verify --out <目录>` 独立复算。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DD-V1 平台自检 / 一键复跑")
    ap.add_argument("action", choices=["preflight", "run", "verify"])
    ap.add_argument("--out", default=None, help="输出目录（run/verify 必填或用默认）")
    ap.add_argument("--steps", choices=["full", "quick"], default="full")
    ap.add_argument("--keep-going", action="store_true", help="某步失败后继续跑（默认停在首个失败步）")
    args = ap.parse_args(argv)

    if args.action == "preflight":
        pf = preflight()
        print(json.dumps(pf, ensure_ascii=False, indent=2))
        return 0 if pf["ok"] else 1

    if args.action == "verify":
        if not args.out:
            print("verify 需要 --out <目录>", file=sys.stderr)
            return 2
        res = verify_sha256sums(Path(args.out))
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 1

    out = Path(args.out) if args.out else (
        REPO / ".audit" / "platform-selfcheck"
        / datetime.now(CST).strftime("%Y%m%dT%H%M%S")
    )
    rec = one_shot(out, steps=args.steps, keep_going=args.keep_going)
    return 0 if rec.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
