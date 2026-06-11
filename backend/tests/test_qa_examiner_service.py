"""需求01·B1/B2 — 答疑出题器 + 答案评估器测试（DB 隔离 + LLM mock）。"""
from __future__ import annotations

from cangjie_fos.services import qa_examiner_service as ex
from cangjie_fos.services import qa_grader_service as gr


_AI_QUESTIONS = [
    {"category": "财务", "question_text": "你们的毛利率为什么这么低？", "answer_points": ["规模效应", "成本结构"]},
    {"category": "竞争", "question_text": "和头部玩家比壁垒在哪？", "answer_points": ["数据飞轮", "切换成本"]},
]


def test_generate_questions_basic(monkeypatch):
    monkeypatch.setattr(ex, "_llm_generate_questions", lambda m, s, r: [dict(q) for q in _AI_QUESTIONS])
    qs = ex.generate_questions("公司材料……", tenant_id="zt", sector="AI", limit=12)
    assert len(qs) == 2
    assert qs[0]["category"] == "财务"
    assert all(q["source"] == "ai" for q in qs)
    assert qs[0]["answer_points"]


def test_generate_dedups_similar(monkeypatch):
    """AI 生成与历史库高度相似的问题应被去重。"""
    # 先把一个问题沉淀进库
    ex.upsert_question_bank("zt", "你们的毛利率为什么这么低？", ["规模效应"], category="财务", sector="AI")
    # AI 又生成几乎一样的问题 → 应被过滤
    monkeypatch.setattr(ex, "_llm_generate_questions", lambda m, s, r: [
        {"category": "财务", "question_text": "你们的毛利率为什么这么低呀？", "answer_points": []},
        {"category": "团队", "question_text": "核心团队上一段创业经历如何？", "answer_points": ["背景"]},
    ])
    qs = ex.generate_questions("材料", tenant_id="zt", sector="AI", limit=12)
    texts = [q["question_text"] for q in qs]
    # 历史那条在（migrated），团队那条新增，毛利率重复的被滤掉
    assert any("团队" in q["category"] for q in qs)
    assert sum(1 for t in texts if "毛利率" in t) == 1


def test_upsert_increments_hit_count(monkeypatch):
    qid1 = ex.upsert_question_bank("zt", "市场规模有多大？", ["TAM", "SAM"], sector="AI")
    qid2 = ex.upsert_question_bank("zt", "市场规模到底有多大？", [], sector="AI")
    assert qid1 == qid2  # 相似 → 同一条
    from cangjie_fos.services.db_base import _connect
    with _connect() as conn:
        hit = conn.execute("SELECT hit_count FROM qa_question_bank WHERE id = ?", (qid1,)).fetchone()[0]
    assert hit == 2


def test_migrate_history_ordered_by_hit(monkeypatch):
    """历史迁移按 hit_count 降序。"""
    ex.upsert_question_bank("zt", "冷门问题ABCDEF", [], sector="Bio")
    hot = ex.upsert_question_bank("zt", "热门问题UVWXYZ", [], sector="Bio")
    ex.upsert_question_bank("zt", "热门问题UVWXYZ", [], sector="Bio")  # hit=2
    monkeypatch.setattr(ex, "_llm_generate_questions", lambda m, s, r: [])
    qs = ex.generate_questions("材料", tenant_id="zt", sector="Bio", limit=12)
    assert qs[0]["question_text"] == "热门问题UVWXYZ"  # hit 高的在前


# ── 答案评估器 ────────────────────────────────────────────────

def test_grade_answer_hits(monkeypatch):
    monkeypatch.setattr(gr, "_llm_grade", lambda q, ap, t: {
        "score": 80, "hit_points": ["规模效应"], "missed_points": ["成本结构"],
        "logic_flaws": [], "risk_statements": ["承诺三年盈利过于乐观"], "feedback": "答得还行",
    })
    r = gr.grade_answer("毛利率为何低？", ["规模效应", "成本结构"], "因为我们有规模效应……")
    assert r["score"] == 80.0
    assert "规模效应" in r["hit_points"]
    assert "成本结构" in r["missed_points"]
    assert r["risk_statements"]


def test_grade_empty_transcript():
    r = gr.grade_answer("问题", ["要点A", "要点B"], "")
    assert r["score"] == 0.0
    assert r["missed_points"] == ["要点A", "要点B"]


def test_grade_score_fallback_from_ratio(monkeypatch):
    """LLM 未给 score 时，按命中率兜底计算。"""
    monkeypatch.setattr(gr, "_llm_grade", lambda q, ap, t: {
        "hit_points": ["A"], "missed_points": ["B"],
    })
    r = gr.grade_answer("问题", ["A", "B"], "回答提到A")
    assert r["score"] == 50.0  # 1/2 命中


def test_grade_llm_failure_safe(monkeypatch):
    monkeypatch.setattr(gr, "_llm_grade", lambda q, ap, t: {})
    r = gr.grade_answer("问题", ["A"], "有内容的回答")
    assert "score" in r
    assert r["score"] == 0.0  # 无命中
