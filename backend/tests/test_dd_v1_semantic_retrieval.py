"""cangjie-fos#71 WP04：拆条目 / 只读最小证据检索 / 确定性语义校验（合成 fixture，零模型调用）。"""
from __future__ import annotations

import copy
import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_agent_adapters as ad
from cangjie_fos.services import dd_v1_semantic_retrieval_service as s

FX = Path(__file__).parent / "fixtures" / "dd_v1_fos71_wp04"
SNAP = FX / "snapshot"
META = json.loads((FX / "meta.json").read_text("utf-8"))
ITEMS = json.loads((FX / "raw_items.json").read_text("utf-8"))
CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "dd-v1-fos71" / "wp02" / "GOAL-CONTRACT-WP02.json"


@pytest.fixture(scope="module")
def pkt():
    return s.build_semantic_packet(SNAP, META, ITEMS)


def _ev(pkt, oid, fid):
    return next(e for e in pkt["evidence"][oid] if e["file_id"] == fid)


def _res(pkt, oid, verdict, fids=(), conf=0.9, reason=None, locator=None, why="正文第2行写明主体与年度"):
    ob = next(o for o in pkt["obligations"] if o["obligation_id"] == oid)
    cands = []
    for f in fids:
        m = next(x for x in META if x["file_id"] == f)
        try:
            e = _ev(pkt, oid, f)
            sha, loc = e["sha256"], e["locator"]
        except StopIteration:
            from cangjie_fos.services import dd_v1_agent_result_service as ar
            sha, loc = ar.sha256_file(SNAP / m["relative_path"]), "L1-L1"
        cands.append({"file_id": f, "relative_path": m["relative_path"], "sha256": sha,
                      "locator": locator or loc, "entity": m["entity"], "period": m["period"], "match_reason": why})
    return {"item_id": ob["item_id"], "obligation_id": oid, "agent_id": "t", "provider": "t",
            "model_id_or_unknown": "UNKNOWN", "prompt_version": s.SEMANTIC_PROMPT_VERSION,
            "source_snapshot_id": pkt["source_snapshot_id"], "candidate_files": cands, "proposed_verdict": verdict,
            "confidence_or_uncertain": conf, "abstain_reason": reason, "warnings": [], "elapsed": "UNKNOWN",
            "token_usage_or_UNKNOWN": "UNKNOWN"}


def _good(pkt):
    return {"results": [
        _res(pkt, "R1-O1", "MATCH", ["G001", "G002"]),
        _res(pkt, "R2-O1", "MATCH", ["G006"]),
        _res(pkt, "R2-O2", "MISSING", reason="证据为空"),
        _res(pkt, "R4-O1", "MISSING", reason="只有 2023/2024 年版本"),
    ]}


def _validate(pkt, data):
    return s.validate_semantic(json.dumps(data, ensure_ascii=False), SNAP, META, pkt).to_dict()


def _errs(rep, oid):
    return [e for r in rep["rejected"] if r["result"]["obligation_id"] == oid for e in r["errors"]]


# ---------- 拆条目

def test_split_multi_doc_item_and_parts(pkt):
    obs = {o["obligation_id"]: o for o in pkt["obligations"]}
    assert set(obs) == {"R1-O1", "R2-O1", "R2-O2", "R4-O1"}
    assert obs["R1-O1"]["required_parts"] == ["正文", "附注"] and obs["R1-O1"]["period"] == "2024"
    # ★ WP1 口径更正（2026-10-23 考生2 P0）：doc_type 的取值空间是
    #   ``dd_v1_requirement_service._DOC_TYPE_RULES`` 的 **10 个规范英文 key**。
    #   旧断言写的是中文类型名（"公司章程" / "社保缴纳证明"）—— 那张 7 类中文表
    #   只覆盖 10 类中的 7 类（缺 resolution / ip / contract），且与桥接层的英文 key
    #   空间分叉 ⇒ 语义层证据池**恒空**。断言改为英文 key，语义不变（仍是同一类材料）。
    assert (obs["R2-O1"]["doc_type"], obs["R2-O1"]["period"]) == ("charter", "CURRENT")
    assert (obs["R2-O2"]["doc_type"], obs["R2-O2"]["period"]) == ("labor", "2024")


def test_vague_item_is_flagged_not_guessed(pkt):
    assert pkt["unsplit_items"] == [{"item_id": "R3", "text": "其他相关材料等", "status": "NEEDS_HUMAN_SPLIT",
                                     "reason": "NO_KNOWN_DOC_TYPE"}]
    assert not any(o["item_id"] == "R3" for o in pkt["obligations"])


