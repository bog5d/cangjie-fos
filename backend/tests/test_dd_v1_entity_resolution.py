"""DD-V1 WP3-1：主体识别与主体范围判定 · `#108` 实测 P0-1 / P0-2。

**这个文件锁死的红线**：

1. ★ 主体识别**不得**只靠文件夹名 —— 材料库目录是**分类目录**
   （「四川及湖南、北京子公司营业执照」这类），**不是法人级**；
2. 主体证据按强度分级：人工确认 ＞ 登记全称（文件名）＞ 登记别名（文件名）＞
   登记全称（正文）＞ 可信元数据 ＞ **认不出**；
3. ★ **认不出就认不出**（``UNRESOLVED`` ＋ 原因），**不猜**、不拿目录名凑数；
4. ★ 义务**没指名主体**时，主体范围由**考场契约的显式声明**决定
   （``SINGLE_ENTITY`` / ``GROUP``）；**未声明 ⇒ 保持不确定**；
5. ★ 「题目没写主体 ⇒ 集团所有公司都符合要求」是**错的**：
   集团范围来自**权威主体登记**＋契约里的**具体声明**；
6. ``entity_matches`` 的三态：``True`` / ``False`` / ``None``（不可判定）——
   **``None`` ≠ ``False``**（不可判定时既不得当成不符，也不得当成相符）。

★ 全部夹具为合成数据（虚构法人名）。
"""
from __future__ import annotations

import pytest

from cangjie_fos.services import dd_v1_entity_resolution_service as ers

JIA = "合成示例科技有限公司"
YI = "合成样板贸易有限公司"
#: 真实材料库里常见的**分类目录**形态（**不是法人级**）
CATEGORY_DIR = "四川及湖南、北京子公司营业执照"


ENTITIES = [
    {"entity_id": "E01", "display_name": JIA, "source_ref": "合成登记"},
    {"entity_id": "E02", "display_name": YI, "source_ref": "合成登记"},
]
ALIASES = {
    "合成示例": {"entity_id": "E01", "display_name": JIA, "basis": "ALIAS", "source": "config"},
    "合成样板": {"entity_id": "E02", "display_name": YI, "basis": "ALIAS", "source": "config"},
}


class TestMaterialEntityResolution:
    """红线 1/2/3：主体识别不能只看目录名。"""

    def test_filename_containing_registered_name(self):
        r = ers.resolve_material_entity(
            {"relative_path": f"{JIA}/1.审计报告/审计报告2024.pdf", "sha256": "a" * 64},
            ENTITIES, ALIASES)
        assert r["entity"] == JIA
        assert r["matched_by"] == "REGISTRY_DISPLAY_NAME"
        assert r["basis"] == "FACT"

    def test_alias_in_filename_is_inferred_not_fact(self):
        r = ers.resolve_material_entity(
            {"relative_path": "某分类目录/合成示例营业执照.pdf", "sha256": "b" * 64},
            ENTITIES, ALIASES)
        assert r["entity"] == JIA
        assert r["matched_by"] == "REGISTRY_ALIAS"
        assert r["basis"] == "INFERRED", "别名匹配是推断，不得当 FACT"

    def test_body_text_contains_registered_name(self):
        r = ers.resolve_material_entity(
            {"relative_path": "某分类目录/扫描件001.pdf", "sha256": "c" * 64},
            ENTITIES, ALIASES,
            body_text=f"营业执照\n{JIA}\n经营范围：合成样例。")
        assert r["entity"] == JIA
        assert r["matched_by"] == "BODY_TEXT"

    def test_trusted_metadata_field(self):
        r = ers.resolve_material_entity(
            {"relative_path": "某分类目录/扫描件002.pdf", "sha256": "d" * 64,
             "legal_entity": JIA},
            ENTITIES, ALIASES)
        assert r["entity"] == JIA
        assert r["matched_by"] == "TRUSTED_METADATA"

    def test_human_confirmed_map_wins(self):
        r = ers.resolve_material_entity(
            {"relative_path": "某分类目录/扫描件003.pdf", "sha256": "e" * 64},
            ENTITIES, ALIASES,
            confirmed_map={"e" * 64: {"entity_id": "E02", "entity": YI,
                                      "source_ref": "人工确认单 #7"}})
        assert r["entity"] == YI
        assert r["matched_by"] == "HUMAN_CONFIRMED"
        assert r["basis"] == "FACT"

    def test_category_directory_is_not_an_entity(self):
        """★ 分类目录**不得**被当成法人。"""
        r = ers.resolve_material_entity(
            {"relative_path": f"{CATEGORY_DIR}/扫描件.pdf", "sha256": "f" * 64},
            ENTITIES, ALIASES)
        assert r["matched_by"] == "UNRESOLVED"
        assert r["entity"] == ""
        assert r["basis"] == "UNKNOWN"
        assert r["unresolved_reason"], "认不出必须给出原因"

    def test_unknown_directory_stays_unresolved(self):
        r = ers.resolve_material_entity(
            {"relative_path": "某个没见过的目录/文件.pdf", "sha256": "0" * 64},
            ENTITIES, ALIASES)
        assert r["matched_by"] == "UNRESOLVED"
        assert r["entity"] == ""

    def test_declared_meta_is_kept_with_its_basis(self):
        r = ers.resolve_material_entity(
            {"relative_path": "x/y.pdf", "entity": JIA, "entity_basis": "FACT"},
            ENTITIES, ALIASES)
        assert r["entity"] == JIA
        assert r["matched_by"] == "DECLARED_META"
        assert r["basis"] == "FACT"

    def test_no_registry_means_unresolved_not_guess(self):
        r = ers.resolve_material_entity(
            {"relative_path": f"{JIA}/审计报告.pdf"}, [], {})
        assert r["matched_by"] == "UNRESOLVED"
        assert "未登记任何权威主体" in r["unresolved_reason"]


