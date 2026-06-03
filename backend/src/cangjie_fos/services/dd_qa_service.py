"""尽调 gk 模式 F4 — 历史问答复用（单次扒取 + 草稿）。

机构问答响应引擎 阶段一。

流程：
1. extract_qa_pairs_from_folder：扫描历史补充资料文件，AI 提取「问题→答案」对，
   存入 dd_qa_pairs（按 folder_root 归集）。
2. generate_answer_draft：新需求 → 在 dd_qa_pairs 里语义检索最相近历史问答，
   命中给草稿（带历史答案 + 高置信度），无命中给低置信空草稿（不硬塞、待人工）。

MVP 范围：单次扒取即用，落表为 v1.1 持久化知识库铺路，但不做跨会话主动推荐。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

from cangjie_fos.services.db_base import _connect
from cangjie_fos.services.dd_file_parser import extract_text, SUPPORTED_EXTENSIONS
from cangjie_fos.services.dd_llm_client import get_dd_llm_client, call_with_retry

logger = logging.getLogger(__name__)

# 只扫这类「问答型」补充资料文件，正常材料（财报/执照）不进问答扒取
_QA_FILE_KEYWORDS = ("补充", "问答", "答复", "回复", "尽调问题", "访谈", "纪要")

# 草稿命中阈值：bigram 重合度高于此值才算"命中历史问答"
_HIT_THRESHOLD = 0.5

# 语义匹配用停用字（与 dd_match_service 一致，语义稀薄无区分度）
_STOP_CHARS = set("的和与或等及提供相关情况说明文件资料证明（）、，。是有无请贵公司")


def _is_qa_file(filename: str) -> bool:
    """判断是否为问答型补充资料文件。"""
    return any(kw in filename for kw in _QA_FILE_KEYWORDS)


def extract_qa_pairs_from_folder(folder_root: str, tenant_id: str) -> dict:
    """
    扫描 folder_root 下的问答型补充资料文件，提取问答对存入 dd_qa_pairs。
    同步执行，调用方应包装进 BackgroundTask。

    返回：{"extracted": N, "files": M, "folder_root": str}
    """
    root = Path(folder_root)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {folder_root}")

    qa_files = [
        f for f in root.rglob("*")
        if f.is_file()
        and f.suffix.lower() in SUPPORTED_EXTENSIONS
        and _is_qa_file(f.name)
    ]

    extracted = 0
    for f in qa_files:
        try:
            text, readable = extract_text(f)
            if not (readable and text):
                continue
            subfolder = _institution_subfolder(f, root)
            pairs = _llm_extract_qa(f.name, text)
            for p in pairs:
                q = (p.get("question") or "").strip()
                if not q:
                    continue
                _persist_qa_pair(
                    tenant_id, folder_root, f.name,
                    q, (p.get("answer") or "").strip(),
                    subfolder, float(p.get("confidence", 0.5)),
                )
                extracted += 1
        except Exception as e:
            logger.warning("问答扒取失败 %s: %s", f.name, e)

    return {"extracted": extracted, "files": len(qa_files), "folder_root": folder_root}


def _institution_subfolder(file_path: Path, root: Path) -> str:
    """文件来源的机构子文件夹名（根直属那一层）；平铺在根下返回空串。"""
    try:
        parts = file_path.relative_to(root).parts
    except ValueError:
        return ""
    return parts[0] if len(parts) > 1 else ""


def _persist_qa_pair(
    tenant_id: str,
    folder_root: str,
    source_file: str,
    question: str,
    answer: str,
    institution_subfolder: str,
    confidence: float,
) -> None:
    """写入单条问答对到 dd_qa_pairs。"""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_qa_pairs
               (id, tenant_id, folder_root, source_file, question, answer,
                institution_subfolder, confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), tenant_id, folder_root, source_file,
             question, answer, institution_subfolder, confidence, time.time()),
        )


def _llm_extract_qa(filename: str, content: str) -> list[dict]:
    """调用 LLM 从一段文字中提取问答对（可被 monkeypatch）。

    返回：[{"question": str, "answer": str, "confidence": float}, ...]
    """
    client = get_dd_llm_client()
    prompt = (
        f"以下是尽调补充资料《{filename}》的内容：\n\n{content[:4000]}\n\n"
        "请提取其中的「问题→答案」对。只提取明确的问答，不要臆造。\n"
        '返回 JSON 数组：[{"question": "问题", "answer": "答案", '
        '"confidence": 0到1}]。只返回 JSON：'
    )

    def _call() -> list[dict]:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.lower().startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        data = json.loads(raw)
        return data if isinstance(data, list) else []

    return call_with_retry(_call, max_retries=2)


def _bigrams(text: str) -> set[str]:
    """提取汉字二元组（剔除含停用字的组合）。"""
    kws: set[str] = set()
    for i in range(len(text) - 1):
        bg = text[i:i + 2]
        if not any(c in _STOP_CHARS for c in bg):
            kws.add(bg)
    return kws


def _similarity(req: str, question: str) -> float:
    """需求与历史问题的 bigram Jaccard 相似度（0~1）。"""
    a = _bigrams(req)
    b = _bigrams(question)
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def generate_answer_draft(requirement: str, folder_root: str) -> dict:
    """
    为新需求生成答复草稿：在 dd_qa_pairs 里找语义最相近的历史问答。

    命中（相似度 ≥ 阈值）→ 带出历史答案 + 置信度；
    无命中 → 空草稿、低置信、matched=False（不硬塞，待人工）。

    返回：{
        "matched": bool, "answer": str, "confidence": float,
        "source_question": str, "source_file": str,
    }
    """
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT question, answer, source_file, confidence "
            "FROM dd_qa_pairs WHERE folder_root = ?",
            (folder_root,),
        ).fetchall()]

    if not rows:
        return {"matched": False, "answer": "", "confidence": 0.0,
                "source_question": "", "source_file": ""}

    best = None
    best_sim = 0.0
    for r in rows:
        sim = _similarity(requirement, r["question"])
        if sim > best_sim:
            best_sim = sim
            best = r

    if best is not None and best_sim >= _HIT_THRESHOLD:
        # 置信度 = 相似度与历史提取置信度的较小者（保守）
        conf = min(best_sim, float(best.get("confidence") or best_sim))
        return {
            "matched": True,
            "answer": best["answer"],
            "confidence": round(conf, 3),
            "source_question": best["question"],
            "source_file": best["source_file"],
        }

    return {"matched": False, "answer": "", "confidence": round(best_sim, 3),
            "source_question": "", "source_file": ""}
