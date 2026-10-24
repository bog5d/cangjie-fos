"""
P0 稳健性补丁 TDD 测试（三组）：

Patch 1 — SQLite 每日快照备份（db_backup.py）
  防单文件损坏/误删导致全部数据丢失。

Patch 2 — 匹配异常不再误标"完成"（dd_match_service.run_matching）
  run_matching 内部抛异常时，session 状态应为 'failed' 而非 'matched'，
  避免前端/导出把残缺结果当成功结果。

Patch 3 — LLM 全失败降级关键词匹配（dd_match_service._keyword_fallback_match）
  DeepSeek 三次重试全失败时，不再整批静默归零，
  而是用汉字 bigram 关键词兜底匹配，结果标注"⚠️ AI暂不可用，关键词匹配"。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ════════════════════════════════════════════════════════════════════
# Patch 1 — SQLite 快照备份
# ════════════════════════════════════════════════════════════════════

def _make_db_with_data(path: Path) -> None:
    """造一个含数据的小型 SQLite 文件。"""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    conn.executemany("INSERT INTO t (name) VALUES (?)", [("机构甲",), ("机构乙",)])
    conn.commit()
    conn.close()


def test_create_snapshot_creates_valid_copy(tmp_path):
    """快照应是源库的一致副本，能独立打开且数据完整。"""
    from cangjie_fos.services import db_backup

    src = tmp_path / "live.sqlite"
    _make_db_with_data(src)
    backup_dir = tmp_path / "backups"

    snap = db_backup.create_snapshot(db_path=str(src), backup_dir=backup_dir)

    assert snap.exists(), "快照文件应被创建"
    assert snap.parent == backup_dir
    # 快照可独立打开，数据与源一致
    conn = sqlite3.connect(str(snap))
    rows = conn.execute("SELECT name FROM t ORDER BY id").fetchall()
    conn.close()
    assert [r[0] for r in rows] == ["机构甲", "机构乙"]


def test_snapshot_is_independent_of_source(tmp_path):
    """快照生成后，源库继续写入不应影响已生成的快照（一致性快照）。"""
    from cangjie_fos.services import db_backup

    src = tmp_path / "live.sqlite"
    _make_db_with_data(src)
    backup_dir = tmp_path / "backups"

    snap = db_backup.create_snapshot(db_path=str(src), backup_dir=backup_dir)

    # 源库再写一条
    conn = sqlite3.connect(str(src))
    conn.execute("INSERT INTO t (name) VALUES (?)", ("机构丙",))
    conn.commit()
    conn.close()

    # 快照仍只有 2 条
    snap_conn = sqlite3.connect(str(snap))
    count = snap_conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    snap_conn.close()
    assert count == 2, "快照应是生成时刻的冻结副本，不随源库变化"


def test_prune_keeps_only_n_newest(tmp_path):
    """超过 keep 数量时，仅保留最新的 N 份，删除最旧的。"""
    from cangjie_fos.services import db_backup

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    # 造 10 份按时间戳命名的假快照（名字字典序 == 时间序）
    names = [f"fos_snapshot_202606{day:02d}_120000.sqlite" for day in range(1, 11)]
    for n in names:
        (backup_dir / n).write_text("x")

    deleted = db_backup.prune_snapshots(keep=7, backup_dir=backup_dir)

    remaining = sorted(p.name for p in db_backup.list_snapshots(backup_dir))
    assert len(remaining) == 7, f"应只剩 7 份，实际 {len(remaining)}"
    assert len(deleted) == 3, f"应删除最旧的 3 份，实际 {len(deleted)}"
    # 保留的应是最新的 7 份（day 04..10）
    assert remaining == sorted(names[3:])


def test_prune_noop_when_under_limit(tmp_path):
    """数量未超 keep 时不删除任何文件。"""
    from cangjie_fos.services import db_backup

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for day in range(1, 4):
        (backup_dir / f"fos_snapshot_202606{day:02d}_120000.sqlite").write_text("x")

    deleted = db_backup.prune_snapshots(keep=7, backup_dir=backup_dir)
    assert deleted == []
    assert len(db_backup.list_snapshots(backup_dir)) == 3


def test_run_daily_backup_creates_and_prunes(tmp_path):
    """run_daily_backup 端到端：生成一份新快照并执行清理，不抛异常。"""
    from cangjie_fos.services import db_backup

    src = tmp_path / "live.sqlite"
    _make_db_with_data(src)
    backup_dir = tmp_path / "backups"

    snap = db_backup.run_daily_backup(
        keep=7, db_path=str(src), backup_dir=backup_dir
    )
    assert snap is not None and snap.exists()
    assert len(db_backup.list_snapshots(backup_dir)) == 1


# ════════════════════════════════════════════════════════════════════
# Patch 2 — 匹配异常不再误标"完成"
# ════════════════════════════════════════════════════════════════════

def _get_session_status(session_id: str) -> str | None:
    from cangjie_fos.services.db_base import _connect
    with _connect() as conn:
        row = conn.execute(
            "SELECT status FROM dd_match_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return row["status"] if row else None


def test_matching_success_marks_matched():
    """正常匹配完成后 session 状态应为 'matched'。"""
    from cangjie_fos.services.dd_match_service import (
        create_match_session, run_matching,
    )
    items = [{"item_no": "1", "category": "基本", "requirement": "营业执照"}]
    session_id = create_match_session("t", "c.xlsx", "/folder", items)

    index_rows = [{"file_path": "/folder/营业执照.pdf",
                   "filename": "营业执照.pdf", "summary": "营业执照"}]

    def fake_batch(*args, **kwargs):
        return {items_id: {} for items_id in []}  # 空，但不抛异常

    with patch("cangjie_fos.services.dd_match_service._get_index_for_folder",
               return_value=index_rows):
        with patch("cangjie_fos.services.dd_match_service._llm_batch_match",
                   return_value={}):
            run_matching(session_id, "/folder")

    assert _get_session_status(session_id) == "matched"


def test_matching_exception_marks_failed():
    """run_matching 内部抛异常时，session 应标记 'failed'，不能是 'matched'。"""
    from cangjie_fos.services.dd_match_service import (
        create_match_session, run_matching,
    )
    items = [{"item_no": "1", "category": "基本", "requirement": "营业执照"}]
    session_id = create_match_session("t", "c.xlsx", "/folder", items)

    index_rows = [{"file_path": "/folder/x.pdf", "filename": "x.pdf", "summary": ""}]

    def boom(*args, **kwargs):
        raise RuntimeError("数据库写入炸了")

    with patch("cangjie_fos.services.dd_match_service._get_index_for_folder",
               return_value=index_rows):
        with patch("cangjie_fos.services.dd_match_service._llm_batch_match",
                   side_effect=boom):
            run_matching(session_id, "/folder")  # 不应向外抛

    assert _get_session_status(session_id) == "failed", (
        "匹配异常时不应把 session 标成 matched（否则前端把残缺当完成）"
    )


def test_matching_no_index_marks_matched():
    """无已索引文件（合法的'无可匹配'）仍应标记 matched，而非 failed。"""
    from cangjie_fos.services.dd_match_service import (
        create_match_session, run_matching,
    )
    items = [{"item_no": "1", "category": "基本", "requirement": "营业执照"}]
    session_id = create_match_session("t", "c.xlsx", "/empty", items)

    with patch("cangjie_fos.services.dd_match_service._get_index_for_folder",
               return_value=[]):
        run_matching(session_id, "/empty")

    assert _get_session_status(session_id) == "matched"


# ════════════════════════════════════════════════════════════════════
# Patch 3 — LLM 全失败降级关键词匹配
# ════════════════════════════════════════════════════════════════════

def test_keyword_fallback_unit():
    """_keyword_fallback_match：直接单元测试，相关文件应被命中并标注关键词。"""
    from cangjie_fos.services.dd_match_service import _keyword_fallback_match

    batch = [{"id": "id-1", "requirement": "营业执照扫描件"}]
    batch_rows = [
        {"file_path": "/f/营业执照.pdf", "filename": "营业执照.pdf", "summary": "公司营业执照"},
        {"file_path": "/f/无关文档.pdf", "filename": "无关文档.pdf", "summary": "其他内容"},
    ]
    result = _keyword_fallback_match(batch, batch_rows)

    assert "id-1" in result
    cands = result["id-1"]["candidates"]
    assert len(cands) >= 1
    # 命中的应是营业执照那份（file_index 0）
    assert cands[0]["file_index"] == 0
    assert "关键词" in cands[0]["reason"]


def test_keyword_fallback_no_match_returns_empty_candidates():
    """需求与所有文件都不相关时，降级匹配返回空候选（不硬塞）。"""
    from cangjie_fos.services.dd_match_service import _keyword_fallback_match

    batch = [{"id": "id-1", "requirement": "完全无关的需求描述"}]
    batch_rows = [
        {"file_path": "/f/营业执照.pdf", "filename": "营业执照.pdf", "summary": "营业执照"},
    ]
    result = _keyword_fallback_match(batch, batch_rows)
    # 无关需求不应被硬匹配；id 可不出现，或 candidates 为空
    if "id-1" in result:
        assert result["id-1"]["candidates"] == []


def test_llm_down_falls_back_to_keyword(monkeypatch):
    """
    LLM 客户端持续抛异常（服务宕机）时，run_matching 不应整批归零，
    而是用关键词兜底，相关项仍能拿到匹配文件 + 降级置信度 + 关键词标注。
    """
    from cangjie_fos.services.dd_match_service import (
        create_match_session, run_matching, get_session_items,
    )

    # 避免 call_with_retry 真实退避 sleep 拖慢测试
    monkeypatch.setattr(
        "cangjie_fos.services.dd_llm_client.time.sleep", lambda *_a, **_k: None
    )

    items = [{"item_no": "1", "category": "基本", "requirement": "营业执照扫描件"}]
    session_id = create_match_session("t", "c.xlsx", "/folder", items)

    index_rows = [
        {"file_path": "/folder/营业执照.pdf", "filename": "营业执照.pdf", "summary": "公司营业执照"},
        {"file_path": "/folder/无关.pdf", "filename": "无关.pdf", "summary": "其他"},
    ]

    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = RuntimeError("LLM 服务不可用")

    with patch("cangjie_fos.services.dd_match_service._get_index_for_folder",
               return_value=index_rows):
        with patch("cangjie_fos.services.dd_match_service.get_dd_llm_client",
                   return_value=fake_client):
            run_matching(session_id, "/folder")

    result = get_session_items(session_id)
    item = result[0]
    assert item["matched_filename"] == "营业执照.pdf", "关键词兜底应匹配到营业执照"
    assert item["confidence"] is not None and item["confidence"] > 0, "降级置信度应非零"
    assert "关键词" in (item["match_reason"] or ""), "应标注为关键词降级匹配"
    # session 仍应标记完成（降级也是一种完成，不是 failed）
    assert _get_session_status(session_id) == "matched"
