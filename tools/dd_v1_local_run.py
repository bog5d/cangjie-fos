#!/usr/bin/env python3
"""cangjie-fos#71 本地运行器：在操作员自己的电脑上，用本地真实材料 + 本地模型 CLI 跑 DD-V1 语义匹配，再本地评分。

安全约束（代码层面）：
- 本程序不联网、不上传、不外发任何文件；模型调用只经操作员本机已登录的 CLI（dsh / codex）。
- 真实材料必须显式 --allow-real-material；DeepSeek Harness 必须显式 --allow-local-dsh。
- `run` 不接受 Gold 参数；Gold 只在 `score` 步骤读取，且不得位于材料目录或运行目录之内。
- 模型输出只是建议：确定性门槛（快照/路径/sha/主体/期间/版本/附件/locator）照常执行，所有接受项 review_required=true。

子命令：
  scaffold  扫描材料目录 → meta.json 草稿（文件名猜年度/文档类型，主体用 --entity；须人工核对）
  split     清单 → 原子义务 obligations.json（零模型；用于制作 Gold 和检查拆分）
  run       建最小证据包 → 模型 CLI → 校验；--per-item 按清单条目拆成多个小包分别跑
  score     读 run 目录下全部 run_record.json + Gold → score.json / score.csv（只含 id 与判定，可回传）
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from cangjie_fos.services import dd_v1_agent_adapters as ad  # noqa: E402
from cangjie_fos.services import dd_v1_semantic_retrieval_service as sem  # noqa: E402

YEAR = re.compile(r"(20\d\d)")


def _load_items(p: Path) -> list[dict[str, str]]:
    if p.suffix.lower() == ".csv":
        with open(p, encoding="utf-8-sig", newline="") as fh:
            return [{"item_id": r["item_id"], "entity": r["entity"], "text": r["text"]} for r in csv.DictReader(fh)]
    return json.loads(p.read_text("utf-8"))


def _json(p: Path):
    return json.loads(p.read_text("utf-8-sig"))


def cmd_scaffold(a) -> int:
    root = Path(a.material_root).resolve()
    meta = []
    for i, f in enumerate(sorted(x for x in root.rglob("*") if x.is_file() and not x.name.startswith("."))):
        rel = f.relative_to(root).as_posix()
        y = YEAR.findall(rel)
        dt = next((d for d in sem.DOC_TYPES if d in rel), "")
        meta.append({"file_id": f"F{i + 1:05d}", "relative_path": rel, "entity": a.entity or "",
                     "period": y[-1] if y else ("CURRENT" if dt in ("营业执照", "公司章程") else ""),
                     "doc_type": dt, "part": "附注" if "附注" in rel else "正文",
                     "version_status": "DRAFT" if re.search(r"草稿|征求意见|draft", rel, re.I) else "EFFECTIVE"})
    Path(a.out).write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    blank = sum(1 for m in meta if not (m["entity"] and m["period"] and m["doc_type"]))
    print(json.dumps({"files": len(meta), "need_manual_fill": blank, "out": str(a.out)}, ensure_ascii=False))
    return 0


def cmd_split(a) -> int:
    obs, flags = sem.split_items(_load_items(Path(a.items)))
    Path(a.out).write_text(json.dumps(obs, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({"obligations": len(obs), "needs_human_split": flags, "out": str(a.out)}, ensure_ascii=False))
    return 0


def _adapter(a):
    if a.adapter == "deepseek-harness":
        if not a.allow_local_dsh:
            print("拒绝：DeepSeek Harness 需要显式 --allow-local-dsh", file=sys.stderr)
            raise SystemExit(3)
        cfg = ad.load_dsh_config(Path(a.dsh_config) if a.dsh_config else None)
        if a.dsh_bin:
            cfg["binary"] = a.dsh_bin
        if a.dsh_file_mode:
            cfg["inline"] = False
        return ad.DeepSeekHarnessAdapter.from_config(cfg, enabled=True)
    if a.adapter == "codex":
        return ad.CodexAdapter(a.codex_bin)
    return ad.ADAPTERS[a.adapter]()


def cmd_run(a) -> int:
    meta = _json(Path(a.meta))
    fixture = sem._inside(Path(a.material_root), ROOT / "backend" / "tests" / "fixtures")
    try:  # 仓库内合成 fixture 免开关；其他任何目录都视为真实材料，必须 --allow-real-material
        snap_dir = sem.local_material_snapshot(Path(a.material_root), meta,
                                               allow_real=fixture or a.allow_real_material)
    except sem.Blocked as e:
        print(f"拒绝：{e}", file=sys.stderr)
        return 3
    out = Path(a.out).resolve()
    if sem._inside(out, snap_dir):
        print("拒绝：--out 不能放在材料目录里（不改动原始材料）", file=sys.stderr)
        return 3
    items = _load_items(Path(a.items))
    obligations = _json(Path(a.obligations)) if a.obligations else None
    text_root = Path(a.text_root).resolve() if a.text_root else None
    budget = ad.Budget(timeout_s=a.timeout, max_calls=a.max_calls,
                       max_cost_usd=a.cost_cap if a.cost_cap is not None else 1e18)  # 未设上限 = 不限（显式记录）
    groups = [[it] for it in items] if a.per_item else [items]
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    for g in groups:
        tag = g[0]["item_id"] if a.per_item else "all"
        obs_g = [o for o in obligations if o["item_id"] in {i["item_id"] for i in g}] if obligations else None
        if obs_g == []:
            summary.append({"group": tag, "status": "NO_OBLIGATIONS"})
            continue
        wd = out / f"run-{tag}"
        if wd.exists() and any(wd.iterdir()):
            if a.resume and (wd / "run_record.json").exists():
                summary.append({"group": tag, "status": "SKIPPED_EXISTING"})
                continue
            print(f"拒绝：{wd} 非空（用 --resume 跳过已完成的条目，或换 --out）", file=sys.stderr)
            return 3
        wd.mkdir(parents=True, exist_ok=True)
        rec = sem.run_semantic(_adapter(a), snap_dir, meta, g, budget, workdir=wd,
                               obligations=obs_g, text_root=text_root)
        v = rec["semantic_validation"]
        summary.append({"group": tag, "adapter_status": rec["adapter"]["status"],
                        "elapsed_s": rec["adapter"]["elapsed_s"], "mode": v["mode"],
                        "accepted": len(v["accepted"]), "rejected": len(v["rejected"]),
                        "uncovered": v["uncovered_obligations"], "degrade_reason": v["degrade_reason"]})
        print(json.dumps(summary[-1], ensure_ascii=False), flush=True)
    (out / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
    return 0 if any(s.get("mode") == "AGENT_SUGGESTION" for s in summary) else 2


def cmd_score(a) -> int:
    gold_p, run_dir = Path(a.gold), Path(a.run_dir)
    sem.assert_gold_isolated(gold_p, run_dir, *( [Path(a.material_root)] if a.material_root else []))
    recs = [json.loads(p.read_text("utf-8")) for p in sorted(run_dir.rglob("run_record.json"))]
    res = sem.score_against_gold(recs, _json(gold_p))
    out = Path(a.out)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    if res.get("rows"):
        with open(out.with_suffix(".csv"), "w", encoding="utf-8-sig", newline="") as fh:
            keys = sorted({k for r in res["rows"] for k in r})
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            for r in res["rows"]:
                w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in r.items()})
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scaffold"); s.add_argument("--material-root", required=True); s.add_argument("--out", required=True)
    s.add_argument("--entity", default="")
    s = sub.add_parser("split"); s.add_argument("--items", required=True); s.add_argument("--out", required=True)
    r = sub.add_parser("run")
    r.add_argument("--material-root", required=True); r.add_argument("--meta", required=True)
    r.add_argument("--items", required=True); r.add_argument("--obligations", default=None)
    r.add_argument("--text-root", default=None); r.add_argument("--out", required=True)
    r.add_argument("--adapter", choices=sorted(ad.ADAPTERS), default="deepseek-harness",
                   help="默认 deepseek-harness（主力）；codex 只作刘江的备用")
    r.add_argument("--allow-real-material", action="store_true",
                   help="材料目录不是仓库内合成 fixture 时必须给（=真实材料，仅限本机）")
    r.add_argument("--allow-local-dsh", action="store_true")
    r.add_argument("--dsh-config", default=None, help="dsh 配置 JSON（binary/profile/extra_args/inline），不得含密钥")
    r.add_argument("--dsh-bin", default=None, help="覆盖配置里的 dsh 路径")
    r.add_argument("--cost-cap", type=float, default=None,
                   help="操作员显式设置的费用上限（元/美元按你的账户口径）；不设则不限制但 run_record 记 cost=UNKNOWN")
    r.add_argument("--dsh-file-mode", action="store_true", help="让 dsh 读 workdir/packet.json，而不是把包放进命令行")
    r.add_argument("--codex-bin", default="codex")
    r.add_argument("--timeout", type=float, default=600.0); r.add_argument("--max-calls", type=int, default=2)
    r.add_argument("--per-item", action="store_true", help="按清单条目拆成小包分别跑（大包/超时时用）")
    r.add_argument("--resume", action="store_true", help="跳过已有 run_record.json 的条目")
    c = sub.add_parser("score"); c.add_argument("--run-dir", required=True); c.add_argument("--gold", required=True)
    c.add_argument("--out", required=True); c.add_argument("--material-root", default=None)
    a = p.parse_args(argv)
    return {"scaffold": cmd_scaffold, "split": cmd_split, "run": cmd_run, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
