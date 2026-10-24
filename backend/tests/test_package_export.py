"""需求03 深化 — 数据包导出 zip 测试。"""
from __future__ import annotations

import io
import zipfile

from cangjie_fos.services import package_export_service as export
from cangjie_fos.services import package_gap_service as gap
from cangjie_fos.services.db_base import _connect


def _set_state(item_id: str, **fields):
    cols = ", ".join(f"{k}=?" for k in fields)
    with _connect() as conn:
        conn.execute(f"UPDATE package_items SET {cols} WHERE id=?",
                     (*fields.values(), item_id))


def test_export_zip_structure():
    sess = gap.create_session("zt", "/data/exp", title="导出测试包")
    items = gap.list_items(sess["session_id"])
    # 给第一项一个已有 + AI 初稿，第二项缺失
    _set_state(items[0]["id"], gap_state="have", matched_filename="营业执照.pdf",
               draft_answer="这是营业执照的合成初稿。")
    _set_state(items[1]["id"], gap_state="missing")

    data, fname = export.build_export_zip(sess["session_id"])
    assert fname.endswith(".zip")
    assert "导出测试包" in fname

    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    assert "缺口报告.md" in names
    # 有初稿的条目导出一份合成稿
    synth_files = [n for n in names if n.startswith("合成稿/")]
    assert len(synth_files) == 1

    report = zf.read("缺口报告.md").decode("utf-8")
    assert "完整度评分" in report
    assert "营业执照" in report

    draft = zf.read(synth_files[0]).decode("utf-8")
    assert "营业执照的合成初稿" in draft
    assert "人工核对" in draft  # 含定稿提示


def test_export_unknown_session_raises():
    import pytest
    with pytest.raises(ValueError):
        export.build_export_zip("不存在")


def test_export_no_drafts_only_report():
    sess = gap.create_session("zt", "/data/exp2")
    data, _ = export.build_export_zip(sess["session_id"])
    zf = zipfile.ZipFile(io.BytesIO(data))
    assert zf.namelist() == ["缺口报告.md"]  # 没有初稿 → 只有报告
