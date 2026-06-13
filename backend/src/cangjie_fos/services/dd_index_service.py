"""扫描本地文件夹，为每个文件生成 AI 摘要，存入 dd_asset_index 表。"""
from __future__ import annotations
import logging
import os
import re
import uuid
import time
from pathlib import Path
from typing import Callable

from cangjie_fos.services.dd_file_parser import (
    extract_text, SUPPORTED_EXTENSIONS,
)
from cangjie_fos.services.db_base import _connect

logger = logging.getLogger(__name__)

# 超过此数量的文件夹不做 LLM 摘要，只索引文件名+类型，避免几小时的 API 调用
MAX_LLM_SUMMARIZE_FILES = 200

def clean_filename(name: str) -> str:
    """去除文件名中的日期、版本号、噪音词，提升二元组预筛准确率。"""
    name = re.sub(r'\.\w+$', '', name)
    name = re.sub(r'20\d{2}[-年/]\d{0,2}[-月/]?\d{0,2}日?', '', name)
    name = re.sub(r'20\d{2}', '', name)
    name = re.sub(r'[vV]\d+(\.\d+)*', '', name)
    for noise in ['最终版', '终稿', '副本', '扫描件', '盖章版', '签字版', '修订']:
        name = name.replace(noise, '')
    name = re.sub(r'[（(【\[].{0,10}[）)\]】]', '', name)
    return name.strip()


