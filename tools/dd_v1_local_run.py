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
  run       建最小证据包 → 模型 CLI → 校验；默认按清单条目拆成小包逐条跑（--single-pack 才合成一个包）
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


# ---------------------------------------------------------------- WP-R1 自动派生
#
# 此前 meta 完全靠 `cmd_scaffold` 让员工**手工逐个文件**打 entity/doc_type/period，
# 而 `retrieve_minimal_evidence` 拿 entity+doc_type 做等值硬筛。
# 员工不打标 ⇒ 该文件对模型完全不可见 ⇒ 静默全 MISSING，且**不报错**。
# 这违反董事长指令第 4 条「不能要求员工预先把文件重命名或精细分类」。
#
# `_auto_meta` 把「扫描 → 抽正文 → 建认知卡/FTS → 自动派生 meta」串成一条链：
# 员工只需给一个材料文件夹 + 一份清单，不需要预先整理任何东西。

_AUTO: dict = {}


def _auto_meta(snap_dir: Path, library_id: str):
    """从材料目录自动派生 meta，返回 (meta, recaller, cached_text_getter)。"""
    from cangjie_fos.services import dd_v1_card_service as cs
    from cangjie_fos.services import dd_v1_manifest_service as mf
    from cangjie_fos.services import dd_v1_parser_service as ps
    from cangjie_fos.services import dd_v1_semantic_retrieval_service as sem

    mf.register_library(library_id, str(snap_dir), authorized_by="auto-meta",
                        display_name=library_id)
    mf.build_manifest(library_id, mode="full")
    ps.parse_pending_batch(library_id, limit=2000)
    cs.build_cards_for_library(library_id)

    rows = mf.list_manifest(library_id, limit=100000)
    path_by_id = {r["file_id"]: r["rel_path"] for r in rows}
    cards = [cs.get_card(r["file_id"]) for r in rows]
    cards = [c for c in cards if c]
    meta = sem.derive_meta_from_cards(cards, file_path_by_id=path_by_id)

    # 召回：用义务原文做正文/标题检索；正文从 Data Plane 缓存取
    def recaller(ob):
        q = ob.get("text") or ob.get("obligation") or ""
        return sem.recall_by_text(library_id, q, limit=12)

    def cached_text_getter(fid):
        try:
            return cs.get_cached_text(fid) or None
        except Exception:  # noqa: BLE001
            return None

    _AUTO.update({"library": library_id, "cards": len(cards), "meta": len(meta)})
    return meta, recaller, cached_text_getter


def _warn_missing_tagging(meta: list[dict[str, str]]) -> None:
    """旧 meta 若整批没有 entity/period，显式告警——**不允许静默全 MISSING**。"""
    if not meta:
        return
    if not any(m.get("entity") for m in meta):
        print("[告警] 所有文件都没有主体标识；检索将退化为全文召回，"
              "主体相关判定会判 UNCERTAIN。建议用 --auto-meta 自动派生。",
              file=sys.stderr)
    if not any(m.get("doc_type") for m in meta):
        print("[告警] 没有文件能识别出文档类型；旧路径会把它们全部排除，"
              "建议用 --auto-meta 从正文派生。", file=sys.stderr)


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
            cfg["mode"] = "file"
        return ad.DeepSeekHarnessAdapter.from_config(cfg, enabled=True)
    if a.adapter == "codex":
        return ad.CodexAdapter(a.codex_bin)
    return ad.ADAPTERS[a.adapter]()


def cmd_run(a) -> int:
    meta = _json(Path(a.meta)) if a.meta else []
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
    recaller = cached_text_getter = None
    if a.auto_meta:
        meta, recaller, cached_text_getter = _auto_meta(snap_dir, a.library)
        print(json.dumps({"auto_meta": _AUTO}, ensure_ascii=False), flush=True)
    else:
        _warn_missing_tagging(meta)
    budget = ad.Budget(timeout_s=a.timeout, max_calls=a.max_calls)
    per_item = not a.single_pack
    groups = [[it] for it in items] if per_item else [items]
    limits = {"cost_cap": "不限额（本地 CLI 不报告费用，代码无法按金额限制；请在 DeepSeek 平台设置余额/预警）",
              "max_total_calls": a.max_total_calls if a.max_total_calls else "不限",
              "max_calls_per_item": a.max_calls}
    print(json.dumps({"limits": limits}, ensure_ascii=False), flush=True)
    calls_total = 0
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    for g in groups:
        tag = g[0]["item_id"] if per_item else "all"
        obs_g = [o for o in obligations if o["item_id"] in {i["item_id"] for i in g}] if obligations else None
        if obs_g == []:
            summary.append({"group": tag, "status": "NO_OBLIGATIONS"})
            continue
        if obs_g is None and not sem.split_items(g)[0]:  # 拆不出义务就不调用模型（不浪费付费调用）
            summary.append({"group": tag, "status": "NEEDS_HUMAN_SPLIT"})
            print(json.dumps(summary[-1], ensure_ascii=False), flush=True)
            continue
        done = a.resume and (out / f"run-{tag}" / "run_record.json").exists()
        if a.max_total_calls and not done and calls_total + a.max_calls > a.max_total_calls:
            # 剩余额度不够一条的最坏情况（含重试）就停，保证总调用数绝不超过上限
            summary.append({"group": tag, "status": "STOPPED_MAX_TOTAL_CALLS", "calls_total": calls_total})
            print(json.dumps(summary[-1], ensure_ascii=False), flush=True)
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
                               obligations=obs_g, text_root=text_root,
                               recaller=recaller, cached_text_getter=cached_text_getter)
        calls_total += rec.get("calls_used", 1)
        v = rec["semantic_validation"]
        summary.append({"group": tag, "adapter_status": rec["adapter"]["status"],
                        "elapsed_s": rec["adapter"]["elapsed_s"], "mode": v["mode"],
                        "accepted": len(v["accepted"]), "rejected": len(v["rejected"]),
                        "uncovered": v["uncovered_obligations"], "degrade_reason": v["degrade_reason"]})
        print(json.dumps(summary[-1], ensure_ascii=False), flush=True)
    (out / "run_summary.json").write_text(json.dumps({"limits": limits, "calls_total": calls_total,
                                                      "groups": summary}, ensure_ascii=False, indent=1), "utf-8")
    return 0 if any(s.get("mode") == "AGENT_SUGGESTION" for s in summary) else 2


