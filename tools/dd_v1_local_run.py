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
import time
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


# GM:A4A:CLI:PERIOD-ANCHOR
def _period_anchor_arg(raw: str | None) -> dict | None:
    """把 ``--period-anchor``（JSON 文本）解析成**显式配置**的可验证锚点。

    ★ 锚点优先级（期间服务口径）：**显式配置 > 原文声明 > 材料自身年度**；
      本函数只负责第一档。默认空 ⇒ ``None`` ⇒ 相对期间若没有其它可验证锚点就判
      「依据不足」（**不擅自拿系统时间当基准**）。
    ★ 给了但不是合法 JSON 对象、或既没有 ``year`` 也没有 ``date`` ⇒ **报错退出**：
      静默忽略会让口径悄悄退化成「无法判定」，而调用方以为锚点已生效。
    """
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
    except (TypeError, ValueError):
        print("拒绝：--period-anchor 不是合法 JSON"
              "（例：'{\"date\": \"2024-12-31\"}' 或 '{\"year\": 2024}'）",
              file=sys.stderr)
        raise SystemExit(3)
    if not isinstance(obj, dict):
        print("拒绝：--period-anchor 必须是一个 JSON 对象", file=sys.stderr)
        raise SystemExit(3)
    out: dict = {}
    if obj.get("year") is not None:
        try:
            yi = int(obj["year"])
        except (TypeError, ValueError):
            print("拒绝：--period-anchor 的 year 必须是整数", file=sys.stderr)
            raise SystemExit(3)
        if not (1900 <= yi <= 2999):
            print("拒绝：--period-anchor 的 year 超出可核验范围（1900-2999）",
                  file=sys.stderr)
            raise SystemExit(3)
        out["year"] = yi
    if obj.get("date") is not None:
        d = str(obj["date"]).strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            print("拒绝：--period-anchor 的 date 必须是 YYYY-MM-DD", file=sys.stderr)
            raise SystemExit(3)
        out["date"] = d
    if not out:
        print("拒绝：--period-anchor 里必须有 year（四位年）或 date（YYYY-MM-DD）",
              file=sys.stderr)
        raise SystemExit(3)
    for k in ("literal", "note"):
        if obj.get(k):
            out[k] = str(obj[k])
    return out



# ── WP2：库侧**权威拆解**的消费入口（#108 实测 P0-2）──────────────────────
# ★ 同一张 42 题考卷，库侧拆 91 条（覆盖 42 题）、运行器侧只拆 15 条（覆盖 12 题）
#   ⇒ 根因是**两套拆解**并存 ⇒ 且 **Gold 引的是库侧那条 obligation_id**
#   ⇒ 运行器用另一套 ⇒ **答卷与标准答案根本对不上**。
# ⇒ 处置（**不开发第三套**）：**库侧那套是唯一权威** ⇒ 运行器**消费**它。

def _load_library_contract(library_id: str) -> dict:
    """读库侧权威义务契约（``dd_v1_requirement_service`` 导出）。"""
    return rq.export_obligation_contract(library_id)