def scan_and_index_folder(
    folder_path: str,
    tenant_id: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict:
    """
    扫描文件夹，对每个支持的文件提取内容并生成摘要，写入 dd_asset_index。
    同步执行，调用方应包装进 BackgroundTask。

    大文件夹优化（v1.1.0）：
    - 文件数 > MAX_LLM_SUMMARIZE_FILES 时跳过 LLM 摘要，只记录文件名。
      匹配引擎的预筛选（prefilter）和 LLM 匹配本身仍可通过文件名工作。
    - progress_callback(done, total) 每处理50个文件回调一次，供前端进度展示。

    返回：{"total": N, "indexed": M, "failed": K, "folder_root": str}
    """
    root = Path(folder_path)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {folder_path}")

    from cangjie_fos.services.dd_gk_service import (  # noqa: PLC0415
        detect_folder_layout, is_file_encrypted,
    )
    layout = detect_folder_layout(str(root))

    files = [
        f for f in root.rglob("*")
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    # per_institution 布局：同名文件跨机构子文件夹去重，只留 mtime 最新一份
    if layout == "per_institution":
        files = _dedup_keep_newest(files)

    total = len(files)
    use_llm = total <= MAX_LLM_SUMMARIZE_FILES
    if not use_llm:
        logger.info(
            "文件夹 %s 含 %d 个文件（>%d），跳过 LLM 摘要，仅索引文件名",
            folder_path, total, MAX_LLM_SUMMARIZE_FILES,
        )

    # 机构数量（供前端布局徽章）：per_institution 下统计去重后文件来源的机构子文件夹数
    inst_set = {
        sf for f in files
        if (sf := _institution_subfolder(f, root))
    }

    results = {
        "total": total, "indexed": 0, "failed": 0,
        "folder_root": str(root), "folder_layout": layout,
        "institution_count": len(inst_set),
    }

    for i, file_path in enumerate(files):
        try:
            subfolder = _institution_subfolder(file_path, root)
            encrypted = is_file_encrypted(file_path)
            _index_single_file(
                file_path, str(root), use_llm=use_llm,
                institution_subfolder=subfolder, is_encrypted=encrypted,
            )
            results["indexed"] += 1
        except Exception as e:
            logger.warning("索引失败 %s: %s", file_path.name, e)
            results["failed"] += 1

        # 每 50 个文件汇报一次进度
        if progress_callback and (i + 1) % 50 == 0:
            progress_callback(results["indexed"], total)

    return results


def _institution_subfolder(file_path: Path, root: Path) -> str:
    """文件来源的机构子文件夹名（根直属那一层）；平铺在根下的文件返回空串。"""
    try:
        parts = file_path.relative_to(root).parts
    except ValueError:
        return ""
    return parts[0] if len(parts) > 1 else ""


def _dedup_keep_newest(files: list[Path]) -> list[Path]:
    """同名文件去重，保留 mtime 最新的一份。"""
    best: dict[str, Path] = {}
    for f in files:
        try:
            mt = f.stat().st_mtime
        except OSError:
            mt = 0.0
        cur = best.get(f.name)
        if cur is None:
            best[f.name] = f
        else:
            cur_mt = cur.stat().st_mtime if cur.exists() else 0.0
            if mt > cur_mt:
                best[f.name] = f
    return list(best.values())


def _index_single_file(
    file_path: Path,
    folder_root: str,
    use_llm: bool = True,
    institution_subfolder: str = "",
    is_encrypted: bool = False,
) -> None:
    # ── 延迟全文抽取（v1.16.0 性能）────────────────────────────────────────────
    # 旧实现对每个文件都 extract_full_text（解析整份 PDF/Word/Excel），是 2~3000 份
    # 大库扫描 10 分钟卡死的主因（~1 文件/秒 → 数千份要几十分钟）。
    # 全文只在「精判」阶段对【已匹配的少数文件】才需要，故扫描阶段不再预抽全文：
    #   - 小文件夹（use_llm）：只抽「轻量前几页/800字」喂 LLM 摘要，比全文快得多；
    #   - 大文件夹：纯元数据（文件名 + 加密标记），秒级完成；
    #   - content_text 留空，待精判按需抽取并回填（dd_match_service._ensure_content_text）。
    if use_llm:
        light_text, readable = extract_text(file_path, max_chars=800)
        summary = _llm_summarize(file_path.name, light_text) if (readable and light_text) else None
    else:
        light_text, readable, summary = "", True, None
    content_text = None  # 延迟到精判按需抽取

    now = time.time()
    try:
        mtime_val = file_path.stat().st_mtime
    except OSError:
        mtime_val = None
    enc = 1 if is_encrypted else 0
    with _connect() as conn:
        # ── 写入 dd_asset_index（DD 专用索引，用于本次会话匹配）──────────────
        existing = conn.execute(
            "SELECT id FROM dd_asset_index WHERE file_path = ?", (str(file_path),)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE dd_asset_index
                   SET summary = ?, readable = ?, indexed_at = ?,
                       institution_subfolder = ?, is_encrypted = ?, mtime = ?,
                       content_text = ?
                   WHERE file_path = ?""",
                (summary, 1 if readable else 0, now,
                 institution_subfolder, enc, mtime_val, content_text, str(file_path)),
            )
        else:
            conn.execute(
                """INSERT INTO dd_asset_index
                   (id, folder_root, file_path, filename, file_type, summary,
                    readable, indexed_at, institution_subfolder, is_encrypted, mtime,
                    content_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    folder_root,
                    str(file_path),
                    file_path.name,
                    file_path.suffix.lower(),
                    summary,
                    1 if readable else 0,
                    now,
                    institution_subfolder,
                    enc,
                    mtime_val,
                    content_text,
                ),
            )


def _llm_summarize(filename: str, content: str) -> str:
    """
    调用 LLM 生成文件一句话摘要（20字以内）。

    v0.7.2 改进：使用 dd_llm_client 统一管理 provider 配置 + 重试。
    """
    from cangjie_fos.services.dd_llm_client import get_dd_llm_client, call_with_retry

    client = get_dd_llm_client()
    prompt = (
        f"文件名：{filename}\n"
        f"内容摘录：\n{content[:600]}\n\n"
        "用一句话（20字以内）说明这是什么资料（例如：2023年财务审计报告）："
    )

    def _call():
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=60,
            temperature=0,
        )
        return resp.choices[0].message.content.strip()

    return call_with_retry(_call, max_retries=2)  # 摘要生成重试2次即可


def get_index_by_folder(folder_root: str) -> list[dict]:
    """返回指定文件夹下所有已索引文件。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM dd_asset_index WHERE folder_root = ? ORDER BY indexed_at DESC",
            (folder_root,),
        ).fetchall()
    return [dict(r) for r in rows]
