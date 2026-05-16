"""
将匹配结果导出为本地文件夹：复制文件 + 生成缺失清单。

v0.7.2 改进：
  - 单文件超过 MB_LIMIT_PER_FILE 时跳过并记入缺失清单（而非直接复制炸盘）
  - 累计导出大小超过 MB_LIMIT_TOTAL 时终止全部导出，返回错误
"""
from __future__ import annotations
import shutil
import logging
from pathlib import Path

from cangjie_fos.services.db_base import _connect

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 导出大小限制（防止超大文件炸盘/爆内存）
# ═══════════════════════════════════════════════════════════════
MB_LIMIT_PER_FILE = 100   # 单文件上限（MB），超过跳过
MB_LIMIT_TOTAL = 500      # 总导出上限（MB），超过终止全部导出


def export_to_folder(session_id: str, output_dir: str) -> dict:
    """
    把匹配结果复制到 output_dir，生成 缺失清单.txt。

    v0.7.2 新增 guard：
      - 单文件 > 100MB → 跳过，记录到缺失清单
      - 累计 > 500MB → 终止，不复制任何更多文件

    返回：{"exported": N, "missing": M, "output_path": str, 可能包含 "error"}
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
    total_bytes = 0

    for item in items:
        if item["user_skipped"]:
            missing.append(item)
            continue

        src = item["matched_file_path"]
        if not src or not Path(src).is_file():
            missing.append(item)
            continue

        src_path = Path(src)
        src_size = src_path.stat().st_size
        src_mb = src_size / (1024 ** 2)

        # ── Guard 1: 单文件过大 → 跳过 ──
        if src_mb > MB_LIMIT_PER_FILE:
            logger.warning(
                "跳过超大文件 %s (%.1fMB > %dMB上限)",
                src_path.name, src_mb, MB_LIMIT_PER_FILE,
            )
            # 记入缺失清单，标注原因
            item["_skip_reason"] = f"文件过大({src_mb:.0f}MB>{MB_LIMIT_PER_FILE}MB)"
            missing.append(item)
            continue

        # ── Guard 2: 累计超限 → 终止全部 ──
        if total_bytes + src_size > MB_LIMIT_TOTAL * 1024 ** 2:
            logger.warning(
                "导出总大小超限(累计%.1fMB + %s %.1fMB > %dMB)，终止导出",
                total_bytes / (1024 ** 2), src_path.name, src_mb, MB_LIMIT_TOTAL,
            )
            return {
                "exported": len(exported),
                "missing": len(missing) + len(items) - len(exported) - len(missing),
                "output_path": str(out),
                "error": (
                    f"导出总大小超限（{MB_LIMIT_TOTAL}MB）。"
                    f"已导出 {len(exported)} 个文件，"
                    f"剩余 {len(items)-len(exported)-len(missing)} 个因限额未复制。"
                    f"建议：删除不需要的文件后重新导出，或分批导出。"
                ),
            }

        cat_dir = out / _safe_dirname(item.get("category") or "其他")
        cat_dir.mkdir(exist_ok=True)
        dest_name = f"{item['item_no']}_{item['matched_filename']}"
        shutil.copy2(src, cat_dir / dest_name)
        exported.append(item)
        total_bytes += src_size

    _write_gap_report(out, missing)

    return {
        "exported": len(exported),
        "missing": len(missing),
        "output_path": str(out),
    }


def _write_gap_report(out: Path, missing: list[dict]) -> None:
    """生成缺失清单（含跳过原因）。"""
    lines = [
        "# 尽调材料缺失清单",
        f"缺失 {len(missing)} 项",
        "",
    ]
    for item in missing:
        cat = f"[{item.get('category', '')}] " if item.get("category") else ""
        skip = item.get("_skip_reason", "")
        reason = f"  ← {skip}" if skip else ""
        lines.append(f"- 第{item['item_no']}项 {cat}{item['requirement']}{reason}")
    (out / "缺失清单.txt").write_text("\n".join(lines), encoding="utf-8")


def _safe_dirname(name: str) -> str:
    """过滤非法文件名字符。"""
    invalid = r'\/:*?"<>|'
    clean = "".join(c for c in name if c not in invalid)
    return clean[:30] or "其他"
