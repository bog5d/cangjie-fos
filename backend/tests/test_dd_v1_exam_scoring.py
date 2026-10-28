"""DD-V1 考场评分系统正确性 · `#85`（第一组：评分系统正确性）。

**这个文件锁死的红线**（全部来自 `#85` + 施工令「五、必须通过的测试 · 第一组」）：

1. 全部正确 ⇒ **满分**；
2. 全部错误 ⇒ **0 分**（不是 NOT_SCORABLE，也不是「理解率高就打个折」）；
3. 全部弃答 ⇒ **0 分**（冻结口径 HR-1/HR-0）；
4. 部分正确 ⇒ **相应分数**（不是非 0 即 100）；
5. 多文件缺一 ⇒ **不得**判完整正确；
6. 同名不同内容 ⇒ **不得**误判命中（只认 SHA256，不认文件名）；
7. 同内容不同路径 ⇒ **必须**按内容证据正确识别；
8. 标准答案缺失 ⇒ **阻塞**正式评分（NOT_SCORABLE + 明确阻塞）；
9. 标准答案泄漏 ⇒ **安全失败**（不进正式评分）。

★ 全部夹具为合成数据（虚构主体名、假 SHA256），**不含任何真实业务材料**。
"""
from __future__ import annotations

import json

import pytest

from cangjie_fos.services import dd_v1_exam_service as ex
from cangjie_fos.services import dd_v1_gold_service as gold_svc

# ── 合成图书馆（4 份材料）───────────────────────────────────────────────────
# F1 / F2 **文件名不同但内容不同**；F2 与 F1 同前缀，用于「同名不同内容」反例
SHA_F1 = "a" * 64      # 甲方 2024 审计报告（正确件）
SHA_F2 = "b" * 64      # 甲方 2024 审计报告（草稿，内容不同 ⇒ 同名不同内容）
SHA_F3 = "c" * 64      # 甲方 营业执照
SHA_F4 = "d" * 64      # 乙方 2023 审计报告
SHA_GHOST = "e" * 64   # 只存在于人工交付包、图书馆里没有

META = [
    {"file_id": "F1", "sha256": SHA_F1, "relative_path": "甲方/2024审计报告.pdf",
     "entity": "主体甲", "entity_basis": "AUTHORITY", "period": "2024",
     "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"},
    {"file_id": "F2", "sha256": SHA_F2, "relative_path": "甲方/2024审计报告_草稿.pdf",
     "entity": "主体甲", "entity_basis": "AUTHORITY", "period": "2024",
     "doc_type": "audit_report", "part": "正文", "version_status": "DRAFT"},
    {"file_id": "F3", "sha256": SHA_F3, "relative_path": "甲方/营业执照.pdf",
     "entity": "主体甲", "entity_basis": "AUTHORITY", "period": "CURRENT",
     "doc_type": "license", "part": "正文", "version_status": "EFFECTIVE"},
    {"file_id": "F4", "sha256": SHA_F4, "relative_path": "乙方/2023审计报告.pdf",
     "entity": "主体乙", "entity_basis": "AUTHORITY", "period": "2023",
     "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"},
]


def _gold_item(oid: str, files: list[dict], verdict: str = "MATCH") -> dict:
    return {"obligation_id": oid, "item_no": oid, "expected_verdict": verdict,
            "expected_files": files}


def _gold_manifest(items: list[dict], *, confirmed: bool = True) -> dict:
    return {
        "schema_version": gold_svc.GOLD_MANIFEST_SCHEMA,
        "gold_pack_id": "GOLD-TEST-01",
        "exam_id": "EX-TEST-01",
        "checklist": {"checklist_id": "CL-TEST", "sha256": "f" * 64, "item_count": len(items)},
        "library": {"library_id": "LIB-TEST", "fingerprint": "0" * 64, "material_count": len(META)},
        "confirmed_by": "测试员" if confirmed else "",
        "confirmed_at": "2026-10-28T20:00:00+08:00" if confirmed else "",
        "items": items,
    }


