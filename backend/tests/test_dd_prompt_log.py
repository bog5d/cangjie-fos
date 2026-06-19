"""开发者可见运行时 prompt — 落库 + 各阶段埋点测试。"""
from __future__ import annotations

from cangjie_fos.services import dd_prompt_log as plog
from cangjie_fos.services import dd_clarify_service as clarify
from cangjie_fos.services import dd_match_service as dms
from cangjie_fos.services.dd_match_service import create_match_session
from cangjie_fos.services.db_base import _connect


def test_record_and_get_prompt():
    plog.record_prompt("s1", "matching", "铁律 prompt 内容")
    plog.record_prompt("s1", "clarify", "澄清 prompt 内容")
    rows = plog.get_prompts("s1")
    stages = [r["stage"] for r in rows]
    assert stages == ["clarify", "matching"]  # 固定顺序
    assert rows[0]["label"] == "解析后·AI自检澄清"
    assert "澄清 prompt" in rows[0]["prompt_text"]


def test_record_replace_keeps_latest():
    plog.record_prompt("s2", "matching", "旧")
    plog.record_prompt("s2", "matching", "新")
    rows = plog.get_prompts("s2")
    assert len(rows) == 1 and rows[0]["prompt_text"] == "新"


def test_record_truncates():
    plog.record_prompt("s3", "verifying", "x" * 50000)
    assert len(plog.get_prompts("s3")[0]["prompt_text"]) == plog.MAX_PROMPT_CHARS


def test_record_empty_session_safe():
    plog.record_prompt(None, "matching", "x")
    plog.record_prompt("", "matching", "x")
    assert plog.get_prompts("") == []


def test_clarify_records_prompt(monkeypatch):
    """生成澄清问题时记录 clarify prompt（用真 _llm_clarify + mock client 抛错也应已记录）。"""
    sid = create_match_session(
        "zt", "清单", "/d", [{"item_no": "1", "category": "财务", "requirement": "审计报告"}],
        context_note="背景X",
    )

    # 用真 _llm_clarify：mock client 让 LLM 调用失败，但 prompt 记录发生在调用前
    def _boom():
        raise RuntimeError("down")
    monkeypatch.setattr(clarify, "get_dd_llm_client", _boom)
    clarify.generate_clarifications(sid)

    rows = plog.get_prompts(sid)
    clarify_rows = [r for r in rows if r["stage"] == "clarify"]
    assert clarify_rows, "应记录 clarify prompt"
    assert "背景X" in clarify_rows[0]["prompt_text"]      # 注入的背景可见
    assert "审计报告" in clarify_rows[0]["prompt_text"]   # 需求清单可见


def test_matching_records_prompt(monkeypatch):
    """run_matching 跑首批匹配时记录 matching prompt（含铁律 + 注入背景）。"""
    import uuid, time
    folder = "/d/plog"
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_asset_index
               (id, folder_root, file_path, filename, file_type, summary, readable, indexed_at)
               VALUES (?, ?, ?, '审计报告.pdf', '.pdf', '审计', 1, ?)""",
            (str(uuid.uuid4()), folder, f"{folder}/审计报告.pdf", time.time()),
        )
    sid = create_match_session(
        "zt", "清单", folder, [{"item_no": "1", "category": "财务", "requirement": "审计报告"}],
        context_note="多主体：泽天/四川",
    )
    # mock 批量匹配的 LLM 客户端，返回空候选（不影响 prompt 记录——记录在调用前）
    monkeypatch.setattr(dms, "_refine_session_matches", lambda *a, **k: None)

    class _FakeResp:
        class _C:
            class _M:
                content = "{}"
            message = _M()
        choices = [_C()]

    class _FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    return _FakeResp()
    monkeypatch.setattr(dms, "get_dd_llm_client", lambda: _FakeClient())

    dms.run_matching(sid, folder)
    rows = plog.get_prompts(sid)
    matching_rows = [r for r in rows if r["stage"] == "matching"]
    assert matching_rows, "应记录 matching prompt"
    assert "多主体：泽天/四川" in matching_rows[0]["prompt_text"]  # 注入背景可见
