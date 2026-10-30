"""DD-V1 考场服务：机器答卷 · 隔离阅卷 · 冻结评分口径 · 版本对比。

对应 `cangjie-fos#85`（永久验收红线）与 `cangjie-teams-channel#108`（刘江 Windows 复测）。

**四件事**：

1. ``build_answer_sheet`` —— **机器答卷**：逐题记录「AI 理解了什么 / 看了哪些候选 /
   最终选了什么 / 实际交付了什么 / 来源路径与 SHA256 / 是否弃答及原因」。
   考生**看不到**标准答案：本模块只消费 run_record 与 packet，不接触 Gold。

2. ``grade_answer_sheet`` —— **隔离阅卷**：阅卷端单独读标准答案包，逐题逐文件比较，
   产出 7 项指标 + 0—100 总成绩单。**有有效标准答案而机器 0 件交付 ⇒ 报 0 分
   （不是 NOT_SCORABLE）**；只有客观不可评分时才 NOT_SCORABLE，并写明阻塞。

3. ``load_scoring_spec`` —— **冻结评分口径**：公式、权重、分母在开考前冻结，
   冻结件带内容指纹；换尺子必须换版本并留差异说明。

4. ``compare_scorecards`` —— **版本成绩比较**：同口径下输出「旧版 → 新版 → 变化」。

红线：
- **不得**把真实 0 分伪装成 NOT_SCORABLE（`#85` 明文）。
- **不得**用高业务分抵消安全闸失败（错主体/错年度/受限外发/哈希不一致/未批准交付）。
- **不得**让考生读取标准答案：阅卷与作答是**两个进程级分离**的入口，
  且本模块对考生侧产物做**泄漏检测**。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cangjie_fos.services import dd_v1_gold_service as gold_svc
from cangjie_fos.services import dd_v1_run_modes as rm

#: 机器答卷版本
ANSWER_SHEET_SCHEMA = "dd_v1_answer_sheet.v1"
#: 成绩单版本
SCORECARD_SCHEMA = "dd_v1_scorecard.v1"
#: 冻结评分口径的默认文件名（放在 backend/config/）
DEFAULT_SCORING_SPEC_FILENAME = "dd_v1_exam_scoring_spec.v1.json"

#: 确定性作答（**UNCERTAIN 与弃答不算「已理解」** —— 没答就没答，不得算覆盖）
DETERMINATE_VERDICTS = ("MATCH", "PARTIAL", "OUTDATED", "CONFLICT", "MISSING")
#: 考生侧**绝对不允许**出现的字段（出现即判泄漏）
GOLD_ONLY_KEYS = ("expected_files", "expected_verdict", "confirmed_by", "confirmed_at",
                  "gold_pack_id", "answer_key")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ─────────────────────────────────────────────────────────────────────────────
# 0. 义务身份：**权威 ID（库侧）** vs **分簇 ID（答卷侧）**
# ─────────────────────────────────────────────────────────────────────────────
#
# ★ **事故形态（#108 刘江 2026-10-30 Windows 真机复测实测）**：
#   · 库侧一条义务被**多主体分簇**（``dd_v1_bridge_service.build_semantic_obligations``）
#     ⇒ 答卷侧每个主体一个**分簇 ID**（``<库侧ID>@<主体>``）⇒ 91 条义务变 200 行；
#   · 标准答案（Gold）引的是**库侧那条** ``obligation_id``（91 条）；
#   ⇒ 答卷与 Gold **对不上** ⇒ 逐题比较全是 ``NO_ANSWER``，
#     且泄漏检测第 3 条判据（义务 id 既不在考卷也不在 Gold）⇒ ``GOLD_LEAK_DETECTED``
#     ⇒ ``scores=null``（#108 实测：分数出不来）。
#
# ★ **处置（不是改主体分簇口径）**：分簇是**业务需要**（跨法人不混桶），不能删。
#   ⇒ 引入**权威 ID**概念：**库侧 obligation_id 才是义务身份**，
#     分簇 ID 只是**该主体下的一个子视图**。
#   ⇒ 阅卷一律按**权威 ID**聚合（一条库义务 ⇒ 若干分簇行 ⇒ 汇总成一行逐题明细）。

def authoritative_obligation_id(obj: dict[str, Any] | None) -> str:
    """取义务的**权威 ID（库侧 obligation_id）**。

    优先级：① 显式 ``source_obligation_id``（桥接层已带）；
    ② ``obligation_id`` 且**不含** ``@``（本身就是库侧 ID）；
    ③ ``obligation_id`` 的 ``@`` 之前部分（分簇 ID 的降级还原）。

    ★ **不用**「先取 obligation_id 再切 @」的单一路径：若上游把分簇 ID 写进了
      ``obligation_id``、而 ``source_obligation_id`` 才是库侧 ID，取错会**静默对不上**。
    """
    o = obj or {}
    src = str(o.get("source_obligation_id") or "").strip()
    if src:
        return src
    oid = str(o.get("obligation_id") or "").strip()
    if not oid:
        return ""
    return oid.split("@", 1)[0]


def cluster_obligation_id(obj: dict[str, Any] | None) -> str:
    """取义务的**分簇 ID**（答卷侧实际使用的那个 ID，可能带 ``@主体`` 后缀）。"""
    o = obj or {}
    oid = str(o.get("obligation_id") or "").strip()
    if oid:
        return oid
    return str(o.get("source_obligation_id") or "").strip()


def group_answer_rows_by_authoritative_id(
        rows: list[dict[str, Any]] | None) -> dict[str, list[dict[str, Any]]]:
    """把答卷行按**权威 ID**分组（一条库义务 ⇒ 若干分簇行）。"""
    out: dict[str, list[dict[str, Any]]] = {}
    for r in (rows or []):
        aid = authoritative_obligation_id(r)
        if not aid:
            continue
        out.setdefault(aid, []).append(r)
    return out


def merge_cluster_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """把**同一义务的多个分簇行**合并成一行（阅卷侧的义务级视图）。

    ★ 合并口径：
      · ``selected`` / ``delivered`` / ``candidates`` ⇒ **并集**（按 file_id 去重）；
      · ``verdict`` ⇒ 取**确定性**判定（多簇里有一簇确定就算这条义务确定）；
      · ``understood`` ⇒ 任一簇理解即算理解；
      · ``abstained`` ⇒ **全部**簇都弃答才算弃答。
    """
    if not rows:
        return {}
    merged: dict[str, Any] = {
        "obligation_id": authoritative_obligation_id(rows[0]),
        "cluster_ids": [cluster_obligation_id(r) for r in rows],
        "item_id": str(rows[0].get("item_id") or ""),
        "text": str(rows[0].get("text") or ""),
        "interpretation": rows[0].get("interpretation") or {},
        "selected": [], "delivered": [], "candidates": [],
        "verdict": "", "confidence": "", "abstained": True,
        "abstain_reason": "", "selection_source": "",
        "warnings": [], "rejected": False, "rejected_reason": "",
        "candidate_window": {},
    }
    seen: dict[str, set[str]] = {"selected": set(), "delivered": set(), "candidates": set()}
    verdicts: list[str] = []
    for r in rows:
        for key in ("selected", "delivered", "candidates"):
            for x in (r.get(key) or []):
                fid = str(x.get("file_id") or "")
                marker = fid or json.dumps(x, ensure_ascii=False, sort_keys=True)
                if marker in seen[key]:
                    continue
                seen[key].add(marker)
                merged[key].append(x)
        v = str(r.get("verdict") or "")
        if v:
            verdicts.append(v)
        if v in DETERMINATE_VERDICTS and not merged["verdict"]:
            merged["verdict"] = v
        if not merged["verdict"] and v == "UNCERTAIN":
            merged["verdict"] = "UNCERTAIN"
        if r.get("understanding_resolved") or (r.get("interpretation") or {}).get("resolved"):
            merged["interpretation"] = r.get("interpretation") or merged["interpretation"]
        if not r.get("abstained"):
            merged["abstained"] = False
        if r.get("abstain_reason") and not merged["abstain_reason"]:
            merged["abstain_reason"] = str(r.get("abstain_reason"))
        if r.get("selection_source") and not merged["selection_source"]:
            merged["selection_source"] = str(r.get("selection_source"))
        for w in (r.get("warnings") or []):
            if w not in merged["warnings"]:
                merged["warnings"].append(w)
        if r.get("rejected"):
            merged["rejected"] = True
            merged["rejected_reason"] = merged["rejected_reason"] or str(r.get("rejected_reason") or "")
        cw = r.get("candidate_window") or {}
        if cw:
            merged["candidate_window"] = cw
        if r.get("confidence") and not merged["confidence"]:
            merged["confidence"] = r.get("confidence")
    if not merged["verdict"] and verdicts:
        merged["verdict"] = verdicts[0]
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# 1. 机器答卷
# ─────────────────────────────────────────────────────────────────────────────

def _candidate_rows(evidence_rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """候选材料（**含来源路径与 SHA256** —— 答卷必须能自证选了哪份原件）。"""
    out: list[dict[str, Any]] = []
    for e in evidence_rows or []:
        out.append({
            "file_id": str(e.get("file_id") or ""),
            "sha256": str(e.get("sha256") or ""),
            "relative_path": str(e.get("relative_path") or ""),
            "entity": str(e.get("entity") or ""),
            "period": str(e.get("period") or ""),
            "doc_type": str(e.get("doc_type") or ""),
            "part": str(e.get("part") or ""),
            "version_status": str(e.get("version_status") or ""),
            "locator": str(e.get("locator") or ""),
            "period_status": str(e.get("period_status") or ""),
        })
    return out


def _interpretation(ob: dict[str, Any] | None) -> dict[str, Any]:
    """考生对一条义务的**理解**（材料类型 / 主体口径 / 期间口径 / 附件要求）。

    ``doc_type_source``：
    - ``RULE`` —— 规则引擎从原文解析出材料类型；
    - ``SEMANTIC`` —— 规则解析不出、**由模型**提出（见 ``proposed_doc_type``）；
    - ``UNRESOLVED`` —— 谁都没解析出 ⇒ 该题**未理解**。
    """
    ob = ob or {}
    dt = str(ob.get("doc_type") or "")
    src = str(ob.get("doc_type_source") or "")
    if not src:
        src = "RULE" if dt else "UNRESOLVED"
    unresolved = bool(ob.get("doc_type_unresolved")) or (not dt and src == "UNRESOLVED")
    return {
        "doc_type": dt,
        "doc_type_label": str(ob.get("doc_type_label") or ""),
        "doc_type_source": src,
        "doc_type_unresolved": unresolved,
        "entity": str(ob.get("entity") or ""),
        "entity_basis": str(ob.get("entity_basis") or ""),
        "period": str(ob.get("period") or ""),
        "required_parts": list(ob.get("required_parts") or []),
        "text": str(ob.get("text") or ""),
        "split_method": str(ob.get("split_method") or ""),
        "resolved": (not unresolved),
    }



def read_delivery_manifest(manifest_path: Path | str) -> list[dict[str, Any]]:
    """读 ``组包manifest.tsv`` ⇒ **实际交付清单**（file_id / 路径 / 源与副本 SHA256）。

    ★ 这是「实际交付」的**权威来源**（人工也是拿它逐件核哈希的那一份）。
    ★ 缺文件 / 坏行 ⇒ 返回空清单并**不抛异常**（调用方据此判「0 件交付」，
      而不是把异常当成「有交付」）。
    """
    import csv

    path = Path(manifest_path)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                fid = str(row.get("file_id") or "").strip()
                if not fid:
                    continue
                same = str(row.get("一致") or "").strip()
                out.append({
                    "file_id": fid,
                    "delivered_path": str(row.get("交付路径") or "").strip(),
                    "source_sha256": str(row.get("源sha256") or "").strip(),
                    "copy_sha256": str(row.get("副本sha256") or "").strip(),
                    "hash_match": same in ("是", "True", "true", "1"),
                    "obligation_key": str(row.get("义务ID") or "").strip(),
                    "obligation_text": str(row.get("原子义务") or "").strip(),
                    "verdict": str(row.get("判定") or "").strip(),
                    "gate": str(row.get("审核结论") or "").strip(),
                })
    except (OSError, UnicodeDecodeError, csv.Error):
        return []
    return out

def build_answer_sheet(run_record: dict[str, Any] | None,
                       packet: dict[str, Any] | None,
                       *,
                       exam_id: str = "",
                       delivered: list[dict[str, Any]] | None = None,
                       gold_resolution: dict[str, Any] | None = None,
                       requested_mode: str = "RULE_ONLY",
                       ) -> dict[str, Any]:
    """由 run_record + packet 产出**机器答卷**。

    ``delivered``：实际组包交付清单（``file_id`` / 交付路径 / 源 SHA256 / 副本 SHA256）。
    ``gold_resolution``：**不参与**本函数（考生侧不读 Gold）——保留形参只为让调用方
    在同一处传参时不会误以为它生效；阅卷在 ``grade_answer_sheet`` 里单独做。
    ``requested_mode``：**请求的运行模式**（RULE_ONLY / AGENT_REQUIRED / AUTO）——
    施工令 V3.0 §6；由调用方（考试台）显式传入，不在这里猜。
    """
    rec = run_record or {}
    pkt = packet or {}
    obligations = {str(o.get("obligation_id")): o for o in (pkt.get("obligations") or [])}
    evidence = pkt.get("evidence") or {}
    evidence_status = pkt.get("evidence_status") or {}
    sem = rec.get("semantic_validation") or {}
    accepted: dict[str, dict[str, Any]] = {}
    for a in sem.get("accepted") or []:
        accepted[str(a.get("obligation_id"))] = a
    rejected = {str(a.get("obligation_id")): a for a in (sem.get("rejected") or [])}
    # ★★ RULE_ONLY（**没接模型**）时，「机器选了什么」只能取**规则链的提示**
    #   （bridge 的 rule_hint：可交付候选 + 规则判定）——
    #   否则答卷里「选中 0 件」⇒ 召回恒 0 ⇒ 考的是「模型跑没跑」，不是「选得对不对」。
    rule_hints = pkt.get("rule_hints") or {}
    adapter = rec.get("adapter") or {}
    delivered_by_file: dict[str, dict[str, Any]] = {}
    for d in delivered or []:
        fid = str(d.get("file_id") or "")
        if fid:
            delivered_by_file[fid] = d

    rows: list[dict[str, Any]] = []
    for oid in sorted(obligations):
        ob = obligations[oid]
        ans = accepted.get(oid) or {}
        rejected_row = rejected.get(oid) or {}
        interp = _interpretation(ob)
        cands = _candidate_rows(evidence.get(oid) or [])
        selected: list[dict[str, Any]] = []
        for c in (ans.get("candidate_files") or []):
            fid = str(c.get("file_id") or "")
            src = next((x for x in cands if x["file_id"] == fid), None)
            selected.append({
                "file_id": fid,
                "sha256": str(c.get("sha256") or (src or {}).get("sha256") or ""),
                "relative_path": str(c.get("relative_path") or (src or {}).get("relative_path") or ""),
                "locator": str(c.get("locator") or ""),
                "match_reason": str(c.get("match_reason") or ""),
                "entity": str(c.get("entity") or (src or {}).get("entity") or ""),
                "period": str(c.get("period") or (src or {}).get("period") or ""),
            })
        verdict = str(ans.get("proposed_verdict") or "")
        selection_source = "MODEL" if ans else ""
        if not selected:
            # ★ 规则链兜底：取 rule_hint 的可交付候选（**标出来源**，不冒充模型判断）
            hint = rule_hints.get(oid) or {}
            for fid in (hint.get("files") or []):
                src = next((x for x in cands if x["file_id"] == str(fid)), None)
                selected.append({
                    "file_id": str(fid),
                    "sha256": str((src or {}).get("sha256") or ""),
                    "relative_path": str((src or {}).get("relative_path") or ""),
                    "locator": str((src or {}).get("locator") or ""),
                    "match_reason": str(hint.get("verdict") or ""),
                    "entity": str((src or {}).get("entity") or ""),
                    "period": str((src or {}).get("period") or ""),
                })
            if selected:
                selection_source = "RULE_HINT"
                if not verdict:
                    verdict = str(hint.get("verdict") or "")
        abstain_reason = ans.get("abstain_reason")
        abstained = bool(verdict == "UNCERTAIN" or (abstain_reason and not selected))
        # ★ 「实际交付」是**事实**（组包复制了哪些原件），不是模型的自我声明 ⇒
        #   按 **file_id** 认（选中 ∪ 候选），**不**只看模型选中那几件。
        #   否则「规则链交付了、模型没选中」会被算成 0 交付 ⇒ HR-1 误伤成 0 分。
        deliv: list[dict[str, Any]] = []
        seen_deliv: set[str] = set()
        for s in list(selected) + list(cands):
            fid = str(s.get("file_id") or "")
            if not fid or fid in seen_deliv:
                continue
            d = delivered_by_file.get(fid)
            if not d:
                continue
            seen_deliv.add(fid)
            deliv.append({
                "file_id": fid,
                "delivered_path": str(d.get("delivered_path") or d.get("relative_path") or ""),
                "source_sha256": str(d.get("source_sha256") or s.get("sha256") or ""),
                "copy_sha256": str(d.get("copy_sha256") or ""),
                "hash_match": bool(d.get("hash_match", True)),
            })
        st = evidence_status.get(oid) or {}
        row = {
            "obligation_id": oid,
            # ★★ **权威 ID（库侧）**（#108 实测事故：分簇 ID 与 Gold 对不上）：
            #   多主体分簇时 ``obligation_id`` 带 ``@主体`` 后缀 ⇒ Gold 引的是库侧那条
            #   ⇒ 必须**同时**带上库侧 ID，阅卷才有得对（不改主体分簇口径）。
            "source_obligation_id": authoritative_obligation_id(ob),
            "obligation_cluster_id": oid,
            "item_id": str(ob.get("item_id") or ""),
            "text": interp["text"],
            "interpretation": interp,
            "candidates": cands,
            "candidate_count": len(cands),
            "selected": selected,
            "selected_count": len(selected),
            # ★ 选材来源：MODEL（模型真的判了）｜RULE_HINT（**没接模型**，取规则链提示）
            "selection_source": selection_source,
            "verdict": verdict,
            "confidence": ans.get("confidence_or_uncertain"),
            "abstained": abstained,
            "abstain_reason": str(abstain_reason or ""),
            "warnings": list(ans.get("warnings") or []),
            "rejected": bool(rejected_row),
            "rejected_reason": str(rejected_row.get("reason") or rejected_row.get("errors") or ""),
            "delivered": deliv,
            "delivered_count": len(deliv),
            "candidate_window": {
                "cap": st.get("candidate_cap"),
                "found": st.get("candidates_total"),
                "checked": st.get("candidates_used"),
                "unchecked": st.get("truncated_candidate_count"),
                "truncated": bool(st.get("candidate_truncated")),
                "stop_reason": str(st.get("candidate_cap_note") or ""),
            },
            "no_candidate_reason": st.get("no_candidate_reason"),
            "candidate_status": st.get("candidate_status"),
        }
        rows.append(row)

    # ★ 交付件数取**交付清单本身**（组包的事实）∪ **逐行归集到的交付件**：
    #   · 只取清单 ⇒ 清单外、但行内有据的交付件会被漏掉；
    #   · 只取行内 ⇒ 挂不上义务的交付件会被漏掉（口径不齐时会出现）。
    #   ⇒ 取**并集**（按 file_id 去重）⇒ 两边都不漏，且件数与清单一致。
    _by_fid: dict[str, dict[str, Any]] = {}
    for d in list(delivered or []):
        fid = str(d.get("file_id") or "")
        if fid:
            _by_fid.setdefault(fid, dict(d))
    for r in rows:
        for d in r.get("delivered") or []:
            fid = str(d.get("file_id") or "")
            if fid:
                _by_fid.setdefault(fid, dict(d))
    delivered_files = list(_by_fid.values())
    summary = {
        "obligations": len(rows),
        "understood": sum(1 for r in rows if r["interpretation"]["resolved"]),
        "answered": sum(1 for r in rows if r["verdict"] in DETERMINATE_VERDICTS),
        "abstained": sum(1 for r in rows if r["abstained"]),
        "selected_files": sum(r["selected_count"] for r in rows),
        "delivered_files": len(delivered_files),
        "delivered_files_attributed": sum(len(r["delivered"]) for r in rows),
        "truncated_obligations": sum(1 for r in rows if r["candidate_window"]["truncated"]),
        "unresolved_doc_type_obligations": sum(1 for r in rows
                                              if r["interpretation"]["doc_type_unresolved"]),
    }
    # ★★★ 参与类别的判定（**只认「盖章」**，**不采信适配器自填的 provenance**）
    #   ★ 真因（第 6 轮独立复核抓到的绕过口）：`adapter.provenance` 是**适配器自己写的
    #     自由字段**（`AdapterResult.provenance`）⇒ 一份 `run_record.json` 把它写成
    #     `"HARNESS_MODEL"` ⇒ 答卷就会自称「有本机 Harness 参与」⇒ **自填即可冒充**。
    #   ⇒ 正解：**只有带 `provenance_source == "ADAPTER_IMPLEMENTATION"` 盖章的值才采信**；
    #     适配器自填的只记进 `declared_provenance`（留痕，不作数）。
    _prov = ""
    _prov_source = ""
    _declared = ""
    # ★ **盖章块自带的 `declared_provenance`**（权威的「声明值」；第 7 轮复核的 F18）
    _stamped_declared = ""
    # ★ 必须在分支**之外**初始化（曾因写在分支里 ⇒ 分支没走时 NameError ⇒ 已修）
    _degrade = ""
    for _src in (pkt.get("model_participation"), rec.get("model_participation"),
                 adapter if isinstance(adapter, dict) else None):
        if not isinstance(_src, dict):
            continue
        if str(_src.get("provenance_source") or "") == "ADAPTER_IMPLEMENTATION":
            _prov = str(_src.get("provenance") or "")
            _prov_source = "ADAPTER_IMPLEMENTATION"
            _stamped_declared = str(_src.get("declared_provenance") or "")
            break
        if not _declared:
            _declared = str(_src.get("provenance") or "")
    if not _declared:
        _declared = str(adapter.get("provenance") or "") if isinstance(adapter, dict) else ""
    # ★ ★ **F18：自填值非法时回落到盖章块的 `declared_provenance`**（信息丢失）
    #   —— 人工贴回执路径：`adapter["provenance"]` 是个 dict（工具层塞的原始载荷）
    #   ⇒ 上一版一律记 `UNDECLARED` ⇒ **盖章块里明明写着 `HARNESS_MANUAL`，审计信息却丢了**。
    #   ★ 只在**自填值不是合法类别**时才回落（合法值照旧保留 ⇒ 不改变既有行为）；
    #   ★ 且**只认盖章块**（与 F3 同一条纪律：下游只认盖章）。
    _LEGAL_DECLARED = ("HARNESS_MODEL", "HARNESS_MANUAL", "PREBAKED_RESULT",
                       "UNKNOWN_ADAPTER", "RULE_ONLY", "MODEL_SELECTION_WITHOUT_RECEIPT")
    if _stamped_declared and str(_declared) not in _LEGAL_DECLARED:
        _declared = _stamped_declared
    # ★ ★ **类别 ≠ 参与**（第 6 轮独立复核的 F1，已修）：
    #   参与**类别**只说明「适配器实现是哪一个」，**不说明**「它这次真的跑出了回执」。
    #   ⇒ 二进制不在 PATH（exit 127）／人工还没贴回执（PENDING_MANUAL）／贴进来的文件不存在
    #   ⇒ **都没跑出回执** ⇒ 此时自称 `HARNESS_MODEL` 就是**假凭据**
    #   ⇒ 正解：**类别 ＋ participated** 两个条件都满足，才算「这次有模型参与」。
    # ★ **没有盖章 ⇒ participated 默认 False**（安全侧：认不出就当没有参与）
    # ★ ★★ **口径必须显式区分**（第 8 轮独立复核的 F21）：
    #   机读产物里有两个「participated 味」的字段，**含义不同**：
    #     `model_participation.participated` ＝「**有义务用了模型选材**」（**选材口径**）
    #     `agent_receipt.participated` ／ `run_participated` ＝「**这次真的跑出了回执**」（**回执口径**）
    #   ★ 上一版在「盖章块缺 `run_participated`」时**退回选材口径** ⇒ **拿选材冒充回执** ⇒
    #     在「回执说跑过、但选材口径是 False」时，会**误判成「没跑出回执」** ⇒ 还写出**不实的**理由。
    #   ⇒ 正解：**只采信标了 `participated_scope == "RECEIPT"` 的源**；
    #     只有选材口径 ⇒ **fail-closed（当作没有参与）**，绝不拿选材口径冒充回执口径。
    _participated = False
    _part_scope = ""
    for _src in (pkt.get("model_participation"), rec.get("model_participation"),
                 adapter if isinstance(adapter, dict) else None):
        if not isinstance(_src, dict):
            continue
        if str(_src.get("provenance_source") or "") != "ADAPTER_IMPLEMENTATION":
            continue
        if str(_src.get("participated_scope") or "") == "RECEIPT":
            _participated = bool(_src.get("participated"))
            _part_scope = "RECEIPT"
            break
        # ★ ★ **只认带口径标记的**（第 9 轮独立复核的 F24③：规则必须与代码**逐字一致**）
        #   ⇒ **不**保留「有 `run_participated` 这个键就算数」的兼容逃逸：
        #     那样文档写「以 `participated_scope` 为准」而代码却多信一条路 ⇒ **文档说不等于代码做**。
        if str(_src.get("run_participated_scope") or "") == "RECEIPT":
            _participated = bool(_src.get("run_participated"))
            _part_scope = "RECEIPT"
            break
        # ★ 到这里只有**选材口径** ⇒ **不拿它当回执口径**（fail-closed），继续找回执口径的源
        #   ★ ★ **标签要如实**（第 10 轮独立复核的 F26）：
        #     「**源自己声明** `participated_scope == "SELECTION"`」⇒ 记 `SELECTION_ONLY`；
        #     「**有盖章但压根没有任何口径标记**」（旧 `run_record.json` 的形状）
        #     ⇒ 记 **`UNMARKED`**（★ 上一版一律记 `SELECTION_ONLY` ⇒ **审计字段把来源说错了**：
        #       那个源其实是**回执语义**，只是没带标记）。
        _part_scope = ("SELECTION_ONLY"
                       if str(_src.get("participated_scope") or "") == "SELECTION"
                       else "UNMARKED")
    if not _part_scope:
        _part_scope = "NONE"
    if _prov in ("HARNESS_MODEL", "HARNESS_MANUAL", "PREBAKED_RESULT", "UNKNOWN_ADAPTER"):
        _examinee_mode = _prov if _participated else "RULE_ONLY"
    elif any(r.get("selection_source") == "MODEL" for r in rows):
        _examinee_mode = "MODEL_SELECTION_WITHOUT_RECEIPT"   # ★ 有模型选材但**没有回执** ⇒ 如实标
    elif rows:
        _examinee_mode = "RULE_ONLY"
    else:
        _examinee_mode = "UNKNOWN"
    if _prov in ("HARNESS_MODEL", "HARNESS_MANUAL", "PREBAKED_RESULT") and not _participated:
        # ★ ★ **两种情形、两种措辞**（第 8 轮 F21 ＋ **第 9 轮 F25**）：
        #   ① **回执口径的标记存在、且明确为假** ⇒ 我们**确实知道**「回执说这次没跑出回执」
        #      ⇒ 直说即可（这是最常见的场景：适配器 exit 127／CALL_FAILED）。
        #   ② **压根没有回执口径的标记**（只有选材口径／什么都没有）⇒ 我们**不知道**原因
        #      ⇒ 只陈述「拿不到可采信的标记」，成因列为**可能**（★ 上一版把①也说成② ⇒ **不准确**）。
        if _part_scope == "RECEIPT":
            _why = ("**回执口径的参与标记为假**"
                    "（回执明确说：这次没跑出回执）")
        else:
            _why = ("**拿不到可采信的回执口径参与标记**"
                    "（可能是：二进制不在 PATH／回执未贴／贴进来的文件不存在／"
                    "回执里没有可核的参与标记）")
        _degrade = (f"★ 适配器实现是 {_prov} 这一类，但本次{_why}"
                    "⇒ 本次**没有可采信的模型参与** ⇒ 参与类别按 RULE_ONLY 记，不自称模型凭据"
                    "（★ 回执本身若在别处留存，请以回执为准）")

    # ★★ **运行模式**：请求的模式 ＋ 实际执行路径（施工令 V3.0 §6）
    #   ★ 实际执行路径由**既有**参与判定派生 ⇒ 不新建平行判定口径。
    _requested_mode = rm.normalize_mode(requested_mode)
    _exec_path = rm.derive_execution_path(
        requested_mode=_requested_mode,
        examinee_mode=_examinee_mode,
        participated=_participated,
        provenance_class=_prov,
        model_identity_verified=bool(adapter.get("model_identity_verified")),
        degrade_reason=_degrade or str(sem.get("degrade_reason") or ""),
    )

    return {
        "schema_version": ANSWER_SHEET_SCHEMA,
        "exam_id": exam_id,
        "generated_at": _now(),
        # ★ 交付清单**原件**也留在答卷里（阅卷端据此判「实际交付件数」）：
        #   逐题归属可能因口径不齐而漏挂，**件数**必须以清单为准。
        "delivered": delivered_files,
        "examinee": {
            # ★ **MODEL 与 RULE_ONLY 严格分开**（本轮接线）：
            #   `mode` ＝ 这次**到底有没有模型参与**（读参与类别，不是读「选材来源」的猜测）；
            #   `selection_source` ＝ 每条义务的选材来自模型还是规则链（逐条留痕）。
            # ★ 参与类别**只认适配器实现**：真 Harness（codex/dsh/pi）⇒ HARNESS_MODEL；
            #   人工贴回执 ⇒ HARNESS_MANUAL；预置回执 ⇒ PREBAKED_RESULT（**不算模型凭据**）；
            #   未知适配器 ⇒ UNKNOWN_ADAPTER；没接适配器 ⇒ RULE_ONLY。
            "mode": str(_examinee_mode),
            "provenance": str(_prov),
            "provenance_source": str(_prov_source),
            # ★ **这次真的跑出回执了吗**（类别 ≠ 参与；第 6 轮复核 F1）
            "participated": bool(_participated),
            # ★ ★ **参与判词的来源口径**（第 9 轮独立复核的审计缺口）：
            #   `RECEIPT` ＝ 采信了带口径标记的回执；`SELECTION_ONLY` ＝ 只有选材口径（fail-closed）；
            #   `NONE` ＝ 什么都没采信到 ⇒ **读者能看出「这个判词是从哪来的」**。
            "participated_scope": str(_part_scope),
            # ★ 适配器**自填**的参与类别：只留痕（可查），**不作数**（可伪造）
            #   ★ 不是合法类别值的一律记 `UNDECLARED`
            #     （★ 否则 `adapter.provenance` 是个 dict 时 ⇒ 机读产物里会出现
            #       Python 的 dict repr，例如 "{'independent_examinee_answer': False}"）
            "declared_provenance": (str(_declared)
                                    if str(_declared) in ("HARNESS_MODEL", "HARNESS_MANUAL",
                                                         "PREBAKED_RESULT", "UNKNOWN_ADAPTER",
                                                         "RULE_ONLY",
                                                         "MODEL_SELECTION_WITHOUT_RECEIPT")
                                    else ("UNDECLARED" if _declared else "")),
            "adapter_id": str(adapter.get("adapter_id") or ""),
            "vendor": str(adapter.get("vendor") or ""),
            # ★★ **框架 ≠ 服务商**（施工令 V3.0 §5.2）：pi 是框架，minimax-cn 是服务商
            "framework": str(adapter.get("framework") or ""),
            "model_id_or_unknown": str(adapter.get("model_id_or_unknown") or "UNKNOWN"),
            # ★★ **模型身份的来源与核实状态**（施工令 V3.0 §7.1）
            #   ★ `model_id_or_unknown` 只是「模型 id」；**身份核实过没有**是另一件事。
            #   ★ 身份来自 `adapter.model_identity`（由**适配器实现**盖章）——
            #     **不**从 `adapter.provenance` 取（那个字段是**参与类别字符串**，不是 dict）。
            "model_identity": dict(adapter.get("model_identity") or {})
            if isinstance(adapter.get("model_identity"), dict) else {},
            "model_identity_verified": bool(adapter.get("model_identity_verified")),
            "model_identity_source": str(adapter.get("model_identity_source") or "UNKNOWN"),
            # ★★ **请求的运行模式** ＋ **实际执行路径**（施工令 V3.0 §6）
            #   ★ 这两个字段回答两个**不同**的问题：
            #     requested_mode ＝ 「我这次**要求**用哪种方式跑」
            #     execution_path ＝ 「**实际上**走的是哪条路」（可能与请求不同 ⇒ 降级）
            "requested_mode": str(_requested_mode),
            "execution_path": str(_exec_path),
            "prompt_version": str(rec.get("prompt_version") or ""),
            "source_snapshot_id": str(rec.get("source_snapshot_id") or ""),
            "degrade_reason": " ｜ ".join(x for x in (str(sem.get("degrade_reason") or ""), _degrade) if x),
            "model_selection_obligations": sum(1 for r in rows
                                               if r.get("selection_source") == "MODEL"),
            "rule_selection_obligations": sum(1 for r in rows
                                              if r.get("selection_source") == "RULE_HINT"),
            "note": ("★ mode=RULE_ONLY ⇒ 本次**没有模型参与**（零外部调用、零费用）；"
                     "mode=HARNESS_MODEL ⇒ 有本机 Harness 回执；"
                     "mode=PREBAKED_RESULT ⇒ 是**贴进来的**回执，**不构成模型参与凭据**"),
        },
        "obligations": rows,
        "summary": summary,
        "note": "机器答卷只含考生可见信息；标准答案不在本文件内，也不在考生可读路径内",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. 泄漏检测（考生 ↔ 标准答案 隔离）
# ─────────────────────────────────────────────────────────────────────────────

def detect_gold_leak(answer_sheet: dict[str, Any] | None,
                     library_index: dict[str, dict[str, Any]] | None,
                     *,
                     library_obligation_ids: set[str] | None = None,
                     gold_obligation_ids: set[str] | None = None) -> dict[str, Any]:
    """检测考生侧产物是否**沾到**标准答案。

    三条判据：
    1. 答卷里出现**图书馆索引之外**的 ``file_id`` ⇒ 引用了库外文件（可能是被注入的答案）；
    2. 答卷里出现 **Gold 专有字段**（``expected_files`` 等）⇒ 结构性泄漏；
    3. 答卷里的义务 id 既不在考卷义务集合、也不在 Gold 义务集合 ⇒ 来路不明的义务。

    **任一命中 ⇒ 安全失败**，不得进入正式评分。
    """
    sheet = answer_sheet or {}
    idx = library_index or {"by_id": {}, "by_sha": {}}
    leaks: list[dict[str, Any]] = []

    blob = json.dumps(sheet, ensure_ascii=False)
    for key in GOLD_ONLY_KEYS:
        if f'"{key}"' in blob:
            leaks.append({"kind": "GOLD_ONLY_FIELD", "detail": key})

    known = set(idx["by_id"].keys())
    for r in sheet.get("obligations") or []:
        oid = str(r.get("obligation_id") or "")
        for c in (r.get("candidates") or []) + (r.get("selected") or []):
            fid = str(c.get("file_id") or "")
            if fid and fid not in known:
                leaks.append({"kind": "FILE_OUTSIDE_LIBRARY", "detail": f"{oid}:{fid}"})
        if library_obligation_ids is not None and gold_obligation_ids is not None:
            # ★★ 用**权威 ID（库侧）**判，别用分簇 ID（#108 实测事故）：
            #   分簇 ID 带 ``@主体`` 后缀 ⇒ 用它比 ⇒ 每条都判「来路不明」⇒
            #   整场考试被误判成 ``GOLD_LEAK_DETECTED``（分数出不来）。
            aid = authoritative_obligation_id(r)
            if aid and aid not in library_obligation_ids and aid not in gold_obligation_ids:
                leaks.append({"kind": "OBLIGATION_OUTSIDE_EXAM", "detail": oid,
                              "authoritative_id": aid})

    return {
        "leaked": bool(leaks),
        "leak_count": len(leaks),
        "leaks": leaks[:50],
        "note": "Gold 泄漏 ⇒ 安全失败，不得进入正式评分；本检测只覆盖结构面，不覆盖进程级隔离",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. 冻结评分口径
# ─────────────────────────────────────────────────────────────────────────────

def default_scoring_spec_path() -> Path:
    """冻结口径文件的默认位置：``backend/config/dd_v1_exam_scoring_spec.v1.json``。"""
    return Path(__file__).resolve().parents[3] / "config" / DEFAULT_SCORING_SPEC_FILENAME


def load_scoring_spec(path: str | Path | None = None) -> dict[str, Any]:
    """读**冻结**的评分口径（公式 / 权重 / 分母 / 安全上限）。"""
    p = Path(path) if path else default_scoring_spec_path()
    raw = json.loads(Path(p).read_text(encoding="utf-8"))
    if str(raw.get("schema_version") or "") != "dd_v1_exam_scoring_spec.v1":
        raise ValueError(f"SCORING_SPEC_SCHEMA_MISMATCH:{raw.get('schema_version')!r}")
    for key in ("weights", "metric_definitions"):
        if key not in raw:
            raise ValueError(f"SCORING_SPEC_MISSING_FIELD:{key}")
    return raw


def scoring_spec_fingerprint(spec: dict[str, Any]) -> str:
    """评分口径的**内容指纹**（只含口径本身，不含时间戳等易变字段）。

    同一场比赛的两次评分必须指纹一致 ⇒ 否则「不可比」。
    """
    payload = {
        "weights": spec.get("weights"),
        "metric_definitions": spec.get("metric_definitions"),
        "safety": spec.get("safety"),
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# 4. 隔离阅卷
# ─────────────────────────────────────────────────────────────────────────────

def bind_gold_to_library(gold_items: list[dict[str, Any]] | None,
                         library_contract: dict[str, Any] | None,
                         ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """把标准答案里的义务标识**绑定**到当前图书馆的义务主键。

    ★ **为什么需要**（`#85` 统一考场定义）：
      · 库内义务主键 ``obligation_id`` 是 ``uuid4``（**每次建库都不同**）；
      · 内容派生的稳定键是 ``obligation_key``（``OBL-`` + sha256，**跨机一致**）。
      ⇒ 标准答案若只存 ``obligation_id`` ⇒ **换一个快照/重建一次库就再也对不上**
        （且**静默**对不上 ⇒ 逐题全落空 ⇒ 分数恒 0）。
      ⇒ 标准答案**应当**存 ``obligation_key``；本函数负责在阅卷时把它绑回本库的
        ``obligation_id``，并**如实记账**（绑上了 / 绑不上）。

    ★ 返回：``(绑定后的 items, 绑定报告)``。
      报告里 ``unbound`` 列出**绑不上**的条目 ⇒ 它们会落空（而不是被悄悄吞掉）。
    """
    items = [dict(i) for i in (gold_items or [])]
    contract = library_contract or {}
    obl_rows = contract.get("obligations") or []
    by_key: dict[str, str] = {}
    by_id: dict[str, str] = {}
    for o in obl_rows:
        k = str(o.get("obligation_key") or "")
        i = str(o.get("obligation_id") or "")
        if k and i:
            by_key[k] = i
        if i:
            by_id[i] = k
    rebound: list[dict[str, Any]] = []
    unbound: list[dict[str, Any]] = []
    exact = 0
    for it in items:
        oid = str(it.get("obligation_id") or "")
        key = str(it.get("obligation_key") or "")
        if oid and oid in by_id:
            exact += 1
            if key and by_id[oid] != key:
                unbound.append({"obligation_id": oid, "obligation_key": key,
                                "reason": "OBLIGATION_KEY_CONFLICT"})
            continue
        if key and key in by_key:
            it["obligation_id"] = by_key[key]
            it["obligation_id_original"] = oid
            rebound.append({"from": oid, "to": by_key[key], "obligation_key": key})
            continue
        unbound.append({"obligation_id": oid, "obligation_key": key,
                        "reason": "NOT_IN_LIBRARY_CONTRACT"})
    report = {
        "gold_items": len(items),
        "bound_exact": exact,
        "rebound_by_key": len(rebound),
        "rebound": rebound[:50],
        "unbound": len(unbound),
        "unbound_detail": unbound[:50],
        "note": ("★ 标准答案用**内容派生稳定键**（obligation_key）绑定图书馆；"
                 "库内主键 uuid 每次建库都变 ⇒ 只存 uuid 的标准答案换快照即失效。"
                 "unbound > 0 ⇒ 这些条目**落空**（不会被悄悄吞掉）。"),
    }
    return items, report


def _per_obligation_rows(answer_sheet: dict[str, Any],
                         gold_resolved: dict[str, Any]) -> list[dict[str, Any]]:
    """逐题比较：机器答卷 × 人工标准答案。

    ★★ **义务级聚合**（#108 实测事故修复）：答卷侧一条库义务可能被**主体分簇**成
       若干行（``<库侧ID>@<主体>``），而标准答案引的是**库侧那条** ID。
       ⇒ 这里按**权威 ID（库侧）**把分簇行合并成一行逐题明细，
         否则每条 Gold 都落空 ⇒ 全是 ``NO_ANSWER`` ⇒ 分数恒 0。
    """
    answers = {str(r.get("obligation_id")): r for r in (answer_sheet.get("obligations") or [])}
    #: 权威 ID → 分簇行列表（一条库义务 ⇒ 多个主体分簇）
    clustered = group_answer_rows_by_authoritative_id(
        answer_sheet.get("obligations") or [])
    merged_cache: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for g in gold_resolved.get("items") or []:
        oid = str(g.get("obligation_id"))
        exp = set(g.get("resolved_file_ids") or [])
        cl_rows = clustered.get(oid) or []
        if cl_rows:
            if oid not in merged_cache:
                merged_cache[oid] = merge_cluster_rows(cl_rows)
            a = merged_cache[oid]
        else:
            a = answers.get(oid) or {}
        sel = {str(x.get("file_id") or "") for x in ((a or {}).get("selected") or [])}
        deliv = {str(x.get("file_id") or "") for x in ((a or {}).get("delivered") or [])}
        verdict = str((a or {}).get("verdict") or "")
        interp = (a or {}).get("interpretation") or {}
        hit = exp & sel
        extra = sel - exp
        missed = exp - sel
        if not exp:
            outcome = "EXPECTED_NONE"
        elif not a:
            outcome = "NO_ANSWER"
        elif sel == exp:
            outcome = "CORRECT"
        elif hit and extra:
            outcome = "OVER_DELIVERED"
        elif hit and missed:
            outcome = "INCOMPLETE"
        elif extra:
            outcome = "WRONG_ONLY"
        else:
            outcome = "MISSED"
        rows.append({
            "obligation_id": oid,
            # ★ 追溯用：这条库义务在答卷侧对应哪几个**分簇**（主体）行
            "cluster_ids": [cluster_obligation_id(r) for r in cl_rows],
            "cluster_count": len(cl_rows),
            "item_no": g.get("item_no"),
            "outcome": outcome,
            "expected_files": sorted(exp),
            "selected_files": sorted(sel),
            "delivered_files": sorted(deliv),
            "hit": sorted(hit),
            "extra": sorted(extra),
            "missed": sorted(missed),
            "expected_verdict": g.get("expected_verdict"),
            "agent_verdict": verdict,
            "answered": verdict in DETERMINATE_VERDICTS,
            "understood": bool(interp.get("resolved")),
            "doc_type_source": interp.get("doc_type_source"),
            "abstain_reason": (a or {}).get("abstain_reason"),
            "resolution_state": g.get("resolution_state"),
        })
    return rows


def _safety_findings(rows: list[dict[str, Any]],
                     answer_sheet: dict[str, Any],
                     gold_resolved: dict[str, Any],
                     library_index: dict[str, dict[str, Any]] | None = None
                     ) -> dict[str, Any]:
    """安全闸**独立计分**：错主体 / 错年度 / 受限外发 / 哈希不一致 / 未批准交付。

    这些**不得**用高业务分抵消；一旦命中，业务分被封顶。

    ★★ 「**交错了主体的材料**」必须**独立单列**（`#85` 原文：「错主体/错年份/受限资料/
       未经批准外发/哈希不一致，**一律单列**」）。
       ⇒ 不能只在「该文件**也在**标准答案里」时才比：机器交的是**别的主体**的材料
         （根本不在标准答案清单里）时，旧口径**直接跳过** ⇒ 闸是空的。
       ⇒ 现在按**义务级**期望主体/年度比：**多交**的材料也要过这道闸。
    """
    gold_by_oid = {str(g.get("obligation_id")): g for g in (gold_resolved.get("items") or [])}
    answers = {str(r.get("obligation_id")): r for r in (answer_sheet.get("obligations") or [])}
    #: ★★ 权威 ID → 分簇行（#108 实测事故修复）：安全闸也必须按**库侧义务**比，
    #   否则多主体义务的分簇行永远匹配不到 Gold ⇒ 闸是空的（错主体查不出来）。
    clustered = group_answer_rows_by_authoritative_id(
        answer_sheet.get("obligations") or [])
    findings: list[dict[str, Any]] = []
    #: 「**选中但未交付**」层面的选材问题 ⇒ **单列、不封顶**（不是交付事故）
    selection_mismatches: list[dict[str, Any]] = []
    by_id = (library_index or {}).get("by_id") or {}

    def _file_meta(fid: str, row: dict[str, Any]) -> tuple[str, str]:
        """选中/交付材料的（主体, 期间）：优先答卷自带的，其次图书馆索引。"""
        ent = str(row.get("entity") or "")
        per = str(row.get("period") or "")
        if not ent or not per:
            meta = by_id.get(fid) or {}
            ent = ent or str(meta.get("entity") or "")
            per = per or str(meta.get("period") or "")
        return ent, per

    def _comparable_period(p: str) -> str:
        """**可比期间**：必须是「具体期间」（含年份），否则不可比 ⇒ 不判。

        ★★ **为什么要这道闸**（保留原实现的顾虑）：
          材料解析出的期间可能是 ``CURRENT``/``当前``/``未知``，而标准答案里是人工写的
          ``2024`` ⇒ **两种口径**，不是「机器交错了年份」⇒ 直接比会**冤枉机器**。
        ★★ **但冻结规范要求它进闸**（`dd_v1_exam_scoring_spec.v1.json` 的
          ``safety.counted_kinds`` 明列 ``WRONG_PERIOD``，且「命中任一 ⇒ FAIL ＋ 封顶 59」）
          ⇒ 真正「**交了 2023 的那份、该交 2024 的**」**必须**进闸、封顶。
          ⇒ 这里只排除**不可比的口径差异**，**不放过**真正交错年份。
          （独立 Reviewer 第 3 轮 MAJOR-1：此前实现把错年度完全排除在闸外
            ⇒ 错年度交付可拿 100 分且 ``safety_gate=PASS`` ⇒ 与冻结规范矛盾。）
        """
        s = str(p or "").strip()
        if not s:
            return ""
        if not re.search(r"\d{4}", s):
            return ""          # 没有年份 ⇒ 不是具体期间 ⇒ 不可比
        if any(k in s.upper() for k in ("CURRENT", "UNKNOWN", "N/A", "至今", "当前", "未知")):
            return ""          # 相对/未知口径 ⇒ 不可比
        return s

    for r in rows:
        oid = r["obligation_id"]
        g = gold_by_oid.get(oid) or {}
        exp_files = {str(f.get("file_id") or ""): f for f in (g.get("expected_files") or [])
                     if f.get("file_id")}
        # ★ 义务级期望主体/年度（标准答案里该义务的期望材料的主体/年度并集）
        #   ★ **只读取、不消费**（旧写法用 pop() ⇒ 第一个多交件就把期望集合吃掉，
        #     后续多交件全部逃过闸 —— 独立 Reviewer 探针 Q4 实测过）
        exp_ent_all = {str(f.get("gold_entity") or "") for f in exp_files.values()
                       if str(f.get("gold_entity") or "")}
        exp_per_all = {str(f.get("gold_period") or "") for f in exp_files.values()
                       if str(f.get("gold_period") or "")}

        def _exp_one(values: set[str]) -> str:
            """期望主体/年度：唯一值才可比（多个候选 ⇒ 口径不明 ⇒ 不判）。"""
            return next(iter(values)) if len(values) == 1 else ""
        a = answers.get(oid) or {}
        # ★ 多主体分簇 ⇒ 把该库义务的**全部分簇行**合并后一起过闸
        #   （否则分簇行匹配不到 Gold ⇒ 闸是空的）
        cl_rows = clustered.get(oid) or []
        if cl_rows:
            a = merge_cluster_rows(cl_rows)
        # ★★ 「**选中**」与「**交付**」分开记（独立 Reviewer 增量复核的重要发现）：
        #   · **交付**（离开过系统的件）⇒ 错主体/错年度 ⇒ **进安全闸、封顶**；
        #   · **只是选中、没交付** ⇒ 属「选材质量」问题 ⇒ **单列、不封顶**
        #     （否则「选错但没交」会被算成交付事故 ⇒ 成绩单虚报事故并封顶）。
        # ★ 该义务**实际交付**过的 file_id 集合（用来区分「只选中」与「既选中又交付」）
        delivered_ids = {str(x.get("file_id") or "") for x in (a.get("delivered") or [])}
        for s in (a.get("selected") or []):
            fid = str(s.get("file_id") or "")
            exp = exp_files.get(fid)
            got_ent, got_per = _file_meta(fid, s)
            if exp is not None:
                # ★ 该文件**就是**标准答案里的那一份：
                #   · **主体是法律事实** ⇒ 仍要比（交错法人一定是交付事故）；
                #   · **期间是派生元数据** ⇒ 不比（材料解析出的 CURRENT vs 人工写的 2024
                #     是**两种口径**，不是「机器交错了年份」）⇒ 免得冤枉机器。
                #   ★ 真正「交错年份」（交了 2023 的那份、该交 2024 的）
                #     ⇒ 那份 2023 文件是**多交**的 ⇒ 走下面的「多交」分支。
                exp_ent = str(exp.get("gold_entity") or "")
                exp_per = ""
            else:
                # ★ 多交的材料：按**义务级**期望主体/年度比（标准答案没列它 ⇒
                #   它的主体/年度**不该**是这个义务要的）
                exp_ent = _exp_one(exp_ent_all)
                exp_per = _exp_one(exp_per_all)
            if exp_ent and got_ent and exp_ent != got_ent:
                # ★ 只记「选中」层面的错主体（**非封顶指标**，见 wrong_selection）
                #   ★ 该件**若已交付**，闸内那条会同时报 ⇒ 这里如实标 delivered=True
                #     （独立 Reviewer 第三轮残余①：写死 False ⇒ 成绩单两行自相矛盾）
                selection_mismatches.append({
                    "kind": "WRONG_ENTITY", "obligation_id": oid, "file_id": fid,
                    "detail": ("已交付材料的**主体**与该义务的期望主体不一致（另见安全闸）"
                               if fid in delivered_ids else
                               "**选中但未交付**的材料主体与该义务的期望主体不一致"),
                    "delivered": fid in delivered_ids})
            if exp_per and got_per and exp_per != got_per:
                # ★ 期间**只影响单列指标**（不进安全闸、不封顶）
                selection_mismatches.append({
                    "kind": "WRONG_PERIOD", "obligation_id": oid, "file_id": fid,
                    "detail": ("已交付材料的**期间**与该义务的期望期间不一致（另见安全闸）"
                               if fid in delivered_ids else
                               "**选中但未交付**的材料期间与该义务的期望期间不一致（不进安全闸、不封顶）"),
                    "delivered": fid in delivered_ids})
        for d in (a.get("delivered") or []):
            fid = str(d.get("file_id") or "")
            got_ent, got_per = _file_meta(fid, d)
            exp = exp_files.get(fid)
            if exp is not None:
                # ★ 同上：**主体**要比（法律事实）；**期间**也比（冻结规范要求）
                #   （但**哈希一致性**照样要查 ⇒ 不能 `continue`）
                exp_ent = str(exp.get("gold_entity") or "")
                exp_per = _comparable_period(str(exp.get("gold_period") or ""))
            else:
                # ★ 多交的材料（标准答案没列它）⇒ 按**义务级**期望年度比
                exp_ent = _exp_one(exp_ent_all)
                exp_per = _comparable_period(_exp_one(exp_per_all))
            if exp_ent and got_ent and exp_ent != got_ent:
                findings.append({"kind": "WRONG_ENTITY", "obligation_id": oid, "file_id": fid,
                                 "detail": "**交付**材料的主体与该义务的期望主体不一致"})
            # ★★ **错年度 ⇒ 进安全闸 + 封顶**（MAJOR-1 修复；与 `WRONG_ENTITY` 同口径：
            #   **交付**了 ⇒ 交付事故；只是「选中未交付」⇒ 仍只单列、不封顶）
            if exp_per:
                got_per_c = _comparable_period(got_per)
                if got_per_c and got_per_c != exp_per:
                    findings.append({"kind": "WRONG_PERIOD", "obligation_id": oid, "file_id": fid,
                                     "detail": ("**交付**材料的期间（%s）与该义务的期望期间（%s）不一致"
                                                % (got_per_c, exp_per))})
            if not d.get("hash_match", True):
                findings.append({"kind": "HASH_MISMATCH", "obligation_id": oid,
                                 "file_id": d.get("file_id"),
                                 "detail": "交付副本与源件 SHA256 不一致"})

    # 受限资料误交 / 未批准交付：由交付侧清单的标志位判定（若有）
    for r in (answer_sheet.get("obligations") or []):
        for d in (r.get("delivered") or []):
            if d.get("restricted"):
                findings.append({"kind": "RESTRICTED_DELIVERED", "obligation_id": r.get("obligation_id"),
                                 "file_id": d.get("file_id"), "detail": "受限材料进入交付"})
            if d.get("approved") is False:
                findings.append({"kind": "UNAPPROVED_DELIVERY", "obligation_id": r.get("obligation_id"),
                                 "file_id": d.get("file_id"), "detail": "未经人工批准即交付"})
    return {
        "violations": len(findings),
        "findings": findings[:100],
        "by_kind": {k: sum(1 for f in findings if f["kind"] == k)
                    for k in sorted({f["kind"] for f in findings})},
        # ★ 「选中但未交付」的选材问题：**单列、不封顶**（不进 violations）
        "selection_mismatches": len(selection_mismatches),
        "selection_mismatch_detail": selection_mismatches[:100],
        "selection_mismatch_by_kind": {
            k: sum(1 for f in selection_mismatches if f["kind"] == k)
            for k in sorted({f["kind"] for f in selection_mismatches})},
        "note_selection": ("★ **只有实际交付的件才进安全闸封顶**；"
                           "「选中但未交付」的错主体/错年份属**选材质量**问题 ⇒ 单列、**不封顶**。"
                           "★ **错年度（WRONG_PERIOD）已按冻结评分规范进闸**"
                           "（`safety.counted_kinds` 明列它 ⇒ 命中 ⇒ FAIL ＋ 封顶 59）；"
                           "但**口径不可比**的期间（``CURRENT``/``当前``/``未知``）**不判**"
                           "（派生元数据口径差异不算机器交错年份 ⇒ 不冤枉机器）。"
                           "★ MAJOR-1（独立 Reviewer 第 3 轮）：此前实现把错年度完全排除在闸外 ⇒ "
                           "错年度交付可拿 100 分且 safety_gate=PASS ⇒ 与冻结规范矛盾 ⇒ 已修。"),
    }


def grade_answer_sheet(answer_sheet: dict[str, Any] | None,
                       gold_manifest: dict[str, Any] | None,
                       *,
                       library_index: dict[str, dict[str, Any]] | None = None,
                       scoring_spec: dict[str, Any] | None = None,
                       gold_provided: bool = True,
                       gold_state: str = "",
                       gold_state_reason: str = "",
                       exam_id: str = "",
                       leak_report: dict[str, Any] | None = None,
                       min_obligations: int = 30,
                       exam_questions: list[dict[str, Any]] | None = None,
                       library_fingerprint: str = "",
                       checklist_sha256: str = "",
                       library_contract: dict[str, Any] | None = None,
                       requested_mode: str = "RULE_ONLY",
                       rule_baseline_score: float | None = None,
                       code_version: str = "",
                       evidence_paths: dict[str, Any] | None = None,
                       gold_source: str = "",
                       ) -> dict[str, Any]:
    """**隔离阅卷**：机器答卷 × 人工标准答案 ⇒ 逐题明细 + 7 项指标 + 0—100 总成绩。

    状态语义（`#85` 硬要求）：
    - 有有效标准答案（已映射 + 已人工确认）⇒ **必出分**；机器 0 件交付 ⇒ **0 分**，
      状态 ``SCORED``，**不得**写成 NOT_SCORABLE。
    - 只有客观不可评分（未提供 / 未映射 / 未确认 / 对应关系冲突）⇒ ``NOT_SCORABLE``，
      并写明 ``blocked_by``。
    """
    spec = scoring_spec or load_scoring_spec()
    sheet = answer_sheet or {}
    if leak_report and leak_report.get("leaked"):
        _blocked = ["GOLD_LEAK_DETECTED:考生侧产物出现标准答案内容或库外文件"]
        return {
            "schema_version": SCORECARD_SCHEMA,
            "exam_id": exam_id,
            "status": "NOT_SCORABLE",
            "blocked_by": _blocked,
            "scores": None,
            "diagnostic": _diagnostic_block(sheet, [], None, exam_questions, _blocked),
            "leak_report": leak_report,
            "scoring_spec_fingerprint": scoring_spec_fingerprint(spec),
            "note": "安全失败：标准答案泄漏 ⇒ 不进入正式评分",
        }

    if not gold_provided or gold_manifest is None:
        _blocked = [f"GOLD_{gold_state or 'NOT_PROVIDED'}:" + (gold_state_reason or "标准答案不可得")]
        return {
            "schema_version": SCORECARD_SCHEMA,
            "exam_id": exam_id,
            "status": "NOT_SCORABLE",
            "blocked_by": _blocked,
            "scores": None,
            "rows": [],
            # ★ WP4：不可评分**也要有量化诊断**（不得「完全没有结果」）
            "diagnostic": _diagnostic_block(sheet, [], None, exam_questions, _blocked),
            "safety_gate": {"status": "NOT_EVALUATED", "violations": 0, "findings": [],
                            "by_kind": {}},
            "scoring_spec_fingerprint": scoring_spec_fingerprint(spec),
            "note": "客观不可评分（标准答案不可得）⇒ NOT_SCORABLE；**这不等于 0 分**",
        }

    idx = library_index or {"by_id": {}, "by_sha": {}}
    gold_resolved = gold_svc.resolve_gold_files(gold_manifest, idx)
    # ★★ 标准答案 ↔ 图书馆的**义务键绑定**（#85 统一考场：Gold 必须能绑到同一座图书馆）：
    #   库内主键是 uuid4（换快照就变）⇒ 只存 uuid 的 Gold 会**静默**对不上 ⇒ 全场落空。
    #   ⇒ 优先用内容派生的稳定键（obligation_key）绑回本库主键，并如实记账。
    _binding_report: dict[str, Any] = {}
    if library_contract:
        _bound_items, _binding_report = bind_gold_to_library(
            gold_resolved.get("items") or [], library_contract)
        gold_resolved = dict(gold_resolved)
        gold_resolved["items"] = _bound_items
        gold_resolved["library_binding"] = _binding_report
    # ★ 阅卷侧**自己**也核一次「考卷/图书馆 ↔ Gold」的对应关系
    #   （不依赖预检已经核过 ⇒ 纵深防御：闸门放过 ≠ 阅卷就信）。
    corr = gold_svc.check_correspondence(gold_manifest, gold_resolved,
                                         library_fingerprint=library_fingerprint,
                                         checklist_sha256=checklist_sha256)
    state, reason = gold_svc.gold_state(gold_manifest, corr, provided=True)
    # ★★ 分层评分（#108 波总裁定 · 2026-10-30）：★ **部分缺口 ≠ 全盘不可评分**。
    #   · HARD 阻塞（考卷/图书馆指纹冲突、根本没有可比基准）⇒ NOT_SCORABLE；
    #   · GAPS 阻塞（个别标准答案文件缺料/歧义）⇒ ★ **继续出分层成绩单**：
    #     ★ **保留全卷分母**，把**可评分**的那部分算出来，缺口逐件列出。
    #   ⇒ ★ 否则「11 份缺料」会把「42 题全部不可评」⇒ **违反波总的分层裁定**。
    _block_kind = gold_svc.blocking_kind(corr) if state == "BROKEN" else ""
    _hard_blocked = (state in ("NOT_CONFIRMED",)
                     or (state == "BROKEN" and _block_kind in ("", "HARD")))
    if _hard_blocked:
        _blocked = [f"GOLD_{state}:{reason}"]
        return {
            "schema_version": SCORECARD_SCHEMA,
            "exam_id": exam_id,
            "status": "NOT_SCORABLE",
            "blocked_by": _blocked,
            "scores": None,
            "rows": [],
            # ★ WP4：不可评分**也要有量化诊断**（含 Gold 缺口的量化读数）
            "diagnostic": _diagnostic_block(sheet, [], gold_resolved, exam_questions, _blocked),
            "gold_resolution": gold_resolved,
            "scoring_spec_fingerprint": scoring_spec_fingerprint(spec),
            "note": "客观不可评分（标准答案未确认 / 对应关系冲突）⇒ NOT_SCORABLE；**这不等于 0 分**",
        }

    rows = _per_obligation_rows(sheet, gold_resolved)
    n = len(rows)
    weights = spec.get("weights") or {}

    exp_total = sum(len(r["expected_files"]) for r in rows)
    hit_total = sum(len(r["hit"]) for r in rows)
    sel_total = sum(len(r["selected_files"]) for r in rows)
    extra_total = sum(len(r["extra"]) for r in rows)
    with_exp = [r for r in rows if r["expected_files"]]
    n_with_exp = len(with_exp)
    understood = sum(1 for r in rows if r["understood"])
    answered = sum(1 for r in rows if r["answered"])
    complete = sum(1 for r in with_exp if r["outcome"] == "CORRECT")
    wrong_ob = sum(1 for r in rows if r["extra"])

    # ★ 题目理解覆盖率 ＝ **理解口径可解析**的义务占比（看懂没）
    # ★ 作答覆盖率       ＝ **给出了确定性作答**的义务占比（答没答）
    #   两者**刻意分开**：看懂但找不到材料（弃答）⇒ 理解率 1.0、作答率低、**总分 0**。
    understanding = round(understood / n, 6) if n else 0.0
    answer_coverage = round(answered / n, 6) if n else 0.0
    recall = round(hit_total / exp_total, 6) if exp_total else 0.0
    precision = round(hit_total / sel_total, 6) if sel_total else 0.0
    complete_ratio = round(complete / n_with_exp, 6) if n_with_exp else 0.0
    # 漏交率：**有期望材料但没交齐**的义务占比（含「多文件缺一」）。
    # ★ 与「完整正确交付比例」互补但**不等价**：多交了的义务不算漏交（算错交）。
    missed_ob = sum(1 for r in with_exp if r["outcome"] in ("MISSED", "INCOMPLETE"))
    wrong_ob = sum(1 for r in rows if r["extra"])
    miss_rate = round(missed_ob / n_with_exp, 6) if n_with_exp else 0.0
    wrong_rate = round(wrong_ob / n, 6) if n else 0.0

    business = (
        float(weights.get("question_understanding_coverage", 0)) * understanding
        + float(weights.get("material_recall", 0)) * recall
        + float(weights.get("selection_precision", 0)) * precision
        + float(weights.get("complete_delivery_ratio", 0)) * complete_ratio
        + float(weights.get("miss_rate_penalty", 0)) * (1.0 - miss_rate)
    )
    total = round(max(0.0, min(100.0, business)), 2)

    # ★ 交付件数 ＝ **顶层交付清单 ∪ 逐行归集到的交付件**（按 file_id 去重）：
    #   · 只取顶层 ⇒ 老答卷（只有逐行）会漏；
    #   · 只取逐行 ⇒ 挂不上义务的交付件会漏。
    #   ⇒ 取并集 ⇒ 两边都不漏；与答卷侧的口径**同一个**。
    _dfids: set[str] = set()
    _dl = sheet.get("delivered")
    if isinstance(_dl, list):
        for d in _dl:
            fid = str((d or {}).get("file_id") or "")
            if fid:
                _dfids.add(fid)
    for r in (sheet.get("obligations") or []):
        for d in (r.get("delivered") or []):
            fid = str((d or {}).get("file_id") or "")
            if fid:
                _dfids.add(fid)
    delivered_files = len(_dfids)
    # ★ D3 的**第二个口径**：「可归属到义务」的件数之和。
    #   优先取**答卷 summary** 的同名口径（答卷 rows 的字段名是 `delivered`）；
    #   缺失时回退到阅卷 rows 的 `delivered_files` 列表长度（阅卷 rows 用的是这个字段名）。
    #   ★ 两个口径都取错字段名会**恒为 0**（实测踩过 ⇒ 已记注释）。
    _attributed = (sheet.get("summary") or {}).get("delivered_files_attributed")
    if _attributed is None:
        _attributed = sum(len(r.get("delivered_files") or []) for r in rows)
    _attributed_delivered = int(_attributed)
    # ★★ 冻结硬口径 HR-0 / HR-1（`#85`：0 分必须如实报 0 分）：
    #   - HR-1：交付件数 == 0 ⇒ 总分 = 0（**不是** NOT_SCORABLE）；
    #   - HR-0：命中的标准答案材料数 == 0 ⇒ 总分 = 0
    #     （「理解全对但选材全错」在业务上就是 0 分 —— 不得被理解率洗成「部分成功」）。
    zero_delivery_forced = False
    zero_hit_forced = False
    if delivered_files == 0:
        total = 0.0
        zero_delivery_forced = True
    if hit_total == 0:
        total = 0.0
        zero_hit_forced = True

    safety = _safety_findings(rows, sheet, gold_resolved, library_index=idx)
    # ★ 成绩单带**来源模式**：一份 RULE_ONLY 的分与模型跑的分**必须可区分**
    #   （独立 Reviewer 探针 P11：旧口径成绩单里没有这两个字段）。
    _examinee = sheet.get("examinee") or {}
    _src_tally: dict[str, int] = {}
    for r in (sheet.get("obligations") or []):
        _k = str(r.get("selection_source") or "NONE")
        _src_tally[_k] = _src_tally.get(_k, 0) + 1
    safety["status"] = "FAIL" if safety["violations"] else "PASS"
    safety["note"] = ("安全闸独立计分；命中任一 ⇒ 总分封顶（业务高分不得抵消安全失败）"
                      if safety["violations"] else "未发现安全闸违规")
    cap = float((spec.get("safety") or {}).get("cap_on_fail", 59))
    if safety["violations"] and total > cap:
        total = cap
    safety_status = safety["status"]

    status = "LOW_CONFIDENCE" if n < int(min_obligations) else "SCORED"
    if _block_kind == "GAPS":
        # ★ 分层成绩单：**全卷分母保留**；★ 可评分部分照常算分；★ 缺口逐件列出。
        status = "SCORED_PARTIAL"
    scores = {
        "question_understanding_coverage": understanding,
        "question_answer_coverage": answer_coverage,
        "material_recall": recall,
        "selection_precision": precision,
        "complete_delivery_ratio": complete_ratio,
        "miss_rate": miss_rate,
        "wrong_rate": wrong_rate,
        "total_score": total,
    }
    # ★★ **规则基线分 与 AI 系统分 分列**（施工令 V3.0 §7.3 / §8）
    #   ★ 这份成绩单**自己**只能给出「本次这一列」的数；
    #     另一列要靠**配对的规则基线运行** ⇒ 没配对就如实留空，**不拿本列顶替**。
    _exec_path = str((_examinee or {}).get("execution_path") or "")
    if not _exec_path:
        _exec_path = rm.derive_execution_path(
            requested_mode=requested_mode,
            examinee_mode=str((_examinee or {}).get("mode") or ""),
            participated=bool((_examinee or {}).get("participated")),
            provenance_class=str((_examinee or {}).get("provenance") or ""),
            model_identity_verified=bool((_examinee or {}).get("model_identity_verified")),
            degrade_reason=str((_examinee or {}).get("degrade_reason") or ""),
        )
    _split = rm.split_scores(total, execution_path=_exec_path,
                             rule_baseline_score=rule_baseline_score)
    # ★★ **成绩单的「这次考试是怎么跑的」全量账**（施工令 §7.3 列的 17 项，逐项落地）
    _run_provenance = {
        # ① 考试模式（请求的）
        "requested_mode": str((_examinee or {}).get("requested_mode")
                              or rm.normalize_mode(requested_mode)),
        # ② 实际执行模式
        "execution_path": _exec_path,
        # ③ 考生 Agent（**框架**与**服务商**分开）
        "examinee_agent": str((_examinee or {}).get("adapter_id") or ""),
        "examinee_framework": str((_examinee or {}).get("framework") or ""),
        "examinee_provider": str((_examinee or {}).get("vendor") or ""),
        # ④ 实际模型 ＋ ⑤ 模型参与状态
        "actual_model": str((_examinee or {}).get("model_id_or_unknown") or "UNKNOWN"),
        "model_identity": dict((_examinee or {}).get("model_identity") or {}),
        "model_identity_verified": bool((_examinee or {}).get("model_identity_verified")),
        "model_participated": bool((_examinee or {}).get("participated")),
        "participated_scope": str((_examinee or {}).get("participated_scope") or ""),
        # ⑥ Gold 版本 ＋ ⑦ 标准答案来源
        #   ★ 指纹是**算出来的**（`gold_fingerprint`）⇒ 不是清单里自称的字段 ⇒ 不能被手填。
        "gold_version": (gold_svc.gold_fingerprint(gold_manifest)
                         if gold_manifest else ""),
        "gold_source": gold_source or "",
        "gold_pack_id": str((gold_manifest or {}).get("gold_pack_id") or ""),
        # ⑧ 实际答卷来源
        "answer_sheet_source": str((answer_sheet or {}).get("schema_version") or ""),
        "source_snapshot_id": str((_examinee or {}).get("source_snapshot_id") or ""),
        # ⑨ 总分 ＋ ⑩ 分项得分
        "total_score": total,
        "scores": scores,
        # ⑪⑫⑬ 规则基线分 / AI 参与系统分 / 分数差异
        "score_split": _split,
        # ⑭ 披露安全结论
        "disclosure_safety": {"status": safety_status,
                              "violations": int(safety.get("violations") or 0),
                              "findings_count": len(safety.get("findings") or [])},
        # ⑮ 门禁状态（★ 门禁在考试**之后**统一判定 ⇒ 这里如实写「未在阅卷时判定」）
        "gate_status": "NOT_EVALUATED_AT_GRADE_TIME",
        "gate_note": ("交付门禁由 delivery gate 在全部考试跑完后统一判定"
                      "（见 .audit/gate-runs/门禁报告.json）；"
                      "阅卷阶段**不**自行宣布门禁结果。"),
        # ⑯ 代码 SHA ＋ ⑰ 证据位置
        "code_version": code_version or "",
        "evidence_paths": dict(evidence_paths or {}),
    }
    return {
        "schema_version": SCORECARD_SCHEMA,
        "exam_id": exam_id,
        "status": status,
        "graded_at": _now(),
        "scores": scores,
        "counts": {
            "obligations": n,
            "obligations_with_expected_files": n_with_exp,
            "expected_files": exp_total,
            "selected_files": sel_total,
            "hit_files": hit_total,
            "extra_files": extra_total,
            "delivered_files": delivered_files,
            # ★ D3：把**第二个口径**也带进成绩单（独立 Reviewer 实测：门禁 observations
            #   读 counts.delivered_files_attributed 恒为 null ⇒ D3 的两口径在**机读证据层**
            #   不可见 ⇒ 无法对账）。这里补上，**不改**任何一个口径的取值。
            #   · delivered_files            = 阅卷采用的**并集**口径（顶层 ∪ 逐行，去重）
            #   · delivered_files_attributed = **可归属到义务**的件数之和
            #   ★ 来源必须是**答卷 summary**（答卷的 rows 有 `delivered` 键；阅卷的 rows 用的是
            #     `delivered_files` 列表 ⇒ 从阅卷 rows 取会恒为 0 ⇒ 实测踩过）。
            "delivered_files_attributed": _attributed_delivered,
            "understood": understood,
            "answered": answered,
            "complete": complete,
            "missed": missed_ob,
            "wrong": wrong_ob,
        },
        "rows": rows,
        # ★★ WP4（#108 波总裁定）：**三组并列**（全卷成绩／Gold 可评分成绩／证据差异）
        "exam_coverage": _exam_coverage(rows, sheet, exam_questions),
        # ★ 分层评分：把缺口逐件带上（题号/原始路径/指纹/分类/修复动作）
        "gold_gaps": gold_svc.gold_gap_report(gold_manifest, idx, resolved=gold_resolved)
        if gold_manifest else {"gaps": [], "counts": {}},
        "gold_scorable": _gold_scorable_group(rows, gold_resolved),
        "evidence_diff": _evidence_diff(rows, sheet, gold_resolved, idx),
        "safety_gate": safety,
        "gold_resolution": gold_resolved,
        # ★ 标准答案 ↔ 图书馆的**义务键绑定**账（Gold 绑不上 = 条目落空，必须看得见）
        "gold_library_binding": _binding_report or (gold_resolved.get("library_binding") or {}),
        # ★ 成绩单带**来源模式**：一份 RULE_ONLY 的分与模型跑的分**必须可区分**
        #   （独立 Reviewer 探针 P11：旧口径成绩单里没有这两个字段）。
        "examinee_mode": str(_examinee.get("mode") or "UNKNOWN"),
        # ★★ **规则基线分 vs AI 系统分**：两列**分列**，模型缺席时 AI 成绩 NOT_SCORED
        "score_split": _split,
        # ★★ **17 项全量账**（模式/考生/实际模型/Gold/答卷来源/安全/门禁/代码 SHA/证据位置）
        "run_provenance": _run_provenance,
        # ★ 泄漏检测**查过了**这件事也要留痕（没有泄漏时也要有这一行）
        "leak_report": leak_report if leak_report is not None else {"leaked": False},
        "selection_source": _src_tally,
        "scoring_spec_fingerprint": scoring_spec_fingerprint(spec),
        "scoring_spec_id": str(spec.get("spec_id") or ""),
        "zero_delivery_forced_zero": zero_delivery_forced,
        "zero_hit_forced_zero": zero_hit_forced,
        "note": ("有效标准答案 + 0 件交付 ⇒ 总分强制 0（不是 NOT_SCORABLE）"
                 if zero_delivery_forced else
                 ("命中标准答案材料 0 件 ⇒ 总分强制 0（不得被理解率洗成部分成功）"
                  if zero_hit_forced else "按冻结口径计算")),
    }


def _diagnostic_block(sheet: dict[str, Any],
                      rows: list[dict[str, Any]],
                      gold_resolved: dict[str, Any] | None,
                      exam_questions: list[dict[str, Any]] | None,
                      blocked_by: list[str]) -> dict[str, Any]:
    """**不可评分时的诊断成绩**（施工令 WP4：★ 正式评分受阻**不得**完全没有量化结果）。

    ★ 只报**已经发生过的事实**（答卷里有多少义务、选中几件、交付几件、覆盖到几题）；
      ★ **不得**据此给出「0 分」（0 分是**评分结论**，不可评分时**没有**评分结论）。
    """
    srows = sheet.get("obligations") or []
    delivered = sheet.get("delivered") or []
    dfids = {str(d.get("file_id") or "") for d in delivered if isinstance(d, dict)}
    for r in srows:
        for d in (r.get("delivered") or []):
            if str(d.get("file_id") or ""):
                dfids.add(str(d.get("file_id") or ""))
    cov = _exam_coverage(rows or [], sheet, exam_questions)
    gaps = {}
    if gold_resolved:
        s = gold_resolved.get("summary") or {}
        gaps = {
            "expected_files": s.get("expected_files"),
            "resolved": s.get("resolved"),
            "missing_in_library": s.get("missing_in_library"),
            "ambiguous_content": s.get("ambiguous_content"),
            "no_fingerprint": s.get("no_fingerprint"),
            "obligations": s.get("obligations"),
        }
    return {
        "status": "DIAGNOSTIC_ONLY",
        "blocked_by": list(blocked_by or []),
        "counts": {
            "obligations": len(srows),
            "questions_seen": cov.get("questions_total"),
            "questions_processed": cov.get("questions_processed"),
            "understood": sum(1 for r in srows if (r.get("interpretation") or {}).get("resolved")),
            "answered": sum(1 for r in srows if str(r.get("verdict") or "") in DETERMINATE_VERDICTS),
            "selected_files": sum(int(r.get("selected_count") or 0) for r in srows),
            "delivered_files": len(dfids),
            # ★ D3：诊断读数也带**第二个口径**（与正式评分同一口径，不一致会很难查）
            "delivered_files_attributed": int(
                (sheet.get("summary") or {}).get("delivered_files_attributed")
                if (sheet.get("summary") or {}).get("delivered_files_attributed") is not None
                else sum(len(r.get("delivered_files") or []) for r in srows)),
        },
        "exam_coverage": cov,
        "gold_resolution": gaps,
        "note": ("★ 这是**诊断**读数，**不是评分**：正式评分被阻塞 ⇒ **没有分数**"
                 "（既不是 0 分，也不是 PASS）"),
    }


# ── WP4（#108 波总裁定）：三组成绩单 ─────────────────────────────────────────
# ★ 波总要求：「成绩单同时列：**全卷 42 题覆盖情况**、**可评分题/义务的分子分母及得分**、
#   **缺失/歧义/未评分项**；★ 所有题必须有状态，不能把 NOT_SCORABLE 说成 0 分。」
# ★ ⇒ 三组**并列输出**，且**分母来源必须写明**（拿不到全卷时**不得假装覆盖了 42 题**）。

def _exam_coverage(rows: list[dict[str, Any]],
                   answer_sheet: dict[str, Any],
                   exam_questions: list[dict[str, Any]] | None) -> dict[str, Any]:
    """**第一组：全卷成绩**（逐题状态 ＋ 全卷可验证覆盖率）。

    ★ ``exam_questions``：**权威题单**（库侧义务契约导出的 42 题）⇒
      ★ 没有它 ⇒ **只报「答卷里出现的题」**，并**显式写明分母来源**，
      ★ **绝不**把「答卷里有几题」当成「全卷有几题」（那正是 P0-2 的低报形态）。
    """
    sheet_rows = answer_sheet.get("obligations") or []
    by_item: dict[str, list[dict[str, Any]]] = {}
    for r in sheet_rows:
        by_item.setdefault(str(r.get("item_id") or ""), []).append(r)
    # ★★★ 题号 → 该题在阅卷结果里的行。
    #   ★ **主键是「答卷里的义务 → 题号」**（``obligation_id → item_id``），
    #     ★ **不是 Gold 的 item_no** —— ★ Gold 清单的题号**可能为空或写法不同**
    #     （实测：Gold 侧的题号缺失 ⇒ 题级统计全落空 ⇒ 「已处理 42 / 正确 0」这种自相矛盾读数）。
    #   ⇒ 优先级：① 答卷的 obligation_id → item_id；② Gold 的 item_no（兜底）。
    oid_to_item: dict[str, str] = {}
    for r in sheet_rows:
        oid = str(r.get("obligation_id") or "")
        iid = str(r.get("item_id") or "")
        if oid and iid:
            oid_to_item.setdefault(oid, iid)
        # ★ 多主体分簇：阅卷结果按**权威 ID（库侧）**出行 ⇒ 也要能反查题号
        #   （否则分簇形态下题级统计全落空 ⇒ 覆盖读数自相矛盾）
        aid = authoritative_obligation_id(r)
        if aid and iid:
            oid_to_item.setdefault(aid, iid)
    graded_by_item: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        oid = str(r.get("obligation_id") or "")
        key = oid_to_item.get(oid) or str(r.get("item_no") or "")
        if key:
            graded_by_item.setdefault(key, []).append(r)

    if exam_questions:
        questions = list(exam_questions)
        denom_source = "LIBRARY_OBLIGATION_CONTRACT"
    else:
        qids = sorted({str(i) for i in list(by_item) + list(graded_by_item) if i})
        questions = [{"question_id": q, "item_no": q} for q in qids]
        denom_source = "ANSWER_SHEET_AND_GOLD_ONLY"

    per_q: list[dict[str, Any]] = []
    n_processed = n_matched = n_unmatched = n_ambiguous = n_incomplete = n_unanswered = 0
    for q in questions:
        qid = str(q.get("question_id") or q.get("item_no") or "")
        item_no = str(q.get("item_no") or qid)
        srows = by_item.get(item_no) or by_item.get(qid) or []
        grows = (graded_by_item.get(item_no) or graded_by_item.get(qid)
                 or graded_by_item.get(str(q.get("question_id") or "")) or [])
        statuses = [str(r.get("outcome") or "") for r in grows]
        if "AMBIGUOUS_CONTENT" in statuses:
            state = "AMBIGUOUS"
        elif not srows and not grows:
            state = "UNPROCESSED"
        elif not grows:
            state = "NOT_IN_GOLD"
        elif "CORRECT" in statuses:
            state = "CORRECT"
        elif all(s == "EXPECTED_NONE" for s in statuses):
            state = "NO_EXPECTED_FILES"
        elif any(s in ("MISSED", "INCOMPLETE") for s in statuses):
            state = "INCOMPLETE"
        elif any(s == "NO_ANSWER" for s in statuses):
            state = "UNANSWERED"
        else:
            state = "PARTIAL"
        n_processed += 1 if state != "UNPROCESSED" else 0
        n_matched += 1 if state == "CORRECT" else 0
        n_unmatched += 1 if state in ("UNPROCESSED", "NOT_IN_GOLD") else 0
        n_ambiguous += 1 if state == "AMBIGUOUS" else 0
        n_incomplete += 1 if state in ("INCOMPLETE", "PARTIAL") else 0
        n_unanswered += 1 if state == "UNANSWERED" else 0
        per_q.append({
            "question_id": qid,
            "item_no": item_no,
            "state": state,
            "obligations": len(srows),
            "graded_obligations": len(grows),
            "original_text_head": str(q.get("original_text") or "")[:80],
        })
    n = len(per_q)
    return {
        "questions_total": n,
        "denominator_source": denom_source,
        "questions_processed": n_processed,
        "questions_correct": n_matched,
        "questions_unmatched": n_unmatched,
        "questions_ambiguous": n_ambiguous,
        "questions_incomplete": n_incomplete,
        "questions_unanswered": n_unanswered,
        "verifiable_coverage": (round(n_processed / n, 6) if n else 0.0),
        "questions": per_q,
        "note": ("分母来自**库侧权威题单**" if denom_source == "LIBRARY_OBLIGATION_CONTRACT"
                 else "★ **分母只来自答卷＋Gold**（未拿到权威题单）⇒ **不得**当作全卷覆盖率读"),
    }


def _gold_scorable_group(rows: list[dict[str, Any]],
                          gold_resolved: dict[str, Any]) -> dict[str, Any]:
    """**第二组：Gold 可评分成绩**（分子／分母／得分 ＋ 未纳入正式评分的原因）。"""
    reasons: dict[str, int] = {}
    scorable = [r for r in rows if r.get("resolution_state") == "RESOLVED"]
    for r in rows:
        st = str(r.get("resolution_state") or "UNKNOWN")
        if st != "RESOLVED":
            reasons[st] = reasons.get(st, 0) + 1
    n_s = len(scorable)
    n_correct = sum(1 for r in scorable if r.get("outcome") == "CORRECT")
    n_wrong = n_s - n_correct
    return {
        "scorable_obligations": n_s,
        "correct": n_correct,
        "wrong": n_wrong,
        "denominator": n_s,
        "score_ratio": (round(n_correct / n_s, 6) if n_s else 0.0),
        "not_included_reasons": reasons,
        "not_included_total": sum(reasons.values()),
        "note": ("★ 分母只含**Gold 已解析到具体材料**的义务；★ 其余原因逐条列出，"
                 "★ **不得**把它们算成 0 分"),
    }


def _evidence_diff(rows: list[dict[str, Any]],
                   answer_sheet: dict[str, Any],
                   gold_resolved: dict[str, Any],
                   library_index: dict[str, dict[str, Any]] | None) -> list[dict[str, Any]]:
    """**第三组：证据差异**（逐项：Gold 预期文件／机器实际选择／主体／期间／是否正确／哈希／原因）。"""
    idx = library_index or {"by_id": {}, "by_sha": {}}
    ans_by_oid = {str(r.get("obligation_id")): r for r in (answer_sheet.get("obligations") or [])}
    #: ★ 多主体分簇 ⇒ 同一库义务的**分簇行合并**后再逐项比对（#108 实测事故修复）
    clustered = group_answer_rows_by_authoritative_id(
        answer_sheet.get("obligations") or [])
    gold_by_oid = {str(g.get("obligation_id")): g for g in (gold_resolved.get("items") or [])}
    out: list[dict[str, Any]] = []
    for r in rows:
        oid = str(r.get("obligation_id") or "")
        g = gold_by_oid.get(oid) or {}
        cl_rows = clustered.get(oid) or []
        a = merge_cluster_rows(cl_rows) if cl_rows else (ans_by_oid.get(oid) or {})
        exp_files = []
        for f in (g.get("expected_files") or []):
            exp_files.append({
                "file_id": str(f.get("file_id") or ""),
                "sha256": str(f.get("sha256") or ""),
                "gold_relative_path": str(f.get("gold_relative_path") or ""),
                "entity": str(f.get("gold_entity") or ""),
                "period": str(f.get("gold_period") or ""),
                "resolution": str(f.get("resolution") or ""),
            })
        sel_files = []
        for s in (a.get("selected") or []):
            sid = str(s.get("file_id") or "")
            sel_files.append({
                "file_id": sid,
                "sha256": str(s.get("sha256") or ""),
                "relative_path": str(s.get("relative_path") or ""),
                "entity": str(s.get("entity") or ""),
                "period": str(s.get("period") or ""),
                "match_reason": str(s.get("match_reason") or ""),
            })
        out.append({
            "obligation_id": oid,
            "item_no": r.get("item_no"),
            "outcome": r.get("outcome"),
            "correct": r.get("outcome") == "CORRECT",
            "expected_files": exp_files,
            "selected_files": sel_files,
            "hit": list(r.get("hit") or []),
            "extra": list(r.get("extra") or []),
            "missed": list(r.get("missed") or []),
            "delivered_files": list(r.get("delivered_files") or []),
            "agent_verdict": r.get("agent_verdict"),
            "expected_verdict": r.get("expected_verdict"),
            "abstain_reason": r.get("abstain_reason"),
            "resolution_state": r.get("resolution_state"),
            "reason": _diff_reason(r),
        })
    return out


def _diff_reason(row: dict[str, Any]) -> str:
    """给一行差异**一个能直接读的归因**（不做主观发挥，只按已有事实分类）。"""
    o = str(row.get("outcome") or "")
    if o == "CORRECT":
        return "选中集合与 Gold 期望完全一致"
    if o == "EXPECTED_NONE":
        return "Gold 该义务没有期望文件 ⇒ 无可比基准（不算答错）"
    if o == "NO_ANSWER":
        return "机器答卷里没有这条义务 ⇒ 未作答"
    if o == "OVER_DELIVERED":
        return "命中了期望材料，但**多选了**不属于 Gold 的材料"
    if o == "INCOMPLETE":
        return "只命中了部分期望材料 ⇒ 漏交"
    if o == "WRONG_ONLY":
        return "选中的材料**都不是**期望材料 ⇒ 错选"
    if o == "MISSED":
        return "期望材料**一个都没选**⇒ 漏交"
    return "未归类"


# ─────────────────────────────────────────────────────────────────────────────
# 5. 版本成绩比较
# ─────────────────────────────────────────────────────────────────────────────

COMPARE_METRICS = (
    ("question_understanding_coverage", "题目理解率"),
    ("material_recall", "材料召回率"),
    ("selection_precision", "选材准确率"),
    ("complete_delivery_ratio", "完整交付率"),
    ("total_score", "总分"),
)


def compare_scorecards(old: dict[str, Any] | None,
                       new: dict[str, Any] | None,
                       *,
                       old_label: str = "旧版本",
                       new_label: str = "新版本") -> dict[str, Any]:
    """同口径版本比较 ⇒ 「指标 | 旧版 | 新版 | 变化」。

    **旧版本没有真实成绩时标「未建立可比基线」**——**禁补造历史分数**。
    """
    def _scores(card: dict[str, Any] | None) -> dict[str, Any] | None:
        if not card:
            return None
        s = card.get("scores")
        return s if isinstance(s, dict) else None

    o, n = _scores(old), _scores(new)
    baseline_established = o is not None
    rows: list[dict[str, Any]] = []
    for key, label in COMPARE_METRICS:
        ov = o.get(key) if o else None
        nv = n.get(key) if n else None
        if ov is None or nv is None:
            delta = None
            note = "未建立可比基线" if ov is None else "新版本未出分"
        else:
            delta = round(float(nv) - float(ov), 6)
            note = ""
        rows.append({"metric": key, "label": label, "old": ov, "new": nv,
                     "delta": delta, "note": note})
    comparable = baseline_established and n is not None
    return {
        "old_label": old_label,
        "new_label": new_label,
        "baseline_established": baseline_established,
        "comparable": comparable,
        "old_status": (old or {}).get("status"),
        "new_status": (new or {}).get("status"),
        "old_spec_fingerprint": (old or {}).get("scoring_spec_fingerprint"),
        "new_spec_fingerprint": (new or {}).get("scoring_spec_fingerprint"),
        "same_scoring_spec": ((old or {}).get("scoring_spec_fingerprint")
                              == (new or {}).get("scoring_spec_fingerprint")
                              and (old or {}).get("scoring_spec_fingerprint") is not None),
        "rows": rows,
        "note": ("两版评分口径指纹不同 ⇒ 分数不可直接比较" if comparable and not
                 ((old or {}).get("scoring_spec_fingerprint")
                  == (new or {}).get("scoring_spec_fingerprint"))
                 else "同口径比较"),
    }


def compare_markdown(cmp: dict[str, Any]) -> str:
    """版本比较的 Markdown 表（可直接贴进交接文档 / Issue）。"""
    lines = ["| 指标 | %s | %s | 变化 |" % (cmp.get("old_label"), cmp.get("new_label")),
             "|---|---:|---:|---:|"]
    for r in cmp.get("rows") or []:
        ov = "未建立可比基线" if r["old"] is None else f"{float(r['old']):.4f}"
        nv = "未出分" if r["new"] is None else f"{float(r['new']):.4f}"
        d = "—" if r["delta"] is None else f"{float(r['delta']):+.4f}"
        lines.append(f"| {r['label']} | {ov} | {nv} | {d} |")
    if not cmp.get("baseline_established"):
        lines.append("")
        lines.append("> **旧版本未建立可比基线** —— 本表不构成「提升」结论。")
    return "\n".join(lines)
