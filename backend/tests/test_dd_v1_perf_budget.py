"""P5：性能与可靠性（施工令 V3.0 §P5）。

覆盖：
- **分 Agent 超时预算**（不许机械地把所有超时统一成 420 秒）；
- **重试退避**（失败恢复）+ **总墙钟上限**（杜绝无限等待）；
- **并发护栏**（同一进程内同时在飞的 Agent 调用 ≤ 1）；
- **成本/耗时记账**（可复算）。

全部用 Python 假 CLI，**不联网、不调用真实模型**。
"""
from __future__ import annotations

import json
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_agent_adapters as ad

FX = Path(__file__).parent / "fixtures" / "dd_v1_fos71"
SNAP = FX / "snapshot"
META = json.loads((FX / "meta.json").read_text("utf-8"))
OBS = json.loads((FX / "obligations.json").read_text("utf-8"))


def _fake(tmp_path: Path, name: str, body: str) -> list[str]:
    p = tmp_path / "bin" / f"{name}.py"
    p.parent.mkdir(exist_ok=True)
    p.write_text("import sys, os, json, time\n" + textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, str(p)]


def _wd(tmp_path, name="wd"):
    d = tmp_path / name
    d.mkdir()
    return d


# ─────────────────────────────────────────────────── 分 Agent 超时预算

def test_timeout_budgets_are_per_agent_not_uniform():
    """每个 Agent 的超时**不同**；且**没有**哪个被统一设成 420。"""
    vals = set(ad.AGENT_TIMEOUT_BUDGETS.values())
    assert len(vals) > 1, "所有 Agent 用同一个超时 = 机械统一，禁止"
    assert 420.0 not in vals, "不许把所有超时统一设成 420 秒"
    assert ad.AGENT_TIMEOUT_BUDGETS["pi"] != ad.AGENT_TIMEOUT_BUDGETS["deepseek-harness"]
    assert ad.AGENT_TIMEOUT_BUDGETS["codex-cli"] != ad.AGENT_TIMEOUT_BUDGETS["pi"]


def test_budget_for_framework_uses_table():
    for fw, t in ad.AGENT_TIMEOUT_BUDGETS.items():
        b = ad.budget_for_framework(fw)
        assert b.timeout_s == t
        assert b.max_calls == 2, "默认应允许 1 次重试（失败恢复）"
        assert b.max_total_s >= b.timeout_s, "总墙钟上限必须 ≥ 单次超时，否则第一次就会被砍"


def test_budget_for_framework_explicit_override_wins():
    b = ad.budget_for_framework("pi", timeout_s=42.0)
    assert b.timeout_s == 42.0
    assert b.max_total_s >= 42.0


def test_budget_for_framework_rejects_bad_values():
    with pytest.raises(ValueError):
        ad.budget_for_framework("pi", timeout_s=0)
    with pytest.raises(ValueError):
        ad.budget_for_framework("pi", timeout_s=-1)
    with pytest.raises(ValueError):
        ad.budget_for_framework("pi", max_calls=0)


def test_unknown_framework_gets_fallback_not_zero():
    b = ad.budget_for_framework("不存在的框架")
    assert b.timeout_s == ad.DEFAULT_TIMEOUT_S > 0


def test_adapter_framework_is_framework_not_vendor():
    """★ 框架 ≠ 服务商：预算查的是 framework，不是 vendor。"""
    assert ad.adapter_framework(ad.PiAdapter()) == "pi"
    assert ad.adapter_framework(ad.PiAdapter()).startswith("pi")
    assert ad.adapter_framework(ad.CodexAdapter()) == "codex-cli"
    assert ad.adapter_framework(ad.DeepSeekHarnessAdapter()) == "deepseek-harness"
    # vendor 是另一件事
    assert ad.PiAdapter().vendor == "minimax-cn"


# ─────────────────────────────────────────────────── 重试退避 + 总墙钟上限

def _flaky_codex(tmp_path: Path, fail_times: int, sleep_s: float = 0.0):
    cnt = tmp_path / "count.txt"
    exe = _fake(tmp_path, "codex", f"""
        p = {str(cnt)!r}
        n = int(open(p).read()) + 1 if os.path.exists(p) else 1
        open(p, "w").write(str(n))
        if {sleep_s} > 0:
            time.sleep({sleep_s})
        if n <= {fail_times}:
            sys.exit(2)
        sys.exit(0)
    """)
    return exe, cnt


def test_retry_backoff_actually_waits(tmp_path):
    """重试之间**必须退避**（否则撞供应商限流 ⇒ 本可避免的 TIMEOUT）。"""
    exe, cnt = _flaky_codex(tmp_path, fail_times=1, sleep_s=0.0)
    wd = _wd(tmp_path)
    t0 = time.monotonic()
    rec = ad.run_agent(ad.CodexAdapter(exe), SNAP, META, OBS,
                       ad.Budget(timeout_s=10, max_calls=2, retry_backoff_s=0.4), workdir=wd)
    dt = time.monotonic() - t0
    assert rec["calls_used"] == 2
    assert dt >= 0.4, f"退避没生效（{dt:.2f}s < 0.4s）"


