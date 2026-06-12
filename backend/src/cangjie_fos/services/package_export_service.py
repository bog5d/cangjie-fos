"""需求03 深化 — 数据包一键导出（zip 下载，跨网络可用，不依赖服务器本地路径）。

zip 内容：
  缺口报告.md          —— 完整度评分 + 三态汇总 + 逐项状态表 + 必备缺失点名
  合成稿/分类-条目.md   —— 每个有 AI 合成初稿的条目一份（含人工核对提示）
"""
from __future__ import annotations

import io
import re
import time
import zipfile

from cangjie_fos.services import package_gap_service as gap

_STATE_LABEL = {"have": "✅ 已有", "update": "🟡 需更新", "missing": "❌ 缺失", "pending": "⏳ 待分析"}


def _safe_name(s: str, limit: int = 40) -> str:
    """文件名净化：去掉路径分隔与非法字符。"""
    s = re.sub(r'[\\/:*?"<>|\r\n]+', "_", s).strip()
    return s[:limit] or "未命名"


def build_report_md(session: dict, items: list[dict], summary: dict) -> str:
    lines: list[str] = []
    title = session.get("title") or "数据包缺口报告"
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"- 材料库：`{session.get('folder_root', '')}`")
    lines.append(f"- **完整度评分：{summary['score']} / 100**（core 项加权）")
    lines.append(
        f"- 共 {summary['total']} 项：已有 {summary['have']} · "
        f"需更新 {summary['update']} · 缺失 {summary['missing']}"
    )
    if summary.get("core_missing"):
        lines.append(f"- ⚠️ **投资人必看项缺失 {summary['core_missing']} 个**，优先补全：")
        for it in items:
            if it.get("importance") == "core" and it.get("gap_state") == "missing":
                lines.append(f"  - {it['category']} / {it['requirement']}")
    lines.append("")

    # 分维度逐项表
    by_cat: dict[str, list[dict]] = {}
    for it in items:
        by_cat.setdefault(it.get("category", "未分类"), []).append(it)
    for cat, group in by_cat.items():
        lines.append(f"## {cat}")
        lines.append("")
        lines.append("| 材料项 | 状态 | 命中文件 | 说明 |")
        lines.append("|---|---|---|---|")
        for it in group:
            state = _STATE_LABEL.get(it.get("gap_state", "pending"), it.get("gap_state", ""))
            core = "【必备】" if it.get("importance") == "core" else ""
            matched = it.get("matched_filename") or "—"
            reason = (it.get("match_reason") or "").replace("|", "/")[:50]
            draft_mark = " ·已有AI初稿" if (it.get("draft_answer") or "").strip() else ""
            lines.append(f"| {core}{it['requirement']} | {state}{draft_mark} | {matched} | {reason} |")
        lines.append("")
    return "\n".join(lines)


def build_export_zip(session_id: str) -> tuple[bytes, str]:
    """生成导出 zip。返回 (zip_bytes, 建议文件名)。"""
    session = gap.get_session(session_id)
    if not session:
        raise ValueError(f"会话 {session_id} 不存在")
    items = gap.list_items(session_id)
    summary = gap.gap_summary(session_id)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("缺口报告.md", build_report_md(session, items, summary))
        for it in items:
            draft = (it.get("draft_answer") or "").strip()
            if not draft:
                continue
            name = f"合成稿/{_safe_name(it.get('category', ''))}-{_safe_name(it['requirement'])}.md"
            body = (
                f"# {it['requirement']}\n\n"
                f"> ⚠️ AI 合成初稿（已经事实护栏校验数字来源），**正式使用前请人工核对定稿**。\n\n"
                f"{draft}\n"
            )
            zf.writestr(name, body)
    fname = f"数据包_{_safe_name(session.get('title') or '导出', 20)}_{time.strftime('%Y%m%d')}.zip"
    return buf.getvalue(), fname