#: 标准答案：O1 单文件、O2 多文件（缺一要被抓）、O3 跨主体
GOLD_ITEMS = [
    _gold_item("O1", [{"sha256": SHA_F1, "relative_path": "人工交付包/2024年度审计报告最终版.pdf",
                        "entity": "主体甲", "period": "2024", "doc_type": "audit_report"}]),
    _gold_item("O2", [{"sha256": SHA_F1, "entity": "主体甲", "period": "2024"},
                      {"sha256": SHA_F3, "entity": "主体甲", "period": "CURRENT"}]),
    _gold_item("O3", [{"sha256": SHA_F4, "entity": "主体乙", "period": "2023"}]),
]


# ── 机器答卷构造 ────────────────────────────────────────────────────────────

def _packet() -> dict:
    """语义包（义务 + 证据 + 候选窗口读数）。"""
    obs = []
    evidence = {}
    status = {}
    for oid, dt in (("O1", "audit_report"), ("O2", "audit_report"), ("O3", "audit_report")):
        obs.append({"obligation_id": oid, "item_id": oid, "text": f"{oid} 的要求",
                    "entity": "", "entity_basis": "AUTHORITY", "period": "2024",
                    "doc_type": dt, "doc_type_unresolved": False, "doc_type_source": "RULE",
                    "required_parts": [], "split_method": "TEST"})
        evidence[oid] = [{"file_id": m["file_id"], "sha256": m["sha256"],
                          "relative_path": m["relative_path"], "entity": m["entity"],
                          "period": m["period"], "doc_type": m["doc_type"],
                          "part": m["part"], "version_status": m["version_status"],
                          "locator": "p1"} for m in META]
        status[oid] = {"candidate_cap": 20, "candidates_total": len(META),
                       "candidates_used": len(META), "candidate_truncated": False,
                       "truncated_candidate_count": 0, "candidate_cap_note": ""}
    return {"obligations": obs, "evidence": evidence, "evidence_status": status}


def _run_record(selections: dict[str, list[str]], *,
                verdicts: dict[str, str] | None = None,
                abstains: dict[str, str] | None = None) -> dict:
    """构造 run_record（semantic_validation.accepted 形状）。

    ★ 每条义务**都要**产出一行（哪怕一条都没选材料）——否则「全部弃答」这个场景
      会被伪装成「考生根本没回答」，掩盖「答了但弃答」的真实读数。
    """
    verdicts = verdicts or {}
    abstains = abstains or {}
    accepted = []
    for oid in ("O1", "O2", "O3"):
        fids = selections.get(oid, [])
        accepted.append({
            "obligation_id": oid,
            "candidate_files": [{"file_id": f, "relative_path": "", "sha256": "",
                                 "locator": "p1", "entity": "", "period": "",
                                 "match_reason": "合成夹具：内容指纹一致"} for f in fids],
            "proposed_verdict": verdicts.get(oid, "MATCH" if fids else "MISSING"),
            "confidence_or_uncertain": 0.9,
            "abstain_reason": abstains.get(oid),
            "warnings": [],
        })
    return {
        "prompt_version": "test-prompt-v1",
        "source_snapshot_id": "snap-test",
        "adapter": {"adapter_id": "codex", "vendor": "test", "model_id_or_unknown": "test-model",
                    "status": "OK"},
        "semantic_validation": {"mode": "AGENT_SUGGESTION", "degrade_reason": "",
                                "uncovered_obligations": [], "accepted": accepted,
                                "rejected": [], "warnings": []},
        "authoritative_validation": "semantic_validation",
    }


def _sheet(selections: dict[str, list[str]], *, verdicts=None, abstains=None) -> dict:
    return ex.build_answer_sheet(_run_record(selections, verdicts=verdicts, abstains=abstains),
                                  _packet(), exam_id="EX-TEST-01")


