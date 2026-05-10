"""LangGraph 融资评估：薄封装 `agent_runner`（SPEC A4）+ 指数退避重试（R3）。

路演分支（category=='01_机构路演'）直接调用 run_roadshow_intel_analysis，
其他场景走 LangGraph 两阶段评估。
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from cangjie_fos.engine.coach.agent_runner import run_pitch_evaluation_via_langgraph_with_state
from cangjie_fos.engine.coach.llm_judge import run_roadshow_intel_analysis

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [2, 4, 8]  # seconds between attempt 1→2, 2→3, 3→4
_ROADSHOW_CATEGORY = "01_机构路演"


class PitchGraphService:
    @staticmethod
    def run_evaluation_with_state(
        *,
        tenant_id: str,
        words: list[Any],
        model_choice: str = "deepseek",
        explicit_context: dict[str, Any] | None = None,
        qa_text: str = "",
        company_background: str = "",
        on_notice: Callable[[str], None] | None = None,
        historical_memories: list[Any] | None = None,
        trace_id: str | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        category = (explicit_context or {}).get("biz_type", "")
        if category == _ROADSHOW_CATEGORY:
            # ── 路演情报分析分支（不打分、不评判话术）────────────────────────────
            logger.info(
                "roadshow_intel_branch: trace_id=%s category=%s", trace_id, category
            )
            last_exc: Exception | None = None
            for attempt in range(len(_RETRY_DELAYS) + 1):
                if attempt > 0:
                    delay = _RETRY_DELAYS[attempt - 1]
                    logger.warning(
                        "roadshow_intel_retry attempt=%d/%d sleep=%ds reason=%s",
                        attempt + 1,
                        len(_RETRY_DELAYS) + 1,
                        delay,
                        last_exc,
                    )
                    time.sleep(delay)
                try:
                    report = run_roadshow_intel_analysis(
                        words,
                        model_choice=model_choice,
                        explicit_context=explicit_context,
                        on_notice=on_notice,
                    )
                    return report, {}
                except (ConnectionError, TimeoutError) as e:
                    last_exc = e
            assert last_exc is not None
            raise last_exc

        # ── 常规评估分支（LangGraph 两阶段打分）──────────────────────────────────
        last_exc = None
        for attempt in range(len(_RETRY_DELAYS) + 1):  # 0, 1, 2, 3
            if attempt > 0:
                delay = _RETRY_DELAYS[attempt - 1]
                logger.warning(
                    "llm_retry attempt=%d/%d sleep=%ds reason=%s",
                    attempt + 1,
                    len(_RETRY_DELAYS) + 1,
                    delay,
                    last_exc,
                )
                time.sleep(delay)
            try:
                report, excerpt = run_pitch_evaluation_via_langgraph_with_state(
                    tenant_id=tenant_id,
                    words=words,
                    model_choice=model_choice,
                    explicit_context=explicit_context,
                    qa_text=qa_text,
                    company_background=company_background,
                    on_notice=on_notice,
                    historical_memories=historical_memories,
                    trace_id=trace_id,
                )
                break  # success
            except (ConnectionError, TimeoutError) as e:
                last_exc = e
        else:
            assert last_exc is not None
            raise last_exc

        try:
            from cangjie_fos.services.institution_intel_extract import extract_and_persist_institution_intel

            extract_and_persist_institution_intel(
                tenant_id=tenant_id,
                words=words,
                report=report,
                trace_id=trace_id,
                explicit_context=explicit_context or {},
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("institution_intel_extract_skipped: %s", e)
            if trace_id:
                try:
                    from cangjie_fos.services.pitch_job_db import db_job_update  # noqa: PLC0415
                    db_job_update(trace_id, warnings={"institution_extract": str(e)})
                except Exception:  # noqa: BLE001
                    pass
        return report, excerpt
