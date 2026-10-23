"""cangjie-fos#71 R2-WP1 · 期间语义四态 单元测试（纯函数、零 IO、零模型、零费用）。

覆盖 WP1 派工本对期间语义的硬要求：

- 四种期间语义各能判出来：明确年度 / 相对期间 / 当前有效 / 期间未知；
- **依据不足 ⇒ UNVERIFIABLE**：既不升格 MATCHED，也不判成「不满足／缺失」；
- 相对期间**必须**有可验证的截止日期（锚点）才能展开；
  锚点只认显式配置 / 清单声明 / 材料自身年度 —— **禁止**拿当前系统时间当隐式基准；
- 六态阶梯与候选状态枚举**不扩**（本模块只给「期间维度」的结论，不动别处的枚举）；
- 10 类材料类型**唯一权威**仍在 requirement service ⇒ 本模块不得出现第二套类型表。

★ 全部输入都是**合成字面**，不含任何真实材料 / 个人信息 / 密钥。
"""
from __future__ import annotations

import inspect

import pytest

from cangjie_fos.services import dd_v1_period_service as ps


# ═══════════════════════════════════════════════════════════════════════
# 1. 四态解析
# ═══════════════════════════════════════════════════════════════════════


def test_explicit_single_year():
    spec = ps.parse_period_spec("请提供2024年度审计报告")
    assert spec["kind"] == "EXPLICIT"
    assert spec["years"] == [2024]
    assert spec["basis"] == ps.FACT


def test_explicit_year_range():
    spec = ps.parse_period_spec("请提供2022年至2024年审计年报")
    assert spec["kind"] == "EXPLICIT"
    assert spec["years"] == [2022, 2023, 2024]


def test_explicit_scattered_years_are_inferred():
    spec = ps.parse_period_spec("请提供2022年与2024年审计报告")
    assert spec["kind"] == "EXPLICIT"
    assert spec["years"] == [2022, 2023, 2024]
    assert spec["basis"] == ps.INFERRED


def test_relative_years_is_relative_and_unresolved_without_anchor():
    spec = ps.parse_period_spec("请提供近三年的审计报告")
    assert spec["kind"] == "RELATIVE"
    assert spec["relative"] == {"span": 3, "unit": "YEAR", "mode": "WINDOW"}
    assert spec["resolved"] is False
    assert spec["basis"] == "relative_unresolved"


def test_relative_previous_year_is_backward_one_year():
    for text in ("请提供上一年度审计报告", "请提供去年的审计报告", "请提供上年度审计报告"):
        spec = ps.parse_period_spec(text)
        assert spec["kind"] == "RELATIVE", text
        assert spec["relative"] == {"span": 1, "unit": "YEAR", "mode": "PREVIOUS"}, text
        assert spec["resolved"] is False


def test_relative_current_year_is_forward_one_year():
    for text in ("请提供本年度财务报表", "请提供今年的财务报表"):
        spec = ps.parse_period_spec(text)
        assert spec["kind"] == "RELATIVE", text
        assert spec["relative"] == {"span": 1, "unit": "YEAR", "mode": "CURRENT"}, text


def test_relative_twelve_months_is_month_unit():
    spec = ps.parse_period_spec("请提供最近十二个月的财务情况")
    assert spec["kind"] == "RELATIVE"
    assert spec["relative"] == {"span": 12, "unit": "MONTH", "mode": "WINDOW"}
    assert spec["resolved"] is False


def test_relative_period_unit_cannot_be_converted():
    spec = ps.parse_period_spec("请提供最近一期的财务情况")
    assert spec["kind"] == "RELATIVE"
    assert spec["relative"]["unit"] == "PERIOD"
    assert spec["resolved"] is False
    assert spec["basis"] == "unresolved"


def test_current_doc_type_never_inherits_segment_year():
    """★ R1 已落地的 CURRENT 优先语义：执照/章程类**不继承**段落年份。"""
    spec = ps.parse_period_spec("请提供2024年度营业执照", current_doc_type=True)
    assert spec["kind"] == "CURRENT"
    assert spec["years"] == []


