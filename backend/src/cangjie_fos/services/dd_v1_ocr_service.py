"""DD-V1 本地 OCR 服务（WP-A2 / G-A2-6）。

**为什么需要它**：W9 实测发现，材料库里相当大比例是**扫描件**（图片 / 无文字层
PDF）——既有抽取链读不到任何文字，`parse_method` 落到 ``M_RAW`` / ``M_EMPTY``，
认知卡的 期间 / 主体 / 用途 三件套填不出来（实测填充率仅 ~50-60%）。

**本服务做什么**：对**确实没有文字层**的文件调本机 ``tesseract`` 做本地 OCR，
并**必须解决扫描件常见的 0/90/180/270 度旋转**。

**成本与依赖**：零网络、零付费 API、**不新增任何 pip 依赖**——
只用系统已有的 ``tesseract``（chi_sim）与已在 venv 里的 Pillow；
旋转像素纯用 PIL，**不引入 poppler（pdftoppm/pdfimages）**，**不走 docling**。
PDF 栅格化用 ``pypdfium2``（pdfplumber 的既有传递依赖，已在 venv 中），
缺失时自动降级为「不 OCR」，不报错。

**方向选择算法**（固定、可复现）：

1. 对同一张图依次试 **0 / 90 / 180 / 270** 四个候选方向（PIL ``rotate`` 语义 =
   **逆时针**），每个候选都跑一次 tesseract；
2. 统计每个候选 OCR 文本中的**中文（CJK）码位数**，取**最高者**胜出；
3. 计数用的是**置信度过滤后**的 OCR 文本（词级 conf ≥ ``MIN_WORD_CONF``）。
   这一步是必需的、不是修饰：实测中文页在**错误方向**下 tesseract 会「幻觉」
   出等量的中文字符（未过滤时 16/16 个方向的判读全错，例如正确方向 68 字、
   倒置方向 69 字）；按词置信度过滤后，错误方向的可靠中文降到 8~20 字，
   正确方向保持在 63~96 字，方向判读 16/16 全对。
4. 胜出方向的 ``orientation`` 即「把源图逆时针旋转多少度可以正立」，
   也就是**页面相对正立被顺时针转了多少度**（CW 90 的扫描件 → orientation=90）。
   并列时按（可靠中文数 → 平均置信度 → 角度小者优先）确定性打破平局。

**诚实性红线**：

- OCR 一无所获时**不得**产出空正文冒充成功——``readable=False``，
  上层必须继续维持 ``M_EMPTY`` / ``M_UNREADABLE``；
- 本服务**只产出文本与方法标记**，**绝不产出任何判定（verdict）**；
- 识别不出就不给字，绝不用「猜出来的字」填充卡片字段。
"""
from __future__ import annotations

import csv
import io
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# 抽取方式标记（写入 parse_method，与 parser 层的 M_* 同一套命名）
M_OCR = "ocr"

#: 四个候选方向（PIL rotate 语义 = 逆时针）
ORIENTATIONS: tuple[int, ...] = (0, 90, 180, 270)

#: 可以做 OCR 的文件类型：图片 + PDF（PDF 走 pypdfium2 栅格化）
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"})
PDF_SUFFIXES = frozenset({".pdf"})

# CJK 码位：CJK 扩展 A / 基本区 / 兼容表意 / 扩展 B
_CJK_RE = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002a6df]"
)

