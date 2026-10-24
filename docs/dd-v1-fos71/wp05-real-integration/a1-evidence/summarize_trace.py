#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A1 call-trace 汇总器：从 trace JSONL 统计**每个模块的函数调用数**。

## 为什么这个文件是 G1 的核心证据

A0 实测过：入口 A（``tools/dd_team_channel.py run``）走的 6 个服务是
``card / manifest / parser / requirement / match / policy``，
而 **``semantic`` / ``agent_result`` / ``agent_adapters`` 三个模块的调用数全是 0**
⇒ 两条链在语义/Agent 层**完全不相交**，这就是「线没接好」的具体形态。

A1 接上薄桥之后，入口 A 的 trace 里必须出现
``semantic_retrieval_service`` / ``bridge_service`` / ``agent_result_service`` 的调用，
且计数 **> 0**。本汇总器就是把这个事实**从 trace 里数出来**，不靠人工读日志。

用法：
    python summarize_trace.py <trace.jsonl> [--json out.json]
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

#: A0 记录的入口 A 六模块 + A1 必须接通的三模块
SERVICE_SUFFIX = {
    "card_service": "dd_v1_card_service",
    "manifest_service": "dd_v1_manifest_service",
    "parser_service": "dd_v1_parser_service",
    "requirement_service": "dd_v1_requirement_service",
    "match_service": "dd_v1_match_service",
    "policy_service": "dd_v1_policy_service",
    "semantic_retrieval_service": "dd_v1_semantic_retrieval_service",
    "agent_result_service": "dd_v1_agent_result_service",
    "agent_adapters": "dd_v1_agent_adapters",
    "bridge_service": "dd_v1_bridge_service",
    "pii_service": "dd_v1_pii_service",
}
CORE6 = ("card_service", "manifest_service", "parser_service",
         "requirement_service", "match_service", "policy_service")
BRIDGE3 = ("semantic_retrieval_service", "agent_result_service", "agent_adapters")


def summarize(trace: Path) -> dict:
    modules: Counter = Counter()
    funcs: Counter = Counter()
    calls = 0
    meta = None
    done = None
    for line in trace.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        ev = rec.get("event")
        if ev == "meta":
            meta = rec
        elif ev == "done":
            done = rec
        elif ev == "call":
            calls += 1
            m = rec.get("module") or ""
            modules[m] += 1
            funcs[f"{m}.{rec.get('func')}"] += 1
    by_service: Counter = Counter()
    for m, n in modules.items():
        for key, suffix in SERVICE_SUFFIX.items():
            if m.endswith(suffix):
                by_service[key] += n
                break
    keys = tuple(SERVICE_SUFFIX)
    return {
        "trace": str(trace),
        "run_id": (meta or {}).get("run_id"),
        "head_sha": (meta or {}).get("head_sha"),
        "exit_code": (done or {}).get("exit_code"),
        "done_error": (done or {}).get("error"),
        "total_call_events": calls,
        "by_service": {k: by_service.get(k, 0) for k in keys},
        "bridge_services_connected": {k: by_service.get(k, 0) for k in BRIDGE3},
        "bridge_service": by_service.get("bridge_service", 0),
        "modules": dict(modules.most_common()),
        "top_funcs": dict(funcs.most_common(12)),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: summarize_trace.py <trace.jsonl> [--json out.json]", file=sys.stderr)
        return 2
    trace = Path(sys.argv[1])
    out = summarize(trace)
    if "--json" in sys.argv:
        p = Path(sys.argv[sys.argv.index("--json") + 1])
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    # 退出码语义：真实退出码非 0 ⇒ 失败
    return int(out["exit_code"] or 0)


if __name__ == "__main__":
    raise SystemExit(main())