def _match_obligations_to_items(obligations: list[dict], items: list[dict]) -> tuple:
    """按**题号**把库侧义务挂到运行器条目上 ⇒ 返回 (挂上的, 没挂上的)。

    ★ join 键**两级**（与实体映射同思路）：① 题号**逐字**相同；
      ② **归一**题号相同（``canonical_question_id``）—— ★ 归一只用于 join，
      ★ **不改写机构原编号**。
    ★ ★ **挂不上的必须显式报出**（``unmatched_items`` / ``unmatched_obligations``）：
      静默丢题 ⇒ 覆盖率被低报 ⇒ **这正是 P0-2 的形态** ⇒ 绝不静默。
    """
    by_exact: dict[str, list[dict]] = {}
    by_canon: dict[str, list[dict]] = {}
    for o in obligations:
        by_exact.setdefault(str(o.get("item_id") or ""), []).append(o)
        by_canon.setdefault(str(o.get("question_id") or ""), []).append(o)
    used: set[str] = set()
    out: list[dict] = []
    unmatched_items: list[dict] = []
    for it in items:
        iid = str(it.get("item_id") or "")
        hits = by_exact.get(iid) or by_canon.get(rq.canonical_question_id(iid)) or []
        if not hits:
            unmatched_items.append({"item_id": iid,
                                    "canonical_id": rq.canonical_question_id(iid),
                                    "text_head": str(it.get("text") or "")[:80]})
            continue
        for o in hits:
            v = dict(o)
            v["item_id"] = iid
            v["_join"] = "EXACT" if by_exact.get(iid) else "CANONICAL"
            out.append(v)
            used.add(str(o.get("obligation_id") or ""))
    unmatched_obl = [o for o in obligations
                     if str(o.get("obligation_id") or "") not in used]
    return out, unmatched_items, unmatched_obl

# GM:A4A:CLI:SPLIT
def cmd_split(a) -> int:
    items = _maybe_blind_items(a, _load_items(Path(a.items)))
    anchor = _period_anchor_arg(getattr(a, "period_anchor", None))
    coverage = None
    unmatched_items: list[dict] = []
    unmatched_obl: list[dict] = []
    library_id = str(getattr(a, "library", "") or "")
    if library_id:
        # ★★ **权威路径**：库侧那套拆解（**永不丢题**）⇒ 运行器**消费**它。
        contract = _load_library_contract(library_id)
        obs, unmatched_items, unmatched_obl = _match_obligations_to_items(
            contract["obligations"], items)
        coverage = {"source": "LIBRARY_CONTRACT", "library_id": library_id,
                    "obligations_in_library": contract["counts"]["obligations"],
                    "questions_in_library": contract["counts"]["questions"],
                    "questions_matched": len({o["question_id"] for o in obs}),
                    "unmatched_items": unmatched_items,
                    "unmatched_obligations": len(unmatched_obl)}
        flags = [{"item_id": o.get("item_id"), "status": "NEEDS_HUMAN_SPLIT",
                  "obligation_id": o.get("obligation_id"),
                  "reason": "NO_KNOWN_DOC_TYPE"}
                 for o in obs if o.get("needs_human_split")]
    else:
        # ★ 旧路径（**规则侧拆解**）：★ **会丢题**（无材料类型关键词 ⇒ 整题丢弃）
        #   ⇒ 保留只为兼容既有用法 ⇒ ★ **打印显式警告**，不假装与库侧一致。
        obs, flags = sem.split_items(items, period_anchor=anchor)
        coverage = {"source": "LOCAL_RULE_SPLIT",
                    "warning": "LOCAL_RULE_SPLIT_DROPS_ITEMS:本地规则拆解会丢掉"
                               "「无材料类型关键词」的整题 ⇒ 覆盖率被低报；"
                               "★ 请用 --library <LIB> 走库侧权威拆解"}
    # ★ 输出面脱敏：写盘 / 打印的文本一律走 dd_v1_pii_service（不另抄正则）。
    #   检索与摘录仍用原文（摘录的检索键是类型词/期间/附件，不含义务文本）⇒ 不退化。
    obs, flags = sem.redact_for_output(obs, flags)
    Path(a.out).write_text(json.dumps(obs, ensure_ascii=False, indent=1), "utf-8")
    out = {"obligations": len(obs),
           "coverage": coverage,
           "needs_human_split": [f for f in flags if f.get("status") in ("NEEDS_HUMAN_SPLIT", "PARTIAL_SPLIT")],
           "ambiguous_splits": [f for f in flags if f.get("status") == "AMBIGUOUS_SPLIT"],
           "out": str(a.out)}
    print(json.dumps(out, ensure_ascii=False))
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