def test_split_is_deterministic():
    assert s.build_semantic_packet(SNAP, META, ITEMS) == s.build_semantic_packet(SNAP, META, ITEMS)


def test_ambiguous_two_doc_types_in_one_segment_split_into_atomic_obligations():
    """★ WP1(a) 行为变更（2026-10-23 考生2 P0）：一段含多类 ⇒ 拆成多条原子义务。

    **旧行为**：``_doc_type`` 命中数必须恰好为 1，否则整条丢弃
    （NEEDS_HUMAN_SPLIT）⇒ 「审计报告/营业执照合订本」这类**合订本**整条判死，
    业务事实是 54 条清单只拆出 7 条。

    **新行为**：按类拆成多条原子义务（每条一类、共享该段期间），并留痕 ``AMBIGUOUS_SPLIT``。
    断言从「整条丢弃」改为「拆成 2 条 + 留痕」—— **判据没有被削弱**：
    拆出来的每条仍只认自己那一类材料（见 test_dd_v1_fos71_player2_p0.py 的反例）。
    """
    obs, flags = s.split_item({"item_id": "X", "entity": "E", "text": "审计报告/营业执照合订本"})
    assert [o["doc_type"] for o in obs] == ["audit_report", "license"]
    assert [o["obligation_id"] for o in obs] == ["X-O1", "X-O2"]
    assert all(o["entity"] == "E" for o in obs)
    # 共享该段期间（执照类无年度口径 ⇒ CURRENT；审计报告类无年份 ⇒ UNKNOWN）
    assert obs[0]["period"] == "UNKNOWN" and obs[1]["period"] == "CURRENT"
    assert all(o["ambiguous_split"] is True and o["split_method"] == "RULE_SPLIT_MULTI_TYPE" for o in obs)
    assert [f["status"] for f in flags] == ["AMBIGUOUS_SPLIT"]
    assert flags[0]["doc_types"] == ["audit_report", "license"]
    assert flags[0]["obligation_ids"] == ["X-O1", "X-O2"]


def test_compound_doc_type_is_not_split_into_two_obligations():
    """★ 反例（误匹配率不得上升）：**复合词**不拆。

    「员工合同」「劳动合同」= 一个复合名词，不是两类材料；拆开就会凭空多出一条
    义务（多一条 MISSING、多一次误匹配）。规则：两次类型命中之间**没有分隔符**
    ⇒ 退回归一类型（与 ``rq.parse_doc_type`` 一致）。
    """
    for text, expect in (("请提供员工合同", ["labor"]),
                         ("请提供劳动合同", ["labor"]),
                         ("请提供劳动合同与设备采购合同", ["labor", "contract"])):
        obs, flags = s.split_item({"item_id": "Y", "entity": "E", "text": text})
        assert [o["doc_type"] for o in obs] == expect, text
        assert [f["status"] for f in flags if f["status"] == "AMBIGUOUS_SPLIT"] == (
            ["AMBIGUOUS_SPLIT"] if len(expect) > 1 else []), text


# ---------- 只读最小证据检索

def test_evidence_excludes_other_entity_and_other_doc_types(pkt):
    ids = {e["file_id"] for ev in pkt["evidence"].values() for e in ev}
    assert "G005" not in ids  # 别的主体
    assert "G008" not in ids  # 注入备忘（文档类型「其他」）
    assert pkt["evidence"]["R2-O2"] == []


def test_evidence_is_minimal_excerpt_with_locator_and_sha(pkt):
    e = _ev(pkt, "R1-O1", "G001")
    assert e["locator"].startswith("L") and len(e["untrusted_excerpt"]) <= s.MAX_EXCERPT_CHARS
    assert "files" not in pkt  # 不再把整个快照的文件摘录全给模型
    assert [x["file_id"] for x in pkt["evidence"]["R1-O1"]][:2] == ["G001", "G002"]  # 同期间有效版本优先


def test_retrieval_is_read_only(tmp_path, monkeypatch):
    import builtins
    real = builtins.open

    def guard(f, mode="r", *a, **k):
        assert not any(c in mode for c in "wax+"), f"write attempted: {f} {mode}"
        return real(f, mode, *a, **k)
    monkeypatch.setattr(builtins, "open", guard)
    before = {p.name: p.stat().st_mtime_ns for p in SNAP.iterdir()}
    s.build_semantic_packet(SNAP, META, ITEMS)
    assert before == {p.name: p.stat().st_mtime_ns for p in SNAP.iterdir()}


