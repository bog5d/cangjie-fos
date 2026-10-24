"""进化记录 JSON 落盘（按 tenant 分目录）。"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from cangjie_fos.core.paths import get_evolution_data_dir
from cangjie_fos.schemas.evolution import EvolutionRecord, EvolutionStatus, TextDiffFeedbackRequest
from cangjie_fos.services.diff_service import build_unified_diff

logger = logging.getLogger(__name__)


class EvolutionJsonStore:
    def __init__(self, base: Path | None = None) -> None:
        self._base = base or get_evolution_data_dir()

    def persist_text_diff(self, req: TextDiffFeedbackRequest) -> EvolutionRecord:
        diff = build_unified_diff(ai_text=req.ai_text, user_text=req.user_text)
        rid = uuid.uuid4().hex
        tenant_dir = self._base / self._safe_segment(req.tenant_id)
        tenant_dir.mkdir(parents=True, exist_ok=True)
        record = EvolutionRecord(
            record_id=rid,
            tenant_id=req.tenant_id,
            trace_id=req.trace_id,
            ai_text=req.ai_text,
            user_text=req.user_text,
            diff_unified=diff,
            status=EvolutionStatus.PENDING_REFLECTION,
            exp_delta=18,
        )
        path = tenant_dir / f"{rid}.json"
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        logger.info(
            "evolution_record_saved record_id=%s tenant_id=%s trace_id=%s path=%s",
            rid,
            req.tenant_id,
            req.trace_id,
            path,
        )
        return record

    @staticmethod
    def _safe_segment(tenant_id: str) -> str:
        return tenant_id.replace("/", "_").replace("..", "_")[:128]

    def list_pending_records(self, *, tenant_id: str | None = None) -> list[Path]:
        out: list[Path] = []
        if tenant_id:
            dirs = [self._base / self._safe_segment(tenant_id)]
        else:
            dirs = [p for p in self._base.iterdir() if p.is_dir()]
        for d in dirs:
            if not d.is_dir():
                continue
            for p in d.glob("*.json"):
                try:
                    raw = json.loads(p.read_text(encoding="utf-8"))
                    st = raw.get("status")
                    if st == EvolutionStatus.PENDING_REFLECTION.value:
                        out.append(p)
                except (json.JSONDecodeError, OSError):
                    continue
        return out

    def mark_reflected(self, path: Path) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["status"] = EvolutionStatus.REFLECTED.value
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
