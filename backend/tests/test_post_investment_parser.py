"""投后季报模板解析器测试（gk 模式 scenario='post_investment'）。

验证：从季报模板提取「待填项」，输出与 dd_match_items 兼容（item_no/category/
requirement），并带 field_kind 元数据（blank/field/narrative）。
"""
from __future__ import annotations

from cangjie_fos.services.post_investment_parser import (
    extract_fillable_items,
    parse_report_template,
)

_TEMPLATE = """项目1
一、基本信息
1、项目名称：                 （项目责任人：）
2、地址：
6、主营业务：
13、公司拥有的技术专利数【】，其中发明专利数【】、实用新型数【】。
三、项目核心能力分析（技术的先进性，不少于500字）
四、近三年主要财务指标分析（不少于500字）
截止2023年9月30日，公司总资产人民币【 】万元，净资产人民币【】万元。
"""


def test_extracts_inline_blanks_each_as_item():
    """每个行内【】空格各成一项，带整句上下文。"""
    items = extract_fillable_items(_TEMPLATE)
    blanks = [it for it in items if it["field_kind"] == "blank"]
    # 专利那行 3 个 + 财务那行 2 个 = 5 个空格
    assert len(blanks) == 5
    # 同句多空格带序号标注
    patent_blanks = [b for b in blanks if "技术专利数" in b["requirement"]]
    assert len(patent_blanks) == 3
    assert all("第" in b["requirement"] and "个空格" in b["requirement"] for b in patent_blanks)


def test_extracts_empty_numbered_fields():
    """冒号后为空的编号字段（地址：/主营业务：）成为 field 项。"""
    items = extract_fillable_items(_TEMPLATE)
    fields = [it for it in items if it["field_kind"] == "field"]
    reqs = [f["requirement"] for f in fields]
    assert any("地址" in r for r in reqs)
    assert any("主营业务" in r for r in reqs)


def test_extracts_narrative_sections():
    """带字数要求的章节/字段识别为 narrative。"""
    items = extract_fillable_items(_TEMPLATE)
    narratives = [it for it in items if it["field_kind"] == "narrative"]
    reqs = " ".join(n["requirement"] for n in narratives)
    assert "核心能力分析" in reqs
    assert "财务指标分析" in reqs
    assert len(narratives) >= 2


def test_section_assigned_as_category():
    """章节标题作为后续项的 category，不单独成项。"""
    items = extract_fillable_items(_TEMPLATE)
    # 章节标题本身（纯标题）不入项
    assert not any(it["requirement"].strip() in ("一、基本信息",) for it in items)
    # 基本信息下的字段 category 为「一、基本信息」
    addr = next(it for it in items if "地址" in it["requirement"])
    assert addr["category"] == "一、基本信息"
    # 财务空格的 category 为「四、近三年主要财务指标分析…」
    fin = next(it for it in items if "总资产" in it["requirement"])
    assert fin["category"].startswith("四、")


def test_item_no_sequential_and_unique():
    """item_no 连续且唯一，结构与 dd_match_items 兼容。"""
    items = extract_fillable_items(_TEMPLATE)
    nos = [it["item_no"] for it in items]
    assert nos == [str(i) for i in range(1, len(items) + 1)]
    for it in items:
        assert set(it.keys()) >= {"item_no", "category", "requirement", "field_kind"}


def test_parse_report_template_text_source():
    """parse_report_template 走 text 源等价于 extract_fillable_items。"""
    a = parse_report_template(_TEMPLATE, "text")
    b = extract_fillable_items(_TEMPLATE)
    assert a == b


def test_empty_template_yields_no_items():
    assert extract_fillable_items("") == []
    assert extract_fillable_items("一、基本信息\n二、股权结构") == []
