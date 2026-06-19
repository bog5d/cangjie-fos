"""评估器反思回环（Evaluator→retrieval 有界回边）测试。

判「不满足」→ 从候选里换下一个重判 → 命中即采用并改匹配文件；封顶 + 受 LLM 预算约束。
"""
from __future__ import annotations

import json
import time
import uuid

from cangjie_fos.services import dd_match_service as dms
from cangjie_fos.services.dd_match_service import create_match_session, _refine_session_matches
from cangjie_fos.services.db_base import _connect


def _seed_index(folder: str, files: list[tuple[str, str]]):
    """(file_path, content_text)。"""
    with _connect() as conn:
        for path, content in files:
            conn.execute(
                """INSERT INTO dd_asset_index
                   (id, folder_root, file_path, filename, file_type, summary,
                    readable, indexed_at, content_text)
                   VALUES (?, ?, ?, ?, '.txt', '', 1, ?, ?)""",
                (str(uuid.uuid4()), folder, path, path.split("/")[-1], time.time(), content),
            )


def _mk_item_with_candidates(session_id: str, requirement: str, primary: str,
                             primary_name: str, alt: str, alt_name: str):
    """造一条已匹配项：主候选 primary + 备选 alt（candidates_json）。"""
    iid = str(uuid.uuid4())
    cands = json.dumps([
        {"file_path": primary, "filename": primary_name, "confidence": 0.6},
        {"file_path": alt, "filename": alt_name, "confidence": 0.5},
    ], ensure_ascii=False)
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_match_items
               (id, session_id, item_no, category, requirement, matched_file_path,
                matched_filename, confidence, candidates_json)
               VALUES (?, ?, '1', '财务', ?, ?, ?, 0.6, ?)""",
            (iid, session_id, requirement, primary, primary_name, cands),
        )
    return iid


def _item(iid: str) -> dict:
    with _connect() as conn:
        return dict(conn.execute("SELECT * FROM dd_match_items WHERE id=?", (iid,)).fetchone())


def test_reflection_switches_to_alt_candidate(monkeypatch):
    """主候选判不满足、备选满足 → 换到备选并判绿，匹配文件被改写。"""
    folder = "/d/reflect1"
    _seed_index(folder, [
        ("/d/reflect1/2022申报表.txt", "2022年增值税申报表"),
        ("/d/reflect1/2021申报表.txt", "2021年增值税申报表"),
    ])
    sid = create_match_session("zt", "清单", folder, [], context_note="")
    iid = _mk_item_with_candidates(
        sid, "泽天湖南2021年12月增值税申报表",
        "/d/reflect1/2022申报表.txt", "2022申报表.txt",
        "/d/reflect1/2021申报表.txt", "2021申报表.txt",
    )

    # 主候选(2022)判不满足；备选(2021)判满足
    def fake_refine(client, requirement, filename, content, context="", session_id=None):
        if "2021" in (content or ""):
            return {"satisfies": True, "confidence": 0.9, "evidence": "2021年匹配"}
        return {"satisfies": False, "confidence": 0.2, "evidence": "年份不符"}
    monkeypatch.setattr(dms, "_llm_refine_candidate", fake_refine)
    monkeypatch.setattr(dms, "get_dd_llm_client", lambda: object())

    _refine_session_matches(sid)

    it = _item(iid)
    assert it["matched_file_path"] == "/d/reflect1/2021申报表.txt"  # 换到备选
    assert it["verdict"] == "green"
    assert "🔁 反思换候选" in (it["evidence"] or "")
    # 反思轮次落库
    with _connect() as conn:
        ri = conn.execute("SELECT reflection_iter FROM dd_match_sessions WHERE session_id=?", (sid,)).fetchone()[0]
    assert ri >= 1


def test_reflection_all_fail_stays_red(monkeypatch):
    """主候选与备选都不满足 → 仍判红，不乱换。"""
    folder = "/d/reflect2"
    _seed_index(folder, [
        ("/d/reflect2/a.txt", "无关内容A"),
        ("/d/reflect2/b.txt", "无关内容B"),
    ])
    sid = create_match_session("zt", "清单", folder, [], context_note="")
    iid = _mk_item_with_candidates(
        sid, "商业计划书", "/d/reflect2/a.txt", "a.txt", "/d/reflect2/b.txt", "b.txt",
    )
    monkeypatch.setattr(dms, "_llm_refine_candidate",
                        lambda *a, **k: {"satisfies": False, "confidence": 0.1, "evidence": "不符"})
    monkeypatch.setattr(dms, "get_dd_llm_client", lambda: object())

    _refine_session_matches(sid)
    it = _item(iid)
    assert it["verdict"] == "red"
    # 全失败不改匹配文件（保留主候选）
    assert it["matched_file_path"] == "/d/reflect2/a.txt"


def test_no_reflection_when_primary_satisfies(monkeypatch):
    """主候选直接满足 → 不触发反思（不浪费 LLM 调用）。"""
    folder = "/d/reflect3"
    _seed_index(folder, [("/d/reflect3/ok.txt", "本审计报告显示公司财务状况良好")])
    sid = create_match_session("zt", "清单", folder, [], context_note="")
    iid = _mk_item_with_candidates(
        sid, "审计报告", "/d/reflect3/ok.txt", "ok.txt", "/d/reflect3/ok.txt", "ok.txt",
    )
    calls = {"n": 0}
    def fake_refine(client, requirement, filename, content, context="", session_id=None):
        calls["n"] += 1
        return {"satisfies": True, "confidence": 0.95, "evidence": "满足"}
    monkeypatch.setattr(dms, "_llm_refine_candidate", fake_refine)
    monkeypatch.setattr(dms, "get_dd_llm_client", lambda: object())

    _refine_session_matches(sid)
    assert calls["n"] == 1  # 只判主候选一次，未反思
    assert _item(iid)["verdict"] == "green"


def test_parse_alt_candidates_excludes_current():
    cj = json.dumps([
        {"file_path": "/x/a.pdf", "filename": "a.pdf"},
        {"file_path": "/x/b.pdf", "filename": "b.pdf"},
    ])
    alts = dms._parse_alt_candidates(cj, exclude_path="/x/a.pdf")
    assert [a["file_path"] for a in alts] == ["/x/b.pdf"]
    assert dms._parse_alt_candidates(None, "/x/a.pdf") == []
    assert dms._parse_alt_candidates("坏JSON", "/x/a.pdf") == []
