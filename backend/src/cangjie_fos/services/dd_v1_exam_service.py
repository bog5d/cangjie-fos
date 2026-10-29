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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cangjie_fos.services import dd_v1_gold_service as gold_svc

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
                       ) -> dict[str, Any]:
    """由 run_record + packet 产出**机器答卷**。

    ``delivered``：实际组包交付清单（``file_id`` / 交付路径 / 源 SHA256 / 副本 SHA256）。
    ``gold_resolution``：**不参与**本函数（考生侧不读 Gold）——保留形参只为让调用方
    在同一处传参时不会误以为它生效；阅卷在 ``grade_answer_sheet`` 里单独做。
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
        if str(_src.get("run_participated_scope") or "") == "RECEIPT" or "run_participated" in _src:
            _participated = bool(_src.get("run_participated"))
            _part_scope = "RECEIPT"
            break
        # ★ 到这里只有**选材口径** ⇒ **不拿它当回执口径**（fail-closed），继续找回执口径的源
        _part_scope = "SELECTION_ONLY"
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
        # ★ **不无条件断言具体成因**（第 8 轮独立复核的 F21）：
        #   上一版直接写「这次没跑出回执」⇒ 在「**只是拿不到回执口径的参与标记**」的场合，
        #   那句话**是假的**（回执可能明明跑过）⇒ 改为**只陈述我们确实知道的事**，成因列为**可能**。
        _why = ("**拿不到可采信的回执口径参与标记**"
                "（可能是：二进制不在 PATH／回执未贴／贴进来的文件不存在／"
                "回执里没有可核的参与标记）")
        _degrade = (f"★ 适配器实现是 {_prov} 这一类，但本次{_why}"
                    "⇒ 本次**没有可采信的模型参与** ⇒ 参与类别按 RULE_ONLY 记，不自称模型凭据"
                    "（★ 回执本身若在别处留存，请以回执为准）")

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
            "model_id_or_unknown": str(adapter.get("model_id_or_unknown") or "UNKNOWN"),
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
            if oid and oid not in library_obligation_ids and oid not in gold_obligation_ids:
                leaks.append({"kind": "OBLIGATION_OUTSIDE_EXAM", "detail": oid})

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

def _per_obligation_rows(answer_sheet: dict[str, Any],
                         gold_resolved: dict[str, Any]) -> list[dict[str, Any]]:
    """逐题比较：机器答卷 × 人工标准答案。"""
    answers = {str(r.get("obligation_id")): r for r in (answer_sheet.get("obligations") or [])}
    rows: list[dict[str, Any]] = []
    for g in gold_resolved.get("items") or []:
        oid = str(g.get("obligation_id"))
        exp = set(g.get("resolved_file_ids") or [])
        a = answers.get(oid)
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
                    "detail": ("已交付材料的**期间**与该义务的期望期间不一致（不进安全闸、不封顶）"
                               if fid in delivered_ids else
                               "**选中但未交付**的材料期间与该义务的期望期间不一致（不进安全闸、不封顶）"),
                    "delivered": fid in delivered_ids})
        for d in (a.get("delivered") or []):
            fid = str(d.get("file_id") or "")
            got_ent, got_per = _file_meta(fid, d)
            exp = exp_files.get(fid)
            if exp is not None:
                # ★ 同上：**主体**要比（法律事实）；**期间**不比（派生元数据口径）
                #   （但**哈希一致性**照样要查 ⇒ 不能 `continue`）
                exp_ent = str(exp.get("gold_entity") or "")
            else:
                exp_ent = _exp_one(exp_ent_all)
            if exp_ent and got_ent and exp_ent != got_ent:
                findings.append({"kind": "WRONG_ENTITY", "obligation_id": oid, "file_id": fid,
                                 "detail": "**交付**材料的主体与该义务的期望主体不一致"})
            # ★ 交付件的**期间**不比（派生元数据口径差异不算机器交错年份；与「选中」口径一致）
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
        "note_selection": ("错主体/错年份属**选材质量**问题，单列且**不封顶**；"
                           "只有**实际交付**的件才进安全闸封顶；"
                           "★ **期间（年份）只影响本单列指标**，不进安全闸、不封顶"
                           "（派生元数据口径差异不算机器交错年份）"),
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
        return {
            "schema_version": SCORECARD_SCHEMA,
            "exam_id": exam_id,
            "status": "NOT_SCORABLE",
            "blocked_by": ["GOLD_LEAK_DETECTED:考生侧产物出现标准答案内容或库外文件"],
            "scores": None,
            "leak_report": leak_report,
            "scoring_spec_fingerprint": scoring_spec_fingerprint(spec),
            "note": "安全失败：标准答案泄漏 ⇒ 不进入正式评分",
        }

    if not gold_provided or gold_manifest is None:
        return {
            "schema_version": SCORECARD_SCHEMA,
            "exam_id": exam_id,
            "status": "NOT_SCORABLE",
            "blocked_by": [f"GOLD_{gold_state or 'NOT_PROVIDED'}:" + (gold_state_reason or "标准答案不可得")],
            "scores": None,
            "rows": [],
            "safety_gate": {"status": "NOT_EVALUATED", "violations": 0, "findings": [],
                            "by_kind": {}},
            "scoring_spec_fingerprint": scoring_spec_fingerprint(spec),
            "note": "客观不可评分（标准答案不可得）⇒ NOT_SCORABLE；**这不等于 0 分**",
        }

    idx = library_index or {"by_id": {}, "by_sha": {}}
    gold_resolved = gold_svc.resolve_gold_files(gold_manifest, idx)
    corr = gold_svc.check_correspondence(gold_manifest, gold_resolved)
    state, reason = gold_svc.gold_state(gold_manifest, corr, provided=True)
    if state in ("NOT_CONFIRMED", "BROKEN"):
        return {
            "schema_version": SCORECARD_SCHEMA,
            "exam_id": exam_id,
            "status": "NOT_SCORABLE",
            "blocked_by": [f"GOLD_{state}:{reason}"],
            "scores": None,
            "rows": [],
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
            "understood": understood,
            "answered": answered,
            "complete": complete,
            "missed": missed_ob,
            "wrong": wrong_ob,
        },
        "rows": rows,
        "safety_gate": safety,
        "gold_resolution": gold_resolved,
        # ★ 成绩单带**来源模式**：一份 RULE_ONLY 的分与模型跑的分**必须可区分**
        #   （独立 Reviewer 探针 P11：旧口径成绩单里没有这两个字段）。
        "examinee_mode": str(_examinee.get("mode") or "UNKNOWN"),
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
