"""需求01·A1 — BP 要点提炼器测试（LLM 全 mock）。"""
from __future__ import annotations

from cangjie_fos.services import coach_keypoint_service as svc


def test_extract_key_points_basic(monkeypatch):
    """提炼出结构化要点，point_no 连续，字段齐全。"""
    fake = [
        {"page_no": 1, "point_text": "我们做 AI 尽调自动化", "weight": "core"},
        {"page_no": 2, "point_text": "已签约 30 家机构客户", "weight": "normal"},
    ]
    monkeypatch.setattr(svc, "_llm_extract_keypoints_chunk", lambda chunk: list(fake))
    points = svc.extract_key_points("第一页：我们做...\n第二页：客户...")
    assert len(points) == 2
    assert points[0]["point_no"] == "1"
    assert points[1]["point_no"] == "2"
    assert set(points[0].keys()) >= {"point_no", "page_no", "point_text", "weight"}
    assert points[0]["weight"] == "core"


def test_extract_dedup_across_chunks(monkeypatch):
    """重叠分块产生的重复要点应被去重。"""
    dup = {"page_no": 1, "point_text": "我们做 AI 尽调自动化平台", "weight": "core"}
    monkeypatch.setattr(svc, "_llm_extract_keypoints_chunk", lambda chunk: [dict(dup)])
    # 强制多块：构造超长文本
    long_text = "我们做 AI 尽调自动化平台。" * 500
    points = svc.extract_key_points(long_text)
    assert len(points) == 1  # 多块返回同一要点，去重后只剩 1


def test_empty_bp_returns_empty():
    assert svc.extract_key_points("") == []
    assert svc.extract_key_points("   ") == []


def test_invalid_weight_falls_back_to_normal():
    """非法 weight 被规整为 normal。"""
    raw = '[{"page_no": 1, "point_text": "测试要点", "weight": "超级重要"}]'
    points = svc._parse_keypoints_json(raw)
    assert len(points) == 1
    assert points[0]["weight"] == "normal"


def test_parse_strips_markdown_fence():
    """带 ```json 包裹也能解析。"""
    raw = '```json\n[{"page_no": 0, "point_text": "壁垒是数据飞轮", "weight": "core"}]\n```'
    points = svc._parse_keypoints_json(raw)
    assert len(points) == 1
    assert points[0]["point_text"] == "壁垒是数据飞轮"


def test_parse_garbage_returns_empty():
    assert svc._parse_keypoints_json("这不是JSON") == []
    assert svc._parse_keypoints_json('{"not": "a list"}') == []


# ── 要点事实护栏 ──────────────────────────────────────────────

_SOURCE = "我们自建算力集群，毛利率58%。团队来自一线大厂，CTO 曾负责推荐系统。"


def _pt(text, evidence=""):
    return {"point_no": "1", "page_no": 1, "point_text": text,
            "weight": "core", "evidence": evidence}


def test_guard_drops_fabricated_number():
    """真实案例：原文没有「32张GPU」「3000万参数」→ 含这些数字的要点丢弃。"""
    points = [
        _pt("自建32张GPU算力集群", evidence="我们自建算力集群"),
        _pt("CTO有3000万参数模型训练经验", evidence="CTO 曾负责推荐系统"),
    ]
    assert svc._filter_grounded_points(points, _SOURCE) == []


def test_guard_drops_numeric_point_without_evidence():
    """含数字但没给出处的要点 → 丢弃（数据类主张必须可溯源）。"""
    points = [_pt("毛利率58%")]
    assert svc._filter_grounded_points(points, _SOURCE) == []


def test_guard_drops_fabricated_evidence():
    """出处对不上原文 → 丢弃（拦数字真实但指标串号的情况）。"""
    points = [_pt("客户留存率58%", evidence="客户留存率58%")]
    assert svc._filter_grounded_points(points, _SOURCE) == []


def test_guard_keeps_grounded_numeric_point():
    points = [_pt("毛利率58%", evidence="毛利率58%")]
    kept = svc._filter_grounded_points(points, _SOURCE)
    assert len(kept) == 1


def test_guard_keeps_non_numeric_point_without_evidence():
    """不含数字的定性要点，没有出处也保留（避免过度过滤）。"""
    points = [_pt("团队来自一线大厂")]
    kept = svc._filter_grounded_points(points, _SOURCE)
    assert len(kept) == 1