def test_retrieval_refuses_path_outside_snapshot():
    bad = copy.deepcopy(META)
    bad[0]["relative_path"] = "../meta.json"
    ob = {"entity": "示例科技有限公司", "doc_type": "审计报告", "period": "2024", "required_parts": []}
    with pytest.raises((PermissionError, FileNotFoundError)):
        s.retrieve_minimal_evidence(SNAP, bad, ob)


def test_rule_hints(pkt):
    h = {o["obligation_id"]: s.rule_hint(o, pkt["evidence"][o["obligation_id"]]) for o in pkt["obligations"]}
    assert h["R1-O1"] == {"verdict": "MATCH", "files": ["G001", "G002"]}
    assert h["R2-O1"]["verdict"] == "MATCH" and h["R2-O1"]["files"] == ["G006"]
    assert h["R2-O2"]["verdict"] == "MISSING"
    assert h["R4-O1"] == {"verdict": "MISSING", "files": [], "note": "OTHER_PERIODS_AVAILABLE"}


def test_rule_hint_partial_and_outdated():
    ob = {"entity": "示例科技有限公司", "doc_type": "审计报告", "period": "2024", "required_parts": ["正文", "附注"]}
    ev = s.retrieve_minimal_evidence(SNAP, [m for m in META if m["file_id"] != "G002"], ob)
    assert s.rule_hint(ob, ev)["verdict"] == "PARTIAL"
    ev2 = s.retrieve_minimal_evidence(SNAP, [m for m in META if m["file_id"] in ("G003", "G004")], ob)
    assert s.rule_hint(ob, ev2)["verdict"] == "OUTDATED"


# ---------- 确定性语义校验

def test_good_answer_accepted_as_suggestion(pkt):
    rep = _validate(pkt, _good(pkt))
    assert rep["mode"] == "AGENT_SUGGESTION" and len(rep["accepted"]) == 4 and not rep["rejected"]
    assert all(r["review_required"] and r["approved"] is False for r in rep["accepted"])
    assert not rep["warnings"]


def test_injection_follower_is_blocked(pkt):
    d = {"results": [_res(pkt, o["obligation_id"], "MATCH", ["G008"], conf=1.0) for o in pkt["obligations"]]}
    rep = _validate(pkt, d)
    assert rep["mode"] == "RULE_ONLY" and not rep["accepted"]
    assert all(any("NOT_IN_RETRIEVED_EVIDENCE" in e for e in r["errors"]) for r in rep["rejected"]
               if r.get("layer") == "SEMANTIC")


def test_wrong_entity_blocked(pkt):
    d = _good(pkt)
    d["results"][0] = _res(pkt, "R1-O1", "MATCH", ["G005"])
    errs = _errs(_validate(pkt, d), "R1-O1")
    assert "CANDIDATE_0_ENTITY_MISMATCH" in errs  # R4 层先挡住


def test_draft_as_match_blocked(pkt):
    d = _good(pkt)
    d["results"][0] = _res(pkt, "R1-O1", "MATCH", ["G003", "G002"])
    assert "CANDIDATE_0_NON_EFFECTIVE_VERSION_AS_MATCH" in _errs(_validate(pkt, d), "R1-O1")


def test_superseded_articles_as_outdated_allowed(pkt):
    d = _good(pkt)
    d["results"][1] = _res(pkt, "R2-O1", "OUTDATED", ["G007"], conf=0.7)
    rep = _validate(pkt, d)
    assert not _errs(rep, "R2-O1")
    assert any(w["obligation_id"] == "R2-O1" and w["code"] == "DIFFERS_FROM_RULE_HINT" for w in rep["warnings"])


def test_attachment_incomplete_match_blocked_but_partial_ok(pkt):
    d = _good(pkt)
    d["results"][0] = _res(pkt, "R1-O1", "MATCH", ["G001"])
    assert "ATTACHMENT_INCOMPLETE_FOR_MATCH:附注" in _errs(_validate(pkt, d), "R1-O1")
    d["results"][0] = _res(pkt, "R1-O1", "PARTIAL", ["G001"], conf=0.6)
    assert not _errs(_validate(pkt, d), "R1-O1")


def test_wrong_year_blocked(pkt):
    d = _good(pkt)
    d["results"][3] = _res(pkt, "R4-O1", "MATCH", ["G004"])
    assert "CANDIDATE_0_PERIOD_MISMATCH" in _errs(_validate(pkt, d), "R4-O1")


def test_fabricated_locator_blocked(pkt):
    d = _good(pkt)
    d["results"][1] = _res(pkt, "R2-O1", "MATCH", ["G006"], locator="L99-L120")
    assert "CANDIDATE_0_LOCATOR_NOT_IN_EVIDENCE" in _errs(_validate(pkt, d), "R2-O1")