# —— 可调旋钮（环境变量，全部有默认值，不配置也能跑）——
#: OCR 语言包（chi_sim 必选；eng 附带识别数字/拉丁字母）
OCR_LANG = os.getenv("CANGJIE_DD_V1_OCR_LANG", "chi_sim+eng") or "chi_sim+eng"
#: 页面分割模式。4 = 单列文本（不做自动旋转，方向判定只由本服务决定）
OCR_PSM = int(os.getenv("CANGJIE_DD_V1_OCR_PSM", "4") or "4")
#: 单次 tesseract 调用超时（秒）——必须有界，绝不让测试/批处理挂死
OCR_TIMEOUT = float(os.getenv("CANGJIE_DD_V1_OCR_TIMEOUT", "30") or "30")
#: 单个文件 OCR 的总时间预算（秒）——四方向 × 多页都受它约束
OCR_TOTAL_BUDGET = float(os.getenv("CANGJIE_DD_V1_OCR_BUDGET", "120") or "120")
#: 词级置信度阈值：低于此值视为幻觉乱码，不计入中文计数
MIN_WORD_CONF = float(os.getenv("CANGJIE_DD_V1_OCR_MIN_CONF", "50") or "50")
#: 判定「可用」所需的最小可靠中文数（低于此值 = 没识别出来）
MIN_CJK_USABLE = int(os.getenv("CANGJIE_DD_V1_OCR_MIN_CJK", "2") or "2")
#: PDF 最多栅格化几页（扫描件正文通常在前几页；避免大文件拖死批处理）
MAX_PDF_PAGES = int(os.getenv("CANGJIE_DD_V1_OCR_MAX_PAGES", "3") or "3")
#: PDF 栅格化 DPI（tesseract 偏好的输入分辨率）
PDF_RENDER_DPI = float(os.getenv("CANGJIE_DD_V1_OCR_DPI", "200") or "200")
#: 图像长边上限（超过则等比缩放，限制 OCR 耗时）
MAX_IMAGE_EDGE = int(os.getenv("CANGJIE_DD_V1_OCR_MAX_EDGE", "3000") or "3000")
#: 小图放大阈值（长边小于此值时放大 2 倍，提升识别率）
MIN_IMAGE_EDGE = int(os.getenv("CANGJIE_DD_V1_OCR_MIN_EDGE", "800") or "800")

# tesseract 可执行文件的候选位置（shutil.which 找不到时兜底）
_TESSERACT_FALLBACKS = (
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/usr/bin/tesseract",
)


@dataclass
class OcrWord:
    """一个 OCR 词及其置信度（0~100）。"""

    text: str
    conf: float
    line_key: tuple = ()  #: (page, block, par, line) —— 用来还原行结构


@dataclass
class OcrResult:
    """一次 OCR 的可观测结果。**只有 readable=True 才允许被当作正文使用。**"""

    text: str = ""
    readable: bool = False
    method: str = M_OCR
    orientation: int | None = None      #: 胜出方向（= 页面相对正立顺时针旋转的度数）
    chinese_chars: int = 0              #: 胜出方向的可靠中文数（置信度过滤后）
    raw_chinese_chars: int = 0          #: 胜出方向的原始中文数（不过滤，仅诊断用）
    mean_conf: float = 0.0
    pages: int = 0
    page_orientations: list[int] = field(default_factory=list)
    error: str = ""
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "readable": self.readable,
            "orientation": self.orientation,
            "chinese_chars": self.chinese_chars,
            "raw_chinese_chars": self.raw_chinese_chars,
            "mean_conf": round(self.mean_conf, 1),
            "pages": self.pages,
            "page_orientations": list(self.page_orientations),
            "chars": len(self.text),
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
        }


# --------------------------------------------------------------------------
# 能力探测
# --------------------------------------------------------------------------
def tesseract_binary() -> str | None:
    """找 tesseract 可执行文件；找不到返回 None（调用方据此降级）。"""
    found = shutil.which("tesseract")
    if found:
        return found
    for cand in _TESSERACT_FALLBACKS:
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def tesseract_available() -> bool:
    """本机是否有可用的 tesseract。"""
    return tesseract_binary() is not None


def pillow_available() -> bool:
    """Pillow 是否可用（OCR 图像处理的前提）。"""
    try:
        import PIL  # noqa: F401,PLC0415
        return True
    except Exception:  # noqa: BLE001
        return False


def ocr_available() -> bool:
    """本地 OCR 是否可用（tesseract + Pillow 都在）。"""
    return tesseract_available() and pillow_available()


def supports_ocr(path: str | Path) -> bool:
    """该文件类型是否走本地 OCR（图片 / PDF）。其它类型一律不走。"""
    suffix = Path(path).suffix.lower()
    return suffix in IMAGE_SUFFIXES or suffix in PDF_SUFFIXES


def count_chinese(text: str) -> int:
    """统计文本中的中文（CJK）码位数——方向选择的主指标。"""
    if not text:
        return 0
    return len(_CJK_RE.findall(text))


# --------------------------------------------------------------------------
# tesseract 调用
# --------------------------------------------------------------------------
def _tesseract_env() -> dict:
    env = os.environ.copy()
    # 单线程：避免在受限环境里因线程创建失败而报错；不改动代理等网络设置
    env["OMP_THREAD_LIMIT"] = "1"
    return env


