"""DD-V1 正文抽取适配层（WP2）。

**复用优先**（SCP v3.8 §1）：本层不重写解析器，而是把既有能力编排成一条
**有方法标记、可降级、可观测**的抽取链，并按需接入 Docling。

抽取链（按顺序尝试，任何一层成功即返回，**绝不编造**）：

    1. ``docling``      —— 多格式/版面/表格标准化解析。可选依赖，未安装则跳过。
    2. ``existing``     —— 复用 `dd_content_extractor.extract_for_verify`：
                           解密 → 文本 → MarkItDown 三层降级，自带 method 标记。
    3. ``raw``          —— 复用 `dd_file_parser` 的纯文本抽取（兜底）。
    4. ``unreadable``   —— 全部失败 → 显式标记不可读，**不返回半截正文冒充成功**。

三个必须守住的不变量（对��� D5）：

- **截断必须显式标记**：超过长度上限时 ``truncated=True`` 并记录原始长度，
  绝不返回「看起来完整」的被砍内容。
- **方法必须可追溯**：每次抽取都返回 ``method``，写入 Manifest 的 ``parse_method``，
  使「扫描件 / 加密件 / 损坏件 / 截断件」在 Schema 层即可区分。
- **失败必须有原因**：``parse_error`` 记录真实异常摘要，不吞错。

Docling 为**可选 extra**（`pip install 'cangjie-fos[docling]'`）：
未安装时自动跳过该层并降级，不影响任何既有行为——
低���本、可逆，且不让一个重依赖卡住主链。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from cangjie_fos.services import dd_v1_manifest_service as mf
from cangjie_fos.services import dd_v1_ocr_service as ocr

logger = logging.getLogger(__name__)

# 抽取方式（写入 parse_method，可直接用于排查）
M_DOCLING = "docling"
M_EXISTING = "existing"          # dd_content_extractor（含 decrypt/markitdown 分支）
M_RAW = "raw"                    # dd_file_parser 纯文本兜底
M_OCR = ocr.M_OCR                # "ocr" —— 本地 tesseract（**仅用于无文字层的扫描件**）
M_EMPTY = "empty"                # 抽到了但是空的
M_UNREADABLE = "unreadable"      # 明确不可读
M_MISSING = "missing"            # 文件已不在（软删除/移动盘掉线）

# 正文长度上限。与旧 dd_prefetch_service._PREFETCH_MAX_CHARS 同量级，
# 但这里**超限即显式标记 truncated**，不再像旧预热那样静默砍断。
DEFAULT_MAX_CHARS = int(
    __import__("os").getenv("CANGJIE_DD_V1_MAX_CHARS", "50000") or "50000"
)


@dataclass
class ExtractResult:
    """一次抽取的完整可观测结果。"""
    text: str = ""
    readable: bool = False
    method: str = M_UNREADABLE
    truncated: bool = False
    original_chars: int = 0
    error: str = ""
    elapsed_ms: int = 0
    #: 仅 OCR 命中时有值：页面相对正立**顺时针**旋转的度数（0/90/180/270）
    orientation: int | None = None

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "readable": self.readable,
            "truncated": self.truncated,
            "chars": len(self.text),
            "original_chars": self.original_chars,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "orientation": self.orientation,
        }


def docling_available() -> bool:
    """Docling 是否可用（可选依赖探测，不硬编码依赖）。"""
    try:
        import docling  # noqa: F401,PLC0415
        return True
    except Exception:  # noqa: BLE001
        return False


def _extract_docling(path: Path, max_chars: int) -> ExtractResult:
    """Docling 适配器。不可用时抛 ImportError，由上层降级。

    单独成函数而非内联，便于未来换用 docling 的不同 pipeline 而不动主链。
    """
    from docling.document_converter import DocumentConverter  # noqa: PLC0415

    converter = DocumentConverter()
    doc = converter.convert(str(path)).document
    text = doc.export_to_markdown() or ""
    res = ExtractResult(original_chars=len(text), method=M_DOCLING)
    if len(text) > max_chars:
        res.text = text[:max_chars]
        res.truncated = True
    else:
        res.text = text
    res.readable = bool(res.text.strip())
    if not res.readable:
        res.method = M_EMPTY
    return res


def _extract_existing(path: Path, max_chars: int) -> ExtractResult:
    """复用 dd_content_extractor 的既有三层降级抽取（含解密与 MarkItDown）。"""
    from cangjie_fos.services.dd_content_extractor import (  # noqa: PLC0415
        extract_for_verify,
    )

    text, readable, method = extract_for_verify(str(path))
    text = text or ""
    res = ExtractResult(
        text=text,
        readable=bool(readable) and bool(text.strip()),
        method=method or M_EXISTING,
        original_chars=len(text),
    )
    if len(text) > max_chars:
        res.text = text[:max_chars]
        res.truncated = True
    return res


def _extract_raw(path: Path, max_chars: int) -> ExtractResult:
    """兜底：复用 dd_file_parser 的纯文本抽取。"""
    from cangjie_fos.services.dd_file_parser import extract_text  # noqa: PLC0415

    text = extract_text(str(path)) or ""
    res = ExtractResult(
        text=text,
        readable=bool(text.strip()),
        method=M_RAW,
        original_chars=len(text),
    )
    if len(text) > max_chars:
        res.text = text[:max_chars]
        res.truncated = True
    return res


def _extract_ocr(path: Path, max_chars: int) -> ExtractResult:
    """本地 OCR 层：只对**没有文字层**的扫描件/图片生效。

    走本机 tesseract（零成本、离线、不新增依赖），并做 0/90/180/270 四方向择一
    （见 ``dd_v1_ocr_service``）。**识别不出就返回不可读**——绝不产出空正文冒充成功。
    """
    res = ocr.ocr_file(path)
    if not res.readable:
        r = ExtractResult(method=M_UNREADABLE, error=res.error or "本地 OCR 未识别出可用文本")
        r.elapsed_ms = res.elapsed_ms
        return r
    text = res.text or ""
    out = ExtractResult(
        text=text[:max_chars] if len(text) > max_chars else text,
        readable=True,
        method=M_OCR,
        truncated=len(text) > max_chars,
        original_chars=len(text),
        error=res.error,
        orientation=res.orientation,
    )
    out.elapsed_ms = res.elapsed_ms
    logger.info(
        "本地 OCR 命中 %s：orientation=%s chinese_chars=%s pages=%s",
        path.name, res.orientation, res.chinese_chars, res.pages,
    )
    return out


def _ocr_fallback(res: ExtractResult, path: Path, max_chars: int) -> ExtractResult:
    """无文字层时的本地 OCR 兜底。

    - 文件类型不支持 OCR（文本类文件）→ 原样返回，**不碰 OCR**；
    - OCR 失败 / 没识别出可用文本 → **保持原 method**（M_EMPTY / M_UNREADABLE），
      只把失败原因追加进 error（可观测，不掩盖）。
    """
    if not ocr.supports_ocr(path):
        return res
    try:
        ocr_res = _extract_ocr(path, max_chars)
    except Exception as exc:  # noqa: BLE001 — OCR 崩了不能拖垮抽取链
        res.error = (res.error + f" | ocr: {type(exc).__name__}: {exc}")[:300]
        logger.info("本地 OCR 失败（%s）：%s", path.name, exc)
        return res
    if not ocr_res.readable:
        res.error = (res.error + f" | ocr: {ocr_res.error or '未识别出可用文本'}")[:300]
        logger.info("本地 OCR 未识别出可用正文（%s），维持 %s", path.name, res.method)
        return res
    return ocr_res


def extract_content(
    path: str | Path,
    max_chars: int = DEFAULT_MAX_CHARS,
    allow_docling: bool = True,
) -> ExtractResult:
    """按链抽取正文，永不编造、绝不静默失败。"""
    p = Path(path)
    t0 = time.perf_counter()

    if not p.is_file():
        r = ExtractResult(method=M_MISSING, error=f"文件不存在：{p}")
        r.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return r

    chain = []
    if allow_docling and docling_available():
        chain.append(("docling", _extract_docling))
    chain.append(("existing", _extract_existing))
    chain.append(("raw", _extract_raw))

    last_error = ""
    for name, fn in chain:
        try:
            res = fn(p, max_chars)
        except Exception as exc:  # noqa: BLE001 — 单层失败继续降级，但必须留痕
            last_error = f"{name}: {type(exc).__name__}: {exc}"[:300]
            logger.debug("抽取层 %s 失败，降级下一层：%s", name, exc)
            continue
        if res.readable:
            res.elapsed_ms = int((time.perf_counter() - t0) * 1000)
            if res.truncated:
                logger.info("正文被截断 %s→%s（%s）", res.original_chars, len(res.text), p.name)
            return res
        if res.method == M_EMPTY:
            # 该层读到空 —— 很可能就是**没有文字层**的扫描件 → 试本地 OCR。
            # OCR 也认不出，就维持 M_EMPTY（**不编造正文**）。
            res = _ocr_fallback(res, p, max_chars)
            res.elapsed_ms = int((time.perf_counter() - t0) * 1000)
            return res
        last_error = last_error or f"{name}: 返回不可读"

    # 全部抽取层都没产出正文 → 本地 OCR 最后兜底（认不出就明确不可读）
    r = _ocr_fallback(
        ExtractResult(method=M_UNREADABLE, error=last_error or "全部抽取层均失败"),
        p, max_chars,
    )
    r.elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return r


def extract_and_record(
    library_id: str,
    file_id: str,
    db_path: Path | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    allow_docling: bool = True,
) -> dict:
    """抽取单份材料并把结果写回 Manifest 的解析状态位。

    只写 ``dd_v1_manifest`` 的解析四列（status/method/error/truncated），
    **不改正文入库**——正文与索引属 WP2 的后续步骤，避免单次改动面过大。

    返回该次抽取的可观测结果，供 Evidence 与排查使用。
    """
    conn = mf._connect(db_path)
    row = conn.execute(
        "SELECT * FROM dd_v1_manifest WHERE library_id=? AND file_id=?",
        (library_id, file_id),
    ).fetchone()
    if row is None:
        raise KeyError(f"Manifest 无此条目：library={library_id} file_id={file_id}")

    res = extract_content(row["abs_path"], max_chars=max_chars,
                          allow_docling=allow_docling)

    if res.method == M_MISSING:
        status = mf.PARSE_SKIPPED
    elif res.readable and res.truncated:
        status = mf.PARSE_PARTIAL
    elif res.readable:
        status = mf.PARSE_OK
    else:
        status = mf.PARSE_FAILED

    conn.execute(
        """UPDATE dd_v1_manifest
           SET parse_status=?, parse_method=?, parse_error=?, truncated=?
           WHERE file_id=?""",
        (status, res.method, res.error[:500], 1 if res.truncated else 0, file_id),
    )
    conn.commit()

    # 正文缓存（受控 Data Plane）。认知卡与 FTS 索引依赖它——
    # 没有正文缓存，FTS 就只能搜到标题，材料内容等于没进索引。
    # WP-A1（G5 位置 2）：**入索引前 PII 拒识**——抽取正文写进卡片缓存 / FTS 前
    # 必须脱敏（纯规则、确定性；缓存与索引里不得出现 PII 原串）。
    if res.readable and res.text:
        from cangjie_fos.services.dd_v1_card_service import (  # noqa: PLC0415
            cache_text,
        )
        from cangjie_fos.services import dd_v1_pii_service as pii  # noqa: PLC0415

        red = pii.redact_detailed(res.text)
        cache_text(file_id, library_id, red["text"], method=res.method,
                   truncated=res.truncated, original_chars=res.original_chars,
                   db_path=db_path)
        if red["redacted"]:
            logger.info("正文入索引前拒识 PII %d 处（file_id=%s）", red["count"], file_id)

    out = res.to_dict()
    out.update({"file_id": file_id, "parse_status": status})
    return out


def parse_pending_batch(
    library_id: str,
    limit: int = 200,
    db_path: Path | None = None,
    allow_docling: bool = True,
    progress_callback=None,
) -> dict:
    """批量抽取尚未解析（或需重试）的材料。"""
    conn = mf._connect(db_path)
    rows = conn.execute(
        """SELECT file_id FROM dd_v1_manifest
           WHERE library_id=? AND deleted_at IS NULL
             AND (parse_status IN (?,?) OR parse_status=?)
           ORDER BY file_id LIMIT ?""",
        (library_id, mf.PARSE_PENDING, mf.PARSE_FAILED, mf.PARSE_PARTIAL, limit),
    ).fetchall()

    tally = {mf.PARSE_OK: 0, mf.PARSE_PARTIAL: 0, mf.PARSE_FAILED: 0,
             mf.PARSE_SKIPPED: 0}
    failures = []
    for i, r in enumerate(rows, 1):
        out = extract_and_record(library_id, r["file_id"], db_path=db_path,
                                 allow_docling=allow_docling)
        tally[out["parse_status"]] = tally.get(out["parse_status"], 0) + 1
        if out["parse_status"] == mf.PARSE_FAILED:
            failures.append({"file_id": r["file_id"], "error": out["error"]})
        if progress_callback:
            progress_callback(i, len(rows))

    return {
        "library_id": library_id,
        "processed": len(rows),
        "by_status": tally,
        "failures": failures[:20],
        "failure_count": len(failures),
        "docling_available": docling_available(),
    }
