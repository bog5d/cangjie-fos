"""将匹配结果导出为本地文件夹：复制文件 + 生成缺失清单。"""
from __future__ import annotations
import shutil
import logging
from pathlib import Path

from cangjie_fos.services.db_base import _connect

logger = logging.getLogger(__name__)


def export_to_folder(session_id: str, output_dir: str) -> dict:
    """
    把匹配结果复制到 output_dir，生成 缺失清单.txt。
    返回 {"exported": N, "missing": M, "output_path": str}
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    with _connect() as conn:
        items = [dict(r) for r in conn.execute(
            """SELECT item_no, category, requirement,
                      matched_file_path, matched_filename,
                      confidence, user_skipped
               FROM dd_match_items
               WHERE session_id = ?
               ORDER BY item_no""",
            (session_id,),
        ).fetchall()]

    exported: list[dict] = []
    missing: list[dict] = []

    for item in items:
        if item["user_skipped"]:
            missing.append(item)
            continue

        src = item["matched_file_path"]
        if src and Path(src).is_file():
            cat_dir = out / _safe_dirname(item.get("category") or "其他")
            cat_dir.mkdir(exist_ok=True)
            dest_name = f"{item['item_no']}_{item['matched_filename']}"
            shutil.copy2(src, cat_dir / dest_name)
            exported.append(item)
        else:
            missing.append(item)

    _write_gap_report(out, missing)

    return {
        "exported": len(exported),
        "missing": len(missing),
        "output_path": str(out),
    }


def _write_gap_report(out: Path, missing: list[dict]) -> None:
    lines = [
        "# 尽调材料缺失清单",
        f"缺失 {len(missing)} 项",
        "",
    ]
    for item in missing:
        cat = f"[{item.get('category', '')}] " if item.get("category") else ""
        lines.append(f"- 第{item['item_no']}项 {cat}{item['requirement']}")
    (out / "缺失清单.txt").write_text("\n".join(lines), encoding="utf-8")


def _safe_dirname(name: str) -> str:
    invalid = r'\/:*?"<>|'
    clean = "".join(c for c in name if c not in invalid)
    return clean[:30] or "其他"