def test_current_literal_is_latest_semantics():
    spec = ps.parse_period_spec("请提供最新审计报告")
    assert spec["kind"] == "CURRENT"
    assert spec["latest"] is True


def test_unknown_period_when_text_mentions_no_period():
    spec = ps.parse_period_spec("营业执照正、副本复印件")
    assert spec["kind"] == "UNKNOWN"
    assert spec["basis"] == ps.UNKNOWN


def test_period_kinds_are_closed():
    assert ps.PERIOD_KINDS == ("EXPLICIT", "RELATIVE", "CURRENT", "UNKNOWN")


# ═══════════════════════════════════════════════════════════════════════
# 2. 锚点：只认可验证来源，禁系统时间
# ═══════════════════════════════════════════════════════════════════════


def test_anchor_from_explicit_config():
    anchor = ps.resolve_anchor(config_anchor={"date": "2024-12-31"})
    assert anchor["source"] == "EXPLICIT_CONFIG"
    assert anchor["year"] == 2024
    assert anchor["date"] == "2024-12-31"


def test_anchor_from_checklist_declaration():
    spec = ps.parse_period_spec("请提供近三年审计报告（报告期截至2024-06-30）")
    assert spec["declared_anchor"]["source"] == "CHECKLIST_DECLARATION"
    assert spec["declared_anchor"]["year"] == 2024
    assert spec["declared_anchor"]["date"] == "2024-06-30"


def test_anchor_from_material_own_year():
    anchor = ps.resolve_anchor(material_years=["2019", "2021", "2020"])
    assert anchor["source"] == "MATERIAL_DATE"
    assert anchor["year"] == 2021


def test_anchor_priority_is_config_then_declaration_then_material():
    anchor = ps.resolve_anchor(
        config_anchor={"year": 2018},
        declared_anchor={"year": 2017, "source": "CHECKLIST_DECLARATION"},
        material_years=["2019"])
    assert anchor["source"] == "EXPLICIT_CONFIG"
    assert anchor["year"] == 2018
    anchor2 = ps.resolve_anchor(
        declared_anchor={"year": 2017, "source": "CHECKLIST_DECLARATION"},
        material_years=["2019"])
    assert anchor2["source"] == "CHECKLIST_DECLARATION"
    assert anchor2["year"] == 2017


def test_no_anchor_at_all_is_none_not_system_time():
    assert ps.resolve_anchor() is None
    assert ps.resolve_anchor(material_years=[]) is None


def test_relative_period_expands_with_anchor():
    spec = ps.build_period_spec("请提供近三年的审计报告", config_anchor={"year": 2024})
    assert spec["resolved"] is True
    assert spec["years"] == [2022, 2023, 2024]
    assert spec["anchor"]["source"] == "EXPLICIT_CONFIG"


def test_previous_year_expands_with_anchor():
    spec = ps.build_period_spec("请提供上一年度审计报告", config_anchor={"year": 2024})
    assert spec["resolved"] is True
    assert spec["years"] == [2023]


def test_current_year_expands_with_anchor():
    spec = ps.build_period_spec("请提供本年度财务报表", config_anchor={"year": 2024})
    assert spec["resolved"] is True
    assert spec["years"] == [2024]


def test_twelve_months_expands_with_date_anchor():
    spec = ps.build_period_spec("请提供最近十二个月的财务情况",
                                config_anchor={"date": "2024-12-31"})
    assert spec["resolved"] is True
    assert spec["years"] == [2024]


def test_month_span_needs_a_date_anchor_not_only_a_year():
    """★ 只有年份定位不了「N 个月」窗口 ⇒ 保持未锚定（不猜）。"""
    spec = ps.build_period_spec("请提供最近三个月的财务情况", config_anchor={"year": 2024})
    assert spec["resolved"] is False
    assert spec["years"] == []


def test_relative_period_uses_material_year_when_no_other_source():
    spec = ps.build_period_spec("请提供近三年的审计报告", material_years=["2019"])
    assert spec["anchor"]["source"] == "MATERIAL_DATE"
    assert spec["years"] == [2017, 2018, 2019]


