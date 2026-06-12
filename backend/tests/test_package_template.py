"""需求03 — 标准数据包模板测试。"""
from __future__ import annotations

from cangjie_fos.services.package_template import get_standard_template, template_categories


def test_template_has_three_dimensions():
    cats = template_categories()
    assert cats == ["财务", "法务", "业务"]


def test_template_item_shape_and_numbering():
    items = get_standard_template()
    assert len(items) >= 18
    # item_no 连续从 1
    assert [it["item_no"] for it in items] == [str(i + 1) for i in range(len(items))]
    for it in items:
        assert set(it.keys()) == {"item_no", "category", "requirement", "importance"}
        assert it["importance"] in ("core", "normal")
        assert it["category"] in ("财务", "法务", "业务")
        assert it["requirement"].strip()


def test_template_covers_key_requirements():
    reqs = " ".join(it["requirement"] for it in get_standard_template())
    for kw in ("营业执照", "审计报告", "公司章程", "商业计划书", "客户", "团队"):
        assert kw in reqs, f"标准模板应覆盖 {kw}"
