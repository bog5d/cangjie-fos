"""DD-V1 **WP3／WP4**（#108 波总裁定 · 2026-10-30）：**Gold 逐件缺口 ＋ 三组成绩单**。

**波总要求（原文口径）**：
1. 保留原始 42 题、Gold manifest 和指纹，★ **不删原始 Gold、不把分母缩小、不用缺失项凑 0 分或 PASS**；
2. 先列出 **11 份缺失、4 份歧义** 的**逐件清单、原始路径/哈希及对应题号**，
   排查是**路径、文件名、哈希或材料库范围错误**；能在本机安全纠正映射的直接纠正，
   **确实缺料的单列补料清单**；
3. 成绩单同时列：**全卷 42 题覆盖情况**、**可评分题/义务的分子分母及得分**、**缺失/歧义/未评分项**；
4. ★ 所有题必须有状态；★ 不能把 NOT_SCORABLE 说成 0 分；★ **也不能因为正式评分受阻就完全没有量化结果**。

★ 全部夹具为**合成**数据。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_exam_service as ex
from cangjie_fos.services import dd_v1_gold_service as gold_svc

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_MISS = "c" * 64
SHA_OTHER = "d" * 64

META = [
    {"file_id": "F1", "sha256": SHA_A, "relative_path": "人工包/2024审计报告.pdf",
     "entity": "主体甲", "entity_basis": "AUTHORITY", "period": "2024",
     "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"},
    {"file_id": "F2", "sha256": SHA_B, "relative_path": "人工包/营业执照.pdf",
     "entity": "主体甲", "entity_basis": "AUTHORITY", "period": "CURRENT",
     "doc_type": "license", "part": "正文", "version_status": "EFFECTIVE"},
]


def _index(meta=None):
    return gold_svc.index_from_snapshot({}, meta if meta is not None else META)


def _manifest(items) -> dict:
    return {
        "schema_version": gold_svc.GOLD_MANIFEST_SCHEMA,
        "gold_pack_id": "GOLD-T",
        "exam_id": "EX-WP3-01",
        "checklist": {"checklist_id": "CL-T", "sha256": "e" * 64, "item_count": 3},
        "library": {"library_id": "LIB-T", "fingerprint": "f" * 64},
        "confirmed_by": "测试员",
        "confirmed_at": "2026-10-30T10:00:00+08:00",
        "items": items,
    }


def _item(oid, item_no, files, verdict="MATCH"):
    return {"obligation_id": oid, "item_no": item_no, "expected_verdict": verdict,
            "expected_files": files}


# ── WP3：逐件缺口分类 ───────────────────────────────────────────────────────

class TestGoldGapReport:
    def test_missing_file_is_classified_A_and_listed_per_item(self):
        """★ **真缺料** ⇒ 分类 A（补料清单）⇒ 且**逐件**带题号/路径/指纹。"""
        man = _manifest([
            _item("O1", "1-1-1", [{"sha256": SHA_A, "relative_path": "人工包/2024审计报告.pdf",
                                   "entity": "主体甲", "period": "2024"}]),
            _item("O2", "1-1-2", [{"sha256": SHA_MISS, "relative_path": "人工包/缺失件.pdf",
                                   "entity": "主体甲", "period": "2023"}]),
        ])
        rep = gold_svc.gold_gap_report(man, _index())
        assert rep["counts"]["gaps"] == 1, rep
        g = rep["gaps"][0]
        assert g["gap_class"] == "A_MISSING", g
        assert g["item_no"] == "1-1-2"
        assert g["gold_sha256"] == SHA_MISS
        assert "人工包/缺失件.pdf" in g["gold_relative_path"]
        assert "补料" in g["remedy"]

    def test_same_path_different_content_is_classified_D(self):
        """★ 同路径、不同指纹 ⇒ 分类 D（内容被替换 / Gold 记错）⇒ **给候选**。"""
        meta = [{"file_id": "F9", "sha256": SHA_OTHER, "relative_path": "人工包/2024审计报告.pdf",
                 "entity": "主体甲", "entity_basis": "AUTHORITY", "period": "2024",
                 "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"}]
        man = _manifest([
            _item("O1", "1-1-1", [{"sha256": SHA_A, "relative_path": "人工包/2024审计报告.pdf",
                                   "entity": "主体甲", "period": "2024"}]),
        ])
        rep = gold_svc.gold_gap_report(man, _index(meta))
        g = rep["gaps"][0]
        assert g["gap_class"] == "D_FINGERPRINT_MISMATCH", g
        assert g["candidates"] and g["candidates"][0]["file_id"] == "F9"

    def test_same_name_different_content_is_classified_C(self):
        """★ 同名、不同指纹 ⇒ 分类 C（文件名匹配错）⇒ 给候选。"""
        meta = [{"file_id": "F8", "sha256": SHA_OTHER, "relative_path": "别处/2024审计报告.pdf",
                 "entity": "主体甲", "entity_basis": "AUTHORITY", "period": "2024",
                 "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"}]
        man = _manifest([
            _item("O1", "1-1-1", [{"sha256": SHA_A, "relative_path": "人工包/2024审计报告.pdf",
                                   "entity": "主体甲", "period": "2024"}]),
        ])
        rep = gold_svc.gold_gap_report(man, _index(meta))
        g = rep["gaps"][0]
        assert g["gap_class"] == "C_NAME_MISMATCH", g
        assert g["candidates"] and g["candidates"][0]["file_id"] == "F8"

    def test_ambiguous_content_is_listed_with_candidates(self):
        """★ **内容歧义**（同一指纹命中多份库材料）⇒ 列出**候选 file_id**（人工指定）。"""
        meta = list(META) + [
            {"file_id": "F1B", "sha256": SHA_A, "relative_path": "人工包/2024审计报告-副本.pdf",
             "entity": "主体甲", "entity_basis": "AUTHORITY", "period": "2024",
             "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"}]
        man = _manifest([
            _item("O1", "1-1-1", [{"sha256": SHA_A, "relative_path": "人工包/2024审计报告.pdf",
                                   "entity": "主体甲", "period": "2024"}]),
        ])
        rep = gold_svc.gold_gap_report(man, _index(meta))
        assert rep["counts"]["gaps"] == 1
        g = rep["gaps"][0]
        assert g["resolution"] == "AMBIGUOUS_CONTENT", g
        assert "F1" in g["resolution_note"] and "F1B" in g["resolution_note"]

    def test_item_without_expected_files_is_F(self):
        """★ 条目**没有期望文件** ⇒ 分类 F（Gold 清单侧需人工补）⇒ **不得**算「答对」。"""
        man = _manifest([_item("O1", "1-1-1", [])])
        rep = gold_svc.gold_gap_report(man, _index())
        g = rep["gaps"][0]
        assert g["gap_class"] == "F_NEEDS_HUMAN_CONFIRM", g
        assert g["resolution"] == "NO_EXPECTED_FILES"

    def test_resolved_files_are_not_listed_as_gaps(self):
        """★ 已解析的**不列**（不制造噪声）⇒ 缺口清单只含真正待处置的。"""
        man = _manifest([
            _item("O1", "1-1-1", [{"sha256": SHA_A, "relative_path": "人工包/2024审计报告.pdf",
                                   "entity": "主体甲", "period": "2024"}]),
        ])
        rep = gold_svc.gold_gap_report(man, _index())
        assert rep["counts"]["gaps"] == 0, rep
        assert rep["counts"]["resolved"] == 1

    def test_report_never_mutates_the_manifest(self):
        """★ **不删 Gold、不改 Gold**：报告只读 ⇒ 清单逐字不变。"""
        man = _manifest([
            _item("O1", "1-1-1", [{"sha256": SHA_MISS, "relative_path": "人工包/x.pdf"}]),
        ])
        before = json.dumps(man, ensure_ascii=False, sort_keys=True)
        gold_svc.gold_gap_report(man, _index())
        assert json.dumps(man, ensure_ascii=False, sort_keys=True) == before


# ── WP4：三组成绩单 ─────────────────────────────────────────────────────────

def _sheet(rows):
    return {"obligations": rows, "delivered": [], "examinee": {"mode": "RULE_ONLY"}}


class TestThreeScoreGroups:
    def test_scorecard_has_three_groups(self):
        """★ 成绩单**同时**给三组：全卷／Gold 可评分／证据差异。"""
        man = _manifest([
            _item("O1", "1-1-1", [{"sha256": SHA_A, "relative_path": "人工包/2024审计报告.pdf",
                                   "entity": "主体甲", "period": "2024"}]),
            _item("O2", "1-1-2", [{"sha256": SHA_MISS, "relative_path": "人工包/缺.pdf"}]),
        ])
        idx = _index()
        sheet = _sheet([
            {"obligation_id": "O1", "item_id": "1-1-1", "verdict": "MATCH",
             "interpretation": {"resolved": True},
             "selected": [{"file_id": "F1", "sha256": SHA_A, "relative_path": "人工包/2024审计报告.pdf",
                           "entity": "主体甲", "period": "2024", "match_reason": "同名同期间"}],
             "delivered": [], "candidate_count": 1, "selected_count": 1},
            {"obligation_id": "O2", "item_id": "1-1-2", "verdict": "MISSING",
             "interpretation": {"resolved": True},
             "selected": [], "delivered": [], "candidate_count": 0, "selected_count": 0},
        ])
        card = ex.grade_answer_sheet(sheet, man, library_index=idx, exam_id="EX-WP3-01",
                                     exam_questions=[
                                         {"question_id": "1-1-1", "item_no": "1-1-1"},
                                         {"question_id": "1-1-2", "item_no": "1-1-2"},
                                         {"question_id": "1-1-3", "item_no": "1-1-3"}])

        # ★ 第一组：全卷（**含未处理的题**）
        cov = card["exam_coverage"]
        assert cov["questions_total"] == 3, cov
        assert cov["denominator_source"] == "LIBRARY_OBLIGATION_CONTRACT"
        assert cov["questions_processed"] == 2, cov
        assert cov["questions_correct"] == 1, cov
        assert cov["questions_unmatched"] == 1, cov
        states = {q["question_id"]: q["state"] for q in cov["questions"]}
        assert states["1-1-3"] == "UNPROCESSED", states

        # ★ 第二组：Gold 可评分（**分母只含已解析的义务**）
        gs = card["gold_scorable"]
        assert gs["scorable_obligations"] == 1, gs
        assert gs["correct"] == 1, gs
        assert gs["denominator"] == 1
        assert gs["not_included_reasons"].get("MISSING_IN_LIBRARY") == 1, gs

        # ★ 分层评分（波总裁定）：**部分缺口 ≠ 全盘不可评分** ⇒ 状态 ＝ SCORED_PARTIAL
        assert card["status"] == "SCORED_PARTIAL", card["status"]
        assert card["scores"]["total_score"] is not None
        gaps = card.get("gold_gaps") or {}
        assert gaps.get("counts", {}).get("gaps") == 1, gaps

        # ★ 第三组：证据差异（逐项）
        diff = card["evidence_diff"]
        assert len(diff) == 2, diff
        assert diff[0]["expected_files"][0]["sha256"] == SHA_A
        assert diff[0]["selected_files"][0]["file_id"] == "F1"
        assert diff[0]["correct"] is True
        assert diff[1]["expected_files"][0]["gold_relative_path"] == "人工包/缺.pdf"

    def test_unscorable_keeps_diagnostic_numbers(self):
        """★ 正式评分受阻 ⇒ **仍要有量化诊断**（不得「完全没有结果」），
        且 ★ **不得**给出 0 分（0 分是评分结论）。"""
        sheet = _sheet([
            {"obligation_id": "O1", "item_id": "1-1-1", "verdict": "MATCH",
             "interpretation": {"resolved": True},
             "selected": [{"file_id": "F1", "sha256": SHA_A}], "delivered": [],
             "candidate_count": 1, "selected_count": 1},
        ])
        card = ex.grade_answer_sheet(sheet, None, library_index=_index(),
                                     gold_provided=False, gold_state="NOT_MAPPED",
                                     gold_state_reason="没映射上")
        assert card["status"] == "NOT_SCORABLE"
        assert card["scores"] is None, "★ 不可评分时不得给分数（尤其不是 0）"
        diag = card["diagnostic"]
        assert diag["status"] == "DIAGNOSTIC_ONLY"
        assert diag["counts"]["obligations"] == 1
        assert diag["counts"]["selected_files"] == 1
        assert diag["counts"]["questions_seen"] == 1
        assert "不是评分" in diag["note"]

    def test_denominator_source_is_explicit_without_authoritative_questions(self):
        """★ 拿不到权威题单 ⇒ 分母来源**必须写明**（不得假装覆盖了全卷）。"""
        man = _manifest([
            _item("O1", "1-1-1", [{"sha256": SHA_A, "relative_path": "人工包/2024审计报告.pdf"}]),
        ])
        sheet = _sheet([
            {"obligation_id": "O1", "item_id": "1-1-1", "verdict": "MATCH",
             "interpretation": {"resolved": True},
             "selected": [{"file_id": "F1", "sha256": SHA_A}], "delivered": [],
             "candidate_count": 1, "selected_count": 1},
        ])
        card = ex.grade_answer_sheet(sheet, man, library_index=_index(), exam_id="EX-WP3-01")
        cov = card["exam_coverage"]
        assert cov["denominator_source"] == "ANSWER_SHEET_AND_GOLD_ONLY", cov
        assert "不得" in cov["note"]

    def test_zero_delivery_still_forces_zero_score(self):
        """★ **既有硬口径不得回退**：0 件交付 ⇒ 总分 0（不是 NOT_SCORABLE）。"""
        man = _manifest([
            _item("O1", "1-1-1", [{"sha256": SHA_A, "relative_path": "人工包/2024审计报告.pdf"}]),
        ])
        sheet = _sheet([
            {"obligation_id": "O1", "item_id": "1-1-1", "verdict": "MISSING",
             "interpretation": {"resolved": True},
             "selected": [], "delivered": [], "candidate_count": 0, "selected_count": 0},
        ])
        card = ex.grade_answer_sheet(sheet, man, library_index=_index(), exam_id="EX-WP3-01")
        assert card["status"] != "NOT_SCORABLE"
        assert card["scores"]["total_score"] == 0.0
        assert card["zero_delivery_forced_zero"] is True


class TestBlockingKinds:
    """★ **两类阻塞必须分开**：HARD（真不可评分）／GAPS（可分层评分）。"""

    def test_gaps_kind_is_gaps(self):
        corr = {"problems": ["GOLD_FILES_MISSING_IN_LIBRARY:11"]}
        assert gold_svc.blocking_kind(corr) == "GAPS"

    def test_fingerprint_conflict_is_hard(self):
        corr = {"problems": ["LIBRARY_FINGERPRINT_MISMATCH:abc"]}
        assert gold_svc.blocking_kind(corr) == "HARD"

    def test_no_expected_files_is_hard(self):
        corr = {"problems": ["GOLD_NO_EXPECTED_FILES:没有可比基准"]}
        assert gold_svc.blocking_kind(corr) == "HARD"

    def test_hard_conflict_still_not_scorable(self):
        """★ **硬冲突不得被「分层」稀释**：指纹冲突 ⇒ NOT_SCORABLE（不���出分）。"""
        man = _manifest([
            _item("O1", "1-1-1", [{"sha256": SHA_A, "relative_path": "人工包/2024审计报告.pdf"}]),
        ])
        man["library"]["fingerprint"] = "0" * 64   # ⇒ 与索引指纹冲突
        idx = _index()
        sheet = _sheet([
            {"obligation_id": "O1", "item_id": "1-1-1", "verdict": "MATCH",
             "interpretation": {"resolved": True},
             "selected": [{"file_id": "F1", "sha256": SHA_A}], "delivered": [],
             "candidate_count": 1, "selected_count": 1},
        ])
        card = ex.grade_answer_sheet(sheet, man, library_index=idx, exam_id="EX-WP3-01",
                                     library_fingerprint="f" * 64,
                                     checklist_sha256="e" * 64)
        assert card["status"] == "NOT_SCORABLE", card["status"]
        assert card["scores"] is None
