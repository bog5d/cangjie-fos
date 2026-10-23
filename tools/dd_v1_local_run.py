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

# GM:A4A:CLI:SHUTIL
import argparse
import csv
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

# GM:A4A:CLI:IMPORTS
from cangjie_fos.services import dd_v1_agent_adapters as ad  # noqa: E402
from cangjie_fos.services import dd_v1_blind_service as bl  # noqa: E402
from cangjie_fos.services import dd_v1_doc_type_service as dts  # noqa: E402
from cangjie_fos.services import dd_v1_requirement_service as rq  # noqa: E402
from cangjie_fos.services import dd_v1_score_service as sc  # noqa: E402
from cangjie_fos.services import dd_v1_semantic_retrieval_service as sem  # noqa: E402
from cangjie_fos.services import dd_v1_snapshot_freeze_service as fz  # noqa: E402

YEAR = re.compile(r"(20\d\d)")


def _load_items(p: Path) -> list[dict[str, str]]:
    if p.suffix.lower() == ".csv":
        with open(p, encoding="utf-8-sig", newline="") as fh:
            return [{"item_id": r["item_id"], "entity": r["entity"], "text": r["text"]} for r in csv.DictReader(fh)]
    return json.loads(p.read_text("utf-8"))


def _json(p: Path):
    return json.loads(p.read_text("utf-8-sig"))


# GM:A4A:CLI:HELPERS
def _leak_words(raw: str) -> list[str]:
    """泄漏词表（逗号 / 中文逗号分隔）。空串 ⇒ 不盲化。"""
    if not raw:
        return []
    out: list[str] = []
    for part in str(raw).replace("，", ",").split(","):
        w = part.strip()
        if w:
            out.append(w)
    return out


def _maybe_blind_items(a, items: list[dict[str, str]]) -> list[dict[str, str]]:
    """条目盲化（与材料盲化**同一张映射表** ⇒ 义务里的主体口径与 meta 一致）。

    只改 ``entity`` 与 ``text`` 两个字段里的泄漏串；条目 id / 其他字段不动。
    """
    words = _leak_words(getattr(a, "blind_leak_words", "") or "")
    if not words:
        return items
    table = bl.build_substitution_table(words)
    out: list[dict[str, str]] = []
    for it in items:
        n = dict(it)
        for k in ("entity", "text"):
            if isinstance(n.get(k), str):
                n[k] = bl.blind_text(n[k], table)
        out.append(n)
    dest = getattr(a, "blind_items_out", None)
    if dest:
        p = Path(dest)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    return out


def _prepare_material(a, material_root: Path, meta: list[dict]) -> tuple[Path, list[dict]]:
    """盲化 + 冻结（A4a 新增开关；默认关闭 ⇒ 既有语义与退出码不变）。

    盲化：材料目录 → 盲化目录（相对路径 + 正文里的泄漏串），映射表落在材料目录之外。
    冻结：盲化目录 → 冻结目录（逐件现场 sha256 + snapshot.json + 只读）；
    被考侧 / 被评侧各一份 ⇒ 逐件 sha256 相等才算「同一份快照」。
    """
    blind_out = getattr(a, "blind_material_out", None)
    if blind_out:
        res = bl.blind_material(
            material_root, meta,
            leak_words=_leak_words(getattr(a, "blind_leak_words", "") or ""),
            blind_dir=Path(blind_out),
            mapping_out=Path(a.blind_mapping_out) if getattr(a, "blind_mapping_out", None) else None,
            meta_file=Path(a.meta),
        )
        meta = res["meta"]
        material_root = Path(res["blind_dir"]).resolve()
    freeze_dir = getattr(a, "snapshot_freeze_dir", None)
    if freeze_dir:
        fz.freeze_snapshot(material_root, meta, Path(freeze_dir))
        material_root = Path(freeze_dir).resolve()
        evaluate_dir = getattr(a, "snapshot_evaluate_dir", None)
        if evaluate_dir:
            fz.freeze_snapshot(material_root, meta, Path(evaluate_dir))
    return material_root, meta


