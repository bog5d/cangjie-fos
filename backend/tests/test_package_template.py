"""需求03 — 标准数据包模板 + DB 模板存取层测试。"""
from __future__ import annotations

from cangjie_fos.services import package_template_store as store
from cangjie_fos.services.package_template import get_standard_template, template_categories


# ── 内置种子模板（调研版）────────────────────────────────────

def test_template_has_five_dimensions():
    cats = template_categories()
    assert cats == ["财务税务", "法务合规", "业务经营", "团队组织", "技术研发"]


def test_template_item_shape_and_numbering():
    items = get_standard_template()
    assert len(items) >= 45  # 调研版：49 条
    assert [it["item_no"] for it in items] == [str(i + 1) for i in range(len(items))]
    for it in items:
        assert set(it.keys()) == {"item_no", "category", "requirement", "importance"}
        assert it["importance"] in ("core", "normal")
        assert it["requirement"].strip()


def test_template_covers_researched_requirements():
    """覆盖中国一级市场尽调清单高频必查项（调研来源见 package_template.py 文档头）。"""
    reqs = " ".join(it["requirement"] for it in get_standard_template())
    for kw in ("营业执照", "审计报告", "公司章程", "商业计划书", "前十大客户",
               "前十大供应商", "知识产权", "社保公积金", "关联", "对外担保",
               "纳税申报", "诉讼", "行政处罚", "对赌", "验资", "团队简历"):
        assert kw in reqs, f"标准模板应覆盖 {kw}"


# ── DB 模板存取（在线编辑 + 多套复用）────────────────────────

def test_builtin_seeded_on_first_access():
    rows = store.list_templates("t1")
    assert len(rows) == 1
    assert rows[0]["template_id"] == store.BUILTIN_ID
    assert rows[0]["is_builtin"] == 1
    assert rows[0]["item_count"] == len(get_standard_template())


def test_create_template_copy_from_builtin():
    r = store.create_template("A轮精简包", "t1", copy_from=store.BUILTIN_ID)
    assert r["item_count"] == len(get_standard_template())
    items = store.get_template_items(r["template_id"], "t1")
    assert items[0]["requirement"] == get_standard_template()[0]["requirement"]


def test_replace_items_edits_template():
    r = store.create_template("自定义包", "t1")
    n = store.replace_items(r["template_id"], [
        {"category": "财务", "requirement": "条目A", "importance": "core"},
        {"category": "", "requirement": "条目B", "importance": "瞎填"},
        {"category": "财务", "requirement": "  ", "importance": "core"},  # 空的被剔
    ], "t1")
    assert n == 2
    items = store.get_template_items(r["template_id"], "t1")
    assert [it["requirement"] for it in items] == ["条目A", "条目B"]
    assert items[1]["category"] == "未分类"      # 空分类规整
    assert items[1]["importance"] == "normal"    # 非法 importance 规整


def test_reset_builtin_restores_default():
    store.ensure_builtin("t2")
    store.replace_items(store.BUILTIN_ID, [
        {"category": "X", "requirement": "只剩一条", "importance": "core"},
    ], "t2")
    assert len(store.get_template_items(store.BUILTIN_ID, "t2")) == 1
    n = store.reset_builtin("t2")
    assert n == len(get_standard_template())
    assert len(store.get_template_items(store.BUILTIN_ID, "t2")) == n


def test_delete_template_rules():
    r = store.create_template("可删包", "t1")
    assert store.delete_template(r["template_id"], "t1") is True
    assert not store.template_exists(r["template_id"], "t1")
    # 内置不可删
    assert store.delete_template(store.BUILTIN_ID, "t1") is False
    assert store.template_exists(store.BUILTIN_ID, "t1")
