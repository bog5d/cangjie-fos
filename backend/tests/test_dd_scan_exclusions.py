"""现场实测反馈 hotfix（2026-06-19）——扫描排除派生缓存 + 摘要失败优雅降级。

来源：科sir 现场实测 issue（_cangjie_预处理_md 二次入库污染 / Key 失效致可读文件不入库）。
"""
from __future__ import annotations

from cangjie_fos.services import dd_index_service as idx
from cangjie_fos.services.db_base import _connect


def _rows(folder: str) -> list[dict]:
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT filename, summary, institution_subfolder FROM dd_asset_index WHERE folder_root = ?",
            (folder,),
        ).fetchall()]


def test_scan_excludes_cangjie_internal_dir(tmp_path, monkeypatch):
    """预热产物 _cangjie_预处理_md/ 不得被二次扫描入库（P1：污染候选集）。"""
    monkeypatch.setattr(idx, "_llm_summarize", lambda n, t: "摘要")
    # 原始材料 2 份
    (tmp_path / "泽天湖南_增值税申报表.txt").write_text("增值税申报表正文", encoding="utf-8")
    (tmp_path / "四川_成本结构.txt").write_text("成本结构正文", encoding="utf-8")
    # 预热派生 md（应被排除）
    md = tmp_path / "_cangjie_预处理_md" / "泽天湖南"
    md.mkdir(parents=True)
    (md / "泽天湖南_增值税申报表.txt.md").write_text("# 派生md", encoding="utf-8")
    (md / "四川_成本结构.txt.md").write_text("# 派生md", encoding="utf-8")

    res = idx.scan_and_index_folder(str(tmp_path), "zt")
    assert res["indexed"] == 2, "只应索引 2 份原始材料，派生 md 被排除"

    rows = _rows(str(tmp_path))
    assert len(rows) == 2
    assert all("_cangjie_" not in (r["institution_subfolder"] or "") for r in rows)
    assert not any(r["filename"].endswith(".md") for r in rows)


def test_scan_keeps_file_when_summary_fails(tmp_path, monkeypatch):
    """摘要 LLM 失败（如 Key 401）不应让可读文件整份不入库（P2：降级 summary=None）。"""
    def boom(name, text):
        raise RuntimeError("Error code: 401 - Authentication Fails ... invalid")
    monkeypatch.setattr(idx, "_llm_summarize", boom)
    (tmp_path / "泽天湖南_2021年12月增值税申报表.txt").write_text("申报表正文", encoding="utf-8")

    res = idx.scan_and_index_folder(str(tmp_path), "zt2")
    assert res["indexed"] == 1
    assert res["failed"] == 0
    rows = _rows(str(tmp_path))
    assert len(rows) == 1
    assert rows[0]["summary"] is None  # 摘要降级为空，但文件已入库
