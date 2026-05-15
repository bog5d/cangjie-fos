"""Bridge: FOS pitch jobs → legacy AI_Pitch_Coach report_builder HTML output.

Public API
----------
generate_job_html_report(job_id) -> Path
"""
from __future__ import annotations

import logging
from pathlib import Path

from cangjie_fos.core.paths import get_backend_root
from cangjie_fos.engine.report_builder import generate_html_report
from cangjie_fos.engine.schema import AnalysisReport, TranscriptionWord
from cangjie_fos.services.pitch_job_db import db_job_get, db_job_update

logger = logging.getLogger(__name__)


def generate_job_html_report(job_id: str) -> Path:
    """Load job data from SQLite, call legacy report_builder, save HTML.

    Returns the Path to the generated HTML file.
    Raises ValueError if job not found or missing required data.
    When audio file is missing, generates a text-only HTML report.
    """
    # 1. Load from DB
    row = db_job_get(job_id)
    if not row:
        raise ValueError(f"Job not found: {job_id}")

    # 2. Choose report: edited_report if committed, else original_report
    report_dict = row.get("edited_report") or row.get("original_report")
    if not report_dict:
        raise ValueError(f"Job {job_id} has no report data")

    words_raw = row.get("words_json") or []
    if not words_raw:
        raise ValueError(f"Job {job_id} has no transcription words")

    # 3. Audio file — graceful degradation if missing
    audio_path = Path(row.get("audio_path") or "")
    if not audio_path.is_file():
        logger.warning(
            "Audio file missing for job %s: %s — generating text-only report",
            job_id, audio_path,
        )

    # 4. Convert FOS data → legacy types
    words_list = [TranscriptionWord.model_validate(w) for w in words_raw]
    report_obj = AnalysisReport.model_validate(report_dict)

    # 5. Output path
    output_dir = get_backend_root() / "data" / "html_reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{job_id}.html"

    # 6. Call legacy builder
    result_path = generate_html_report(
        audio_path=audio_path,
        words_list=words_list,
        report_obj=report_obj,
        output_html_path=output_path,
    )

    # 7. Persist html_report_path back to DB
    db_job_update(job_id, html_report_path=str(result_path))

    return result_path
