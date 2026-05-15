"""job_pipeline.py 单元测试 — 覆盖工具函数：文件名脱敏、上下文构建、敏感词掩码。"""
from __future__ import annotations

import pytest
from cangjie_fos.engine.job_pipeline import (
    safe_fs_segment,
    apply_html_filename_masks,
)


class TestSafeFsSegment:
    def test_normal_name(self):
        assert safe_fs_segment("路演录音") == "路演录音"

    def test_removes_special_chars(self):
        result = safe_fs_segment("文件:名?测试")
        assert ":" not in result
        assert "?" not in result

    def test_truncates_long_name(self):
        long_name = "A" * 250
        result = safe_fs_segment(long_name)
        assert len(result) == 200

    def test_empty_name_returns_placeholder(self):
        result = safe_fs_segment("")
        assert result == "未命名批次"

    def test_whitespace_only(self):
        result = safe_fs_segment("   ")
        assert result == "未命名批次"


class TestApplyHtmlFilenameMasks:
    def test_no_masks_returns_unchanged(self):
        assert apply_html_filename_masks("报告_A公司", {}) == "报告_A公司"

    def test_applies_mask(self):
        masks = {"A公司": "XX公司"}
        result = apply_html_filename_masks("报告_A公司_2026", masks)
        assert "XX公司" in result
        assert "A公司" not in result
