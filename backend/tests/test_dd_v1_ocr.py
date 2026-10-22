"""DD-V1 本地 OCR 服务测试（WP-A2 / G-A2-6）。

覆盖验收要点：

- 四个方向（0/90/180/270）**全部试跑**，并按**中文字数最多**择一；
- 合成中文扫描件被旋转 90/180/270 后仍能读回正文，且报告出正确方向；
- OCR **只在「没有文字层」时**触发——有文字层的文件绝不被重新 OCR；
- OCR 失败 / 认不出字时**维持 M_EMPTY / M_UNREADABLE**，不编造正文；
- 不引入 poppler / docling / 任何新依赖——纯本地、零成本。

用到的图片**全部是本测试自己合成的**（PIL 渲染中文文本），不依赖任何真实材料库。
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_ocr_service as ocr
from cangjie_fos.services import dd_v1_parser_service as ps

# 常见中文字体（按优先级探测）；找不到就跳过「真实 OCR」用例，不伪造结果
FONT_CANDIDATES = (
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simsun.ttc",
)

# 合成图片上的中文（OCR 稳定可辨的词）
SCAN_LINES = ("审计报告", "二〇二四年度", "净资产余额", "应收账款")
ANCHOR = "审计报告"


def _font_path() -> str | None:
    for cand in FONT_CANDIDATES:
        if os.path.isfile(cand):
            return cand
    return None


def _make_scan_image(path: Path, width: int = 1300, height: int = 900,
                     lines: tuple[str, ...] = SCAN_LINES) -> Path:
    """合成一张「扫描件」：白底 + 中文文本。"""
    from PIL import Image, ImageDraw, ImageFont

    font_path = _font_path()
    assert font_path, "本机没有可用的中文字体"
    font = ImageFont.truetype(font_path, 56)
    img = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((90, 120 + i * 150), line, font=font, fill=0)
    img.save(path)
    return path


def _rotate_clockwise(img, degrees: int):
    """把图**顺时针**转 degrees 度（PIL rotate 正数 = 逆时针，故取负）。"""
    if degrees == 0:
        return img.copy()
    return img.rotate(-degrees, expand=True)


def _detect_angle(png_bytes: bytes) -> int | None:
    """从候选图里认出它是第几个方向（左上角黑色方块随逆时针旋转换位）。"""
    from PIL import Image

    img = Image.open(io.BytesIO(png_bytes)).convert("L")
    w, h = img.size
    for angle, (x, y) in {
        0: (6, 6),
        90: (6, h - 7),
        180: (w - 7, h - 7),
        270: (w - 7, 6),
    }.items():
        if img.getpixel((x, y)) < 128:
            return angle
    return None


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """**强制离线、零成本**：视觉大模型一律不启用（否则 markitdown 会走付费 API）。"""
    monkeypatch.setenv("CANGJIE_OCR_DISABLED", "1")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("CANGJIE_VISION_BASE_URL", raising=False)
    monkeypatch.delenv("CANGJIE_VISION_API_KEY", raising=False)
    monkeypatch.delenv("CANGJIE_VISION_MODEL", raising=False)


# --------------------------------------------------------------------------
# 基础能力
# --------------------------------------------------------------------------
def test_local_ocr_toolchain_available():
    """本机必须自带 tesseract + Pillow（零新增依赖的前提）。"""
    assert ocr.tesseract_available(), "本机缺少 tesseract"
    assert ocr.pillow_available(), "venv 里缺少 Pillow"
    assert ocr.ocr_available()


def test_count_chinese_counts_only_cjk():
    assert ocr.count_chinese("审计报告") == 4
    assert ocr.count_chinese("audit 2024 报告") == 2
    assert ocr.count_chinese("") == 0
    assert ocr.count_chinese("abc123") == 0


def test_supports_ocr_only_for_image_and_pdf(tmp_path):
    assert ocr.supports_ocr(tmp_path / "a.png") is True
    assert ocr.supports_ocr(tmp_path / "a.jpg") is True
    assert ocr.supports_ocr(tmp_path / "a.pdf") is True
    assert ocr.supports_ocr(tmp_path / "a.txt") is False
    assert ocr.supports_ocr(tmp_path / "a.docx") is False


# --------------------------------------------------------------------------
# 方向选择算法
# --------------------------------------------------------------------------
def test_pick_prefers_the_candidate_with_most_chinese_characters():
    """选取规则 = 可靠中文字数最多者胜出（并列时确定性打破平局）。"""
    candidates = [
        {"angle": 0, "chinese_chars": 3, "mean_conf": 90.0},
        {"angle": 90, "chinese_chars": 12, "mean_conf": 40.0},
        {"angle": 180, "chinese_chars": 12, "mean_conf": 80.0},
        {"angle": 270, "chinese_chars": 5, "mean_conf": 95.0},
    ]
    best = ocr._pick(candidates)
    assert best["angle"] == 180, "中文数并列时应按平均置信度取更高者"
    assert best["chinese_chars"] == 12


def test_all_four_orientations_are_tried(tmp_path, monkeypatch):
    """四个方向（0/90/180/270）必须**全部**试跑，顺序固定。"""
    from PIL import Image, ImageDraw

    img = Image.new("L", (1300, 900), 255)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 40, 40), fill=0)  # 左上角标记，用来认出方向
    src = tmp_path / "marker.png"
    img.save(src)

    seen: list[int] = []

    def fake_run(png_bytes, timeout=None):
        angle = _detect_angle(png_bytes)
        assert angle is not None, "候选图应能定位方向标记"
        seen.append(angle)
        return []

    monkeypatch.setattr(ocr, "_run_tesseract", fake_run)
    ocr.ocr_image_file(src)

    assert seen == [0, 90, 180, 270]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_recovers_rotated_chinese_scan(tmp_path, rotation):
    """合成扫描件被旋转后，仍能读回中文正文，并报告正确方向。"""
    from PIL import Image

    base = tmp_path / "base.png"
    _make_scan_image(base)
    with Image.open(base) as img:
        rotated = _rotate_clockwise(img, rotation)
    src = tmp_path / f"rot{rotation}.png"
    rotated.save(src)

    res = ocr.ocr_image_file(src)

    assert res.readable is True, f"方向 {rotation} 应能识别出正文：{res.error}"
    assert ANCHOR in res.text, f"方向 {rotation} 读回正文不符：{res.text[:80]!r}"
    assert res.orientation == rotation, (
        f"方向 {rotation} 报告为 {res.orientation}（=页面相对正立顺时针旋转的度数）"
    )
    assert res.chinese_chars >= 4
    assert res.method == ocr.M_OCR


# --------------------------------------------------------------------------
# 接入点：只在「没有文字层」时触发
# --------------------------------------------------------------------------
def test_parser_uses_ocr_for_image_without_text_layer(tmp_path):
    """图片没有文字层 → 走本地 OCR，method 记为 ocr，并带出方向。"""
    src = tmp_path / "扫描件.png"
    _make_scan_image(src)

    res = ps.extract_content(src)

    assert res.readable is True
    assert res.method == ps.M_OCR
    assert res.method == "ocr"
    assert ANCHOR in res.text
    assert res.orientation in (0, 90, 180, 270)
    assert res.to_dict()["orientation"] == res.orientation


def test_text_layer_file_is_never_ocred(tmp_path, monkeypatch):
    """有文字层的文件**绝不**被重新 OCR（OCR 只在无文字层时兜底）。"""
    calls: list[str] = []

    def boom(path, *a, **k):
        calls.append(str(path))
        raise AssertionError("有文字层的文件不应触发 OCR")

    monkeypatch.setattr(ps.ocr, "ocr_file", boom)

    txt = tmp_path / "正文.txt"
    txt.write_text("这是有文字层的正文，二〇二四年度。", encoding="utf-8")

    res = ps.extract_content(txt)

    assert res.readable is True
    assert res.method != ps.M_OCR
    assert calls == []


def test_non_image_types_skip_ocr_entirely(tmp_path, monkeypatch):
    """非图片/非 PDF 类型连 OCR 入口都不进（OCR 不是默认路径）。"""
    calls: list[str] = []

    def spy(path, *a, **k):
        calls.append(str(path))
        return ocr.OcrResult(method=ocr.M_OCR, readable=False, error="不应被调用")

    monkeypatch.setattr(ps.ocr, "ocr_file", spy)

    empty = tmp_path / "空.txt"
    empty.write_text("", encoding="utf-8")

    res = ps.extract_content(empty)

    assert calls == []
    assert res.method in (ps.M_UNREADABLE, ps.M_EMPTY)


# --------------------------------------------------------------------------
# 诚实性：认不出就不许编造
# --------------------------------------------------------------------------
def test_ocr_failure_keeps_unreadable_and_no_text(tmp_path, monkeypatch):
    """OCR 失败 → 维持 M_EMPTY / M_UNREADABLE，且**没有正文**。"""
    def failing(path, *a, **k):
        return ocr.OcrResult(method=ocr.M_OCR, readable=False, error="tesseract 崩溃")

    monkeypatch.setattr(ps.ocr, "ocr_file", failing)

    src = tmp_path / "扫描件.png"
    _make_scan_image(src)

    res = ps.extract_content(src)

    assert res.readable is False
    assert res.method in (ps.M_UNREADABLE, ps.M_EMPTY)
    assert res.text == "", "OCR 失败不得留下半截正文"
    assert res.error


def test_blank_image_does_not_fabricate_text(tmp_path):
    """空白图片（无任何字）→ 认不出就**不产出正文**，不假装解析成功。"""
    from PIL import Image

    blank = tmp_path / "空白.png"
    Image.new("L", (1200, 900), 255).save(blank)

    res = ps.extract_content(blank)

    assert res.readable is False
    assert res.method in (ps.M_UNREADABLE, ps.M_EMPTY)
    assert res.text.strip() == "", "认不出字就不许产出正文"


def test_ocr_service_result_is_unreadable_when_nothing_found(tmp_path):
    """OCR 服务自身：没有识别出中文 → readable=False（上层据此维持不可读）。"""
    from PIL import Image

    blank = tmp_path / "空白.png"
    Image.new("L", (1200, 900), 255).save(blank)

    res = ocr.ocr_file(blank)

    assert res.readable is False
    assert res.text == ""
    assert res.error


# --------------------------------------------------------------------------
# 依赖红线：不引入 poppler / docling / 任何新依赖
# --------------------------------------------------------------------------
def test_no_poppler_docling_or_new_dependency_in_ocr_path():
    """OCR 路径源码里不得出现 poppler / docling 等被否决的重依赖。

    只查**可执行代码**（剔除文档字符串与行内注释）——文档里写明「不用 poppler」
    是允许的，但代码里一旦真的去调它就必须失败。
    """
    import re as _re

    src = Path(ocr.__file__).read_text(encoding="utf-8")
    stripped = [
        line.split("  # ")[0] for line in src.splitlines()
        if not line.strip().startswith("#")
    ]
    code = "\n".join(stripped)
    code = _re.sub(r'"""[\s\S]*?"""', "", code)   # 模块/函数文档字符串
    code = _re.sub(r"'''[\s\S]*?'''", "", code)

    for banned in ("pdftoppm", "pdfimages", "poppler", "docling"):
        assert banned not in code.lower(), f"OCR 路径不得引入 {banned}"
    assert "import numpy" not in code
    assert "subprocess" in code


def test_ocr_module_import_does_not_pull_heavy_deps():
    """导入 OCR 服务不得牵出 docling 等重依赖。"""
    import subprocess
    import sys

    code = (
        "import sys;"
        "import cangjie_fos.services.dd_v1_ocr_service as o;"
        "print('docling' in sys.modules, 'torch' in sys.modules)"
    )
    src_dir = str(Path(ocr.__file__).resolve().parents[2])  # .../backend/src
    env = dict(os.environ, PYTHONPATH=src_dir)
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=120, env=env,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False False", out.stdout


# --------------------------------------------------------------------------
# PDF（无文字层的 PDF 同样走本地 OCR；用 pdfplumber 的既有传递依赖栅格化）
# --------------------------------------------------------------------------
def test_image_only_pdf_is_ocred(tmp_path):
    """无文字层 PDF → 栅格化后本地 OCR，读回中文正文。"""
    pytest.importorskip("pypdfium2")
    base = tmp_path / "base.png"
    _make_scan_image(base)
    pdf = tmp_path / "扫描件.pdf"
    from PIL import Image

    with Image.open(base) as img:
        img.save(pdf, "PDF", resolution=200.0)

    res = ocr.ocr_file(pdf)

    assert res.readable is True, res.error
    assert ANCHOR in res.text
    assert res.pages == 1
    assert res.orientation in (0, 90, 180, 270)


# --------------------------------------------------------------------------
# 落库：抽取方式必须可追溯
# --------------------------------------------------------------------------
def test_parse_method_is_recorded_as_ocr(tmp_path, monkeypatch):
    """OCR 命中后，Manifest 的 parse_method 必须记成 ocr（可追溯）。"""
    from cangjie_fos.services import dd_v1_manifest_service as mf

    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    db = tmp_path / "_dp" / "manifest.sqlite"
    root = tmp_path / "materials"
    root.mkdir()
    mf.register_library("lib_ocr", str(root), authorized_by="test", db_path=db)
    _make_scan_image(root / "扫描件.png")
    mf.build_manifest("lib_ocr", db_path=db)
    entry = mf.get_manifest_entry("lib_ocr", "扫描件.png", db_path=db)
    assert entry is not None

    out = ps.extract_and_record("lib_ocr", entry["file_id"], db_path=db)

    assert out["method"] == ps.M_OCR
    assert out["parse_status"] == mf.PARSE_OK
    assert out["orientation"] in (0, 90, 180, 270)
    row = mf.get_manifest_entry("lib_ocr", "扫描件.png", db_path=db)
    assert row["parse_method"] == "ocr"