def _run_tesseract(png_bytes: bytes, timeout: float | None = None) -> list[OcrWord]:
    """跑一次 tesseract，返回词列表（含置信度）。

    图像以 PNG 字节**走 stdin**（``tesseract stdin stdout``），**不落临时文件**。
    超时 / 崩溃 / 非零退出码一律抛异常，由上层降级并留痕。
    """
    binary = tesseract_binary()
    if not binary:
        raise RuntimeError("本机未安装 tesseract")
    cmd = [
        binary, "stdin", "stdout",
        "-l", OCR_LANG,
        "--psm", str(OCR_PSM),
        "tsv",
    ]
    try:
        proc = subprocess.run(  # noqa: S603 — 命令固定，无 shell
            cmd,
            input=png_bytes,
            capture_output=True,
            timeout=timeout if timeout is not None else OCR_TIMEOUT,
            env=_tesseract_env(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"tesseract 超时（>{timeout if timeout is not None else OCR_TIMEOUT}s）") from exc
    except OSError as exc:
        raise RuntimeError(f"tesseract 调用失败：{exc}") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "ignore").strip()[:200]
        raise RuntimeError(f"tesseract 退出码 {proc.returncode}：{err}")
    return _parse_tsv(proc.stdout.decode("utf-8", "ignore"))


def _parse_tsv(raw: str) -> list[OcrWord]:
    """解析 tesseract TSV 输出，取词级文本、置信度与行结构。"""
    words: list[OcrWord] = []
    if not raw.strip():
        return words
    reader = csv.reader(io.StringIO(raw), delimiter="\t", quoting=csv.QUOTE_NONE)
    for i, row in enumerate(reader):
        if i == 0:
            continue  # 表头
        if len(row) < 12:
            continue
        level = row[0].strip()
        if level != "5":  # 只取词级行
            continue
        text = row[11].strip()
        if not text:
            continue
        try:
            conf = float(row[10])
        except (TypeError, ValueError):
            conf = -1.0
        line_key = tuple(row[j].strip() for j in (1, 2, 3, 4))
        words.append(OcrWord(text=text, conf=conf, line_key=line_key))
    return words


def _needs_space(prev: str, cur: str) -> bool:
    """两个相邻词之间是否要补空格。

    tesseract 对中文是**逐字切词**的（"审计" "报告"），若一律用空格拼，
    正文会变成 "审计 报告"，下游关键词匹配全废。故：**只有两侧都是 ASCII
    字母数字时才补空格**，中文之间直接相连。
    """
    if not prev or not cur:
        return False
    return bool(prev[-1].isascii() and prev[-1].isalnum()
                and cur[0].isascii() and cur[0].isalnum())


def _join_tokens(tokens: list[str]) -> str:
    out = ""
    for tok in tokens:
        if out and _needs_space(out, tok):
            out += " "
        out += tok
    return out


def _words_to_text(words: list[OcrWord]) -> str:
    """词列表 → 文本（保留行结构；中文逐字词之间不插空格）。"""
    lines: list[list[str]] = []
    cur_key: tuple | None = None
    for w in words:
        if w.line_key != cur_key:
            lines.append([])
            cur_key = w.line_key
        lines[-1].append(w.text)
    return "\n".join(_join_tokens(toks) for toks in lines if toks).strip()


# --------------------------------------------------------------------------
# 图像预处理 + 四方向判定
# --------------------------------------------------------------------------
def _load_image(path: Path):
    """打开图片 → 灰度、白底合成、EXIF 摆正、尺寸兜底。"""
    from PIL import Image, ImageOps  # noqa: PLC0415

    img = Image.open(path)
    img = ImageOps.exif_transpose(img) or img
    if img.mode in ("RGBA", "LA") or "transparency" in img.info:
        # 透明像素转灰度会变黑（= 前景色），先合成到白底
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    img = img.convert("L")

    w, h = img.size
    long_edge = max(w, h)
    if long_edge and long_edge > MAX_IMAGE_EDGE:
        scale = MAX_IMAGE_EDGE / long_edge
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    elif long_edge and long_edge < MIN_IMAGE_EDGE:
        img = img.resize((w * 2, h * 2), Image.LANCZOS)
    return img


