"""统一内容抽取（供精判节点按需调用）— 解密 + 多格式 + OCR 兜底。

定位（关键架构）：只在「读正文验证（精判）」节点、对【粗匹配出来的少数候选文件】
调用——惰性、少量；绝不在扫描期对全库跑（那正是大库扫描卡死的旧坑）。

三层降级（每层依赖都惰性导入；缺失或失败都不影响 app 启动，自动退到下一层）：
  1. 加密文件 → 用登记密码解密到临时文件（Office: msoffcrypto / PDF: pikepdf）
  2. 文字层快速抽取（pdfplumber / python-docx / openpyxl，复用 dd_file_parser）
  3. 文字层为空（扫描件 / 图片型 PDF）→ MarkItDown 统一转换；若配置了视觉模型
     （CANGJIE_VISION_*）则对图片走 OCR/视觉识别，否则尽力抽取文字层。

返回 (text, readable, method)：method ∈ text/decrypt+text/markitdown/unreadable/missing。
所有内部步骤可被测试 monkeypatch。
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from cangjie_fos.services.dd_file_parser import extract_full_text

logger = logging.getLogger(__name__)

_OFFICE_EXTS = {".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt"}


def extract_for_verify(
    file_path: str, password: str = "", max_chars: int = 6000,
) -> tuple[str, bool, str]:
    """精判前的统一内容抽取（解密 → 文字层 → MarkItDown 兜底）。

    返回 (text, readable, method)。
    """
    p = Path(file_path)
    if not file_path or not p.exists():
        return "", False, "missing"

    decrypted: Path | None = None
    work = p
    if password:
        decrypted = _try_decrypt(p, password)
        if decrypted is not None:
            work = decrypted

    try:
        # 2. 文字层快速抽取
        text, _readable = extract_full_text(work, max_chars=max_chars)
        if text and text.strip():
            return text, True, ("decrypt+text" if decrypted else "text")

        # 3. 文字层为空（扫描件/图片型）→ MarkItDown 兜底
        md_text = _try_markitdown(work, max_chars)
        if md_text and md_text.strip():
            return md_text, True, ("decrypt+markitdown" if decrypted else "markitdown")

        return "", False, "unreadable"
    finally:
        if decrypted is not None:
            try:
                decrypted.unlink()
            except OSError:
                pass


def _try_decrypt(path: Path, password: str) -> Path | None:
    """用密码解密加密 Office/PDF，返回临时明文文件路径；失败/非加密返回 None。"""
    ext = path.suffix.lower()
    try:
        if ext in _OFFICE_EXTS:
            import msoffcrypto  # noqa: PLC0415
            with open(path, "rb") as f:
                office = msoffcrypto.OfficeFile(f)
                office.load_key(password=password)
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                try:
                    office.decrypt(tmp)
                finally:
                    tmp.close()
            return Path(tmp.name)
        if ext == ".pdf":
            import pikepdf  # noqa: PLC0415
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            tmp.close()
            with pikepdf.open(str(path), password=password) as pdf:
                pdf.save(tmp.name)
            return Path(tmp.name)
    except Exception as e:  # noqa: BLE001
        # 密码错 / 非加密 / 依赖缺失 → 不阻断，退回普通抽取
        logger.warning("解密失败（退回普通抽取）%s: %s", path.name, e)
    return None


def _resolve_vision() -> tuple[str, str, str] | None:
    """解析视觉 OCR 配置（用于把扫描件/图片识别成文字）。返回 (base_url, api_key, model) 或 None。

    优先级（开箱即用）：
      1. 显式覆盖：CANGJIE_VISION_BASE_URL + CANGJIE_VISION_API_KEY + CANGJIE_VISION_MODEL
      2. 显式关闭：CANGJIE_OCR_DISABLED=1/true/yes → 返回 None（省 API 成本）
      3. 默认：复用百炼 DASHSCOPE_API_KEY（同事为 ASR 早已配好）→ qwen-vl-max，
         走 DashScope OpenAI 兼容端点；模型可用 CANGJIE_VISION_MODEL 覆盖。
    """
    base = os.getenv("CANGJIE_VISION_BASE_URL")
    key = os.getenv("CANGJIE_VISION_API_KEY")
    model = os.getenv("CANGJIE_VISION_MODEL")
    if base and key and model:
        return base, key, model

    if os.getenv("CANGJIE_OCR_DISABLED", "").strip().lower() in ("1", "true", "yes"):
        return None

    ds_key = os.getenv("DASHSCOPE_API_KEY")
    if ds_key:
        return (
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ds_key,
            model or "qwen-vl-max",
        )
    return None


def _build_markitdown():
    """构建 MarkItDown 实例；解析到视觉配置则启用图片 OCR，否则纯文本抽取（优雅降级）。"""
    from markitdown import MarkItDown  # noqa: PLC0415
    cfg = _resolve_vision()
    if cfg:
        base, key, model = cfg
        try:
            from openai import OpenAI  # noqa: PLC0415
            client = OpenAI(base_url=base, api_key=key)
            return MarkItDown(llm_client=client, llm_model=model)
        except Exception as e:  # noqa: BLE001
            logger.warning("视觉模型初始化失败，MarkItDown 退回纯文本抽取: %s", e)
    return MarkItDown()


def _try_markitdown(path: Path, max_chars: int) -> str:
    """用 MarkItDown 统一转换（多格式 + 图片 OCR 若已配视觉模型）。失败返回空串。"""
    try:
        md = _build_markitdown()
        result = md.convert(str(path))
        return (getattr(result, "text_content", "") or "")[:max_chars]
    except Exception as e:  # noqa: BLE001
        logger.warning("MarkItDown 抽取失败 %s: %s", path.name, e)
        return ""
