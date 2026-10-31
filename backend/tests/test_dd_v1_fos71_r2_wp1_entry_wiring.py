"""R2-WP1：**官方入口接线**测试（tools/dd_v1_local_run.py ＋ tools/dd_team_channel.py）。

★ 本文件只测**接线**：锚点/四态有没有真的从入口传到服务层、能不能在报告里露出来。
  期间语义本身另有专测（``test_dd_v1_period_service.py`` ＋
  ``test_dd_v1_fos71_r2_wp1_period.py``）⇒ 这里**不重复实现口径**，断言一律对着
  服务层的真实返回值。
★ 旧字符串 ``period`` 的口径**一字不改**（本轮只**附加**结构化视图）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "backend" / "src"))

import dd_team_channel as tc  # noqa: E402
import dd_v1_local_run as lr  # noqa: E402

# ── A. local_run：--period-anchor 的解析与传递 ────────────────────────────────


def test_period_anchor_arg_empty_is_none():
    """不给锚点 ⇒ ``None``（**不擅自假定**；相对期间无其它锚点时判「依据不足」）。"""
    assert lr._period_anchor_arg("") is None
    assert lr._period_anchor_arg(None) is None
    assert lr._period_anchor_arg("   ") is None


def test_period_anchor_arg_accepts_date_and_year():
    """合法锚点原样解析（date / year 两种形态）。"""
    assert lr._period_anchor_arg('{"date": "2024-12-31"}') == {"date": "2024-12-31"}
    assert lr._period_anchor_arg('{"year": 2024}') == {"year": 2024}
    assert lr._period_anchor_arg('{"year": "2024"}') == {"year": 2024}


@pytest.mark.parametrize("raw", [
    "not-json",
    "[1, 2]",
    "{}",
    '{"year": "x"}',
    '{"year": 1800}',
    '{"date": "2024/12/31"}',
])
def test_period_anchor_arg_rejects_invalid(raw):
    """非法锚点 ⇒ **报错退出**（不静默忽略：静默忽略会让口径悄悄退化成「无法判定」）。"""
    with pytest.raises(SystemExit) as ei:
        lr._period_anchor_arg(raw)
    assert ei.value.code == 3


def _split_args(items_path: Path, out_path: Path, anchor: str = "") -> SimpleNamespace:
    return SimpleNamespace(items=str(items_path), out=str(out_path),
                           period_anchor=anchor, blind_leak_words="",
                           blind_items_out=None)


def test_split_passes_anchor_into_semantic_service(tmp_path, monkeypatch):
    """★ 接线本体：``split`` 把 ``--period-anchor`` 传到 ``sem.split_items``。"""
    seen = []

    def _fake_split(items, *, period_anchor=None):
        seen.append(period_anchor)
        return ([{"obligation_id": "O1", "period": "2024", "text": "x"}], [])

    monkeypatch.setattr(lr.sem, "split_items", _fake_split)
    monkeypatch.setattr(lr.sem, "redact_for_output", lambda obs, flags: (obs, flags))
    items = tmp_path / "items.json"
    items.write_text(json.dumps([{"item_id": "i1", "entity": "E", "text": "要求"}],
                                 ensure_ascii=False), "utf-8")
    out = tmp_path / "obs.json"

    assert lr.cmd_split(_split_args(items, out, '{"year": 2024}')) == 0
    assert seen == [{"year": 2024}], "锚点没有传到语义层"

    seen.clear()
    assert lr.cmd_split(_split_args(items, out)) == 0
    assert seen == [None], "不给锚点时必须传 None（而不是空 dict）"


def test_run_rejects_invalid_anchor_before_any_work(tmp_path):
    """★ ``run`` 先解析锚点 ⇒ 非法锚点在**任何**材料准备/模型调用之前就退出。"""
    args = SimpleNamespace(period_anchor="{bad json}")
    with pytest.raises(SystemExit) as ei:
        lr.cmd_run(args)
    assert ei.value.code == 3


# ── B. team_channel：四态视图与锚点链 ────────────────────────────────────────


def test_config_anchor_reads_anchor_year():
    """``--anchor-year`` 折成**显式配置**锚点（第一优先档）；没给 ⇒ None。"""
    assert tc._config_anchor(SimpleNamespace(anchor_year=2024)) == {"year": 2024}
    assert tc._config_anchor(SimpleNamespace(anchor_year=None)) is None
    assert tc._config_anchor(SimpleNamespace(anchor_year=1800)) is None


def test_period_spec_view_current_keeps_legacy_label():
    """规则层判 CURRENT 的类型（执照/章程）⇒ 四态 CURRENT，且**只认同标签**（不放宽）。"""
    spec = tc._period_spec_view({"text": "提供营业执照", "period": "CURRENT"})
    assert spec["kind"] == "CURRENT"
    assert spec["current_mode"] == "LABEL"


def test_period_spec_view_explicit_from_legacy_string():
    """规则层已解析出单一年份 ⇒ 以它为准（唯一退化入口）。"""
    spec = tc._period_spec_view({"text": "提供审计报告", "period": "2024"})
    assert spec["kind"] == "EXPLICIT"
    assert spec["years"] == [2024]


def test_period_spec_view_relative_wins_over_single_year():
    """★ 相对期间优先于单年显式（与语义层同一优先级，C-1 口径在入口侧同样成立）。"""
    spec = tc._period_spec_view({
        "text": "请提供近三年的审计报告（报告期截至2024年6月30日）",
        "period": "2024"})
    assert spec["kind"] == "RELATIVE"
    assert spec["resolved"] is True
    assert spec["years"] == [2022, 2023, 2024]


def test_period_spec_view_relative_without_anchor_is_unresolved():
    """★ 没有可验证锚点 ⇒ **保持未锚定**（不拿系统时间当基准）⇒ 落「依据不足」。"""
    spec = tc._period_spec_view({"text": "请提供近三年的审计报告", "period": ""})
    assert spec["kind"] == "RELATIVE"
    assert spec["resolved"] is False
    assert "依据不足" in tc._period_view_text(spec)


def test_period_spec_view_declared_anchor_is_used():
    """原文自带的截止日期声明 ⇒ 可验证锚点（第二优先档）。"""
    spec = tc._period_spec_view({
        "text": "请提供近三年的审计报告（报告期截至2024-06-30）", "period": ""})
    assert spec["kind"] == "RELATIVE"
    assert spec["resolved"] is True
    assert spec["anchor"]["source"] == "CHECKLIST_DECLARATION"


def test_period_spec_view_config_anchor_wins_over_declared():
    """★ 锚点链优先级：**显式配置 > 原文声明**（服务层口径，入口侧不自己发明优先级）。"""
    spec = tc._period_spec_view({
        "text": "请提供近三年的审计报告（报告期截至2024-06-30）", "period": ""},
        config_anchor={"year": 2026})
    assert spec["kind"] == "RELATIVE"
    assert spec["resolved"] is True
    assert spec["anchor"]["source"] == "EXPLICIT_CONFIG"
    assert spec["anchor"]["year"] == 2026


def _fake_bridge() -> dict:
    return {"ok": True, "result": {
        "mode": "SYNTHETIC_REPLAY", "degrade_reason": "", "external_model_calls": 0,
        "advisory_only": True, "review_required": True, "changes_hard_verdict": False,
        "sent_to_institution": False, "warnings": [],
        "counts": {"obligations_with_evidence": 1, "obligations_out": 1, "evidence_total": 1},
        "obligations": [{
            "obligation_id": "O1", "source_obligation_id": "S1", "entity": "E",
            "entity_basis": "FACT", "subject_verified": True, "doc_type": "audit_report",
            "period": "2024", "evidence_count": 1,
            "rule_hint": {"verdict": "SUFFICIENT"},
            "evidence": [{"file_id": "F1", "sha256": "0" * 64, "locator": "L",
                          "relative_path": "a.pdf", "entity": "E",
                          "subject_verified": True, "version_status": "EFFECTIVE",
                          "part": "正文"}],
        }],
    }}


def test_bridge_json_attaches_period_spec_and_keeps_legacy_string():
    """★ 接线本体：桥接机读产物**附加**四态视图，旧字符串 ``period`` 一字不改。"""
    payload = tc._bridge_json(_fake_bridge(), config_anchor={"year": 2024})
    ob = payload["obligations"][0]
    assert ob["period"] == "2024"
    assert ob["period_spec"]["kind"] == "EXPLICIT"
    assert ob["period_spec"]["years"] == [2024]


def test_period_view_text_covers_four_kinds():
    """四态各有一句人话（报告里给人看的那一行）。"""
    assert "EXPLICIT" in tc._period_view_text({"kind": "EXPLICIT", "years": [2024]})
    assert "CURRENT" in tc._period_view_text({"kind": "CURRENT"})
    assert "UNKNOWN" in tc._period_view_text({"kind": "UNKNOWN"})
    assert "依据不足" in tc._period_view_text(
        {"kind": "RELATIVE", "resolved": False, "years": []})
    assert "2022" in tc._period_view_text(
        {"kind": "RELATIVE", "resolved": True, "years": [2022, 2023, 2024]})