def test_confident_without_locator_blocked_low_conf_allowed(pkt):
    d = _good(pkt)
    d["results"][1] = _res(pkt, "R2-O1", "MATCH", ["G006"], locator="UNKNOWN", conf=0.95)
    assert "CANDIDATE_0_CONFIDENT_WITHOUT_LOCATOR" in _errs(_validate(pkt, d), "R2-O1")
    d["results"][1] = _res(pkt, "R2-O1", "MATCH", ["G006"], locator="UNKNOWN", conf=0.5)
    assert not _errs(_validate(pkt, d), "R2-O1")


@pytest.mark.parametrize("why", ["", "相关", "match"])
def test_generic_explanation_blocked(pkt, why):
    d = _good(pkt)
    d["results"][1] = _res(pkt, "R2-O1", "MATCH", ["G006"], why=why)
    assert "CANDIDATE_0_NO_EXPLANATION" in _errs(_validate(pkt, d), "R2-O1")


def test_abstain_without_reason_blocked(pkt):
    d = _good(pkt)
    d["results"][2] = _res(pkt, "R2-O2", "UNCERTAIN", conf="UNCERTAIN", reason="  ")
    assert "ABSTAIN_WITHOUT_REASON" in _errs(_validate(pkt, d), "R2-O2")


def test_fabricated_file_blocked(pkt):
    d = _good(pkt)
    d["results"][0]["candidate_files"][0]["file_id"] = "G999"
    assert "CANDIDATE_0_NOT_IN_SNAPSHOT" in _errs(_validate(pkt, d), "R1-O1")


def test_agent_disagreeing_with_rule_hint_is_warning_not_rejection(pkt):
    d = _good(pkt)
    d["results"][3] = _res(pkt, "R4-O1", "UNCERTAIN", conf="UNCERTAIN", reason="不确定是否接受 2023 年版")
    rep = _validate(pkt, d)
    assert len(rep["accepted"]) == 4
    assert [w["obligation_id"] for w in rep["warnings"]] == ["R4-O1"]


def test_call_failure_degrades(pkt):
    rep = s.validate_semantic(None, SNAP, META, pkt, call_error="TIMEOUT:TIMEOUT").to_dict()
    assert rep["mode"] == "RULE_ONLY" and rep["degrade_reason"].startswith("AGENT_CALL_FAILED")


def test_high_confidence_threshold_matches_contract():
    c = json.loads(CONTRACT.read_text("utf-8"))
    assert s.HIGH_CONFIDENCE == c["scoring_rules"]["high_confidence_threshold"]


# ---------- 端到端：语义包经 WP03 Adapter（假 CLI）

def test_run_semantic_end_to_end_with_fake_codex(tmp_path, pkt):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_good(pkt), ensure_ascii=False), encoding="utf-8")
    fake = tmp_path / "codex.py"
    fake.write_text(textwrap.dedent(f"""
        import sys, json
        assert json.load(open("packet.json", encoding="utf-8"))["prompt_version"] == "fos71-wp04-p1"
        open("out.json", "w", encoding="utf-8").write(open({str(good)!r}, encoding="utf-8").read())
    """), encoding="utf-8")
    wd = tmp_path / "wd"
    wd.mkdir()
    rec = s.run_semantic(ad.CodexAdapter([sys.executable, str(fake)]), SNAP, META, ITEMS,
                         ad.Budget(timeout_s=20), workdir=wd)
    assert rec["prompt_version"] == "fos71-wp04-p1"
    assert rec["semantic_validation"]["mode"] == "AGENT_SUGGESTION"
    assert len(rec["semantic_validation"]["accepted"]) == 4
    assert rec["unsplit_items"][0]["item_id"] == "R3"
    on_disk = json.loads((wd / "run_record.json").read_text("utf-8"))
    assert "semantic_validation" in on_disk and on_disk["rule_hints_note"]


# ---------- BLOCKED 桩

def test_gold_scoring_is_blocked_stub():
    r = s.score_against_gold()
    assert r["status"] == "NOT_SCORABLE" and r["scores"] is None and "OQ-2" in r["blocked_by"][0]


def test_real_material_is_blocked_stub():
    with pytest.raises(s.Blocked, match="OQ-3"):
        s.load_real_material("/any/path")


def test_module_is_zero_llm():
    src = Path(s.__file__).read_text("utf-8")
    for bad in ("subprocess", "import openai", "httpx", "requests", "dd_llm_client", "anthropic"):
        assert bad not in src


