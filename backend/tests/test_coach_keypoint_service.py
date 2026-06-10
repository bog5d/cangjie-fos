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