def test_relative_period_never_follows_the_system_clock():
    """★ 判别力：材料是 2019 年的 ⇒ 窗口必须是 2017-2019，**不是**运行当年的窗口。"""
    spec = ps.build_period_spec("请提供近三年的审计报告", material_years=["2019"])
    assert spec["years"] == [2017, 2018, 2019]
    import datetime
    this_year = datetime.date.today().year
    assert this_year not in spec["years"], "相对期间不得以系统时间为基准"


def test_module_contains_no_system_clock_call():
    ps.assert_no_system_clock()


# ═══════════════════════════════════════════════════════════════════════
# 3. 兼容判定：MATCH / MISMATCH / UNVERIFIABLE / NOT_A_CONSTRAINT
# ═══════════════════════════════════════════════════════════════════════


def _spec_explicit(year=2024):
    return ps.parse_period_spec("请提供%d年度审计报告" % year)


def test_explicit_matches_same_year():
    r = ps.compatibility(_spec_explicit(), "2024")
    assert r["status"] == "MATCH"
    assert r["abstain_reason"] is None


def test_explicit_mismatches_other_year():
    r = ps.compatibility(_spec_explicit(), "2023")
    assert r["status"] == "MISMATCH"
    assert r["abstain_reason"] is None


def test_explicit_with_material_without_year_is_unverifiable():
    r = ps.compatibility(_spec_explicit(), "")
    assert r["status"] == "UNVERIFIABLE"
    assert r["abstain_reason"]


def test_explicit_with_current_material_is_mismatch():
    r = ps.compatibility(_spec_explicit(), "CURRENT")
    assert r["status"] == "MISMATCH"


def test_relative_resolved_matches_inside_window():
    spec = ps.build_period_spec("请提供近三年的审计报告", config_anchor={"year": 2024})
    r = ps.compatibility(spec, "2023")
    assert r["status"] == "MATCH"


def test_relative_resolved_mismatches_outside_window():
    spec = ps.build_period_spec("请提供近三年的审计报告", config_anchor={"year": 2024})
    r = ps.compatibility(spec, "2020")
    assert r["status"] == "MISMATCH"


def test_relative_unresolved_is_unverifiable_with_abstain_reason():
    spec = ps.build_period_spec("请提供近三年的审计报告")
    r = ps.compatibility(spec, "2024")
    assert r["status"] == "UNVERIFIABLE"
    assert r["abstain_reason"]
    assert "候选" not in r["abstain_reason"]


def test_relative_unresolved_never_mismatch_or_match():
    spec = ps.build_period_spec("请提供上一年度审计报告")
    for mp in ("2024", "2023", "CURRENT", ""):
        r = ps.compatibility(spec, mp)
        assert r["status"] == "UNVERIFIABLE", mp


def test_current_doc_type_matches_current_material():
    spec = ps.parse_period_spec("请提供营业执照", current_doc_type=True)
    r = ps.compatibility(spec, "CURRENT")
    assert r["status"] == "MATCH"


def test_current_doc_type_matches_dated_copy():
    """★ 无年度口径类：材料自带年份**不构成**年度冲突（否则是假拒绝）。"""
    spec = ps.parse_period_spec("请提供营业执照", current_doc_type=True)
    r = ps.compatibility(spec, "2024")
    assert r["status"] == "MATCH"


def test_latest_literal_picks_the_newest_in_pool():
    spec = ps.parse_period_spec("请提供最新审计报告")
    r = ps.compatibility(spec, "2024", pool_periods=["2022", "2024"])
    assert r["status"] == "MATCH"
    r2 = ps.compatibility(spec, "2022", pool_periods=["2022", "2024"])
    assert r2["status"] == "MISMATCH"


def test_unknown_obligation_period_is_not_a_constraint():
    spec = ps.parse_period_spec("营业执照正、副本复印件")
    r = ps.compatibility(spec, "2024")
    assert r["status"] == "NOT_A_CONSTRAINT"
    assert r["abstain_reason"] is None