def _png_bytes(img) -> bytes:
    """PIL 图 → PNG 字节（灰度，tesseract 友好）。"""
    buf = io.BytesIO()
    img.convert("L").save(buf, format="PNG")
    return buf.getvalue()


def _ocr_candidates(img, timeout: float | None = None,
                    deadline: float | None = None) -> list[dict]:
    """试四个方向，返回每个方向的识别结果（文本 / 中文数 / 置信度）。

    ``timeout`` 是单次 tesseract 调用超时；``deadline`` 是 time.monotonic() 时刻的
    总预算——预算用尽后不再试下一个方向，用已试过的候选决出胜者
    （保证批处理不会被单份材料拖死）。
    """
    out: list[dict] = []
    for angle in ORIENTATIONS:
        if deadline is not None and out and time.monotonic() > deadline:
            logger.warning("OCR 总预算用尽，停止尝试更多方向（已试 %s）", [c["angle"] for c in out])
            break
        cand = img if angle == 0 else img.rotate(angle, expand=True)
        words = _run_tesseract(_png_bytes(cand), timeout=timeout)
        text = _words_to_text(words)
        strong = [w for w in words if w.conf >= MIN_WORD_CONF]
        strong_text = _words_to_text(strong)
        strong_cjk = count_chinese(strong_text)
        raw_cjk = count_chinese(text)
        confs = [w.conf for w in strong if _CJK_RE.search(w.text)]
        mean_conf = (sum(confs) / len(confs)) if confs else 0.0
        out.append({
            "angle": angle,
            "text": text,
            "strong_text": strong_text,
            "chinese_chars": strong_cjk,
            "raw_chinese_chars": raw_cjk,
            "mean_conf": mean_conf,
        })
    return out


def _pick(candidates: list[dict]) -> dict:
    """按（可靠中文数 → 平均置信度 → 角度小）选出胜出方向。"""
    if not candidates:
        raise RuntimeError("没有任何方向的候选结果")
    return max(candidates, key=lambda c: (c["chinese_chars"], c["mean_conf"], -c["angle"]))


def _ocr_page(img, timeout: float | None = None, deadline: float | None = None) -> dict:
    """单页图的四方向判定，返回胜出方向的识别结果。"""
    candidates = _ocr_candidates(img, timeout=timeout, deadline=deadline)
    best = _pick(candidates)
    best["all"] = candidates
    return best


def _result_from_page(best: dict, pages: int, orientations: list[int]) -> OcrResult:
    """把单页识别结果装成 OcrResult（**识别不出就 readable=False，绝不编造**）。"""
    usable = best["chinese_chars"] >= MIN_CJK_USABLE and bool(best["text"].strip())
    return OcrResult(
        text=best["text"] if usable else "",
        readable=usable,
        method=M_OCR,
        orientation=best["angle"],
        chinese_chars=best["chinese_chars"],
        raw_chinese_chars=best["raw_chinese_chars"],
        mean_conf=best["mean_conf"],
        pages=pages,
        page_orientations=orientations,
        error="" if usable else (
            f"未识别出可用中文（chinese_chars={best['chinese_chars']}）"
        ),
    )


# --------------------------------------------------------------------------
# 对外接口
# --------------------------------------------------------------------------
def ocr_image_file(path: str | Path, timeout: float | None = None) -> OcrResult:
    """对**图片文件**做本地 OCR（四方向择一）。"""
    t0 = time.perf_counter()
    p = Path(path)
    res = OcrResult()
    if not p.is_file():
        res.error = f"文件不存在：{p}"
        return res
    if not tesseract_available():
        res.error = "本机未安装 tesseract，跳过本地 OCR"
        return res
    try:
        img = _load_image(p)
    except Exception as exc:  # noqa: BLE001
        res.error = f"图片读取失败：{type(exc).__name__}: {exc}"[:200]
        res.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return res
    try:
        best = _ocr_page(img, timeout=timeout,
                         deadline=time.monotonic() + OCR_TOTAL_BUDGET)
    except Exception as exc:  # noqa: BLE001
        res.error = f"OCR 失败：{type(exc).__name__}: {exc}"[:200]
        res.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return res
    res = _result_from_page(best, pages=1, orientations=[best["angle"]])
    res.elapsed_ms = int((time.perf_counter() - t0) * 1000)
    logger.info(
        "本地 OCR 完成 %s：orientation=%s chinese_chars=%s conf=%.1f",
        p.name, res.orientation, res.chinese_chars, res.mean_conf,
    )
    return res


