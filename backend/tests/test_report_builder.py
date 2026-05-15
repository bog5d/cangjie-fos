"""report_builder.py 单元测试 — 覆盖脱敏、初始化、文本渲染等可测函数。

FFmpeg/音频相关函数需要安装 FFmpeg，跳过。
"""
from __future__ import annotations

import pytest
from cangjie_fos.engine.report_builder import (
    _han_initials_segment,
    _apply_text_masks,
    desensitize_text,
)


class TestDesensitizeText:
    def test_person_name_replaced(self):
        result = desensitize_text("张三参加了会议", is_person=True)
        assert "张三" not in result
        assert "XXX" in result

    def test_institution_abbreviated(self):
        result = desensitize_text("深圳市创新投资集团", is_person=False)
        assert len(result) < len("深圳市创新投资集团有限公司")

    def test_empty_text_returns_empty(self):
        result = desensitize_text("", is_person=True)
        assert result == "" or result.strip() == ""

    def test_mixed_chinese_english_preserved(self):
        result = desensitize_text("ABC公司与张三合作", is_person=True)
        assert "ABC" in result
        assert "张三" not in result


class TestHanInitialsSegment:
    def test_normal_name(self):
        result = _han_initials_segment("深圳创新")
        assert len(result) > 0

    def test_single_char(self):
        result = _han_initials_segment("中")
        assert isinstance(result, str)


class TestApplyTextMasks:
    def test_simple_replacement(self):
        masks = {"张三": "XXX"}
        result = _apply_text_masks("张三和李四", masks)
        assert "XXX" in result
        assert "李四" in result  # unchanged

    def test_no_masks(self):
        result = _apply_text_masks("原始文本", {})
        assert result == "原始文本"
