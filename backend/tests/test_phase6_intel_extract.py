"""Phase 6：路演后情报抽取落盘。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from cangjie_fos.schemas.institution import PipelineStage
from cangjie_fos.services.institution_intel_extract import extract_and_persist_institution_intel
from cangjie_fos.services.institution_store import get_by_name


class _W:
    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text


@pytest.fixture
def _inst_db(monkeypatch, tmp_path):
    root = tmp_path / "fos_backend"
    (root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("cangjie_fos.core.paths.get_backend_root", lambda: root)
    yield


def test_heuristic_extracts_sequoia_from_transcript(_inst_db, monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    words = [_W("红杉资本合伙人反复追问产能利用率和 capex 节奏")]
    report = SimpleNamespace(positive_highlights=["表达清晰"], risk_points=["产能数据口径"])
    extract_and_persist_institution_intel(
        tenant_id="demo",
        words=words,
        report=report,
        trace_id="tr-heur",
        explicit_context={"filename": "pitch.wav"},
    )
    g = get_by_name(tenant_id="demo", name="红杉资本")
    assert g is not None
    assert g.stage in (PipelineStage.PITCHED, PipelineStage.DD, PipelineStage.TARGETED, PipelineStage.TERM_SHEET)
    assert "产能" in (g.concerns or "") or "产能" in (g.preferences or "") or "红杉" in (g.ai_summary or "")


def test_no_institution_when_no_signal(_inst_db, monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    words = [_W("我们内部复盘一下产品节奏")]
    report = SimpleNamespace(positive_highlights=[], risk_points=[])
    extract_and_persist_institution_intel(
        tenant_id="demo",
        words=words,
        report=report,
        trace_id="tr2",
        explicit_context={},
    )
    assert get_by_name(tenant_id="demo", name="红杉资本") is None
