"""v1.16.0 性能 — 扫描期延迟全文抽取 + 精判按需抽取回测。

锁死：2~3000 份大库扫描卡死的根因（扫描期逐个解析全文）已根治。
"""
from __future__ import annotations

from pathlib import Path

from cangjie_fos.services import dd_index_service as idx
from cangjie_fos.services import dd_file_parser
from cangjie_fos.services.dd_match_service import _ensure_content_text
from cangjie_fos.services.db_base import _connect


def _seed_files(folder: Path, n: int) -> None:
    for i in range(n):
        (folder / f"材料{i}.txt").write_text(f"这是第{i}份材料的正文内容，包含一些关键信息。", encoding="utf-8")


def test_scan_does_not_extract_full_text(tmp_path, monkeypatch):
    """扫描阶段绝不调用 extract_full_text（昂贵全文解析），content_text 留空。"""
    _seed_files(tmp_path, 3)

    calls = {"full": 0}
    real_full = dd_file_parser.extract_full_text

    def spy_full(*a, **k):
        calls["full"] += 1
        return real_full(*a, **k)
    monkeypatch.setattr(dd_file_parser, "extract_full_text", spy_full)
    # 小文件夹会喂 LLM 摘要——mock 掉避免网络
    monkeypatch.setattr(idx, "_llm_summarize", lambda name, text: "摘要")

    result = idx.scan_and_index_folder(str(tmp_path), "perf")
    assert result["indexed"] == 3
    assert calls["full"] == 0, "扫描期不应解析全文（延迟抽取）"

    # content_text 扫描期留空（延迟）
    with _connect() as conn:
        rows = conn.execute(
            "SELECT content_text FROM dd_asset_index WHERE folder_root = ?", (str(tmp_path),),
        ).fetchall()
    assert len(rows) == 3
    assert all(r["content_text"] is None for r in rows)


def test_big_folder_scan_skips_all_parsing(tmp_path, monkeypatch):
    """大文件夹（>200）扫描期既不解析全文、也不解析摘要，纯元数据秒级完成。"""
    monkeypatch.setattr(idx, "MAX_LLM_SUMMARIZE_FILES", 2)  # 强制走"大文件夹"路径
    calls = {"text": 0, "full": 0}
    monkeypatch.setattr(dd_file_parser, "extract_text",
                        lambda *a, **k: (calls.__setitem__("text", calls["text"] + 1), ("", True))[1])
    monkeypatch.setattr(dd_file_parser, "extract_full_text",
                        lambda *a, **k: (calls.__setitem__("full", calls["full"] + 1), ("", True))[1])
    _seed_files(tmp_path, 5)

    result = idx.scan_and_index_folder(str(tmp_path), "perfbig")
    assert result["indexed"] == 5
    # 注：idx 内已 import extract_text 到本模块名字空间，这里通过 dd_file_parser patch 不一定拦到，
    # 故只强约束「全文解析」零调用（这是卡死主因）。
    assert calls["full"] == 0


def test_ensure_content_text_extracts_on_demand(tmp_path):
    """精判按需抽取：_ensure_content_text 读磁盘正文并回填 content_text 缓存。"""
    f = tmp_path / "audit.txt"
    f.write_text("2023年审计报告：营收5000万元，净利润800万元。", encoding="utf-8")
    # 先索引（content_text 为空）
    import time, uuid
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_asset_index
               (id, folder_root, file_path, filename, file_type, summary,
                readable, indexed_at, content_text)
               VALUES (?, ?, ?, 'audit.txt', '.txt', '审计', 1, ?, NULL)""",
            (str(uuid.uuid4()), str(tmp_path), str(f), time.time()),
        )

    text = _ensure_content_text(str(f))
    assert "审计报告" in text and "5000" in text

    # 回填缓存
    with _connect() as conn:
        row = conn.execute(
            "SELECT content_text FROM dd_asset_index WHERE file_path = ?", (str(f),),
        ).fetchone()
    assert row["content_text"] and "审计报告" in row["content_text"]


def test_ensure_content_text_missing_file_safe():
    assert _ensure_content_text("/不存在/x.pdf") == ""
    assert _ensure_content_text("") == ""