_NO_GOLD = object()   # 哨兵：区分「不传 gold」与「gold=None（明确没有标准答案）」


def _grade(selections: dict[str, list[str]], *, gold=_NO_GOLD, verdicts=None, abstains=None,
           delivered: dict[str, list[str]] | None = None):
    sheet = _sheet(selections, verdicts=verdicts, abstains=abstains)
    if delivered is not None:
        for row in sheet["obligations"]:
            row["delivered"] = [{"file_id": f, "delivered_path": f"交付/{f}",
                                 "source_sha256": "", "copy_sha256": "", "hash_match": True}
                                for f in delivered.get(row["obligation_id"], [])]
        sheet["summary"]["delivered_files"] = sum(
            len(r["delivered"]) for r in sheet["obligations"])
    idx = gold_svc.index_from_snapshot(None, META)
    manifest = _gold_manifest(GOLD_ITEMS) if gold is _NO_GOLD else gold
    return ex.grade_answer_sheet(sheet, manifest, library_index=idx,
                                 gold_provided=manifest is not None,
                                 exam_id="EX-TEST-01", min_obligations=3)


# ────────────────────────────────────────────────────────────────────────────

class TestScoringCorrectness:
    """第一组：评分系统正确性。"""

    def test_all_correct_gives_full_score(self):
        card = _grade({"O1": ["F1"], "O2": ["F1", "F3"], "O3": ["F4"]},
                      delivered={"O1": ["F1"], "O2": ["F1", "F3"], "O3": ["F4"]})
        assert card["status"] == "SCORED", card
        sc = card["scores"]
        assert sc["total_score"] == 100.0, sc
        assert sc["material_recall"] == 1.0
        assert sc["selection_precision"] == 1.0
        assert sc["complete_delivery_ratio"] == 1.0
        assert sc["miss_rate"] == 0.0
        assert sc["wrong_rate"] == 0.0

    def test_all_wrong_gives_zero(self):
        """全部选错 ⇒ **0 分**（理解率高也不打折）。"""
        card = _grade({"O1": ["F2"], "O2": ["F4"], "O3": ["F2"]},
                      delivered={"O1": ["F2"], "O2": ["F4"], "O3": ["F2"]})
        sc = card["scores"]
        assert sc["material_recall"] == 0.0
        assert sc["complete_delivery_ratio"] == 0.0
        assert sc["total_score"] == 0.0, sc
        assert card["status"] == "SCORED", "0 分仍是已评分，不是 NOT_SCORABLE"
        assert card["zero_hit_forced_zero"] is True

    def test_all_abstain_gives_zero(self):
        """全部弃答 ⇒ 0 分（不是 NOT_SCORABLE）。

        ★ 弃答时**理解率仍是 1.0**（考生确实看懂了题目，只是找不到材料）——
          这正是「理解率高也救不了 0 交付」的形状 ⇒ 分数必须由 HR-1 压成 0。
        """
        card = _grade({}, verdicts={"O1": "UNCERTAIN", "O2": "UNCERTAIN", "O3": "UNCERTAIN"},
                      abstains={"O1": "没找到", "O2": "没找到", "O3": "没找到"})
        assert card["status"] == "SCORED"
        assert card["scores"]["total_score"] == 0.0
        assert card["scores"]["question_answer_coverage"] == 0.0
        assert card["zero_delivery_forced_zero"] is True

    def test_partial_correct_gives_partial_score(self):
        card = _grade({"O1": ["F1"], "O2": ["F1"], "O3": ["F4"]},
                      delivered={"O1": ["F1"], "O2": ["F1"], "O3": ["F4"]})
        sc = card["scores"]
        assert 0 < sc["total_score"] < 100, sc
        assert sc["material_recall"] == pytest.approx(3 / 4)
        assert sc["complete_delivery_ratio"] == pytest.approx(2 / 3)

    def test_multi_file_missing_one_is_not_complete(self):
        """多文件缺一 ⇒ 不得判完整正确。"""
        card = _grade({"O1": ["F1"], "O2": ["F1"], "O3": ["F4"]},
                      delivered={"O1": ["F1"], "O2": ["F1"], "O3": ["F4"]})
        row = next(r for r in card["rows"] if r["obligation_id"] == "O2")
        assert row["outcome"] == "INCOMPLETE", row
        assert row["missed"] == ["F3"]
        assert card["scores"]["complete_delivery_ratio"] == pytest.approx(2 / 3)
        assert card["scores"]["miss_rate"] == pytest.approx(1 / 3)

    def test_same_name_different_content_not_matched(self):
        """同名不同内容 ⇒ **不得**误判命中（只认 SHA256）。"""
        items = [_gold_item("O1", [{"sha256": SHA_GHOST,
                                     "relative_path": "甲方/2024审计报告.pdf",
                                     "entity": "主体甲", "period": "2024"}])]
        manifest = _gold_manifest(items)
        idx = gold_svc.index_from_snapshot(None, META)
        resolved = gold_svc.resolve_gold_files(manifest, idx)
        f = resolved["items"][0]["expected_files"][0]
        assert f["resolution"] == "MISSING_IN_LIBRARY", f
        assert f["file_id"] == "", "不得按文件名命中"

    def test_same_content_different_path_is_matched(self):
        """同内容不同路径 ⇒ 必须按内容证据正确识别。"""
        items = [_gold_item("O1", [{"sha256": SHA_F1,
                                     "relative_path": "人工交付包/2024年度审计报告最终版.pdf",
                                     "entity": "主体甲", "period": "2024"}])]
        manifest = _gold_manifest(items)
        idx = gold_svc.index_from_snapshot(None, META)
        resolved = gold_svc.resolve_gold_files(manifest, idx)
        f = resolved["items"][0]["expected_files"][0]
        assert f["resolution"] == "RESOLVED", f
        assert f["file_id"] == "F1"

    def test_missing_gold_blocks_scoring(self):
        """标准答案缺失 ⇒ 阻塞正式评分，并写明阻塞。"""
        card = _grade({"O1": ["F1"]}, gold=None)
        assert card["status"] == "NOT_SCORABLE"
        assert card["scores"] is None
        assert card["blocked_by"], card
        assert "NOT_PROVIDED" in card["blocked_by"][0]

    def test_unconfirmed_gold_blocks_scoring(self):
        """标准答案未人工确认 ⇒ 阻塞（不得当已确认）。"""
        manifest = _gold_manifest(GOLD_ITEMS, confirmed=False)
        card = _grade({"O1": ["F1"]}, gold=manifest)
        assert card["status"] == "NOT_SCORABLE"
        assert any("NOT_CONFIRMED" in b for b in card["blocked_by"]), card

    def test_gold_leak_is_safety_failure(self):
        """标准答案泄漏 ⇒ 安全失败，不进正式评分。"""
        sheet = _sheet({"O1": ["F1"], "O2": ["F1", "F3"], "O3": ["F4"]})
        # 注入：考生答卷里出现 Gold 专有字段
        sheet["obligations"][0]["expected_files"] = [{"file_id": "F1"}]
        idx = gold_svc.index_from_snapshot(None, META)
        leak = ex.detect_gold_leak(sheet, idx)
        assert leak["leaked"] is True
        assert any(x["kind"] == "GOLD_ONLY_FIELD" for x in leak["leaks"])
        card = ex.grade_answer_sheet(sheet, _gold_manifest(GOLD_ITEMS), library_index=idx,
                                     leak_report=leak, min_obligations=3)
        assert card["status"] == "NOT_SCORABLE"
        assert any("GOLD_LEAK" in b for b in card["blocked_by"])

    def test_file_outside_library_is_leak(self):
        """考生引用了图书馆之外的文件 ⇒ 判泄漏。"""
        sheet = _sheet({"O1": ["F1"]})
        sheet["obligations"][0]["selected"].append(
            {"file_id": "GHOST-FILE", "sha256": SHA_GHOST, "relative_path": "外部.pdf",
             "locator": "p1", "match_reason": "x", "entity": "", "period": ""})
        idx = gold_svc.index_from_snapshot(None, META)
        leak = ex.detect_gold_leak(sheet, idx)
        assert leak["leaked"] is True
        assert any(x["kind"] == "FILE_OUTSIDE_LIBRARY" for x in leak["leaks"])


