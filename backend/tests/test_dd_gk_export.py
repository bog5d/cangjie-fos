"""
TDD：尽调 gk 模式 F2（按问题归档导出）+ F5（命名确认）。

F2：每条需求一个子文件夹「问题NN_对方问题名」，匹配文件拷进去；
    匹配不到的不建空文件夹、进缺失清单.txt。
    多文件：只拷 user_confirmed 勾选项（通过 extra_files_json 多选）。

F5：导出时可传入 folder_name_overrides（item_id → 自定义文件夹名），
    用于「统一用对方问题名命名」或单条手动改名。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


def _make_session_with_items(tmp_path, items_spec):
    """造一个 session，items_spec: list of (item_no, requirement, matched_path)。"""
    from cangjie_fos.services.dd_match_service import create_match_session
    from cangjie_fos.services.db_base import _connect

    items = [
        {"item_no": no, "category": "基本", "requirement": req}
        for no, req, _ in items_spec
    ]
    sid = create_match_session("gk", "c.xlsx", str(tmp_path), items)

    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, item_no FROM dd_match_items WHERE session_id = ? ORDER BY item_no",
            (sid,),
        ).fetchall()
        id_by_no = {r["item_no"]: r["id"] for r in rows}
        for no, req, matched in items_spec:
            if matched:
                conn.execute(
                    "UPDATE dd_match_items SET matched_file_path = ?, "
                    "matched_filename = ?, confidence = 0.9 WHERE id = ?",
                    (str(matched), Path(matched).name, id_by_no[no]),
                )
    return sid, id_by_no


def test_export_by_question_creates_per_question_folders(tmp_path):
    """每条有匹配的需求 → 一个「问题NN_xxx」子文件夹，文件落位。"""
    from cangjie_fos.services.dd_export_service import export_by_question

    f1 = tmp_path / "2024财报.txt"; f1.write_text("财报", encoding="utf-8")
    f2 = tmp_path / "营业执照.txt"; f2.write_text("执照", encoding="utf-8")
    sid, _ = _make_session_with_items(tmp_path, [
        ("1", "近三年财务报表", f1),
        ("2", "营业执照", f2),
    ])

    out = tmp_path / "导出"
    result = export_by_question(sid, str(out))

    assert result["exported"] == 2
    folders = sorted(p.name for p in out.iterdir() if p.is_dir())
    assert any("财务报表" in f for f in folders), f"应有财务报表问题文件夹，实际 {folders}"
    assert any("营业执照" in f for f in folders)
    # 文件确实拷进对应文件夹
    fin = next(p for p in out.iterdir() if p.is_dir() and "财务报表" in p.name)
    assert (fin / "2024财报.txt").exists()


def test_export_missing_goes_to_gap_report_not_empty_folder(tmp_path):
    """无匹配的需求不建空文件夹，进缺失清单.txt。"""
    from cangjie_fos.services.dd_export_service import export_by_question

    f1 = tmp_path / "2024财报.txt"; f1.write_text("财报", encoding="utf-8")
    sid, _ = _make_session_with_items(tmp_path, [
        ("1", "近三年财务报表", f1),
        ("2", "审计报告", None),  # 无匹配
    ])

    out = tmp_path / "导出"
    result = export_by_question(sid, str(out))

    assert result["exported"] == 1
    assert result["missing"] == 1
    folders = [p.name for p in out.iterdir() if p.is_dir()]
    assert not any("审计报告" in f for f in folders), "无匹配项不应建空文件夹"
    gap = (out / "缺失清单.txt").read_text(encoding="utf-8")
    assert "审计报告" in gap


def test_export_folder_name_override(tmp_path):
    """F5：folder_name_overrides 指定的名字应用于子文件夹命名。"""
    from cangjie_fos.services.dd_export_service import export_by_question

    f1 = tmp_path / "2024财报.txt"; f1.write_text("财报", encoding="utf-8")
    sid, id_by_no = _make_session_with_items(tmp_path, [
        ("1", "近三年财务报表", f1),
    ])

    out = tmp_path / "导出"
    overrides = {id_by_no["1"]: "Q1_机构要的财报"}
    export_by_question(sid, str(out), folder_name_overrides=overrides)

    folders = [p.name for p in out.iterdir() if p.is_dir()]
    assert any("机构要的财报" in f for f in folders), f"应用自定义名，实际 {folders}"


def test_export_multi_file_per_question(tmp_path):
    """一条需求多文件（extra_files_json）→ 全部拷进同一问题文件夹。"""
    from cangjie_fos.services.dd_export_service import export_by_question
    from cangjie_fos.services.db_base import _connect
    import json

    f2022 = tmp_path / "2022财报.txt"; f2022.write_text("a", encoding="utf-8")
    f2023 = tmp_path / "2023财报.txt"; f2023.write_text("b", encoding="utf-8")
    f2024 = tmp_path / "2024财报.txt"; f2024.write_text("c", encoding="utf-8")
    sid, id_by_no = _make_session_with_items(tmp_path, [
        ("1", "近三年财务报表", f2024),
    ])
    # 追加两个额外文件
    with _connect() as conn:
        conn.execute(
            "UPDATE dd_match_items SET extra_files_json = ? WHERE id = ?",
            (json.dumps([
                {"file_path": str(f2022), "filename": "2022财报.txt"},
                {"file_path": str(f2023), "filename": "2023财报.txt"},
            ]), id_by_no["1"]),
        )

    out = tmp_path / "导出"
    result = export_by_question(sid, str(out))

    fin = next(p for p in out.iterdir() if p.is_dir() and "财务报表" in p.name)
    names = sorted(p.name for p in fin.iterdir())
    assert names == ["2022财报.txt", "2023财报.txt", "2024财报.txt"], (
        f"三份财报都应拷入，实际 {names}"
    )
    assert result["exported"] == 3
