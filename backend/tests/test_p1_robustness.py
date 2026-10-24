"""
P1 稳健性补丁 TDD 测试（四组）：

P1-A — Token 持久化（auth.py）
  服务重启后内存 _sessions 清空，token 仍能从 SQLite fos_sessions 表中恢复，
  避免所有用户被强制重新登录。

P1-B — 内存字典容量上限（dd_response.py）
  _scan_status / _match_status 只增不清会造成长期内存泄漏；
  超过 200 条时自动清除最旧条目，内存占用有界。

P1-C — LLM Prompt 长度上限（dd_match_service.py）
  批量匹配时，单条文件摘要超过 150 字符的被截断，防止
  50 条 × 长摘要把 DeepSeek 的上下文撑爆导致整批失败。

P1-D — 匹配进度 DB 降级（dd_response.py）
  服务重启后 _match_status 清空，前端仍能通过 /match-status 轮询
  拿到 DB 中存储的 session 终态（matched/failed），不会永久 not_found。
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest


# ════════════════════════════════════════════════════════════════════
# P1-A — Token 持久化
# ════════════════════════════════════════════════════════════════════

def test_token_survives_memory_clear():
    """登录后清空内存 _sessions，get_session 应能从 DB 中恢复 token。"""
    from cangjie_fos.api.routes import auth as auth_mod

    # 登录创建 token
    import uuid
    token = str(uuid.uuid4())
    sess = {"username": "zt001", "tenant_id": "zt", "login_at": time.time()}
    auth_mod._sessions[token] = sess
    auth_mod._save_session_to_db(token, sess)

    # 模拟重启：清空内存
    auth_mod._sessions.clear()
    assert token not in auth_mod._sessions

    # get_session 应降级读 DB，重新载入内存
    recovered = auth_mod.get_session(token)
    assert recovered is not None, "重启后 token 应能从 DB 恢复"
    assert recovered["username"] == "zt001"
    assert recovered["tenant_id"] == "zt"


def test_expired_token_not_restored_from_db():
    """已过期的 token（login_at 超过 TTL）不应从 DB 中恢复。"""
    from cangjie_fos.api.routes import auth as auth_mod

    import uuid
    token = str(uuid.uuid4())
    # 登录时间设为 100 小时前（远超 72 小时 TTL）
    old_login_at = time.time() - 100 * 3600
    sess = {"username": "zt001", "tenant_id": "zt", "login_at": old_login_at}
    auth_mod._save_session_to_db(token, sess)
    # 确保内存里没有
    auth_mod._sessions.pop(token, None)

    result = auth_mod.get_session(token)
    assert result is None, "过期 token 不应从 DB 恢复"


def test_logout_removes_from_db():
    """logout 后，token 应从 DB 中也删除，重启后不可恢复。"""
    from cangjie_fos.api.routes import auth as auth_mod

    import uuid
    token = str(uuid.uuid4())
    sess = {"username": "gk001", "tenant_id": "gk", "login_at": time.time()}
    auth_mod._sessions[token] = sess
    auth_mod._save_session_to_db(token, sess)

    # 注销
    auth_mod._delete_session_from_db(token)
    auth_mod._sessions.pop(token, None)

    result = auth_mod.get_session(token)
    assert result is None, "logout 后 DB 里的 token 应被删除"


# ════════════════════════════════════════════════════════════════════
# P1-B — 内存字典容量上限
# ════════════════════════════════════════════════════════════════════

def test_scan_status_dict_capped():
    """_scan_status 超过容量上限后，字典大小应保持有界（≤ MAX_SIZE）。"""
    from cangjie_fos.api.routes.dd_response import _evict_oldest, _MAX_STATUS_ENTRIES

    d: dict = {}
    # 写入 MAX + 50 条
    for i in range(_MAX_STATUS_ENTRIES + 50):
        d[f"scan_{i}"] = {"status": "done", "ts": i}
        _evict_oldest(d, _MAX_STATUS_ENTRIES)

    assert len(d) <= _MAX_STATUS_ENTRIES, (
        f"字典应不超过 {_MAX_STATUS_ENTRIES} 条，实际 {len(d)}"
    )


def test_match_status_dict_capped():
    """_match_status 超过容量上限后，字典大小应保持有界。"""
    from cangjie_fos.api.routes.dd_response import _evict_oldest, _MAX_STATUS_ENTRIES

    d: dict = {}
    for i in range(_MAX_STATUS_ENTRIES + 100):
        d[f"session_{i}"] = {"status": "running", "ts": i}
        _evict_oldest(d, _MAX_STATUS_ENTRIES)

    assert len(d) <= _MAX_STATUS_ENTRIES


def test_evict_removes_oldest_entries():
    """_evict_oldest 清除的是最旧（插入最早）的条目，不是随机删除。"""
    from cangjie_fos.api.routes.dd_response import _evict_oldest

    d: dict = {}
    for i in range(10):
        d[f"key_{i}"] = i

    # 上限设为 5，应保留最后 5 个
    _evict_oldest(d, 5)
    assert len(d) <= 5
    # 最新的 key_9 应还在
    assert "key_9" in d


# ════════════════════════════════════════════════════════════════════
# P1-C — LLM Prompt 长度上限
# ════════════════════════════════════════════════════════════════════

def test_long_summary_truncated_in_file_list():
    """构建文件列表文本时，超过 MAX_SUMMARY_CHARS 的摘要应被截断。"""
    from cangjie_fos.services.dd_match_service import _build_file_list_text, _MAX_SUMMARY_CHARS

    rows = [
        {"filename": "营业执照.pdf", "summary": "A" * 300},  # 超长摘要
        {"filename": "审计报告.pdf", "summary": "正常长度摘要"},
    ]
    text = _build_file_list_text(rows)

    # 超长摘要应被截断到 MAX_SUMMARY_CHARS
    lines = text.split("\n")
    long_line = lines[0]
    assert len(long_line) < 300 + 50, "超长摘要应被截断"
    assert "A" * (_MAX_SUMMARY_CHARS + 1) not in long_line, (
        f"单条摘要不应超过 {_MAX_SUMMARY_CHARS} 字符"
    )


def test_prompt_total_length_bounded():
    """50 条文件 × 超长摘要时，生成的文件列表文本仍在合理范围内（< 15000 字符）。"""
    from cangjie_fos.services.dd_match_service import _build_file_list_text

    rows = [
        {"filename": f"文件{i}.pdf", "summary": "B" * 500}
        for i in range(50)
    ]
    text = _build_file_list_text(rows)
    assert len(text) < 15_000, (
        f"50 条超长摘要的文件列表应 < 15000 字符，实际 {len(text)}"
    )


# ════════════════════════════════════════════════════════════════════
# P1-D — 匹配进度 DB 降级
# ════════════════════════════════════════════════════════════════════

def test_match_status_db_fallback():
    """内存 _match_status 无记录时，应降级读取 dd_match_sessions 表的 status。"""
    from cangjie_fos.api.routes.dd_response import _match_status
    from cangjie_fos.services.dd_match_service import create_match_session
    from fastapi.testclient import TestClient
    from cangjie_fos.main import create_app

    client = TestClient(create_app())

    items = [{"item_no": "1", "category": "基本", "requirement": "营业执照"}]
    session_id = create_match_session("t_fallback", "c.xlsx", "/folder", items)

    # 模拟重启：确保内存里没有这条记录
    _match_status.pop(session_id, None)

    resp = client.get(f"/api/v1/dd/sessions/{session_id}/match-status")
    assert resp.status_code == 200
    data = resp.json()

    assert data.get("source") == "db_fallback", (
        f"重启后应降级查 DB（source=db_fallback），实际: {data}"
    )
    assert data.get("status") in ("pending", "matched", "failed", "matching"), (
        f"DB 降级应返回合法 status，实际: {data}"
    )


def test_match_status_not_found_for_unknown_session():
    """不存在的 session_id 应返回 not_found（而不是 500 或其他错误）。"""
    from fastapi.testclient import TestClient
    from cangjie_fos.main import create_app

    client = TestClient(create_app())

    resp = client.get("/api/v1/dd/sessions/nonexistent_xyz_session/match-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "not_found"