class TestSafetyGate:
    """安全闸独立计分：高业务分**不得**抵消。"""

    def test_wrong_entity_delivered_is_listed_and_caps_score(self):
        """★ **交付**了错主体的材料 ⇒ 进安全闸 ⇒ 封顶 59。

        ★ 口径（独立 Reviewer 增量复核）：**只有实际交付的件**才进安全闸；
          「选中但未交付」的错主体属**选材质量**问题 ⇒ **单列、不封顶**
          （否则「选错但没交」会被算成交付事故 ⇒ 成绩单虚报事故并封顶）。
        """
        sheet = _sheet({"O1": ["F1"], "O2": ["F1", "F3"], "O3": ["F4"]})
        for row in sheet["obligations"]:
            if row["obligation_id"] == "O1":
                row["selected"][0]["entity"] = "主体乙"     # 错主体
                row["delivered"] = [{"file_id": "F1", "delivered_path": "d", "source_sha256": "",
                                     "copy_sha256": "", "hash_match": True,
                                     "entity": "主体乙", "period": "2024"}]
        idx = gold_svc.index_from_snapshot(None, META)
        card = ex.grade_answer_sheet(sheet, _gold_manifest(GOLD_ITEMS), library_index=idx,
                                     min_obligations=3)
        gate = card["safety_gate"]
        assert gate["status"] == "FAIL", gate
        assert gate["by_kind"].get("WRONG_ENTITY") == 1, gate
        assert card["scores"]["total_score"] <= 59, card["scores"]
        # ★ 独立 Reviewer 第三轮残余①：**既选中又交付**的件，单列那条必须如实标
        #   delivered=True（否则成绩单会出现「闸内：交付材料…」与「单列：选中但未交付…」互相矛盾）
        _same = [m for m in gate.get("selection_mismatch_detail", [])
                 if m.get("file_id") == "F1"]
        assert _same and _same[0].get("delivered") is True, gate.get("selection_mismatch_detail")

    def test_wrong_entity_selected_but_not_delivered_does_not_cap(self):
        """★ 「选中但**未交付**」的错主体 ⇒ **单列、不封顶**（不是交付事故）。"""
        sheet = _sheet({"O1": ["F1"], "O2": ["F1", "F3"], "O3": ["F4"]})
        for row in sheet["obligations"]:
            if row["obligation_id"] == "O1":
                row["selected"][0]["entity"] = "主体乙"     # 错主体，但**没交付**
                row["delivered"] = []
        idx = gold_svc.index_from_snapshot(None, META)
        card = ex.grade_answer_sheet(sheet, _gold_manifest(GOLD_ITEMS), library_index=idx,
                                     min_obligations=3)
        gate = card["safety_gate"]
        assert gate["status"] == "PASS", gate
        assert gate["violations"] == 0, gate
        assert gate["selection_mismatches"] >= 1, gate
        assert gate["selection_mismatch_by_kind"].get("WRONG_ENTITY") == 1, gate

    def test_hash_mismatch_is_listed(self):
        sheet = _sheet({"O1": ["F1"]})
        sheet["obligations"][0]["delivered"] = [
            {"file_id": "F1", "delivered_path": "d", "source_sha256": SHA_F1,
             "copy_sha256": "f" * 64, "hash_match": False}]
        idx = gold_svc.index_from_snapshot(None, META)
        card = ex.grade_answer_sheet(sheet, _gold_manifest(GOLD_ITEMS), library_index=idx,
                                     min_obligations=3)
        assert card["safety_gate"]["by_kind"].get("HASH_MISMATCH") == 1
        assert card["safety_gate"]["status"] == "FAIL"


