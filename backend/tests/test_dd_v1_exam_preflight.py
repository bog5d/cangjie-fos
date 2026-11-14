"""DD-V1 WP1：考场预检 —— 考卷 / 图书馆 / 标准答案 三者是否**正确关联**。

**这个文件锁死的红线**（`#85` + 施工令 WP1）：

1. 预检必须逐项给出：**考卷 / 图书馆 / 标准答案** 的「已找到 / 未找到」，
   以及**对应关系**的「已确认 / 待确认」，最后给出**是否具备正式评分条件**；
2. ★ **「未接入」≠「不存在」**：标准答案的三种未就绪状态
   （``NOT_PROVIDED`` / ``NOT_MAPPED`` / ``NOT_CONFIRMED``）**必须分开报**；
3. 未就绪时必须输出**明确的阻塞原因**（含责任人与修复动作）；
4. ★ **开考前**就要把「主体范围未声明」顶出来 —— 未指名主体的义务在多主体库上
   **必然**判「无法判定」⇒ 42 题全 UNCERTAIN、0 交付（`#108` 实测 P0-1）；
5. 标准答案**不得**落在材料目录 / 运行目录 / Git 工作树内（隔离闸）。

★ 全部夹具为合成数据。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_exam_preflight_service as pf
from cangjie_fos.services import dd_v1_gold_service as gold_svc

SHA_F1 = "a" * 64
SHA_F2 = "b" * 64

META = [
    {"file_id": "F1", "sha256": SHA_F1, "relative_path": "甲方/2024审计报告.pdf",
     "entity": "主体甲", "entity_basis": "AUTHORITY", "period": "2024",
     "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"},
    {"file_id": "F2", "sha256": SHA_F2, "relative_path": "甲方/营业执照.pdf",
     "entity": "主体甲", "entity_basis": "AUTHORITY", "period": "CURRENT",
     "doc_type": "license", "part": "正文", "version_status": "EFFECTIVE"},
]

OBLIGATIONS = [
    {"obligation_id": "O1", "entity": "", "entity_scope": "", "obligation": "2024年度审计报告"},
    {"obligation_id": "O2", "entity": "主体甲", "entity_scope": "entity_hint:主体甲",
     "obligation": "营业执照"},
]

LIBRARY_FP = pf.library_fingerprint(META)


def _contract(**over) -> dict:
    c = pf.exam_contract_template()
    c.update({
        "exam_id": "EX-TEST-01",
        "name": "合成考场",
        "institution": "Institution_XX",
        "checklist": {"checklist_id": "CL-T", "library_id": "LIB-T", "sha256": "c" * 64,
                      "item_count": 2, "institution": "Institution_XX"},
        "library": {"library_id": "LIB-T", "material_root": "", "fingerprint": LIBRARY_FP,
                    "material_count": len(META)},
        "gold": {"gold_pack_id": "GOLD-T", "manifest_path": "", "provided": False},
        "entity_scope": {"scope_mode": "GROUP", "group_root_id": "E01",
                         "entity_ids": ["E01"], "declared_by": "测试员",
                         "declared_at": "2026-10-28T20:00:00+08:00"},
    })
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(c.get(k), dict):
            c[k].update(v)
        else:
            c[k] = v
    return c


def _library() -> dict:
    return {"library_id": "LIB-T", "root_path": "/tmp/does-not-matter",
            "snapshot": {m["file_id"]: {"sha256": m["sha256"]} for m in META}}


def _gold_manifest(tmp_path: Path, *, confirmed: bool = True, fingerprint: str = "") -> Path:
    p = tmp_path / "gold_manifest.json"
    p.write_text(json.dumps({
        "schema_version": gold_svc.GOLD_MANIFEST_SCHEMA,
        "gold_pack_id": "GOLD-T",
        "exam_id": "EX-TEST-01",
        "checklist": {"checklist_id": "CL-T", "sha256": "c" * 64, "item_count": 2},
        "library": {"library_id": "LIB-T", "fingerprint": fingerprint or LIBRARY_FP,
                    "material_count": len(META)},
        "confirmed_by": "测试员" if confirmed else "",
        "confirmed_at": "2026-10-28T20:00:00+08:00" if confirmed else "",
        "items": [
            {"obligation_id": "O1", "item_no": "1",
             "expected_verdict": "MATCH",
             "expected_files": [{"sha256": SHA_F1, "relative_path": "人工包/审计报告.pdf",
                                 "entity": "主体甲", "period": "2024"}]},
            {"obligation_id": "O2", "item_no": "2",
             "expected_verdict": "MATCH",
             "expected_files": [{"sha256": SHA_F2, "entity": "主体甲", "period": "CURRENT"}]},
        ],
    }, ensure_ascii=False, indent=2), "utf-8")
    return p


def _run(contract, **kw):
    args = dict(library=_library(), meta=META, obligations=OBLIGATIONS,
                material_root=None, entities_registered=2)
    args.update(kw)
    return pf.run_preflight(contract, **args)


class TestPreflightStates:
    def test_all_ready_means_scoring_ready(self, tmp_path):
        gm = _gold_manifest(tmp_path)
        c = _contract(gold={"gold_pack_id": "GOLD-T", "manifest_path": str(gm), "provided": True})
        rep = _run(c)
        assert rep["checklist"]["state"] == "FOUND"
        assert rep["library"]["state"] == "FOUND"
        assert rep["gold"]["state"] == "FOUND"
        assert rep["gold"]["correspondence"]["state"] == "CONFIRMED"
        assert rep["scoring_ready"] is True
        assert rep["status"] == "READY_FOR_FORMAL_SCORING"
        assert rep["blockers"] == []

    def test_gold_not_provided_is_not_said_to_be_nonexistent(self, tmp_path):
        """★ 「未提供」≠「不存在」。"""
        c = _contract(gold={"provided": False, "manifest_path": ""})
        rep = _run(c)
        assert rep["gold"]["state"] == "NOT_PROVIDED"
        assert rep["scoring_ready"] is False
        assert rep["terms"]["not_provided"]
        codes = [b["code"] for b in rep["blockers"]]
        assert "TEST_BLOCKED_GOLD_NOT_PROVIDED" in codes
        # 文案必须明说「不等于历史上没有标准答案」
        assert "不等于历史上没有标准答案" in rep["gold"]["detail"]
        assert not rep["terms"]["not_mapped"], "未提供 ≠ 未映射"

    def test_gold_not_mapped_is_distinct_from_not_provided(self, tmp_path):
        """★ 「已拿到但没映射」是**另一种**状态。"""
        c = _contract(gold={"provided": True, "manifest_path": str(tmp_path / "nope.json")})
        rep = _run(c)
        assert rep["gold"]["state"] == "NOT_PROVIDED"
        assert "GOLD_MANIFEST_FILE_MISSING" in rep["gold"]["problems"]

    def test_unconfirmed_gold_blocks(self, tmp_path):
        gm = _gold_manifest(tmp_path, confirmed=False)
        c = _contract(gold={"provided": True, "manifest_path": str(gm)})
        rep = _run(c)
        assert rep["gold"]["state"] == "NOT_CONFIRMED"
        assert rep["terms"]["not_confirmed"]
        codes = [b["code"] for b in rep["blockers"]]
        assert "TEST_BLOCKED_GOLD_NOT_CONFIRMED" in codes

    def test_library_fingerprint_conflict_is_broken(self, tmp_path):
        gm = _gold_manifest(tmp_path, fingerprint="9" * 64)
        c = _contract(gold={"provided": True, "manifest_path": str(gm)})
        rep = _run(c)
        assert rep["gold"]["state"] == "BROKEN"
        codes = [b["code"] for b in rep["blockers"]]
        assert "TEST_BLOCKED_GOLD_BROKEN" in codes

    def test_blockers_carry_owner_and_remedy(self, tmp_path):
        c = _contract(gold={"provided": False})
        rep = _run(c)
        for b in rep["blockers"]:
            assert b.get("owner"), b
            assert b.get("remedy"), b

    def test_markdown_mentions_every_required_item(self, tmp_path):
        gm = _gold_manifest(tmp_path)
        c = _contract(gold={"provided": True, "manifest_path": str(gm)})
        md = pf.preflight_markdown(_run(c))
        for token in ("考卷", "图书馆", "标准答案", "对应关系", "主体范围",
                      "是否具备正式评分条件"):
            assert token in md, token


class TestEntityScopeIsCaughtBeforeTheExam:
    """★ 开考前的 Gate：主体范围未声明 ⇒ 必然全盘 UNCERTAIN，必须提前拦。"""

    def test_unscoped_multi_entity_library_is_blocked(self):
        c = _contract(entity_scope={"scope_mode": "UNSCOPED", "group_root_id": "",
                                    "entity_ids": [], "declared_by": "", "declared_at": ""})
        rep = _run(c, entities_registered=3)
        assert rep["entity_scope"]["state"] == "UNDECLARED"
        assert rep["entity_scope"]["unnamed_obligations"] == 1
        codes = [b["code"] for b in rep["blockers"]]
        assert "ENTITY_SCOPE_UNDECLARED" in codes
        assert rep["scoring_ready"] is False

    def test_declared_group_scope_passes(self):
        rep = _run(_contract(), entities_registered=3)
        assert rep["entity_scope"]["state"] == "DECLARED"
        codes = [b["code"] for b in rep["blockers"]]
        assert "ENTITY_SCOPE_UNDECLARED" not in codes


class TestContractValidation:
    def test_bad_schema_rejected(self):
        with pytest.raises(pf.ExamContractError):
            pf.validate_exam_contract({"schema_version": "nope", "exam_id": "x",
                                       "checklist": {}, "library": {}, "gold": {}})

    def test_group_scope_requires_root(self):
        c = pf.exam_contract_template()
        c["entity_scope"] = {"scope_mode": "GROUP", "group_root_id": ""}
        with pytest.raises(pf.ExamContractError):
            pf.validate_exam_contract(c)

    def test_template_is_valid(self):
        c = pf.exam_contract_template()
        c["exam_id"] = "EX-1"
        pf.validate_exam_contract(c)


class TestGoldIsolation:
    def test_gold_inside_material_dir_is_rejected(self, tmp_path):
        mat = tmp_path / "material"
        mat.mkdir()
        gm = mat / "gold_manifest.json"
        gm.write_text(json.dumps({"schema_version": gold_svc.GOLD_MANIFEST_SCHEMA,
                                   "gold_pack_id": "G", "items": []}), "utf-8")
        c = _contract(gold={"provided": True, "manifest_path": str(gm)})
        rep = _run(c, forbidden_dirs=(mat,))
        assert rep["gold"]["state"] == "BROKEN"
        assert any("GOLD_NOT_ISOLATED" in p for p in rep["gold"]["problems"])
