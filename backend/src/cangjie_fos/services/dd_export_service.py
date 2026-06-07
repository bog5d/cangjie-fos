"""
将匹配结果导出为本地文件夹：复制文件 + 生成缺失清单。

v0.7.2 改进：
  - 单文件超过 MB_LIMIT_PER_FILE 时跳过并记入缺失清单（而非直接复制炸盘）
  - 累计导出大小超过 MB_LIMIT_TOTAL 时终止全部导出，返回错误
"""
from __future__ import annotations
import json
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
        dest_name = f"{_safe_component(str(item['item_no']), 12) or 'x'}_{_safe_filename(item['matched_filename'])}"
        dest = cat_dir / dest_name
        # 兜底闸：清洗后仍可能异常 → 确认目标在 output_dir 之内才写
        if not _within(out, dest):
            logger.warning("跳过疑似越界目标 %s（item %s）", dest, item.get("item_no"))
            item["_skip_reason"] = "文件名异常（安全跳过）"
            missing.append(item)
            continue
        shutil.copy2(src, dest)
        exported.append(item)
        total_bytes += src_size

    _write_gap_report(out, missing)
    _write_password_note(out, [it["matched_file_path"] for it in exported if it.get("matched_file_path")])

    return {
        "exported": len(exported),
        "missing": len(missing),
        "output_path": str(out),
    }


def export_by_question(
    session_id: str,
    output_dir: str,
    folder_name_overrides: dict | None = None,
) -> dict:
    """
    F2 + F5：按问题归档导出。

    每条有匹配文件的需求 → 一个「问题NN_需求名」子文件夹；
    无匹配 → 不建空文件夹，追加到缺失清单.txt。
    多文件（extra_files_json）全部拷入同一子文件夹。
    folder_name_overrides: {item_id: 自定义文件夹名} 用于 F5 命名确认。

    返回：{"exported": 文件数, "missing": 缺失需求数, "output_path": str}
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    overrides = folder_name_overrides or {}
    exported_paths: list[str] = []

    with _connect() as conn:
        items = [dict(r) for r in conn.execute(
            """SELECT id, item_no, category, requirement,
                      matched_file_path, matched_filename,
                      confidence, user_skipped, extra_files_json
               FROM dd_match_items
               WHERE session_id = ?
               ORDER BY item_no""",
            (session_id,),
        ).fetchall()]

    exported_files = 0
    missing: list[dict] = []

    for item in items:
        if item["user_skipped"]:
            missing.append(item)
            continue

        src = item["matched_file_path"]
        if not src or not Path(src).is_file():
            missing.append(item)
            continue

        # ── 确定文件夹名 ─────────────────────────────────────────
        if item["id"] in overrides:
            folder_name = _safe_dirname(overrides[item["id"]])
        else:
            folder_name = _safe_dirname(
                f"问题{item['item_no']}_{item['requirement']}"
            )

        q_dir = out / folder_name
        q_dir.mkdir(exist_ok=True)

        # ── 主匹配文件 ────────────────────────────────────────────
        dest = q_dir / _safe_filename(Path(src).name)
        if _within(out, dest):
            shutil.copy2(src, dest)
            exported_files += 1
            exported_paths.append(src)

        # ── 额外文件（extra_files_json） ─────────────────────────
        extra_raw = item.get("extra_files_json")
        if extra_raw:
            try:
                extra_list = json.loads(extra_raw)
            except (json.JSONDecodeError, TypeError):
                extra_list = []
            for ef in extra_list:
                ep = ef.get("file_path", "")
                edest = q_dir / _safe_filename(Path(ep).name)
                if ep and Path(ep).is_file() and _within(out, edest):
                    shutil.copy2(ep, edest)
                    exported_files += 1
                    exported_paths.append(ep)

    _write_gap_report(out, missing)
    _write_password_note(out, exported_paths)

    return {
        "exported": exported_files,
        "missing": len(missing),
        "output_path": str(out),
    }


def _write_password_note(out: Path, exported_paths: list[str]) -> None:
    """为导出的加密文件生成「加密文件密码.txt」（原样附带，不解密）。

    仅当存在已登记密码的加密文件时才生成该清单，供对方据此打开文件。
    """
    if not exported_paths:
        return
    placeholders = ",".join("?" * len(exported_paths))
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT filename, unlock_password FROM dd_asset_index "
            f"WHERE file_path IN ({placeholders}) "
            f"AND is_encrypted = 1 AND unlock_password != ''",
            exported_paths,
        ).fetchall()
    if not rows:
        return
    lines = ["# 加密文件密码清单", f"共 {len(rows)} 个加密文件", ""]
    for r in rows:
        lines.append(f"- {r['filename']}  密码：{r['unlock_password']}")
    (out / "加密文件密码.txt").write_text("\n".join(lines), encoding="utf-8")


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


def _safe_component(name: str, maxlen: int) -> str:
    """清洗单个路径组件：去非法字符/路径分隔/控制字符/前导尾随点。

    红队加固：杜绝 `.`、`..`、含 `/`、`\\` 的名字，防止导出时穿越出 output_dir。
    """
    invalid = set(r'\/:*?"<>|') | {chr(c) for c in range(32)}
    clean = "".join(c for c in (name or "") if c not in invalid)
    clean = clean.replace("\x00", "").strip().strip(".").strip()
    return clean[:maxlen] or ""


def _safe_dirname(name: str) -> str:
    """过滤非法文件名字符（目录名）。"""
    return _safe_component(name, 30) or "其他"


def _safe_filename(name: str) -> str:
    """清洗文件名：先取 basename（去掉任何路径），再清洗。保留扩展名中的点。"""
    base = Path(name or "").name  # 去掉任何 ../ 路径成分
    return _safe_component(base, 80) or "未命名文件"


def _within(base: Path, target: Path) -> bool:
    """target 解析后是否仍在 base 之内（防穿越的兜底闸）。"""
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except (ValueError, OSError):
        return False