def cmd_score(a) -> int:
    gold_p, run_dir = Path(a.gold), Path(a.run_dir)
    sem.assert_gold_isolated(gold_p, run_dir, *[Path(x) for x in (a.material_root, a.text_root) if x])
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


def _validate_args(a) -> str | None:
    """参数自检。**没有 meta 也没开 --auto-meta 时明确报错**，
    不允许走到检索阶段才静默全 MISSING。"""
    if getattr(a, "cmd", "") != "run":
        return None
    if not a.meta and not getattr(a, "auto_meta", False):
        return ("缺少 --meta 且未开 --auto-meta。\n"
                "  手工打标：先跑 cmd_scaffold 生成 meta.json 再 --meta 传入；\n"
                "  推荐：直接 --auto-meta，由系统从材料内容自动派生（无需预先整理）")
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scaffold"); s.add_argument("--material-root", required=True); s.add_argument("--out", required=True)
    s.add_argument("--entity", default="")
    s = sub.add_parser("split"); s.add_argument("--items", required=True); s.add_argument("--out", required=True)
    r = sub.add_parser("run")
    r.add_argument("--material-root", required=True)
    r.add_argument("--meta", default=None,
                   help="材料清单 meta.json（cmd_scaffold 生成）。"
                        "配合 --auto-meta 时可省略，由系统自动派生")
    r.add_argument("--items", required=True); r.add_argument("--obligations", default=None)
    r.add_argument("--text-root", default=None); r.add_argument("--out", required=True)
    r.add_argument("--library", default="auto",
                   help="--auto-meta 时用的材料库标识（同一库可复用已抽正文）")
    r.add_argument("--auto-meta", action="store_true",
                   help="从材料目录自动扫描/抽正文/建认知卡并派生 meta（不需手工打标）")
    r.add_argument("--adapter", choices=sorted(ad.ADAPTERS), default="deepseek-harness",
                   help="默认 deepseek-harness（主力）；codex 只作刘江的备用")
    r.add_argument("--allow-real-material", action="store_true",
                   help="材料目录不是仓库内合成 fixture 时必须给（=真实材料，仅限本机）")
    r.add_argument("--allow-local-dsh", action="store_true")
    r.add_argument("--dsh-config", default=None, help="dsh 配置 JSON（binary/profile/extra_args/mode），不得含密钥")
    r.add_argument("--dsh-bin", default=None, help="覆盖配置里的 dsh 路径")
    r.add_argument("--max-total-calls", type=int, default=None,
                   help="整次运行最多调用模型多少次（含重试），到了就停；这是唯一能真正执行的花费上限")
    r.add_argument("--cost-cap", type=float, default=None,
                   help="操作员显式设置的费用上限（元/美元按你的账户口径）；不设则不限制但 run_record 记 cost=UNKNOWN")
    r.add_argument("--dsh-file-mode", action="store_true",
                   help="让 dsh 自己读 workdir/PROMPT.txt（需要 dsh 有读文件能力，不推荐；默认用标准输入）")
    r.add_argument("--codex-bin", default="codex")
    r.add_argument("--timeout", type=float, default=600.0); r.add_argument("--max-calls", type=int, default=2)
    r.add_argument("--per-item", action="store_true", help="（已是默认，保留兼容）")
    r.add_argument("--single-pack", action="store_true", help="把所有条目合成一个包跑（小清单才用）")
    r.add_argument("--resume", action="store_true", help="跳过已有 run_record.json 的条目")
    c = sub.add_parser("score"); c.add_argument("--run-dir", required=True); c.add_argument("--gold", required=True)
    c.add_argument("--out", required=True); c.add_argument("--material-root", default=None)
    c.add_argument("--text-root", default=None)
    a = p.parse_args(argv)
    err = _validate_args(a)
    if err:
        print(err, file=sys.stderr)
        return 3
    if a.cmd == "run" and a.cost_cap is not None:
        print("拒绝：--cost-cap 无法执行——本地 CLI（dsh/codex）不报告每次费用。"
              "请改用 --max-total-calls N 限制调用次数，并在 DeepSeek 平台设置余额预警", file=sys.stderr)
        return 3
    return {"scaffold": cmd_scaffold, "split": cmd_split, "run": cmd_run, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