def _install_synthetic_reply(replies_dir: Path, tag: str, wd: Path) -> str | None:
    """把预置回贴装进工作目录（``reply.json`` + ``reply.provenance.json``）。

    两个文件都在 ``dd_v1_agent_adapters.MANUAL_ALLOWED`` 白名单里 ⇒ 不触发「工作目录非空」拒绝；
    ManualExchangeAdapter 零进程、零费用地读回贴 ⇒ ``mode == "AGENT_SUGGESTION"`` ⇒ run 退出码 0。
    """
    src = Path(replies_dir) / f"run-{tag}.json"
    if not src.is_file():
        return f"预置回贴不存在：{src}"
    shutil.copy(src, wd / "reply.json")
    prov = src.parent / f"{src.stem}.provenance.json"
    if prov.is_file():
        shutil.copy(prov, wd / "reply.provenance.json")
    return None


def _synthetic_provenance(recs: list[dict]) -> dict:
    """产物上的真实性标注：未跑真模型 ⇒ ``model_id_or_unknown=UNKNOWN`` +
    ``independent_examinee_answer=false``；回贴来源是合成 ⇒ ``synthetic_replay=true``。"""
    sources: set[str] = set()
    models: set[str] = set()
    for rec in recs:
        adapter = rec.get("adapter") or {}
        prov = adapter.get("provenance") or {}
        sources.add(str(prov.get("reply_source") or "UNDECLARED_OPERATOR_PASTE"))
        models.add(str(adapter.get("model_id_or_unknown") or "UNKNOWN"))
    return {
        "model_id_or_unknown": ",".join(sorted(models)) or "UNKNOWN",
        "independent_examinee_answer": False,
        "synthetic_replay": sources == {"SYNTHETIC_REPLAY"},
        "reply_sources": sorted(sources),
        "note": "合成回放：未跑真模型、无独立考生答卷；本产物只证明链路自检通过",
    }


def cmd_scaffold(a) -> int:
    """扫描材料目录 → meta.json 草稿（材料类型**只看文件自己的名字**）。

    ★ **为什么不能按整条相对路径判类型**：真实材料库普遍按法人/类型建多级目录，
      形如 ``1.审计报告(1)/营业执照2024.pdf`` —— 按路径判会把**目录里别人的类型**
      认成这份材料的类型（``dd_v1_doc_type_service`` 的文档字符串已明确记载这个坑）。
      现在走 ``resolve_doc_type(file_name=f.name)``：**只看文件名**、产出**英文 key** 与 provenance。

    ★ **类型取值空间只有一处**：``dd_v1_requirement_service`` 的 10 个规范 key
      （license / charter 等）—— 本文件**不另抄一份类型表**。
    ★ **期间口径**：执照/章程无年度口径 ⇒ ``CURRENT``（与桥接层同口径）；
      其余类型取路径里的年份；都没有 ⇒ 空（需人工补）。
    """
    root = Path(a.material_root).resolve()
    meta = []
    unresolved = 0
    for i, f in enumerate(sorted(x for x in root.rglob("*") if x.is_file() and not x.name.startswith("."))):
        rel = f.relative_to(root).as_posix()
        y = YEAR.findall(rel)
        # ★ 索引/目录/清单件**不是材料**（dd_v1_doc_type_service.is_index_artifact）：
        #   「00_审计报告目录.md」只把同目录材料列一遍 ⇒ 若按文件名判类型会得到
        #   audit_report，与**真**审计报告同主体、同类型、同期间落进同一冲突桶 ⇒ **假 CONFLICT**。
        #   口径与卡片层（dd_v1_card_service）一致：类型强制留空 + 留痕（不静默丢弃）。
        if dts.is_index_artifact(f.name):
            dt, prov = "", dts.UNKNOWN
        else:
            dt, prov, _evidence = dts.resolve_doc_type(file_name=f.name)
        if not dt:
            unresolved += 1
        period = "CURRENT" if dt in rq.CURRENT_DOC_TYPES else (y[-1] if y else "")
        meta.append({"file_id": f"F{i + 1:05d}", "relative_path": rel, "entity": a.entity or "",
                     "period": period,
                     "doc_type": dt, "doc_type_provenance": prov,
                     "part": "附注" if "附注" in rel else "正文",
                     "version_status": "DRAFT" if re.search(r"草稿|征求意见|draft", rel, re.I) else "EFFECTIVE"})
    Path(a.out).write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    blank = sum(1 for m in meta if not (m["entity"] and m["period"] and m["doc_type"]))
    print(json.dumps({"files": len(meta), "need_manual_fill": blank,
                      "doc_type_unresolved": unresolved, "out": str(a.out)}, ensure_ascii=False))
    return 0


