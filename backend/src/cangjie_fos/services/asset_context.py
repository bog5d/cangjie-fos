"""按用户对话关键词从 asset_index.json 检索相关档案，注入 NPC 上下文。"""
from __future__ import annotations

import re

from cangjie_fos.services.fss_asset_scan import load_asset_index_assets

# 触发档案检索的关键词信号（任一命中则启动检索）
_TRIGGER_PATTERNS = re.compile(
    r"材料|文件|档案|资料|BP|商业计划|财务|尽调|DD|投资协议|TS|term.?sheet"
    r"|准备什么|带什么|发什么|给.*看|找.*文件|有没有.*文件|需要.*文件",
    re.IGNORECASE,
)

_STOP_RE = re.compile(r"[\s，。！？、；：「」【】《》\(\)（）\[\],.!?;:\"\'/\\]+")


def _extract_cjk_ngrams(text: str, min_len: int = 2, max_len: int = 6) -> list[str]:
    """提取中文字符序列的滑动窗口 n-gram，用于关键词匹配。"""
    cjk_blocks = re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf\uff00-\uffef]+", text)
    ngrams: list[str] = []
    for block in cjk_blocks:
        for n in range(min_len, max_len + 1):
            for i in range(len(block) - n + 1):
                ngrams.append(block[i : i + n])
    # 也保留英文词（如 BP、DD）
    eng_words = re.findall(r"[A-Za-z0-9]{2,}", text)
    ngrams.extend(w.lower() for w in eng_words)
    return ngrams


def _score_asset(asset: dict, ngrams: list[str]) -> int:
    """越多 n-gram 命中得分越高。"""
    haystack = " ".join([
        (asset.get("filename") or "").lower(),
        (asset.get("summary") or "").lower(),
        " ".join(asset.get("tags") or []).lower(),
        (asset.get("relative_path") or "").lower(),
    ])
    return sum(1 for ng in ngrams if ng in haystack)


def build_relevant_asset_snippet(user_text: str, *, limit: int = 6) -> str:
    """根据用户问话，从 asset_index 检索相关档案并返回格式化字符串。

    不命中触发词或无匹配时返回空字符串，避免污染 NPC 上下文。
    """
    if not user_text:
        return ""
    # 只在对话明确涉及材料/文件时才触发
    if not _TRIGGER_PATTERNS.search(user_text):
        return ""

    assets = load_asset_index_assets()
    if not assets:
        return ""

    ngrams = _extract_cjk_ngrams(user_text)
    if not ngrams:
        return ""

    scored = [(a, _score_asset(a, ngrams)) for a in assets]
    scored.sort(key=lambda x: -x[1])
    matched = [(a, s) for a, s in scored if s > 0][:limit]

    if not matched:
        # 无精确匹配时返回前 N 条兜底
        matched = [(a, 0) for a in assets[:limit]]

    lines: list[str] = []
    for a, _ in matched:
        fn = a.get("filename") or "?"
        rp = a.get("relative_path") or "根目录"
        sm = (a.get("summary") or "").strip()
        tags = a.get("tags") or []
        tag_str = "  [" + " ".join(tags) + "]" if tags else ""
        desc = f"  摘要：{sm}" if sm else ""
        lines.append(f"- {fn}（{rp}）{tag_str}{desc}")

    total = len(assets)
    header = f"[相关档案推荐（共 {total} 个文件，以下为最相关的 {len(matched)} 条）]"
    return header + "\n" + "\n".join(lines)
