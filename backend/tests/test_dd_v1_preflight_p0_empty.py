"""DD-V1 **P0-1**（#108 刘江 2026-10-30 实测）：**空库假 READY** 的负例回归。

**缺陷形态（实测原文）**：材料库 0 份、考卷 0 条义务、标准答案 0 份映射时，
``preflight`` 返回 ``READY_FOR_FORMAL_SCORING``（"具备正式评分条件：是"）⇒ **错误放行**。

**根因（代码级）**：``_check_checklist`` / ``_check_library`` / ``_check_gold`` 三处
**只判「在不在」**（``state="FOUND"``），**不判「空不空」** ⇒ 三处都 FOUND ⇒ ready=True。

**本文件锁死的红线**（施工令 WP1）：

1. ★ **任何不具备正式评分条件的情况，都不得返回 ``READY_FOR_FORMAL_SCORING``**；
2. ★ 九类异常逐条可判：图书馆未构建／0 份材料／0 条义务／题目数为 0／
   Gold 清单为空／Gold 期望文件为 0／Gold 指纹不一致／Gold 文件不存在／Gold 内容歧义；
3. ★ **三档能力必须分开报**：能继续**工程测试** / 能进行**部分业务诊断** / 能**正式评分**
   ⇒ 预检不再只有一个「是／否」布尔；
4. ★ **状态不得把责任指错地方**：库/考卷为空时，状态不能写成「Gold 的问题」。

★ 全部夹具为**合成**数据；★ 本文件**只读**被测代码，不写任何真实业务材料。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_exam_preflight_service as pf
from cangjie_fos.services import dd_v1_gold_service as gold_svc

SHA_F1 = "a" * 64
SHA_F2 = "b" * 64
SHA_MISSING = "c" * 64

META_OK = [
    {"file_id": "F1", "sha256": SHA_F1, "relative_path": "甲方/2024审计报告.pdf",
     "entity": "主体甲", "entity_basis": "AUTHORITY", "period": "2024",
     "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"},
    {"file_id": "F2", "sha256": SHA_F2, "relative_path": "甲方/营业执照.pdf",
     "entity": "主体甲", "entity_basis": "AUTHORITY", "period": "CURRENT",
     "doc_type": "license", "part": "正文", "version_status": "EFFECTIVE"},
]

OBLIGATIONS_OK = [
    {"obligation_id": "O1", "entity": "", "entity_scope": "", "obligation": "2024年度审计报告"},
    {"obligation_id": "O2", "entity": "主体甲", "entity_scope": "entity_hint:主体甲",
     "obligation": "营业执照"},
]

LIBRARY_FP = pf.library_fingerprint(META_OK)


def _contract(**over) -> dict:
    c = pf.exam_contract_template()
    c.update({
        "exam_id": "EX-P0-01",
        "name": "合成考场（空库负例）",
        "institution": "Institution_XX",
        "checklist": {"checklist_id": "CL-T", "library_id": "LIB-T", "sha256": "c" * 64,
                      "item_count": 42, "institution": "Institution_XX"},
        "library": {"library_id": "LIB-T", "material_root": "", "fingerprint": LIBRARY_FP,
                    "material_count": len(META_OK)},
        "gold": {"gold_pack_id": "GOLD-T", "manifest_path": "", "provided": False},
        "entity_scope": {"scope_mode": "GROUP", "group_root_id": "E01",
                         "entity_ids": ["E01"], "declared_by": "测试员",
                         "declared_at": "2026-10-30T10:00:00+08:00"},
    })
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(c.get(k), dict):
            c[k].update(v)
        else:
            c[k] = v
    return c


def _library(meta=None) -> dict:
    meta = META_OK if meta is None else meta
    return {"library_id": "LIB-T", "root_path": "/tmp/does-not-matter",
            "snapshot": {m["file_id"]: {"sha256": m["sha256"]} for m in meta}}


def _gold_manifest(tmp_path: Path, *, expected: bool = True,
                   sha: str = SHA_F1, confirmed: bool = True,
                   confirmed_by_item: bool = False,
                   fingerprint: str = "") -> Path:
    """写一份标准答案清单。

    ``expected=False`` ⇒ 复刻刘江实测的那一档：**``expected_files`` 全为空**。
    """
    p = tmp_path / "gold_manifest.json"
    items = [
        {"obligation_id": "O1", "item_no": "1", "expected_verdict": "MATCH",
         "expected_files": ([{"sha256": sha, "relative_path": "人工包/审计报告.pdf",
                              "entity": "主体甲", "period": "2024"}] if expected else []),
         **({} if confirmed_by_item else {})},
        {"obligation_id": "O2", "item_no": "2", "expected_verdict": "MATCH",
         "expected_files": ([{"sha256": SHA_F2, "entity": "主体甲", "period": "CURRENT"}]
                            if expected else [])},
    ]
    if confirmed_by_item:
        for it in items:
            it["confirmed_by"] = "测试员"
            it["confirmed_at"] = "2026-10-30T10:00:00+08:00"
    p.write_text(json.dumps({
        "schema_version": gold_svc.GOLD_MANIFEST_SCHEMA,
        "gold_pack_id": "GOLD-T",
        "exam_id": "EX-P0-01",
        "checklist": {"checklist_id": "CL-T", "sha256": "c" * 64, "item_count": 42},
        "library": {"library_id": "LIB-T", "fingerprint": fingerprint or LIBRARY_FP,
                    "material_count": len(META_OK)},
        "confirmed_by": "测试员" if confirmed else "",
        "confirmed_at": "2026-10-30T10:00:00+08:00" if confirmed else "",
        "items": items,
    }, ensure_ascii=False, indent=2), "utf-8")
    return p


_UNSET = object()


def _run(contract, *, library=_UNSET, meta=_UNSET, obligations=_UNSET, entities=2):
    """★ 用哨兵值区分「没传」与「传了 None」——★ `library=None`（未登记）必须能被传进去。"""
    return pf.run_preflight(
        contract,
        library=_library() if library is _UNSET else library,
        meta=META_OK if meta is _UNSET else meta,
        obligations=OBLIGATIONS_OK if obligations is _UNSET else obligations,
        material_root=None,
        entities_registered=entities,
    )


# ── ① 刘江实测的那一档：空库 ＋ 0 义务 ＋ 0 映射 ────────────────────────────

class TestEmptyLibraryNeverReady:
    def test_p0_1_repro_is_not_ready(self, tmp_path):
        """★ 刘江实测的**同一组合**：0 份材料 ＋ 0 条义务 ＋ Gold 无期望文件。

        ⇒ **不得**返回 ``READY_FOR_FORMAL_SCORING``；⇒ **不得** ``scoring_ready=True``。
        """
        gm = _gold_manifest(tmp_path, expected=False)
        c = _contract(gold={"gold_pack_id": "GOLD-T", "manifest_path": str(gm), "provided": True})
        rep = _run(c, library=_library(meta=[]), meta=[], obligations=[])

        assert rep["status"] != "READY_FOR_FORMAL_SCORING", rep
        assert rep["scoring_ready"] is False, rep
        assert "READY_FOR_FORMAL_SCORING" not in rep["blocked_by"]

    def test_p0_1_repro_blocks_each_cause(self, tmp_path):
        """★ 三条**空**事实必须各自成为阻塞项（不是合并成一句）。"""
        gm = _gold_manifest(tmp_path, expected=False)
        c = _contract(gold={"gold_pack_id": "GOLD-T", "manifest_path": str(gm), "provided": True})
        rep = _run(c, library=_library(meta=[]), meta=[], obligations=[])

        codes = set(rep["blocked_by"])
        assert "LIBRARY_EMPTY" in codes, rep["blocked_by"]
        assert "CHECKLIST_NO_OBLIGATIONS" in codes, rep["blocked_by"]
        assert "GOLD_NO_EXPECTED_FILES" in codes, rep["blocked_by"]

    def test_p0_1_status_does_not_blame_gold_for_empty_library(self, tmp_path):
        """★ **责任不指错地方**：库/考卷为空时，状态**不得**写成 Gold 的问题。

        （否则排查会去找 Gold，而真因是「库是空的」。）
        """
        gm = _gold_manifest(tmp_path, expected=False)
        c = _contract(gold={"gold_pack_id": "GOLD-T", "manifest_path": str(gm), "provided": True})
        rep = _run(c, library=_library(meta=[]), meta=[], obligations=[])

        assert rep["status"] == "TEST_BLOCKED_EXAM_INPUT_EMPTY", rep["status"]
        assert not rep["status"].startswith("TEST_BLOCKED_GOLD_"), rep["status"]

    def test_p0_1_capability_tier_is_engineering_only(self, tmp_path):
        """★ 空考场 ⇒ 只能做**工程测试**（合成数据），**不得**说能诊断/能评分。"""
        gm = _gold_manifest(tmp_path, expected=False)
        c = _contract(gold={"gold_pack_id": "GOLD-T", "manifest_path": str(gm), "provided": True})
        rep = _run(c, library=_library(meta=[]), meta=[], obligations=[])

        cap = rep["capability"]
        assert cap["tier"] == "ENGINEERING", cap
        assert cap["can_run_engineering_tests"] is True
        assert cap["can_run_business_diagnostic"] is False
        assert cap["can_score_formally"] is False


# ── ② 九类异常逐条 ───────────────────────────────────────────────────────────

class TestNineAbnormalities:
    def test_library_not_registered(self):
        c = _contract()
        rep = _run(c, library=None)
        assert rep["status"] != "READY_FOR_FORMAL_SCORING"
        assert "LIBRARY_NOT_REGISTERED" in rep["blocked_by"]

    def test_library_zero_materials(self):
        c = _contract()
        rep = _run(c, library=_library(meta=[]), meta=[])
        assert "LIBRARY_EMPTY" in rep["blocked_by"]
        assert rep["scoring_ready"] is False

    def test_checklist_zero_obligations(self):
        c = _contract()
        rep = _run(c, obligations=[])
        assert "CHECKLIST_NO_OBLIGATIONS" in rep["blocked_by"]
        assert rep["scoring_ready"] is False

    def test_checklist_item_count_zero(self):
        c = _contract(checklist={"item_count": 0})
        rep = _run(c)
        assert "CHECKLIST_ITEM_COUNT_ZERO" in rep["blocked_by"]
        assert rep["scoring_ready"] is False

    def test_gold_manifest_empty_items(self, tmp_path):
        """★ Gold 清单**条目为空** ⇒ 无可评分对象。"""
        p = tmp_path / "gold_empty.json"
        p.write_text(json.dumps({
            "schema_version": gold_svc.GOLD_MANIFEST_SCHEMA,
            "gold_pack_id": "GOLD-T", "exam_id": "EX-P0-01",
            "checklist": {"checklist_id": "CL-T", "sha256": "c" * 64, "item_count": 42},
            "library": {"library_id": "LIB-T", "fingerprint": LIBRARY_FP},
            "confirmed_by": "测试员", "confirmed_at": "2026-10-30T10:00:00+08:00",
            "items": [],
        }, ensure_ascii=False), "utf-8")
        c = _contract(gold={"provided": True, "manifest_path": str(p)})
        rep = _run(c)
        assert rep["status"] != "READY_FOR_FORMAL_SCORING"
        assert "GOLD_NO_OBLIGATIONS" in rep["blocked_by"]

    def test_gold_expected_files_zero(self, tmp_path):
        """★ 刘江实测那一档：**期望文件为 0** ⇒ 没有可比基准（分母为 0）。"""
        gm = _gold_manifest(tmp_path, expected=False)
        c = _contract(gold={"provided": True, "manifest_path": str(gm)})
        rep = _run(c)
        assert "GOLD_NO_EXPECTED_FILES" in rep["blocked_by"]
        assert rep["scoring_ready"] is False

    def test_gold_fingerprint_mismatch(self, tmp_path):
        """★ Gold 记的图书馆指纹与当前快照不一致 ⇒ BROKEN。"""
        gm = _gold_manifest(tmp_path, fingerprint="d" * 64)
        c = _contract(gold={"provided": True, "manifest_path": str(gm)})
        rep = _run(c)
        assert rep["status"] == "TEST_BLOCKED_GOLD_BROKEN", rep["status"]
        assert rep["scoring_ready"] is False

    def test_gold_file_missing(self, tmp_path):
        """★ Gold 清单文件**不存在** ⇒ 未接入（≠「历史上没有标准答案」）。"""
        c = _contract(gold={"provided": True,
                            "manifest_path": str(tmp_path / "nope.json")})
        rep = _run(c)
        assert rep["status"] == "TEST_BLOCKED_GOLD_NOT_PROVIDED", rep["status"]
        assert rep["scoring_ready"] is False

    def test_gold_ambiguous_content(self, tmp_path):
        """★ 同一内容指纹命中多份库材料 ⇒ 歧义 ⇒ 必须拦（且不得算「答对」）。"""
        meta = list(META_OK) + [
            {"file_id": "F1B", "sha256": SHA_F1, "relative_path": "甲方/2024审计报告-副本.pdf",
             "entity": "主体甲", "entity_basis": "AUTHORITY", "period": "2024",
             "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"}]
        gm = _gold_manifest(tmp_path)
        c = _contract(gold={"provided": True, "manifest_path": str(gm)})
        rep = _run(c, library=_library(meta=meta), meta=meta)
        assert "GOLD_FILES_AMBIGUOUS_CONTENT" in rep["blocked_by"]
        assert rep["scoring_ready"] is False


# ── ③ 三档能力 ───────────────────────────────────────────────────────────────

class TestCapabilityTiers:
    def test_formal_scoring_tier_when_all_ready(self, tmp_path):
        gm = _gold_manifest(tmp_path)
        c = _contract(gold={"provided": True, "manifest_path": str(gm)})
        rep = _run(c)
        assert rep["status"] == "READY_FOR_FORMAL_SCORING", rep["status"]
        cap = rep["capability"]
        assert cap["tier"] == "FORMAL_SCORING"
        assert cap["can_score_formally"] is True
        assert cap["can_run_business_diagnostic"] is True

    def test_diagnostic_tier_when_only_gold_missing(self, tmp_path):
        """★ 有料 ＋ 有义务 ＋ Gold 缺人工确认 ⇒ **可以诊断**，**不得**能正式评分。"""
        gm = _gold_manifest(tmp_path, confirmed=False)
        c = _contract(gold={"provided": True, "manifest_path": str(gm)})
        rep = _run(c)
        cap = rep["capability"]
        assert cap["tier"] == "DIAGNOSTIC", cap
        assert cap["can_run_business_diagnostic"] is True
        assert cap["can_score_formally"] is False
        assert rep["status"] == "TEST_BLOCKED_GOLD_NOT_CONFIRMED"

    def test_markdown_shows_capability(self, tmp_path):
        gm = _gold_manifest(tmp_path, expected=False)
        c = _contract(gold={"provided": True, "manifest_path": str(gm)})
        rep = _run(c, library=_library(meta=[]), meta=[], obligations=[])
        md = pf.preflight_markdown(rep)
        assert "当前档位" in md
        assert "ENGINEERING" in md
        assert "正式评分：不可" in md