# GM:A4A:CLI:SPLIT
def cmd_split(a) -> int:
    items = _maybe_blind_items(a, _load_items(Path(a.items)))
    obs, flags = sem.split_items(items)
    # ★ 输出面脱敏：写盘 / 打印的文本一律走 dd_v1_pii_service（不另抄正则）。
    #   检索与摘录仍用原文（摘录的检索键是类型词/期间/附件，不含义务文本）⇒ 不退化。
    obs, flags = sem.redact_for_output(obs, flags)
    Path(a.out).write_text(json.dumps(obs, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({"obligations": len(obs),
                      "needs_human_split": [f for f in flags if f.get("status") in ("NEEDS_HUMAN_SPLIT", "PARTIAL_SPLIT")],
                      "ambiguous_splits": [f for f in flags if f.get("status") == "AMBIGUOUS_SPLIT"],
                      "out": str(a.out)}, ensure_ascii=False))
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


# gm-fix-minor4-fixture-gate: exemption-by-original-material-root-only
def _fixture_exempt(orig_material_root: Path) -> bool:
    """合成 fixture 豁免：**只看原始材料根**（输入是什么），不看输出落在哪。

    ★ 唯一判据口径（监工第 38 条①）：原始材料根在仓内 backend/tests/fixtures 下 ⇒ 豁免；
      否则一律视为真实材料，必须 --allow-real-material。
    ★ 本函数**只吃一个参数** ⇒ 输出路径（盲化目录 / 冻结目录）在结构上**无法**影响豁免。
    """
    return sem._inside(orig_material_root, ROOT / "backend" / "tests" / "fixtures")


# gm-fix-minor4-write-guard: refuse-writing-outside-material-into-repo
def _guard_material_output_not_in_repo(a, orig_material_root: Path) -> str | None:
    """仓外材料**不得**把副本写进仓库目录（公开仓泄漏面）。

    闸口（fixture 豁免）只拦「处理」，拦不住「写副本」：
    `_prepare_material` 在闸口**之前**就把盲化/冻结副本写到 `--blind-material-out` /
    `--snapshot-freeze-dir` ⇒ 即使随后 exit 3，仓外材料的副本**已经**落进仓库树
    （实测：只按原始根判的 B' 案同样被污染）。
    ⇒ 这里在**任何写入之前**先拦：源材料不在仓内 fixture 下时，
      盲化 / 冻结 / 评估目标一律不得落在仓库树内（仓内合成 fixture 源不受此限）。
    """
    if sem._inside(orig_material_root, ROOT / "backend" / "tests" / "fixtures"):
        return None  # 仓内合成 fixture ⇒ 允许在仓内落副本
    for attr in ("blind_material_out", "snapshot_freeze_dir", "snapshot_evaluate_dir"):
        val = getattr(a, attr, None)
        if not val:
            continue
        p = Path(val).resolve()
        if sem._inside(p, ROOT):
            return (f"BLOCKED: 仓外材料不得写入仓库目录（--{attr}={p}）；"
                    f"请把盲化/冻结目标指向仓库外的目录")
    return None


# GM:A4A:CLI:RUN-HEAD
def cmd_run(a) -> int:
    meta = _json(Path(a.meta))
    orig_material_root = Path(a.material_root).resolve()
    # gm-fix-minor4-write-guard: refuse-writing-outside-material-into-repo
    blocked = _guard_material_output_not_in_repo(a, orig_material_root)
    if blocked:
        print(f"拒绝：{blocked}", file=sys.stderr)
        return 3
    material_root, meta = _prepare_material(a, orig_material_root, meta)
    # gm-fix-minor4-fixture-gate: exemption-by-original-material-root-only
    # gm-fix-a4a-minor4: fixture-exemption-on-original-material-root（前序标记：当时口径写错，见下）
    # ★ 合成 fixture 豁免**只按原始材料根**判定（看**输入**是什么，不看输出落在哪）。
    #   `_prepare_material` 会把材料搬到 `--blind-material-out` / `--snapshot-freeze-dir`；
    #   若把**盲化后/冻结后**路径也算进豁免：输出落在仓内 backend/tests/fixtures 下
    #   ⇒ 任意仓外材料都自动获得豁免 ⇒ 真实材料闸口形同虚设（可被放行），
    #   且仓外材料的副本被写进仓内（公开仓泄漏面）。
    #   ★ 对照实验（会话工作区探针 v2，四组 A/B/B'/C；被测代码 sha256 前缀 15282351088537ee）：
    #       A 仓内合成 fixture         ⇒ 放行（rc 0）
    #       C 仓外材料 + 不盲化        ⇒ 拒绝（rc 3，BLOCKED: 真实材料）
    #       B 仓外材料 + 输出落仓内    ⇒ 旧实现**未触发** BLOCKED（闸口被绕过）
    #       B' 同 B 但只按原始材料根    ⇒ 拒绝（rc 3）⇒ 绕过确由 `or` 那一半引入
    #   修法：豁免只看 `orig_material_root`（**输入**是不是仓内合成 fixture）。
    #   ★ 不放宽真实材料：原始材料根在仓外时仍必须 --allow-real-material。
    fixture = _fixture_exempt(orig_material_root)
    try:  # 仓库内合成 fixture 免开关；其他任何目录都视为真实材料，必须 --allow-real-material
        snap_dir = sem.local_material_snapshot(material_root, meta,
                                               allow_real=fixture or a.allow_real_material)
    except sem.Blocked as e:
        print(f"拒绝：{e}", file=sys.stderr)
        return 3
    out = Path(a.out).resolve()
    if sem._inside(out, snap_dir):
        print("拒绝：--out 不能放在材料目录里（不改动原始材料）", file=sys.stderr)
        return 3
    items = _maybe_blind_items(a, _load_items(Path(a.items)))
    obligations = _json(Path(a.obligations)) if a.obligations else None
    text_root = Path(a.text_root).resolve() if a.text_root else None
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
# GM:A4A:CLI:RUN-REPLY
        wd.mkdir(parents=True, exist_ok=True)
        if getattr(a, "synthetic_replies", None):  # 预置回贴（零进程零费用）
            err = _install_synthetic_reply(Path(a.synthetic_replies), tag, wd)
            if err:
                print(f"拒绝：{err}", file=sys.stderr)
                return 3
        rec = sem.run_semantic(_adapter(a), snap_dir, meta, g, budget, workdir=wd,
                               obligations=obs_g, text_root=text_root)
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


# GM:A4A:CLI:SCORE
def cmd_score(a) -> int:
    gold_p, run_dir = Path(a.gold), Path(a.run_dir)
    sem.assert_gold_isolated(gold_p, run_dir, *[Path(x) for x in (a.material_root, a.text_root) if x])
    rec_paths = sorted(run_dir.rglob("run_record.json"))
    recs = [json.loads(p.read_text("utf-8")) for p in rec_paths]
    if getattr(a, "classify", False):
        return _cmd_score_classified(a, gold_p, run_dir, recs, rec_paths)
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


# GM:A4A:CLI:SCORE-CLASSIFIED
def _cmd_score_classified(a, gold_p: Path, run_dir: Path, recs: list[dict],
                          rec_paths: list[Path]) -> int:
    """错误分类路径（A4a-4）：Gold 隔离（**新增 Git 工作树检测**）+ 人工确认校验 + 分类 + 回指。

    既有 ``score`` 路径（不带 ``--classify``）逐字未改；本路径新增：
    - Gold 落在任何 Git 工作树内 ⇒ 拒绝（退出码 3）；
    - Gold 缺 ``confirmed_by`` / ``confirmed_at`` ⇒ NOT_SCORABLE（退出码 3，不是「当已确认」）；
    - 产出 score.json + score.csv + 错误分类表（CSV）。
    """
    try:
        sc.assert_gold_not_in_git_worktree(gold_p)
    except sc.GoldIsolationError as e:
        print(f"拒绝：{e}", file=sys.stderr)
        return 3
    meta = _json(Path(a.classify_meta)) if getattr(a, "classify_meta", None) else None
    res = sc.score_with_classification(recs, _json(gold_p), meta=meta,
                                       record_paths=[str(p) for p in rec_paths],
                                       run_dir=run_dir,
                                       provenance=_synthetic_provenance(recs))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    rows = (res.get("classification") or {}).get("rows") or []
    if rows:
        with open(out.with_suffix(".csv"), "w", encoding="utf-8-sig", newline="") as fh:
            keys = sorted({k for r in rows for k in r})
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            for r in rows:
                w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v
                            for k, v in r.items()})
        table = Path(a.classify_out) if getattr(a, "classify_out", None) else out.with_name(out.stem + ".errors.csv")
        table.parent.mkdir(parents=True, exist_ok=True)
        cols = ["obligation_id", "category", "flags", "confident_mismatch", "expected_verdict",
                "agent_verdict", "expected_files", "agent_files", "expected_entity",
                "expected_period", "answer_entity", "answer_period", "confidence_or_uncertain",
                "run_record_path", "file_id", "locator", "locator_source", "note"]
        with open(table, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v
                            for k, v in r.items()})
    print(json.dumps({k: v for k, v in res.items()
                      if k not in ("rows", "base", "classification")}, ensure_ascii=False))
    return 0 if res.get("status") in ("SCORED", "LOW_CONFIDENCE") else 3


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scaffold"); s.add_argument("--material-root", required=True); s.add_argument("--out", required=True)
    s.add_argument("--entity", default="")