def test_compat_statuses_are_closed():
    assert ps.COMPAT_STATUSES == ("MATCH", "MISMATCH", "UNVERIFIABLE", "NOT_A_CONSTRAINT")


def test_anchor_sources_are_closed_and_exclude_system_time():
    assert ps.ANCHOR_SOURCES == ("EXPLICIT_CONFIG", "CHECKLIST_DECLARATION", "MATERIAL_DATE")


# ═══════════════════════════════════════════════════════════════════════
# 4. 边界自证：不得出现第二套类型表 / 不得读系统时间 / 纯函数
# ═══════════════════════════════════════════════════════════════════════


def _imported_module_names(src: str) -> set[str]:
    """★ F-1 修复：AST 收口「导入名」——既收 ``node.module``，也收 ``node.names``。

    旧实现只收 ``node.module`` ⇒ 包级写法
    ``from cangjie_fos.services import dd_v1_requirement_service``
    （module=cangjie_fos.services，名字挂在 ``node.names`` 上）整个逃逸 ⇒
    守卫失守（复核席 mut_M2「46 例全绿（漏网）」的根因）。
    """
    import ast
    tree = ast.parse(src)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(str(node.module or ""))
            names.update(a.name for a in node.names)
    return names


def test_f1_guard_catches_package_level_import_form():
    """★ F-1 阳性对照：守卫必须能抓到「包级写法」的 requirement service 导入。

    没有阳性对照的守卫可能本身就是 no-op ⇒ 那个「0 命中」只是探针坏了，不是对象干净。
    """
    sample = "from cangjie_fos.services import dd_v1_requirement_service\n"
    names = _imported_module_names(sample)
    assert [m for m in names if "requirement" in m], names


def test_c1_relative_period_not_swallowed_by_single_year_explicit():
    """★ C-1 回归：含四位年份的相对期间文本，不得被判成单年 EXPLICIT。"""
    spec = ps.parse_period_spec("请提供近三年的审计报告（报告期截至2024-06-30）")
    assert spec["kind"] == "RELATIVE", spec
    assert spec["relative"]["span"] == 3, spec


def test_c1_declared_anchor_expands_relative_period_with_year():
    """★ C-1 回归：相对期间 + 原文声明锚点 ⇒ 可展开为年度窗口（不再被判否）。"""
    spec = ps.build_period_spec("请提供近三年的审计报告（报告期截至2024-06-30）")
    assert spec["kind"] == "RELATIVE", spec
    assert spec["resolved"] is True, spec
    assert spec["years"] == [2022, 2023, 2024], spec


def test_module_has_no_second_doc_type_table():
    """★ 10 类材料类型唯一权威在 requirement service ⇒ 本模块不得抄一份。"""
    import re
    src = inspect.getsource(ps)
    assert "_DOC_TYPE_RULES" not in src
    imported = _imported_module_names(src)
    assert not [m for m in imported if "requirement" in m], imported
    canonical = ("audit_report", "financial_statement", "tax", "license", "charter",
                 "capital", "resolution", "ip", "labor", "contract")
    assert not re.search(r"[\"'](" + "|".join(canonical) + r")[\"']", src)


def test_parse_is_pure_and_repeatable():
    a = ps.parse_period_spec("请提供近三年的审计报告（报告期截至2024-06-30）")
    b = ps.parse_period_spec("请提供近三年的审计报告（报告期截至2024-06-30）")
    assert a == b


def test_build_period_spec_is_json_serializable():
    import json
    spec = ps.build_period_spec("请提供近三年的审计报告（报告期截至2024-06-30）")
    assert json.loads(json.dumps(spec, ensure_ascii=False)) == spec


@pytest.mark.parametrize("text,expected", [
    ("2024年度审计报告", "EXPLICIT"),
    ("近三年审计报告", "RELATIVE"),
    ("最新审计报告", "CURRENT"),
    ("营业执照正副本", "UNKNOWN"),
])
def test_four_states_are_distinguishable(text, expected):
    assert ps.parse_period_spec(text)["kind"] == expected
