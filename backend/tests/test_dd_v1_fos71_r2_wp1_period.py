"""cangjie-fos#71 R2-WP1 · 期间语义**接线**验收（语义层 + R4 校验层）。

本文件是 WP1 派工本「四种期间语义 × 四种材料情形」矩阵的落成用例，
外加三条硬规则的判别力用例：

1. **依据不足 ⇒ UNCERTAIN**：保留候选证据 ＋ 写明 ``abstain_reason``，
   **状态不得升级为 MATCHED**，也**不得**判成「不满足／缺失」；
2. **不得取消或跳过期间检查**：明确年度口径下，年份对不上仍是 MISMATCH
   （候选被排除、``rejected_by_period`` 计数、``candidate_status`` 明确表达）；
3. **六态阶梯与候选状态枚举不扩**（``OK → EXHAUSTED → PERIOD_OR_VERSION_MISMATCH →
   NO_CANDIDATE`` 原样；域外情形由 ``candidate_status`` ＋ ``diagnostics`` 承载）。

★ 期间口径速记（与 ``dd_v1_period_service`` 一致）：
  - 义务**压根没提期间**（UNKNOWN）⇒ 期间维度**不构成门槛**
    （A2 G-A2-5 既有口径：``period_basis=UNKNOWN`` 不据此判 UNCERTAIN，
    见 ``test_dd_v1_period_and_type_coverage.py::test_judge_unknown_period_is_not_a_threshold``）
    ⇒ 候选**不被**期间误杀；**不猜**年份；
  - 义务**提了期间但解析不出**（相对期间缺可验证锚点／材料自身无年度标注）
    ⇒ 依据不足 ⇒ UNCERTAIN ＋ 候选证据 ＋ ``abstain_reason``。

★ 全部材料都是**现场合成**的（tmp_path），不含真实材料 / 个人信息 / 密钥；
  全程**零模型调用**（只跑确定性闸）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_agent_result_service as ar
from cangjie_fos.services import dd_v1_period_service as ps
from cangjie_fos.services import dd_v1_semantic_retrieval_service as sem

JIA = "合成法人甲"
YI = "合成法人乙"

#: 合成材料（相对路径 → 正文）。年份在**文件名**上，与正式入口 scaffold 同口径。
_MATERIALS: dict[str, str] = {
    "甲/审计报告/审计报告2024.txt": "审计报告\n本报告为2024年度财务审计结论。\n",
    "甲/审计报告/审计报告2022.txt": "审计报告\n本报告为2022年度财务审计结论。\n",
    "甲/审计报告/审计报告2021.txt": "审计报告\n本报告为2021年度财务审计结论。\n",
    "甲/营业执照/营业执照.txt": "营业执照\n合成样例。\n",
    "乙/审计报告/审计报告2024.txt": "审计报告\n本报告为2024年度财务审计结论。\n",
}


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "material"
    for rel, body in _MATERIALS.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return root


def _meta() -> list[dict[str, str]]:
    meta = []
    for i, (rel, _body) in enumerate(sorted(_MATERIALS.items())):
        name = Path(rel).name
        year = "".join(ch for ch in name if ch.isdigit())[:4]
        is_lic = "营业执照" in name
        meta.append({
            "file_id": f"F{i + 1:05d}", "relative_path": rel,
            "entity": YI if rel.startswith("乙/") else JIA,
            "period": "CURRENT" if is_lic else year,
            "doc_type": "license" if is_lic else "audit_report",
            "part": "正文", "version_status": "EFFECTIVE",
        })
    return meta


def _ob(text: str, entity: str = JIA) -> dict:
    """按正式入口的拆解口径造一条义务（带 period_spec）。"""
    obs, _flags = sem.split_item({"item_id": "X", "entity": entity, "text": text})
    assert obs, text
    return obs[0]


# ═══════════════════════════════════════════════════════════════════════
# 1. 四种期间语义 × 四种材料情形
# ═══════════════════════════════════════════════════════════════════════


def test_matrix_explicit_year(tmp_path):
    root = _tree(tmp_path)
    meta = _meta()
    ob = _ob("请提供2024年度审计报告")

    # ① 有材料且期间符合 ⇒ 候选可用
    d = sem.retrieve_minimal_evidence_detailed(root, meta, ob)
    assert d["candidate_status"] == "OK", d["candidate_status"]
    assert d["diagnostics"]["period_status"] == "MATCH"
    assert sem.rule_hint(ob, d["evidence"])["verdict"] == "MATCH"

    # ② 有材料但期间不符 ⇒ **不得**升级 MATCHED；候选被排除且留痕
    meta22 = [m for m in meta if m["period"] != "2024"]
    d2 = sem.retrieve_minimal_evidence_detailed(root, meta22, ob)
    assert d2["candidate_status"] == "PERIOD_OR_VERSION_MISMATCH", d2["candidate_status"]
    assert d2["diagnostics"]["rejected_by_period"] >= 1
    assert sem.rule_hint(ob, d2["evidence"])["verdict"] != "MATCH"

    # ③ 无材料 ⇒ 候选为空，原因说清
    d3 = sem.retrieve_minimal_evidence_detailed(root, [], ob)
    assert d3["candidate_status"] == "NO_CANDIDATE"
    assert d3["no_candidate_reason"] == "NO_MATERIAL"
    assert sem.rule_hint(ob, [], "NO_MATERIAL")["verdict"] == "MISSING"

    # ④ 主体不符 ⇒ 候选为空（主体过滤，不是期间问题）
    only_yi = [m for m in meta if m["entity"] == YI]
    d4 = sem.retrieve_minimal_evidence_detailed(root, only_yi, ob)
    assert d4["candidate_status"] == "NO_CANDIDATE"
    assert d4["no_candidate_reason"] == "NO_MATERIAL"


def test_matrix_relative_period_with_verifiable_anchor(tmp_path):
    root = _tree(tmp_path)
    meta = _meta()
    ob = _ob("请提供近三年的审计报告")
    assert ob["period_spec"]["kind"] == "RELATIVE"

    # ① 锚定年 2024 ⇒ 窗口 2022-2024 ⇒ 2024 的材料符合
    d = sem.retrieve_minimal_evidence_detailed(root, meta, ob,
                                                period_anchor={"year": 2024})
    assert d["diagnostics"]["period_spec"]["years"] == [2022, 2023, 2024]
    assert d["candidate_status"] == "OK", d["candidate_status"]
    assert sem.rule_hint(ob, d["evidence"])["verdict"] == "MATCH"

    # ② 窗口外的年份 ⇒ 期间不符（期间检查没有被取消）
    meta21 = [m for m in meta if m["period"] in ("2021", "CURRENT")]
    d2 = sem.retrieve_minimal_evidence_detailed(root, meta21, ob,
                                                 period_anchor={"year": 2024})
    assert d2["candidate_status"] == "PERIOD_OR_VERSION_MISMATCH", d2["candidate_status"]
    assert d2["diagnostics"]["rejected_by_period"] >= 1
    assert sem.rule_hint(ob, d2["evidence"])["verdict"] != "MATCH"


def test_matrix_relative_period_without_anchor_is_uncertain(tmp_path):
    """★ 依据不足 ⇒ UNCERTAIN：保留候选证据 ＋ abstain_reason，**不得**升格 MATCHED。

    ★ 相对期间要展开必须有**可验证**的截止日期（显式配置 / 原文声明 / 材料自身年度）。
      本例里材料**自身也没有年度标注** ⇒ 三种来源都没有 ⇒ 依据不足 ⇒ UNCERTAIN。
      （若材料带年份，则锚点可取自「材料自身日期」⇒ 可判定 ⇒ 见
      ``test_relative_period_anchor_never_uses_system_clock``。）
    """
    root = tmp_path / "material"
    root.mkdir()
    (root / "a.txt").write_text("审计报告\n合成样例\n", encoding="utf-8")
    meta = [{"file_id": "M1", "relative_path": "a.txt", "entity": JIA, "period": "",
             "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"}]
    ob = _ob("请提供近三年的审计报告")
    d = sem.retrieve_minimal_evidence_detailed(root, meta, ob)
    assert d["candidate_status"] == "OK", d["candidate_status"]
    assert d["diagnostics"]["period_status"] == "UNVERIFIABLE"
    assert d["diagnostics"]["period_unverifiable"] >= 1
    assert d["evidence"], "依据不足时**必须保留候选证据**"
    hint = sem.rule_hint(ob, d["evidence"])
    assert hint["verdict"] == "UNCERTAIN", hint
    assert hint["abstain_reason"]
    assert hint["files"], "UNCERTAIN 也要带候选证据"


def test_matrix_current_semantics(tmp_path):
    root = _tree(tmp_path)
    meta = _meta()
    ob = _ob("请提供营业执照")
    assert ob["period_spec"]["kind"] == "CURRENT"

    # ① 有材料且期间符合（CURRENT 口径的执照材料）⇒ 可用
    d = sem.retrieve_minimal_evidence_detailed(root, meta, ob)
    assert d["candidate_status"] == "OK", d["candidate_status"]
    assert sem.rule_hint(ob, d["evidence"])["verdict"] == "MATCH"

    # ② 「当前有效」类**不继承**段落年份 ⇒ 执照义务不会去要 2024 年的执照
    ob2 = _ob("请提供2024年度审计报告与营业执照")
    lic = [o for o in sem.split_item({"item_id": "Y", "entity": JIA,
                                      "text": "请提供2024年度审计报告与营业执照"})[0]
           if o["doc_type"] == "license"][0]
    assert lic["period"] == "CURRENT"
    d2 = sem.retrieve_minimal_evidence_detailed(root, meta, lic)
    assert d2["candidate_status"] == "OK", d2["candidate_status"]

    # ③ 无材料 ⇒ 候选为空
    d3 = sem.retrieve_minimal_evidence_detailed(root, [m for m in meta
                                                       if m["doc_type"] != "license"], ob)
    assert d3["candidate_status"] == "NO_CANDIDATE"

    # ④ 主体不符 ⇒ 候选为空
    d4 = sem.retrieve_minimal_evidence_detailed(root, [m for m in meta if m["entity"] == YI], ob)
    assert d4["candidate_status"] == "NO_CANDIDATE"


def test_matrix_unknown_period_keeps_candidates(tmp_path):
    """★ 期间未知（文本压根没提期间）⇒ 该维度**不构成门槛**（A2 G-A2-5 既有口径）。

    ⇒ 候选**不得**被误杀；同时**不猜**年份（不产出任何年度判定）。
    """
    root = _tree(tmp_path)
    meta = _meta()
    ob = _ob("请提供审计报告")
    assert ob["period_spec"]["kind"] == "UNKNOWN"

    d = sem.retrieve_minimal_evidence_detailed(root, meta, ob)
    assert d["candidate_status"] == "OK", d["candidate_status"]
    assert d["diagnostics"]["period_status"] == "NOT_A_CONSTRAINT"
    assert d["diagnostics"]["rejected_by_period"] == 0
    assert d["evidence"], "期间未知时**不得**把材料判死"
    # 期间维度不构成门槛 ⇒ 既不判否、也不因此升格成「有确定期间」
    assert sem.rule_hint(ob, d["evidence"])["verdict"] in ("MATCH", "PARTIAL")


# ═══════════════════════════════════════════════════════════════════════
# 2. 硬规则判别力
# ═══════════════════════════════════════════════════════════════════════


def test_material_without_year_is_uncertain_not_mismatch(tmp_path):
    """★ 材料自身无年度标注 ⇒ 依据不足 ⇒ UNCERTAIN（**不得**判成期间不符、也不得放行 MATCH）。"""
    root = tmp_path / "material"
    root.mkdir()
    (root / "a.txt").write_text("审计报告\n合成样例\n", encoding="utf-8")
    meta = [{"file_id": "M1", "relative_path": "a.txt", "entity": JIA, "period": "",
             "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"}]
    ob = _ob("请提供2024年度审计报告")
    d = sem.retrieve_minimal_evidence_detailed(root, meta, ob)
    assert d["candidate_status"] == "OK", d["candidate_status"]
    assert d["diagnostics"]["period_status"] == "UNVERIFIABLE"
    assert d["diagnostics"]["rejected_by_period"] == 0
    hint = sem.rule_hint(ob, d["evidence"])
    assert hint["verdict"] == "UNCERTAIN", hint
    assert hint["abstain_reason"]


def test_period_check_is_not_weakened(tmp_path):
    """★ 明确年度口径下，年份不符**必须**被拦（期间检查不得取消/弱化）。"""
    root = _tree(tmp_path)
    meta = _meta()
    ob = _ob("请提供2024年度审计报告")
    meta22 = [m for m in meta if m["period"] in ("2022", "2021", "CURRENT")]
    d = sem.retrieve_minimal_evidence_detailed(root, meta22, ob)
    assert d["diagnostics"]["rejected_by_period"] >= 1
    assert d["candidate_status"] == "PERIOD_OR_VERSION_MISMATCH"
    assert all(e["period_status"] == "MISMATCH" for e in d["evidence"])


def test_candidate_status_ladder_is_unchanged():
    """★ 六态阶梯**不得**扩枚举（域外情形走 diagnostics）。"""
    assert sem.CANDIDATE_STATUSES == ("OK", "EXHAUSTED", "PERIOD_OR_VERSION_MISMATCH",
                                       "NO_CANDIDATE")
    assert sem.NO_CANDIDATE_REASONS == ("NO_MATERIAL", "UNRESOLVED_DOC_TYPE",
                                         "UNKNOWN_ENTITY", "PERMISSION_BLOCKED",
                                         "RETRIEVAL_EXHAUSTED", "OTHER")
    assert ps.COMPAT_STATUSES == ("MATCH", "MISMATCH", "UNVERIFIABLE", "NOT_A_CONSTRAINT")


def test_relative_period_anchor_never_uses_system_clock(tmp_path):
    """★ 相对期间的基准**不得**是运行当天。

    本仓合成材料里审计报告的年度是 2021/2022/2024 ⇒ 可验证锚点（材料自身年度）＝ 2024
    ⇒ 窗口＝2022-2024；**系统当年**（远大于 2024）不得出现在窗口里。
    """
    root = _tree(tmp_path)
    meta = _meta()
    ob = _ob("请提供近三年的审计报告")
    d = sem.retrieve_minimal_evidence_detailed(root, meta, ob)
    years = d["diagnostics"]["period_spec"]["years"]
    assert d["diagnostics"]["period_anchor"]["source"] == "MATERIAL_DATE"
    assert years == [2022, 2023, 2024], years
    import datetime
    assert datetime.date.today().year not in years


def test_relative_period_uses_declaration_in_requirement_text(tmp_path):
    """★ 锚点的**可验证来源**之一：需求原文里自带的截止日期声明。"""
    root = _tree(tmp_path)
    meta = _meta()
    ob = _ob("请提供近三年的审计报告（报告期截至2024-06-30）")
    d = sem.retrieve_minimal_evidence_detailed(root, meta, ob)
    assert d["diagnostics"]["period_anchor"]["source"] == "CHECKLIST_DECLARATION"
    assert d["diagnostics"]["period_spec"]["years"] == [2022, 2023, 2024]


# ═══════════════════════════════════════════════════════════════════════
# 3. R4 校验层：不得升格 MATCHED
# ═══════════════════════════════════════════════════════════════════════


def _agent_result(pkt, ob, verdict, fids, *, reason=None, conf=0.9):
    results = []
    for fid in fids:
        e = next(x for x in pkt["evidence"][ob["obligation_id"]] if x["file_id"] == fid)
        results.append({
            "item_id": ob["item_id"], "obligation_id": ob["obligation_id"], "agent_id": "t",
            "provider": "t", "model_id_or_unknown": "UNKNOWN",
            "prompt_version": pkt["prompt_version"], "source_snapshot_id": pkt["source_snapshot_id"],
            "candidate_files": [{"file_id": fid, "relative_path": e["relative_path"],
                                 "sha256": e["sha256"], "locator": e["locator"],
                                 "entity": e["entity"], "period": e["period"],
                                 "match_reason": "正文写明主体与年度"}],
            "proposed_verdict": verdict, "confidence_or_uncertain": conf,
            "abstain_reason": reason, "warnings": [], "elapsed": "UNKNOWN",
            "token_usage_or_UNKNOWN": "UNKNOWN",
        })
    return {"results": results}


def _errors(rep, oid):
    return [e for r in rep["rejected"] if r["result"]["obligation_id"] == oid
            for e in r["errors"]]


def test_r4_rejects_match_when_period_basis_insufficient(tmp_path):
    """★ 依据不足 ⇒ **不得**接受 MATCH（只能 UNCERTAIN ＋ abstain_reason）。

    本例：相对期间「近三年」**没有任何可验证锚点**（材料自身也没有年度标注）
    ⇒ 期间维度无法判定 ⇒ MATCH 必须被确定性闸拦下。
    """
    root = tmp_path / "material"
    root.mkdir()
    (root / "a.txt").write_text("审计报告\n合成样例\n", encoding="utf-8")
    meta = [{"file_id": "M1", "relative_path": "a.txt", "entity": JIA, "period": "",
             "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"}]
    items = [{"item_id": "X", "entity": JIA, "text": "请提供近三年的审计报告"}]
    pkt = sem.build_semantic_packet(root, meta, items)
    ob = pkt["obligations"][0]
    fid = next(e["file_id"] for e in pkt["evidence"][ob["obligation_id"]])
    rep = sem.validate_semantic(json.dumps(_agent_result(pkt, ob, "MATCH", [fid])),
                                 root, meta, pkt).to_dict()
    assert not rep["accepted"], "依据不足时 MATCH 被放行了"
    assert any("PERIOD_BASIS_INSUFFICIENT" in e for e in _errors(rep, ob["obligation_id"]))


def test_r4_rejects_match_when_material_year_conflicts(tmp_path):
    """★ 期间已知且冲突 ⇒ MATCH 被拒（期间闸门没有被弱化）。"""
    root = _tree(tmp_path)
    meta = _meta()
    ob = _ob("请提供2024年度审计报告")
    pkt = sem.build_semantic_packet(root, meta, [{"item_id": "X", "entity": JIA,
                                                   "text": "请提供2024年度审计报告"}])
    fid = next(e["file_id"] for e in pkt["evidence"][ob["obligation_id"]]
               if e["period"] == "2022")
    rep = sem.validate_semantic(json.dumps(_agent_result(pkt, ob, "MATCH", [fid])),
                                 root, meta, pkt).to_dict()
    assert not rep["accepted"]
    assert any("PERIOD_MISMATCH" in e for e in _errors(rep, ob["obligation_id"]))


def test_r4_accepts_match_when_period_matches(tmp_path):
    """★ 阳性对照：期间对得上 ⇒ MATCH 仍被接受（闸门没被一刀切关掉）。"""
    root = _tree(tmp_path)
    meta = _meta()
    ob = _ob("请提供2024年度审计报告")
    pkt = sem.build_semantic_packet(root, meta, [{"item_id": "X", "entity": JIA,
                                                   "text": "请提供2024年度审计报告"}])
    fid = next(e["file_id"] for e in pkt["evidence"][ob["obligation_id"]]
               if e["period"] == "2024")
    rep = sem.validate_semantic(json.dumps(_agent_result(pkt, ob, "MATCH", [fid])),
                                 root, meta, pkt).to_dict()
    assert rep["accepted"], rep["rejected"]


def test_obligation_carries_period_spec():
    """★ 接线证据：拆出来的义务**带**四态口径（不是只有字符串）。"""
    obs, _flags = sem.split_item({"item_id": "X", "entity": JIA, "text": "请提供2024年度审计报告"})
    assert obs[0]["period_spec"]["kind"] == "EXPLICIT"
    assert obs[0]["period_spec"]["years"] == [2024]
    obs2, _f2 = sem.split_item({"item_id": "X", "entity": JIA, "text": "请提供近三年审计报告"})
    assert obs2[0]["period_spec"]["kind"] == "RELATIVE"
    obs3, _f3 = sem.split_item({"item_id": "X", "entity": JIA, "text": "请提供营业执照"})
    assert obs3[0]["period_spec"]["kind"] == "CURRENT"
    obs4, _f4 = sem.split_item({"item_id": "X", "entity": JIA, "text": "请提供审计报告"})
    assert obs4[0]["period_spec"]["kind"] == "UNKNOWN"


def test_period_spec_is_json_serializable_and_deterministic():
    obs_a, _ = sem.split_item({"item_id": "X", "entity": JIA, "text": "请提供近三年审计报告"})
    obs_b, _ = sem.split_item({"item_id": "X", "entity": JIA, "text": "请提供近三年审计报告"})
    assert obs_a[0]["period_spec"] == obs_b[0]["period_spec"]
    assert json.loads(json.dumps(obs_a[0]["period_spec"], ensure_ascii=False)) == obs_a[0]["period_spec"]


def test_legacy_obligation_without_spec_still_works():
    """★ 旧数据兼容：没有 period_spec 的手写义务仍按字符串口径判定（不放宽、不收紧）。"""
    ob = {"entity": JIA, "doc_type": "audit_report", "period": "2024", "required_parts": []}
    spec = ps.spec_from_obligation(ob)
    assert spec["kind"] == "EXPLICIT" and spec["years"] == [2024]
    ob_cur = {"entity": JIA, "doc_type": "license", "period": "CURRENT", "required_parts": []}
    spec2 = ps.spec_from_obligation(ob_cur)
    assert spec2["kind"] == "CURRENT" and spec2["current_mode"] == "LABEL"
    assert ps.compatibility(spec2, "CURRENT")["status"] == "MATCH"
    assert ps.compatibility(spec2, "2024")["status"] == "MISMATCH"
