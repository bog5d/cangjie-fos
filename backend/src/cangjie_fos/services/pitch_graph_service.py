"""LangGraph 融资评估：薄封装 `agent_runner`（SPEC A4）+ 指数退避重试（R3）。"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from cangjie_fos.core.paths import ensure_pitch_coach_runtime

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [2, 4, 8]  # seconds between attempt 1→2, 2→3, 3→4


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
        ensure_pitch_coach_runtime()
        from agent_runner import run_pitch_evaluation_via_langgraph_with_state

        last_exc: Exception | None = None
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
            raise last_exc  # type: ignore[misc]

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
