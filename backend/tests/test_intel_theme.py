"""情报问题主题归档（theme）测试。

覆盖：
  - IntelQuestion.theme 字段：默认值、合法枚举、非法值被拒
  - _build_roadshow_html 按主题分组渲染（含主题标题）
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from cangjie_fos.engine.schema import IntelQuestion
from cangjie_fos.api.routes.roadshow import _build_roadshow_html


def test_theme_defaults_to_other():
    q = IntelQuestion(verbatim="退出路径是什么", underlying_concern="对退出存疑")
    assert q.theme == "其他"


def test_theme_accepts_valid_enum():
    q = IntelQuestion(verbatim="毛利率多少", underlying_concern="盈利能力", theme="财务")
    assert q.theme == "财务"


def test_theme_rejects_invalid():
    with pytest.raises(ValidationError):
        IntelQuestion(verbatim="x", underlying_concern="y", theme="乱填的主题")


def test_html_groups_questions_by_theme():
    report = {
        "meeting_atmosphere": "warm",
        "meeting_stage": "first_contact",
        "atmosphere_summary": "整体正常推进",
        "key_questions": [
            {"speaker_id": "0", "verbatim": "技术架构怎么设计", "underlying_concern": "壁垒",
             "priority": "high", "theme": "技术"},
            {"speaker_id": "0", "verbatim": "毛利率多少", "underlying_concern": "盈利",
             "priority": "high", "theme": "财务"},
            {"speaker_id": "1", "verbatim": "赛道天花板", "underlying_concern": "市场空间",
             "priority": "medium", "theme": "市场"},
        ],
    }
    html = _build_roadshow_html(report, {"interviewee": "测试路演", "created_at": 0.0})
    # 三个主题标题都应出现（按主题分组渲染）
    assert "🏷 技术" in html
    assert "🏷 财务" in html
    assert "🏷 市场" in html
    # 按主题总标题
    assert "按主题" in html


def test_html_backward_compatible_without_theme():
    """旧报告问题无 theme 字段时，归入「其他」，不报错。"""
    report = {
        "meeting_atmosphere": "warm",
        "meeting_stage": "unknown",
        "atmosphere_summary": "综述",
        "key_questions": [
            {"speaker_id": "0", "verbatim": "老问题", "underlying_concern": "关切", "priority": "medium"},
        ],
    }
    html = _build_roadshow_html(report, {"interviewee": "旧路演", "created_at": 0.0})
    assert "🏷 其他" in html
    assert "老问题" in html
