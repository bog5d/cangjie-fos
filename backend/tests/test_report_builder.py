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

    def test_empty_text_returns_placeholder(self):
        result = desensitize_text("", is_person=True)
        assert result == "未命名"  # by design: empty input → placeholder

    def test_person_mode_replace_all(self):
        # is_person=True → entire input replaced with "XXX"
        result = desensitize_text("ABC公司与张三合作", is_person=True)
        assert result == "XXX"


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


# ── generate_html_report 缺音频优雅降级 (Bug 3.6) ──────────────────────

class TestGenerateHtmlReportMissingAudio:
    """缺失音频文件时，不应崩溃，应生成纯文本 HTML 报告。"""

    def test_missing_audio_generates_text_only_report(self, tmp_path):
        from cangjie_fos.engine.report_builder import generate_html_report
        from cangjie_fos.engine.schema import AnalysisReport, RiskPoint, SceneAnalysis
        from cangjie_fos.engine.report_builder import TranscriptionWord

        audio_path = tmp_path / "nonexistent.mp3"

        words = [
            TranscriptionWord(word_index=0, text="我们", start_time=0.0, end_time=0.3, speaker_id="A"),
            TranscriptionWord(word_index=1, text="的", start_time=0.3, end_time=0.5, speaker_id="A"),
            TranscriptionWord(word_index=2, text="优势", start_time=0.5, end_time=1.0, speaker_id="A"),
        ]
        report = AnalysisReport(
            total_score=85,
            scene_analysis=SceneAnalysis(
                scene_type="首次VC路演",
                speaker_roles="创业者 vs 投资人",
            ),
            total_score_deduction_reason="表达有待改进",
            positive_highlights=["逻辑清晰"],
            risk_points=[
                RiskPoint(
                    risk_level="一般",
                    score_deduction=5,
                    problem_summary="表达不够清晰",
                    tier1_general_critique="商业逻辑没问题但表达模糊",
                    tier2_qa_alignment="与QA口径一致",
                    improvement_suggestion="练习说话节奏",
                    original_text="我们 的 优势",
                    start_word_index=0,
                    end_word_index=2,
                ),
            ],
        )

        output_path = tmp_path / "test_output.html"

        # 关键断言：缺音频不抛异常
        result = generate_html_report(
            audio_path=audio_path,
            words_list=words,
            report_obj=report,
            output_html_path=output_path,
        )
        assert result == output_path
        assert output_path.is_file()

        html_content = output_path.read_text(encoding="utf-8")
        assert "85" in html_content
        assert ("音频缺失" in html_content or "无音频" in html_content
                or "audio" in html_content.lower())

    def test_missing_audio_with_manual_risk_point(self, tmp_path):
        from cangjie_fos.engine.report_builder import generate_html_report
        from cangjie_fos.engine.schema import AnalysisReport, RiskPoint, SceneAnalysis
        from cangjie_fos.engine.report_builder import TranscriptionWord

        audio_path = tmp_path / "also_missing.mp3"
        words: list[TranscriptionWord] = []
        report = AnalysisReport(
            total_score=72,
            scene_analysis=SceneAnalysis(
                scene_type="尽调答疑",
                speaker_roles="创业者 vs 尽调团队",
            ),
            total_score_deduction_reason="关键数据缺失",
            risk_points=[
                RiskPoint(
                    risk_level="严重",
                    score_deduction=10,
                    problem_summary="关键数据缺失",
                    tier1_general_critique="财务模型不完整是致命伤",
                    tier2_qa_alignment="需更新QA口径",
                    improvement_suggestion="补充财务模型",
                    start_word_index=0,
                    end_word_index=0,
                    is_manual_entry=True,
                ),
            ],
        )

        output_path = tmp_path / "manual_only.html"
        result = generate_html_report(
            audio_path=audio_path,
            words_list=words,
            report_obj=report,
            output_html_path=output_path,
        )
        assert output_path.is_file()
        html = output_path.read_text(encoding="utf-8")
        assert "关键数据缺失" in html
        assert "is_manual" in html.lower() or "人工" in html