# GM:A4A:CLI:SIX-STATE
def _six_state_rows(rec: dict) -> list[dict]:
    """把语义层算出的**六态**摊平成 CLI 侧形态（机读三键：候选状态／原因／诊断）。

    ★ 口径全部来自语义层（CLI 只透传）⇒ 入口**不另造一套原因表**，
      **不把「候选为空」统一伪装成 MISSING**（原因不同 ⇒ 机器可区分）。
    ★ 取值域只从语义层封闭枚举取（``sem.NO_CANDIDATE_REASONS``），CLI 不自己列一遍。
    ★ 与薄入口（``tools/dd_team_channel.py``）**同口径**：那边是逐义务三键，
      这边是逐义务三键 ⇒ 两端对齐，不再是「一边齐一边空」。
    """
    status = rec.get("evidence_status") or {}
    hints = rec.get("rule_hints") or {}
    rows: list[dict] = []
    for oid, st in status.items():
        st = st or {}
        hint = hints.get(oid) or {}
        rows.append({
            "obligation_id": oid,
            "candidate_status": st.get("candidate_status"),
            "no_candidate_reason": st.get("no_candidate_reason"),
            "diagnostics": st.get("diagnostics") or {},
            "verdict": hint.get("verdict"),
        })
    return rows


def _six_state_text(rows: list[dict]) -> list[str]:
    """人读形态：候选为空的义务**逐条**写明六态原因（**不合并**成笼统的「缺材料」）。"""
    six = "、".join(sem.NO_CANDIDATE_REASONS)
    empty = [r for r in rows if r.get("no_candidate_reason")]
    lines = ["## 候选为空的义务（为什么没有候选）", "",
             "> 下面每条都**没有**候选材料。原因**分六类**，不合并成一个笼统的「缺材料」；"
             f"取值域（语义层封闭枚举）：`{six}`。",
             "> 本段只透传语义层算出的结论，CLI 不另造一套原因表。", ""]
    if not empty:
        lines += ["（本次运行没有「候选为空」的义务）", ""]
        return lines
    for r in empty:
        dg = r.get("diagnostics") or {}
        lines.append(f"- `{r['obligation_id']}`")
        lines.append(f"    - 候选状态：`{r.get('candidate_status') or '—'}`"
                     f"｜没有候选的原因：`{r.get('no_candidate_reason') or '—'}`"
                     f"｜规则提示：{r.get('verdict') or '—'}")
        if dg:
            lines.append("    - 过滤诊断：" + "｜".join(f"{k}={v}" for k, v in sorted(dg.items())))
        lines.append("")
    return lines