class TestVersionComparison:
    """版本比较：旧版无成绩 ⇒ 标「未建立可比基线」，**禁补造历史分数**。"""

    def test_no_baseline_is_marked(self):
        cmp = ex.compare_scorecards(None, {"scores": {"total_score": 80.0}})
        assert cmp["baseline_established"] is False
        assert cmp["rows"][0]["note"] == "未建立可比基线"
        md = ex.compare_markdown(cmp)
        assert "未建立可比基线" in md

    def test_same_spec_allows_comparison(self):
        old = {"scores": {"question_understanding_coverage": 0.5, "material_recall": 0.4,
                          "selection_precision": 0.6, "complete_delivery_ratio": 0.3,
                          "total_score": 45.0}, "scoring_spec_fingerprint": "fp1"}
        new = {"scores": {"question_understanding_coverage": 0.8, "material_recall": 0.7,
                          "selection_precision": 0.9, "complete_delivery_ratio": 0.6,
                          "total_score": 72.0}, "scoring_spec_fingerprint": "fp1"}
        cmp = ex.compare_scorecards(old, new)
        assert cmp["comparable"] is True
        assert cmp["same_scoring_spec"] is True
        row = next(r for r in cmp["rows"] if r["metric"] == "total_score")
        assert row["delta"] == pytest.approx(27.0)

    def test_different_spec_is_not_comparable(self):
        old = {"scores": {"total_score": 45.0}, "scoring_spec_fingerprint": "fp1"}
        new = {"scores": {"total_score": 72.0}, "scoring_spec_fingerprint": "fp2"}
        cmp = ex.compare_scorecards(old, new)
        assert cmp["same_scoring_spec"] is False
        assert "不可直接比较" in cmp["note"]