def _pdf_page_images(path: Path, max_pages: int) -> list:
    """PDF → PIL 图像列表（pypdfium2 栅格化，pdfplumber 的既有传递依赖）。"""
    import pypdfium2 as pdfium  # noqa: PLC0415

    scale = PDF_RENDER_DPI / 72.0
    doc = pdfium.PdfDocument(str(path))
    imgs = []
    try:
        for i in range(min(len(doc), max_pages)):
            bitmap = doc[i].render(scale=scale)
            imgs.append(bitmap.to_pil())
    finally:
        try:
            doc.close()
        except Exception:  # noqa: BLE001,S110 — 关闭失败不影响结果
            pass
    return imgs


def ocr_pdf_file(path: str | Path, max_pages: int = MAX_PDF_PAGES,
                 timeout: float | None = None) -> OcrResult:
    """对**无文字层的 PDF** 做本地 OCR（逐页四方向择一）。"""
    t0 = time.perf_counter()
    p = Path(path)
    res = OcrResult()
    if not p.is_file():
        res.error = f"文件不存在：{p}"
        return res
    if not tesseract_available():
        res.error = "本机未安装 tesseract，跳过本地 OCR"
        return res
    try:
        page_imgs = _pdf_page_images(p, max_pages)
    except ImportError as exc:
        res.error = f"缺少 pypdfium2，无法栅格化 PDF：{exc}"[:200]
        res.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return res
    except Exception as exc:  # noqa: BLE001
        res.error = f"PDF 栅格化失败：{type(exc).__name__}: {exc}"[:200]
        res.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return res

    texts: list[str] = []
    orientations: list[int] = []
    total_strong = 0
    total_raw = 0
    confs: list[float] = []
    deadline = time.monotonic() + OCR_TOTAL_BUDGET
    for img in page_imgs:
        if time.monotonic() > deadline:
            logger.warning("OCR 总预算用尽，停止处理后续页（已处理 %s 页）", len(orientations))
            break
        try:
            best = _ocr_page(img, timeout=timeout, deadline=deadline)
        except Exception as exc:  # noqa: BLE001
            logger.warning("OCR 单页失败 %s：%s", p.name, exc)
            continue
        orientations.append(best["angle"])
        total_strong += best["chinese_chars"]
        total_raw += best["raw_chinese_chars"]
        if best["mean_conf"]:
            confs.append(best["mean_conf"])
        if best["chinese_chars"] >= MIN_CJK_USABLE and best["text"].strip():
            texts.append(best["text"])

    text = "\n".join(texts).strip()
    res.text = text
    res.readable = bool(text) and total_strong >= MIN_CJK_USABLE
    res.method = M_OCR
    res.orientation = orientations[0] if orientations else None
    res.chinese_chars = total_strong
    res.raw_chinese_chars = total_raw
    res.mean_conf = (sum(confs) / len(confs)) if confs else 0.0
    res.pages = len(orientations)  # 实际 OCR 过的页数（预算用尽时可能少于渲染页数）
    res.page_orientations = orientations
    res.elapsed_ms = int((time.perf_counter() - t0) * 1000)
    if not res.readable:
        # 没识别出来就是没识别出来——不产出正文冒充成功
        res.text = ""
        res.error = res.error or "PDF 未识别出可用文本"
    logger.info(
        "本地 OCR 完成 %s：pages=%s orientations=%s chinese_chars=%s",
        p.name, res.pages, res.page_orientations, res.chinese_chars,
    )
    return res


def ocr_file(path: str | Path, max_pages: int = MAX_PDF_PAGES,
             timeout: float | None = None) -> OcrResult:
    """本地 OCR 总入口：按文件类型分发（图片 / PDF）。"""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return ocr_image_file(p, timeout=timeout)
    if suffix in PDF_SUFFIXES:
        return ocr_pdf_file(p, max_pages=max_pages, timeout=timeout)
    res = OcrResult(method=M_OCR, readable=False)
    res.error = f"不支持本地 OCR 的文件类型：{suffix or '(无后缀)'}"
    return res