# GM:A4A:CLI:RUN-HEAD
def cmd_run(a) -> int:
    # ★ 锚点先解析：**非法锚点在花任何模型调用之前就退出**（不静默忽略）。
    anchor = _period_anchor_arg(getattr(a, "period_anchor", None))
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
    # ★★ WP2（#108 实测 P0-2）：给了 --library ⇒ **用库侧权威拆解**的义务。
    #   旧路径（不��� --library）走本机规则拆解 ⇒ **无材料类型关键词的整题被丢**
    #   ⇒ 同一张考卷只有 12/42 题进入处理链 ⇒ 「覆盖率」被低报成 28.6%。
    coverage_note: dict = {}
    if not obligations and str(getattr(a, "library", "") or ""):
        _contract = _load_library_contract(a.library)
        _obs, _unmatched_items, _unmatched_obl = _match_obligations_to_items(
            _contract["obligations"], items)
        obligations = _obs
        coverage_note = {
            "source": "LIBRARY_CONTRACT", "library_id": a.library,
            "obligations_in_library": _contract["counts"]["obligations"],
            "questions_in_library": _contract["counts"]["questions"],
            "obligations_matched_to_items": len(_obs),
            "items_without_obligations": _unmatched_items,
            "obligations_not_matched": len(_unmatched_obl),
        }
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
        if obs_g is None and not sem.split_items(g, period_anchor=anchor)[0]:  # 拆不出义务就不调用模型（不浪费付费调用）
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
                               obligations=obs_g, text_root=text_root,
                               period_anchor=anchor,
                               resolve_doc_type=bool(getattr(a, "resolve_doc_type", False)))
        calls_total += rec.get("calls_used", 1)
        v = rec["semantic_validation"]
        rows = _six_state_rows(rec)
        summary.append({"group": tag, "adapter_status": rec["adapter"]["status"],
                        "elapsed_s": rec["adapter"]["elapsed_s"], "mode": v["mode"],
                        "accepted": len(v["accepted"]), "rejected": len(v["rejected"]),
                        "uncovered": v["uncovered_obligations"], "degrade_reason": v["degrade_reason"],
                        # ★ 六态外显（机读）：原始容器 ＋ 逐义务三键
                        #   （`evidence_status` ＝ 语义层原样容器；`obligations` ＝ 摊平后的三键）
                        #   ⇒ 「候选为空」在 CLI 上**可区分六种原因**，不被压成同一个 MISSING。
                        "evidence_status": rec.get("evidence_status") or {},
                        "obligations": rows})
        print(json.dumps(summary[-1], ensure_ascii=False), flush=True)
    (out / "run_summary.json").write_text(json.dumps({"limits": limits, "calls_total": calls_total,
                                                      "coverage": coverage_note,
                                                      "groups": summary}, ensure_ascii=False, indent=1), "utf-8")
    # ★ 六态的**人读面**（与薄入口同款口径：只透传语义层结论，不在入口另造原因表）。
    #   落在输出目录里（不进 run-<tag> 工作目录：那里有 adapter 的白名单约束）。
    (out / "six_state.md").write_text(
        "\n".join(["# 六态（候选为空的原因）· DD-V1 本地运行器", "",
                   f"- 取数时刻（UTC）：{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
                   ""] + _six_state_text([r for s in summary for r in (s.get("obligations") or [])])),
        "utf-8")
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
    s.add_argument("--library", default="",
                   help="★ 库 ID：给了就走**库侧权威拆解**（永不丢题，与 Gold 的 obligation_id 同源）；"
                        "不给则用旧的本机规则拆解（★ 会丢题 ⇒ 覆盖率低报）")
    s.add_argument("--period-anchor", default="",
                   help="相对期间的可验证锚点（JSON）：'{\"date\": \"2024-12-31\"}' 或 '{\"year\": 2024}'。"
                        "锚点优先级：显式配置 > 原文声明 > 材料自身年度；"
                        "不给则不擅自假定（相对期间无其它可验证锚点时判「依据不足」）")
    s.add_argument("--blind-leak-words", default="", help="盲化泄漏词表（逗号分隔）；给了就把条目里的泄漏串换成盲化名")
    s.add_argument("--blind-items-out", default=None, help="盲化后的条目落盘路径（拆分依据）")
    r = sub.add_parser("run")
    r.add_argument("--material-root", required=True); r.add_argument("--meta", required=True)
    r.add_argument("--period-anchor", default="",
                   help="同 split：相对期间的可验证锚点（JSON）")
    r.add_argument("--items", required=True); r.add_argument("--obligations", default=None)
    r.add_argument("--library", default="",
                   help="★ 库 ID：给了就用**库侧权威拆解**的义务（覆盖全部题目，且 obligation_id 与 Gold 同源）")
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
    r.add_argument("--resolve-doc-type", action="store_true",
                   help="★ 打开「规则层拆不出材料类型 ⇒ 交给模型判定」这条通道："
                        "这类条目会额外产出一条「类型待判定」义务送模型，模型须给出 "
                        "proposed_doc_type（权威 10 类）或诚实弃答。"
                        "默认关闭：拆不出就不调用模型（不浪费付费调用）")
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