class TestScoringSpec:
    """冻结口径本身必须自洽。"""

    def test_spec_weights_sum_to_100(self):
        spec = ex.load_scoring_spec()
        assert sum(spec["weights"].values()) == 100

    def test_spec_fingerprint_is_stable(self):
        spec = ex.load_scoring_spec()
        a = ex.scoring_spec_fingerprint(spec)
        b = ex.scoring_spec_fingerprint(json.loads(json.dumps(spec)))
        assert a == b
        assert len(a) == 64


# ────────────────────────────────────────────────────────────────────────────
# ★ 回归守卫：「交了**别的主体**的材料」必须**独立单列**（安全闸不许空）
# ────────────────────────────────────────────────────────────────────────────

def test_wrong_entity_delivery_is_listed_in_safety_gate():
    """机器交的是**别的主体**的材料（根本不在标准答案清单里）⇒ 安全闸必须报。

    ★ `#85` 原文：「错主体/错年份/受限资料/未经批准外发/哈希不一致，**一律单列**」。
      旧口径只在「该文件**也在**标准答案里」时才比主体/年度 ⇒ 机器交**别的主体**时
      **直接跳过** ⇒ 闸是空的（独立 Reviewer 探针 P8 实测：`safety_gate=PASS`）。
    ★ 现在的口径：**多交**的材料也要过「义务级期望主体/年度」这道闸。
    """
    # O1 的期望材料是「主体甲 2024」；机器却交了「主体乙 2023」的 F4（不在标准答案里）
    card = _grade({"O1": ["F4"], "O2": ["F1", "F3"], "O3": ["F4"]},
                  delivered={"O1": ["F4"], "O2": ["F1", "F3"], "O3": ["F4"]})
    safety = card["safety_gate"]
    assert safety["status"] == "FAIL", safety
    assert safety["by_kind"].get("WRONG_ENTITY", 0) >= 1, safety
    # ★ 安全闸命中 ⇒ 总分封顶（业务分不得抵消安全失败）
    assert card["scores"]["total_score"] <= 59.0, card["scores"]
