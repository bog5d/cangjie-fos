"""llm_judge 子包 — 从单体 llm_judge.py 拆分而来 (v0.6.2).

1813 行单体文件拆为 7 个逻辑子模块，所有公开 API 在此重新导出。
向后兼容：from cangjie_fos.engine.coach.llm_judge import evaluate_pitch 仍可用。
"""

from cangjie_fos.engine.coach.llm_judge._config import (
    DISPLAY_NAME, JUDGE_MODEL_KEYS, MAX_COMPANY_BG_CHARS,
    MAX_COMPLETION_TOKENS_BY_MODEL, MAX_QA_CHARS, MAX_TRANSCRIPT_CHARS,
    MIDDLE_OMIT_MARK, ROUTER,
    choose_model_with_timeout, detect_logical_conflict,
    truncate_company_background, truncate_qa_text,
)
from cangjie_fos.engine.coach.llm_judge._salvage import (
    _is_valid_risk_point, _recover_risk_point_dicts_from_truncated_json,
    _salvage_analysis_report_from_truncated_json, _salvage_risk_scan_result,
    _validation_suggests_truncated_json,
    salvage_risk_point_dicts_from_truncated_llm_json, salvage_truncated_analysis_report,
)
from cangjie_fos.engine.coach.llm_judge._prompts import (
    _build_deep_single_risk_system_prompt, _build_risk_scan_system_prompt,
    _build_system_prompt, _clamp_word_span, _format_historical_profile_block,
    _format_sniper_block, _normalize_explicit_context, format_transcript_for_llm,
)
from cangjie_fos.engine.coach.llm_judge._evaluation import (
    PitchEvalContext, _compose_total_deduction_reason, _make_client,
    deep_evaluate_single_risk, evaluate_pitch,
    prepare_pitch_evaluation_context, run_phase1_risk_scan,
    run_phase2_deep_eval_and_assemble_report,
)
from cangjie_fos.engine.coach.llm_judge._memory import (
    distill_executive_memory_from_diff, load_transcription_words,
)
from cangjie_fos.engine.coach.llm_judge._refinement import (
    polish_manual_risk_point, refine_risk_point, refine_single_risk_point,
)
from cangjie_fos.engine.coach.llm_judge._roadshow import (
    _save_report, run_roadshow_intel_analysis,
)

__all__ = [
    "DISPLAY_NAME", "JUDGE_MODEL_KEYS", "MAX_COMPANY_BG_CHARS",
    "MAX_COMPLETION_TOKENS_BY_MODEL", "MAX_QA_CHARS", "MAX_TRANSCRIPT_CHARS",
    "MIDDLE_OMIT_MARK", "ROUTER", "PitchEvalContext",
    "choose_model_with_timeout", "detect_logical_conflict",
    "truncate_company_background", "truncate_qa_text",
    "_is_valid_risk_point", "salvage_truncated_analysis_report",
    "_build_system_prompt", "format_transcript_for_llm",
    "_make_client", "evaluate_pitch", "deep_evaluate_single_risk",
    "run_phase1_risk_scan", "run_phase2_deep_eval_and_assemble_report",
    "prepare_pitch_evaluation_context",
    "distill_executive_memory_from_diff", "load_transcription_words",
    "refine_risk_point", "refine_single_risk_point", "polish_manual_risk_point",
    "run_roadshow_intel_analysis", "_save_report",
]
