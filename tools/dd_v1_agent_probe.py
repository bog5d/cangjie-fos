#!/usr/bin/env python3
"""cangjie-fos#71 WP01：Agent 调用探针的确定性辅助脚本（不调用任何模型）。

  build  --fixture DIR --out DIR   生成 packet.json + schema.json 到隔离目录（供 codex/hermes/pi 读取）
  validate --fixture DIR --raw FILE [--call-error MSG]   校验模型原始输出，打印 ValidationReport JSON

退出码：0 = 至少 1 条被接受（AGENT_SUGGESTION）；2 = 降级 RULE_ONLY；1 = 用法错误。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from cangjie_fos.services import dd_v1_agent_result_service as ar  # noqa: E402

SCHEMA = ROOT / "backend/src/cangjie_fos/services/dd_v1_agent_result.v1.schema.json"


def _load(fx: Path):
    return json.loads((fx / "meta.json").read_text("utf-8")), json.loads((fx / "obligations.json").read_text("utf-8"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--fixture", type=Path, required=True); b.add_argument("--out", type=Path, required=True)
    v = sub.add_parser("validate"); v.add_argument("--fixture", type=Path, required=True); v.add_argument("--raw", type=Path, required=True)
    v.add_argument("--call-error", default=None)
    a = p.parse_args(argv)
    meta, obs = _load(a.fixture)
    if a.cmd == "build":
        a.out.mkdir(parents=True, exist_ok=True)
        pkt = ar.build_task_packet(a.fixture / "snapshot", meta, obs)
        (a.out / "packet.json").write_text(json.dumps(pkt, ensure_ascii=False, indent=2), "utf-8")
        shutil.copy(SCHEMA, a.out / "schema.json")
        print(json.dumps({"source_snapshot_id": pkt["source_snapshot_id"], "out": str(a.out)}))
        return 0
    raw = a.raw.read_text("utf-8") if a.raw.exists() else None
    rep = ar.validate_agent_output(raw, a.fixture / "snapshot", meta, obs, call_error=a.call_error)
    print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
    return 0 if rep.mode == "AGENT_SUGGESTION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