# GM:A4A:CLI:ARG-SPLIT
    s = sub.add_parser("split"); s.add_argument("--items", required=True); s.add_argument("--out", required=True)
    s.add_argument("--blind-leak-words", default="", help="盲化泄漏词表（逗号分隔）；给了就把条目里的泄漏串换成盲化名")
    s.add_argument("--blind-items-out", default=None, help="盲化后的条目落盘路径（拆分依据）")
    r = sub.add_parser("run")
    r.add_argument("--material-root", required=True); r.add_argument("--meta", required=True)
    r.add_argument("--items", required=True); r.add_argument("--obligations", default=None)
    r.add_argument("--text-root", default=None); r.add_argument("--out", required=True)
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
# GM:A4A:CLI:ARG-RUN
    r.add_argument("--resume", action="store_true", help="跳过已有 run_record.json 的条目")
    r.add_argument("--blind-material-out", default=None,
                   help="盲化材料目录落盘路径（相对路径 + 正文里的泄漏串一并盲化）")
    r.add_argument("--blind-leak-words", default="", help="盲化泄漏词表（逗号分隔）")
    r.add_argument("--blind-mapping-out", default=None,
                   help="盲化映射表落盘路径（必须落在材料目录之外，且不得进 Git）")
    r.add_argument("--blind-items-out", default=None, help="盲化后的条目落盘路径")
    r.add_argument("--snapshot-freeze-dir", default=None, help="冻结快照目录（被考侧）")
    r.add_argument("--snapshot-evaluate-dir", default=None,
                   help="冻结快照目录（被评侧；与被考侧逐件 sha256 必须相等）")
    r.add_argument("--synthetic-replies", default=None,
                   help="预置回贴目录（<dir>/run-<tag>.json ⇒ 零进程零费用的合成回放）")
# GM:A4A:CLI:ARG-SCORE
    c = sub.add_parser("score"); c.add_argument("--run-dir", required=True); c.add_argument("--gold", required=True)
    c.add_argument("--out", required=True); c.add_argument("--material-root", default=None)
    c.add_argument("--text-root", default=None)
    c.add_argument("--classify", action="store_true", help="启用错误分类（A4a-4：Gold 隔离 + 人工确认校验 + 分类回指）")
    c.add_argument("--classify-out", default=None, help="错误分类表（CSV）落盘路径")
    c.add_argument("--classify-meta", default=None, help="meta.json 路径（locator 派生 + 期望主体/期间推导用）")
    a = p.parse_args(argv)
    if a.cmd == "run" and a.cost_cap is not None:
        print("拒绝：--cost-cap 无法执行——本地 CLI（dsh/codex）不报告每次费用。"
              "请改用 --max-total-calls N 限制调用次数，并在 DeepSeek 平台设置余额预警", file=sys.stderr)
        return 3
    return {"scaffold": cmd_scaffold, "split": cmd_split, "run": cmd_run, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
