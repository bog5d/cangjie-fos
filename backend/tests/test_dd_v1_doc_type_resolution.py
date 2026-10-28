"""DD-V1 WP2：真实题型的**语义理解** —— 类型待判定 ⇒ 由模型判定（而不是丢题 / 规则脚本冒充）。

**这个文件锁死的红线**（`#108` 实测 P0-1 与施工令 WP2）：

1. 规则层拆不出材料类型的**片段**，**不得**整条丢弃 ⇒ 必须产出一条「类型待判定」义务；
2. 「类型待判定」义务的证据池**不按类型筛**（否则模型永远没机会做判断）；
3. 模型**必须**给出 ``proposed_doc_type``（权威 10 类）或诚实弃答；
   ★★ **口径更正（独立 Reviewer 2026-10-29 实测）**：这条只验**自洽性**
   （提案 ∈ 权威 10 类 ∧ 提案 == 所选文件自身类型），
   **不证伪「这是规则脚本」** —— 一个纯规则脚本（取证据池第一个文件、
   按它自身类型提提案）**同样能通过**。
   ⇒ 「AI 真语义判断 vs 规则脚本」**不是**本条能机器判定的；
   本条能机器判定的是「提案自洽且落在权威类型域内」。
4. 模型提出的类型**必须与它自己选的文件自身类型一致**（说了要审计报告却挑执照 ⇒ 拒）；
5. 规则层**已**解析出类型时，模型**不得**静默改写；
6. ★ **既有契约一字不动**：``unsplit_items`` / ``split_flags`` 的语义与形状不变
   （「类型待判定」是**多**出来的一条给模型看的义务，不是**替换**）。

★ 这是「AI 真的做了语义判断」与「AI 只是调用规则脚本」的**机器可验证分界**：
  规则脚本永远产不出 ``proposed_doc_type``，更产不出与文件类型自洽的提案。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_semantic_retrieval_service as s

FX = Path(__file__).parent / "fixtures" / "dd_v1_fos71_wp04"
SNAP = FX / "snapshot"
META = json.loads((FX / "meta.json").read_text("utf-8"))
ITEMS = json.loads((FX / "raw_items.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def pkt():
    """★ 打开「类型待判定」通道的语义包。"""
    return s.build_semantic_packet(SNAP, META, ITEMS, resolve_doc_type=True)


@pytest.fixture(scope="module")
def pkt_default():
    """★ **默认**（不打开该通道）的语义包 —— 既有契约必须一模一样。"""
    return s.build_semantic_packet(SNAP, META, ITEMS)


def _all_obligations(pkt):
    """规则义务 ＋ 类型待判定义务（两者都在模型可见面内）。"""
    return list(pkt["obligations"]) + list(pkt.get("doc_type_resolution") or [])


def _res(pkt, oid, verdict, fids=(), conf=0.9, reason=None, proposed=None):
    ob = next(o for o in _all_obligations(pkt) if o["obligation_id"] == oid)
    cands = []
    for f in fids:
        m = next(x for x in META if x["file_id"] == f)
        e = next((x for x in pkt["evidence"][oid] if x["file_id"] == f), None)
        sha = e["sha256"] if e else ""
        loc = e["locator"] if e else "L1-L1"
        cands.append({"file_id": f, "relative_path": m["relative_path"], "sha256": sha,
                      "locator": loc, "entity": m["entity"], "period": m["period"],
                      "match_reason": "正文写明主体与年度"})
    r = {"item_id": ob["item_id"], "obligation_id": oid, "agent_id": "t", "provider": "t",
         "model_id_or_unknown": "UNKNOWN", "prompt_version": s.SEMANTIC_PROMPT_VERSION,
         "source_snapshot_id": pkt["source_snapshot_id"], "candidate_files": cands,
         "proposed_verdict": verdict, "confidence_or_uncertain": conf,
         "abstain_reason": reason, "warnings": [], "elapsed": "UNKNOWN",
         "token_usage_or_UNKNOWN": "UNKNOWN"}
    if proposed is not None:
        r["proposed_doc_type"] = proposed
    return r


def _validate(pkt, data):
    return s.validate_semantic(json.dumps(data, ensure_ascii=False), SNAP, META, pkt).to_dict()


def _errs(rep, oid):
    return [e for r in rep["rejected"] if r["result"]["obligation_id"] == oid for e in r["errors"]]


class TestUnresolvedDocTypeReachesTheModel:
    """红线 1/2：不得丢题；证据池不按类型筛。"""

    def test_unsplit_item_still_produces_a_resolution_obligation(self, pkt):
        ids = {o["obligation_id"] for o in pkt.get("doc_type_resolution") or []}
        assert "R3-RES1" in ids, "「其他相关材料等」这类片段必须产出一条待判定义务"

    def test_resolution_items_do_not_pollute_the_rule_obligations(self, pkt):
        """★ 归入**独立分区**：``obligations`` 的内容与形状一字不变。"""
        assert {o["obligation_id"] for o in pkt["obligations"]} == {
            "R1-O1", "R2-O1", "R2-O2", "R4-O1"}
        assert not any(o["item_id"] == "R3" for o in pkt["obligations"])

    def test_default_packet_is_unchanged(self, pkt_default):
        """★ **默认关闭**时，既有契约与既有行为**逐字一致**（不偷偷改变花钱方式）。"""
        assert pkt_default.get("doc_type_resolution") == []
        assert {o["obligation_id"] for o in pkt_default["obligations"]} == {
            "R1-O1", "R2-O1", "R2-O2", "R4-O1"}
        assert not any(o["item_id"] == "R3" for o in pkt_default["obligations"])
        assert pkt_default["unsplit_items"] == [
            {"item_id": "R3", "text": "其他相关材料等", "status": "NEEDS_HUMAN_SPLIT",
             "reason": "NO_KNOWN_DOC_TYPE"}]

    def test_existing_unsplit_contract_is_unchanged(self, pkt):
        """★ 既有契约不动：``unsplit_items`` 仍然如实记录 NEEDS_HUMAN_SPLIT。"""
        assert pkt["unsplit_items"] == [
            {"item_id": "R3", "text": "其他相关材料等", "status": "NEEDS_HUMAN_SPLIT",
             "reason": "NO_KNOWN_DOC_TYPE"}]

    def test_resolution_obligation_is_flagged(self, pkt):
        ob = next(o for o in pkt["doc_type_resolution"] if o["obligation_id"] == "R3-RES1")
        assert ob["doc_type"] == ""
        assert ob["doc_type_unresolved"] is True
        assert ob["doc_type_source"] == "UNRESOLVED"
        assert ob["text"] == "其他相关材料等", "必须保留原始题目文字"

    def test_evidence_pool_is_type_agnostic(self, pkt):
        """★ 类型待判定 ⇒ 证据池**不按类型筛**（否则模型永远没机会判断）。"""
        ev = pkt["evidence"]["R3-RES1"]
        assert ev, "证据池不能为空"
        types = {e["doc_type"] for e in ev}
        assert len(types) > 1, f"证据池应当跨类型，实际只有 {types}"
        st = pkt["evidence_status"]["R3-RES1"]
        assert st["diagnostics"]["doc_type_filter"] == "AGNOSTIC_RESOLUTION"
        assert st["diagnostics"]["rejected_by_doc_type"] == 0

    def test_rule_resolved_obligation_keeps_exact_type_filter(self, pkt):
        st = pkt["evidence_status"]["R1-O1"]
        assert st["diagnostics"]["doc_type_filter"] == "EXACT_MATCH"


class TestProposedDocTypeIsVerified:
    """红线 3/4/5：模型提案必须自洽。"""

    def test_valid_proposal_with_consistent_file_is_accepted(self, pkt):
        """模型提出 audit_report 并挑了审计报告 ⇒ 接受（这才是真语义判断）。"""
        data = {"results": [
            _res(pkt, "R1-O1", "MATCH", ["G001"]),
            _res(pkt, "R2-O1", "MATCH", ["G006"]),
            _res(pkt, "R2-O2", "MISSING", reason="证据为空"),
            _res(pkt, "R4-O1", "MISSING", reason="只有 2023/2024 年版本"),
            _res(pkt, "R3-RES1", "MATCH", ["G001"], proposed="audit_report"),
        ]}
        rep = _validate(pkt, data)
        accepted = {r["obligation_id"] for r in rep["accepted"]}
        assert "R3-RES1" in accepted, rep["rejected"]

    def test_missing_proposal_on_match_is_rejected(self, pkt):
        """给了 MATCH 却不说要哪类材料 ⇒ 拒（不许含糊过关）。"""
        data = {"results": [
            _res(pkt, "R3-RES1", "MATCH", ["G001"]),
        ]}
        rep = _validate(pkt, data)
        errs = _errs(rep, "R3-RES1")
        assert any(e.startswith("DOC_TYPE_PROPOSAL_REQUIRED") for e in errs), errs

    def test_proposal_not_matching_chosen_file_is_rejected(self, pkt):
        """说要审计报告却挑了营业执照 ⇒ 拒（自相矛盾）。"""
        data = {"results": [
            _res(pkt, "R3-RES1", "MATCH", ["G006"], proposed="audit_report"),
        ]}
        rep = _validate(pkt, data)
        errs = _errs(rep, "R3-RES1")
        assert any("DOC_TYPE_PROPOSAL_MISMATCH" in e for e in errs), errs

    def test_invalid_proposal_value_is_rejected(self, pkt):
        """提出不在权威 10 类里的类型 ⇒ 拒。"""
        data = {"results": [
            _res(pkt, "R3-RES1", "MATCH", ["G001"], proposed="随便什么"),
        ]}
        rep = _validate(pkt, data)
        errs = _errs(rep, "R3-RES1")
        assert any("DOC_TYPE_PROPOSAL_INVALID" in e for e in errs), errs

    def test_abstain_without_proposal_is_allowed(self, pkt):
        """判断不出来 ⇒ 诚实弃答（允许，且必须写原因）。"""
        data = {"results": [
            _res(pkt, "R3-RES1", "UNCERTAIN", [], reason="无法判断该条要求哪一类材料"),
        ]}
        rep = _validate(pkt, data)
        accepted = {r["obligation_id"] for r in rep["accepted"]}
        assert "R3-RES1" in accepted, rep["rejected"]

    def test_rule_resolved_obligation_cannot_be_overridden(self, pkt):
        """规则层已解析出类型 ⇒ 模型不得静默改写。"""
        data = {"results": [
            _res(pkt, "R1-O1", "MATCH", ["G001"], proposed="financial_statement"),
        ]}
        rep = _validate(pkt, data)
        errs = _errs(rep, "R1-O1")
        assert any("DOC_TYPE_PROPOSAL_CONFLICTS_WITH_RULE" in e for e in errs), errs


class TestRuleOnlyCannotFakeSemanticJudgement:
    """规则脚本**产不出** ``proposed_doc_type`` ⇒ 过不了语义层。

    ★★ 但**反过来不成立**：产得出**自洽**提案**不等于**做了语义判断
    （独立 Reviewer 构造的纯规则脚本能通过自洽性检查）⇒ 本条只锁「必须提出类型」。
    """

    def test_rule_only_produces_no_proposal(self):
        """RULE_ONLY 路径（无适配器）**产不出** proposed_doc_type ⇒ 无法被算成「已理解」。"""
        obs, flags = s.split_items(ITEMS)
        assert not any(o.get("proposed_doc_type") for o in obs)
        # 规则层对 R3 只能给 NEEDS_HUMAN_SPLIT ⇒ 理解不了
        assert any(f.get("status") == "NEEDS_HUMAN_SPLIT" for f in flags)

    def test_unknown_field_is_rejected(self, pkt):
        """自造字段 ⇒ R4 结构层直接拒（防止用旁门字段冒充语义判断）。"""
        r = _res(pkt, "R3-RES1", "MATCH", ["G001"])
        r["my_own_understanding"] = "audit_report"
        rep = _validate(pkt, {"results": [r]})
        errs = _errs(rep, "R3-RES1")
        assert any("UNKNOWN_FIELDS" in e for e in errs), errs