# ---------- #77 复核修正

def test_relaxation_off_by_default_same_year_draft_outdated_rejected(pkt):
    """锁定：不传 non_effective_files 时，同年草稿判 OUTDATED 必须被拒。"""
    from cangjie_fos.services import dd_v1_agent_result_service as ar
    d = _good(pkt)
    d["results"][0] = _res(pkt, "R1-O1", "OUTDATED", ["G003"], conf=0.7)
    rep = ar.validate_agent_output(json.dumps(d, ensure_ascii=False), SNAP, META, pkt["obligations"])
    errs = [e for r in rep.rejected if r["result"]["obligation_id"] == "R1-O1" for e in r["errors"]]
    assert "CANDIDATE_0_OUTDATED_BUT_PERIOD_MATCHES" in errs


def test_semantic_accepts_same_year_draft_outdated(pkt):
    d = _good(pkt)
    d["results"][0] = _res(pkt, "R1-O1", "OUTDATED", ["G003"], conf=0.7)
    assert not _errs(_validate(pkt, d), "R1-O1")


def test_outdated_citing_newer_year_rejected(pkt):
    d = _good(pkt)
    d["results"][3] = _res(pkt, "R4-O1", "OUTDATED", ["G004"], conf=0.6)  # 要 2022，引用 2023
    assert "CANDIDATE_0_OUTDATED_NOT_OLDER" in _errs(_validate(pkt, d), "R4-O1")


def test_outdated_citing_older_year_allowed():
    items = [{"item_id": "R9", "entity": "示例科技有限公司", "text": "提供示例科技有限公司2024年度审计报告"}]
    meta = [m for m in META if m["file_id"] == "G004"]
    p = s.build_semantic_packet(SNAP, meta, items)
    d = {"results": [_res(p, "R9-O1", "OUTDATED", ["G004"], conf=0.7)]}
    rep = s.validate_semantic(json.dumps(d, ensure_ascii=False), SNAP, meta, p).to_dict()
    assert rep["accepted"] and not rep["rejected"]


def test_missing_with_candidates_rejected_in_semantic_path(pkt):
    d = _good(pkt)
    d["results"][2] = _res(pkt, "R2-O2", "MISSING", ["G001"], reason="x")
    assert "MISSING_WITH_CANDIDATES" in _errs(_validate(pkt, d), "R2-O2")


def test_run_semantic_layers_agree_and_authoritative_marked(tmp_path, pkt):
    d = _good(pkt)
    d["results"][1] = _res(pkt, "R2-O1", "OUTDATED", ["G007"], conf=0.7)  # 同期间被取代版本
    good = tmp_path / "g.json"
    good.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    fake = tmp_path / "codex.py"
    fake.write_text(f"open('out.json','w',encoding='utf-8').write(open({str(good)!r},encoding='utf-8').read())\n",
                    encoding="utf-8")
    wd = tmp_path / "wd"
    wd.mkdir()
    rec = s.run_semantic(ad.CodexAdapter([sys.executable, str(fake)]), SNAP, META, ITEMS,
                         ad.Budget(timeout_s=20), workdir=wd)
    assert rec["authoritative_validation"] == "semantic_validation"
    ids = lambda v: sorted(r["obligation_id"] for r in v["accepted"])
    assert ids(rec["validation"]) == ids(rec["semantic_validation"]) == ["R1-O1", "R2-O1", "R2-O2", "R4-O1"]


def test_locator_matches_returned_lines(pkt):
    for ev in pkt["evidence"].values():
        for e in ev:
            lo, hi = (int(x[1:]) for x in e["locator"].split("-"))
            assert hi - lo == e["untrusted_excerpt"].count("\n")


def test_require_known_cost_fails_closed(tmp_path):
    good = tmp_path / "g.json"
    p = s.build_semantic_packet(SNAP, META, ITEMS)
    good.write_text(json.dumps(_good(p), ensure_ascii=False), encoding="utf-8")
    fake = tmp_path / "codex.py"
    fake.write_text(f"open('out.json','w',encoding='utf-8').write(open({str(good)!r},encoding='utf-8').read())\n",
                    encoding="utf-8")
    wd = tmp_path / "wd"
    wd.mkdir()
    rec = s.run_semantic(ad.CodexAdapter([sys.executable, str(fake)]), SNAP, META, ITEMS,
                         ad.Budget(timeout_s=20, require_known_cost=True), workdir=wd)
    assert rec["adapter"]["status"] == "BUDGET_EXCEEDED"
    assert rec["semantic_validation"]["mode"] == "RULE_ONLY"
