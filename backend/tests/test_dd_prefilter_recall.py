"""预筛统一召回（6.2）+ 跨年份需求推断（6.4）测试。

对应同事 8/3 报告：#1"营业执照"被挤出候选、"最近两年增值税申报表"只召回单文件。
"""
from __future__ import annotations

from cangjie_fos.services.dd_match_service import (
    _prefilter_files_for_batch,
    expected_years,
    _item_keywords,
)


# ── 6.4 跨年份推断 ────────────────────────────────────────────────────────────

def test_expected_years_explicit():
    assert expected_years("2023年审计报告") == [2023]
    assert expected_years("2022年及2024年财报") == [2022, 2024]


def test_expected_years_recent_n():
    assert expected_years("最近两年12月增值税申报表", current_year=2025) == [2024, 2025]
    assert expected_years("近三年财务报表", current_year=2025) == [2023, 2024, 2025]
    assert expected_years("过去2年审计报告", current_year=2025) == [2024, 2025]


def test_expected_years_none():
    assert expected_years("公司章程") == []


def test_item_keywords_include_years():
    kws = _item_keywords({"requirement": "最近两年增值税申报表"})
    # current year 动态，但至少应包含两个 4 位年份串
    year_kws = {k for k in kws if k.isdigit() and len(k) == 4}
    assert len(year_kws) == 2


# ── 6.2 统一召回：每条需求保底进池 ────────────────────────────────────────────

def _rows(names):
    return [{"filename": n, "summary": ""} for n in names]


def test_low_keyword_item_not_crowded_out():
    """关键词少的"营业执照"应和关键词多的需求一样被召回（不被挤出）。"""
    # 造 60 个噪音文件（含"关联公司"相关关键词），1 个营业执照文件
    names = [f"关联公司资料附件材料说明_{i}.pdf" for i in range(60)]
    names.append("营业执照正副本.pdf")
    rows = _rows(names)

    batch = [
        {"id": "a", "requirement": "营业执照正副本复印件"},
        {"id": "b", "requirement": "关联公司资料附件材料说明文件"},
    ]
    picked = _prefilter_files_for_batch(batch, rows, top_n=50)
    picked_names = {r["filename"] for r in picked}
    # 营业执照文件必须在候选池里（保底），哪怕关联公司噪音文件很多
    assert "营业执照正副本.pdf" in picked_names


def test_year_named_files_recalled_for_multiyear_req():
    """'最近两年'需求应把年份命名的文件召回（6.4 + 6.2 协同）。"""
    import datetime
    cy = datetime.datetime.now().year
    names = [f"日常台账_{i}.xlsx" for i in range(60)]
    names.append(f"{cy}年12月增值税申报表.pdf")
    names.append(f"{cy-1}年12月增值税申报表.pdf")
    rows = _rows(names)

    batch = [{"id": "a", "requirement": "最近两年12月增值税申报表"}]
    picked = {r["filename"] for r in _prefilter_files_for_batch(batch, rows, top_n=30)}
    assert f"{cy}年12月增值税申报表.pdf" in picked
    assert f"{cy-1}年12月增值税申报表.pdf" in picked


def test_small_index_returns_all():
    rows = _rows(["a.pdf", "b.pdf"])
    picked = _prefilter_files_for_batch([{"id": "x", "requirement": "任意"}], rows, top_n=50)
    assert len(picked) == 2