class TestObligationEntityScope:
    """红线 4/5：主体范围由**显式声明**决定，未声明 ⇒ 保留不确定。"""

    def test_named_entity_is_fact(self):
        sc = ers.resolve_obligation_entity_scope({"entity": JIA}, {"scope_mode": "GROUP"})
        assert sc["mode"] == "SINGLE"
        assert sc["entity"] == JIA
        assert sc["basis"] == "FACT"
        assert sc["source"] == "OBLIGATION_NAMED"

    def test_contract_single_entity(self):
        sc = ers.resolve_obligation_entity_scope(
            {"entity": ""}, {"scope_mode": "SINGLE_ENTITY", "entity_ids": ["E01"]})
        assert sc["mode"] == "SINGLE"
        assert sc["basis"] == "INFERRED"
        assert sc["source"] == "CONTRACT_SINGLE"

    def test_contract_group_uses_registered_members(self):
        sc = ers.resolve_obligation_entity_scope(
            {"entity": ""}, {"scope_mode": "GROUP", "group_root_id": "E01"},
            group_members=[JIA, YI])
        assert sc["mode"] == "GROUP"
        assert set(sc["entity_ids"]) == {JIA, YI}
        assert sc["source"] == "CONTRACT_GROUP"

    def test_group_without_members_stays_unresolved(self):
        sc = ers.resolve_obligation_entity_scope(
            {"entity": ""}, {"scope_mode": "GROUP", "group_root_id": "E01"}, group_members=[])
        assert sc["mode"] == "UNRESOLVED"
        assert sc["basis"] == "UNKNOWN"

    def test_unscoped_stays_unresolved(self):
        """★ 没声明 ⇒ 不可判定（**不是**「集团所有公司都算」）。"""
        sc = ers.resolve_obligation_entity_scope({"entity": ""}, {"scope_mode": "UNSCOPED"})
        assert sc["mode"] == "UNRESOLVED"
        assert sc["basis"] == "UNKNOWN"
        assert "不可判定" in sc["reason"] or "未声明" in sc["reason"]

    def test_no_contract_at_all_stays_unresolved(self):
        sc = ers.resolve_obligation_entity_scope({"entity": ""}, None)
        assert sc["mode"] == "UNRESOLVED"


class TestEntityMatchesIsThreeValued:
    """红线 6：``None`` ≠ ``False``。"""

    def test_single_match(self):
        sc = {"mode": "SINGLE", "entity": JIA}
        assert ers.entity_matches(sc, JIA) is True
        assert ers.entity_matches(sc, YI) is False

    def test_group_set_membership(self):
        sc = {"mode": "GROUP", "entity_ids": [JIA, YI]}
        assert ers.entity_matches(sc, JIA) is True
        assert ers.entity_matches(sc, "第三家") is False

    def test_unresolved_is_none_not_false(self):
        assert ers.entity_matches({"mode": "UNRESOLVED"}, JIA) is None
        assert ers.entity_matches(None, JIA) is None

    def test_empty_material_entity_is_none(self):
        assert ers.entity_matches({"mode": "SINGLE", "entity": JIA}, "") is None
