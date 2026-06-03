"""
TDD：尽调 gk 模式 F1 — 多机构池扫描 + 去重 + 布局检测 + 加密标记。

机构问答响应引擎 阶段一。材料库布局：
  flat            — 文件平铺在一个大文件夹（zt 结构，现有行为）
  per_institution — 根目录下按机构名分子文件夹（gk 结构）

per_institution 时：
  - 递归收所有机构子文件夹的文件，记录来源子文件夹
  - 同名文件跨子文件夹去重，只留 mtime 最新一份
  - 加密文件（打不开）标记 is_encrypted=1，仍靠文件名参与匹配
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest


# ════════════════════════════════════════════════════════════════════
# 布局检测
# ════════════════════════════════════════════════════════════════════

def test_detect_layout_flat(tmp_path):
    """文件平铺在根目录 → flat。"""
    from cangjie_fos.services.dd_gk_service import detect_folder_layout

    (tmp_path / "2024财报.txt").write_text("x", encoding="utf-8")
    (tmp_path / "营业执照.txt").write_text("x", encoding="utf-8")

    assert detect_folder_layout(str(tmp_path)) == "flat"


def test_detect_layout_per_institution(tmp_path):
    """根目录下按机构名分多个子文件夹 → per_institution。"""
    from cangjie_fos.services.dd_gk_service import detect_folder_layout

    for inst in ["瑞源正方", "鼎晖投资", "红杉资本"]:
        d = tmp_path / inst
        d.mkdir()
        (d / "2024财报.txt").write_text("x", encoding="utf-8")

    assert detect_folder_layout(str(tmp_path)) == "per_institution"


def test_detect_layout_ignores_system_dirs(tmp_path):
    """只有备份/temp 等系统目录时不应误判为 per_institution。"""
    from cangjie_fos.services.dd_gk_service import detect_folder_layout

    (tmp_path / "备份").mkdir()
    (tmp_path / "temp").mkdir()
    (tmp_path / "2024财报.txt").write_text("x", encoding="utf-8")

    assert detect_folder_layout(str(tmp_path)) == "flat"


# ════════════════════════════════════════════════════════════════════
# 加密检测（字节签名启发式，无需真实密码文件）
# ════════════════════════════════════════════════════════════════════

def test_encrypted_office_detected(tmp_path):
    """加密的 Office 文件是 OLE2 容器（不以 PK 开头）→ is_encrypted。"""
    from cangjie_fos.services.dd_gk_service import is_file_encrypted

    enc = tmp_path / "加密财报.xlsx"
    enc.write_bytes(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1rest")  # OLE2 magic
    assert is_file_encrypted(enc) is True


def test_normal_office_not_encrypted(tmp_path):
    """正常 xlsx/docx 是 zip（PK 开头）→ 非加密。"""
    from cangjie_fos.services.dd_gk_service import is_file_encrypted

    ok = tmp_path / "正常财报.xlsx"
    ok.write_bytes(b"PK\x03\x04rest-of-zip")
    assert is_file_encrypted(ok) is False


def test_encrypted_pdf_detected(tmp_path):
    """含 /Encrypt 标记的 PDF → is_encrypted。"""
    from cangjie_fos.services.dd_gk_service import is_file_encrypted

    enc = tmp_path / "加密.pdf"
    enc.write_bytes(b"%PDF-1.6\n... /Encrypt 12 0 R ...\n")
    assert is_file_encrypted(enc) is True


def test_normal_pdf_not_encrypted(tmp_path):
    """无 /Encrypt 的 PDF → 非加密。"""
    from cangjie_fos.services.dd_gk_service import is_file_encrypted

    ok = tmp_path / "正常.pdf"
    ok.write_bytes(b"%PDF-1.6\n... normal content ...\n")
    assert is_file_encrypted(ok) is False


# ════════════════════════════════════════════════════════════════════
# per_institution 扫描 + 去重
# ════════════════════════════════════════════════════════════════════

def test_per_institution_scan_records_subfolder(tmp_path):
    """per_institution 扫描应记录每个文件来源的机构子文件夹。"""
    from cangjie_fos.services.dd_index_service import scan_and_index_folder
    from cangjie_fos.services.db_base import _connect

    for inst in ["瑞源正方", "鼎晖投资"]:
        d = tmp_path / inst
        d.mkdir()
        (d / f"{inst}专属.txt").write_text("内容", encoding="utf-8")

    with patch("cangjie_fos.services.dd_index_service._llm_summarize",
               return_value="摘要"):
        scan_and_index_folder(str(tmp_path), "gk")

    with _connect() as conn:
        rows = conn.execute(
            "SELECT filename, institution_subfolder FROM dd_asset_index "
            "WHERE folder_root = ?", (str(tmp_path),)
        ).fetchall()
    by_name = {r["filename"]: r["institution_subfolder"] for r in rows}
    assert by_name["瑞源正方专属.txt"] == "瑞源正方"
    assert by_name["鼎晖投资专属.txt"] == "鼎晖投资"


def test_dedup_keeps_newest_across_subfolders(tmp_path):
    """同名文件在多个机构子文件夹出现 → 索引只保留 mtime 最新的一份。"""
    from cangjie_fos.services.dd_index_service import scan_and_index_folder
    from cangjie_fos.services.db_base import _connect

    old_dir = tmp_path / "旧机构"
    new_dir = tmp_path / "新机构"
    old_dir.mkdir()
    new_dir.mkdir()
    old_file = old_dir / "2024财报.txt"
    new_file = new_dir / "2024财报.txt"
    old_file.write_text("旧版", encoding="utf-8")
    new_file.write_text("新版", encoding="utf-8")
    # 显式设置 mtime：旧机构的更早，新机构的更晚
    os.utime(old_file, (time.time() - 10000, time.time() - 10000))
    os.utime(new_file, (time.time(), time.time()))

    with patch("cangjie_fos.services.dd_index_service._llm_summarize",
               return_value="财报"):
        scan_and_index_folder(str(tmp_path), "gk")

    with _connect() as conn:
        rows = conn.execute(
            "SELECT file_path, institution_subfolder FROM dd_asset_index "
            "WHERE folder_root = ? AND filename = ?",
            (str(tmp_path), "2024财报.txt"),
        ).fetchall()
    assert len(rows) == 1, "同名文件应去重，只留一份"
    assert rows[0]["institution_subfolder"] == "新机构", "应保留 mtime 最新的那份"


def test_flat_scan_unchanged(tmp_path):
    """flat 布局扫描行为不变（回归保护）：institution_subfolder 为空。"""
    from cangjie_fos.services.dd_index_service import scan_and_index_folder
    from cangjie_fos.services.db_base import _connect

    (tmp_path / "营业执照.txt").write_text("x", encoding="utf-8")
    (tmp_path / "2024财报.txt").write_text("y", encoding="utf-8")

    with patch("cangjie_fos.services.dd_index_service._llm_summarize",
               return_value="摘要"):
        scan_and_index_folder(str(tmp_path), "gk")

    with _connect() as conn:
        rows = conn.execute(
            "SELECT filename, institution_subfolder FROM dd_asset_index "
            "WHERE folder_root = ?", (str(tmp_path),)
        ).fetchall()
    assert len(rows) == 2
    assert all(r["institution_subfolder"] == "" for r in rows)


def test_encrypted_file_marked_during_scan(tmp_path):
    """扫描时加密文件应标记 is_encrypted=1，仍进索引（靠文件名匹配）。"""
    from cangjie_fos.services.dd_index_service import scan_and_index_folder
    from cangjie_fos.services.db_base import _connect

    enc = tmp_path / "加密财报.xlsx"
    enc.write_bytes(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1encrypted")

    with patch("cangjie_fos.services.dd_index_service._llm_summarize",
               return_value="财报"):
        scan_and_index_folder(str(tmp_path), "gk")

    with _connect() as conn:
        row = conn.execute(
            "SELECT is_encrypted FROM dd_asset_index "
            "WHERE folder_root = ? AND filename = ?",
            (str(tmp_path), "加密财报.xlsx"),
        ).fetchone()
    assert row is not None, "加密文件仍应进索引"
    assert row["is_encrypted"] == 1