def test_retry_backoff_zero_skips_wait(tmp_path):
    exe, _cnt = _flaky_codex(tmp_path, fail_times=1)
    wd = _wd(tmp_path)
    t0 = time.monotonic()
    rec = ad.run_agent(ad.CodexAdapter(exe), SNAP, META, OBS,
                       ad.Budget(timeout_s=10, max_calls=2, retry_backoff_s=0.0), workdir=wd)
    assert rec["calls_used"] == 2
    assert (time.monotonic() - t0) < 3.0


def test_max_total_budget_stops_waiting(tmp_path):
    """总墙钟上限 ⇒ **杜绝无限等待**（重试也不许突破）。"""
    exe, cnt = _flaky_codex(tmp_path, fail_times=99, sleep_s=0.6)
    wd = _wd(tmp_path)
    t0 = time.monotonic()
    rec = ad.run_agent(ad.CodexAdapter(exe), SNAP, META, OBS,
                       ad.Budget(timeout_s=5, max_calls=10, retry_backoff_s=0.0, max_total_s=1.5),
                       workdir=wd)
    dt = time.monotonic() - t0
    assert rec["calls_used"] < 10, "总上限没生效"
    assert dt < 6.0, f"总墙钟上限没生效（{dt:.1f}s）"
    assert any(a.get("status") == "SKIPPED_MAX_TOTAL_BUDGET" for a in rec["attempts"])
    assert rec["perf"]["budget_exhausted"] is True


def test_non_retryable_status_not_retried_even_with_calls(tmp_path):
    wd = _wd(tmp_path)
    rec = ad.run_agent(ad.DeepSeekHarnessAdapter(), SNAP, META, OBS,
                       ad.Budget(timeout_s=5, max_calls=5, retry_backoff_s=0.0), workdir=wd)
    assert rec["calls_used"] == 1


# ─────────────────────────────────────────────────── 并发护栏

def test_max_concurrent_agent_calls_is_one():
    assert ad.MAX_CONCURRENT_AGENT_CALLS == 1


def test_agent_calls_are_serialized_in_process(tmp_path):
    """两个线程同时调 ⇒ **实际不重叠**（并发=1）。"""
    counter = {"cur": 0, "max": 0}
    lock = threading.Lock()

    class _Adapter:
        adapter_id, vendor, role = "fake", "fake", "EXAMINEE_2"
        framework = "fake"
        participation_class = "HARNESS_MODEL"

        def run(self, packet, workdir, budget):
            with lock:
                counter["cur"] += 1
                counter["max"] = max(counter["max"], counter["cur"])
            time.sleep(0.15)
            with lock:
                counter["cur"] -= 1
            res = ad.AdapterResult("fake", "fake", "EXAMINEE_2", status=ad.CALL_FAILED,
                                    reason="forced")
            return res

    adp = _Adapter()
    wds = [_wd(tmp_path, f"w{i}") for i in range(2)]
    ths = [threading.Thread(target=ad.run_agent,
                            args=(adp, SNAP, META, OBS, ad.Budget(timeout_s=5, max_calls=1,
                                                                 retry_backoff_s=0.0), wds[i]))
           for i in range(2)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(30)
    assert counter["max"] == 1, f"Agent 调用发生了重叠（max={counter['max']}）⇒ 并发护栏失效"


# ─────────────────────────────────────────────────── 成本 / 耗时记账

def test_perf_block_records_cost_token_and_elapsed(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"results": []}), encoding="utf-8")
    exe = _fake(tmp_path, "codex", f"""
        open("out.json", "w", encoding="utf-8").write(open({str(good)!r}, encoding="utf-8").read())
    """)
    wd = _wd(tmp_path)
    rec = ad.run_agent(ad.CodexAdapter(exe), SNAP, META, OBS,
                       ad.Budget(timeout_s=10, max_calls=1, retry_backoff_s=0.0), workdir=wd)
    perf = rec["perf"]
    assert perf["total_elapsed_s"] >= 0
    assert "cost_usd_or_UNKNOWN" in perf
    assert perf["attempts_cost"] == [perf["cost_usd_or_UNKNOWN"]]
    assert perf["max_total_s"] == 900.0  # Budget 直构时的默认总墙钟上限
    # 逐次明细里必须带成本与错误码
    a0 = rec["attempts"][0]
    assert "cost_usd_or_UNKNOWN" in a0 and "error_code" in a0
    assert a0["n"] == 1 and a0["wall_elapsed_s"] >= 0
