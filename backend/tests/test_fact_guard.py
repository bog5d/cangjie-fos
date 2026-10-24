"""事实护栏（fact_guard）测试 — 全确定性，零 LLM。

用例直接取自同事实测发现的真实幻觉案例（2026-06-11 反馈）。
"""
from __future__ import annotations

from cangjie_fos.services.fact_guard import (
    evidence_found,
    extract_numbers,
    numbers_grounded,
    ungrounded_numbers,
)

_MATERIAL = "我们收入月复合增长12%，毛利率58%，前三大客户贡献46%的收入。团队20人。"


def test_extract_numbers_basic():
    assert extract_numbers(_MATERIAL) == {"12", "58", "46", "20"}


def test_extract_numbers_decimal_and_fullwidth():
    assert extract_numbers("增长１２.５%，成本3.0万") == {"12.5", "3"}


def test_extract_numbers_normalizes_trailing_zero():
    # "12.0" 与 "12" 视为同一个数
    assert ungrounded_numbers("增长12.0%", "增长12%") == set()


def test_derived_number_is_ungrounded():
    # 真实案例：月增 12% 被推导成「年化流失率 78%」→ 78 不在材料里
    assert ungrounded_numbers("年化流失率高达78%", _MATERIAL) == {"78"}
    assert not numbers_grounded("年化流失率高达78%", _MATERIAL)


def test_existing_number_is_grounded():
    # 注意护栏边界：数字存在但指标搬用（毛利率46%）拦不住，靠 evidence 晒出处
    assert numbers_grounded("毛利率为什么只有58%？", _MATERIAL)


def test_no_numbers_always_grounded():
    assert numbers_grounded("你们的壁垒在哪里？", _MATERIAL)


def test_multiple_sources():
    assert numbers_grounded("12%和95%", "增长12%", "留存95%")
    assert ungrounded_numbers("12%和95%", "增长12%") == {"95"}


def test_evidence_found_verbatim():
    assert evidence_found("我们收入月复合增长12%", _MATERIAL)


def test_evidence_found_ignores_punctuation_and_whitespace():
    # LLM 引用时常丢标点/空格，不应误判
    assert evidence_found("毛利率58% 前三大客户贡献46%的收入", _MATERIAL)


def test_evidence_fabricated_not_found():
    # 真实案例：编一句材料里不存在的话当出处
    assert not evidence_found("客户留存率58%", _MATERIAL)
    assert not evidence_found("CTO有3000万参数模型训练经验", _MATERIAL)


def test_evidence_empty_is_invalid():
    assert not evidence_found("", _MATERIAL)
    assert not evidence_found("   ", _MATERIAL)
