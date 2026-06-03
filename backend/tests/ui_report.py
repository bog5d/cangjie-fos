"""浏览器「模拟人工测试」截图报告器（Playwright + Pillow，零新依赖）。

用途：
  每个浏览器冒烟测试的关键步骤都截一张图，附中文标注（步骤名 + PASS/FAIL +
  备注），最终合成一份多页 PDF。让人/AI 能像看人工测试录像一样逐帧审核 UI
  真实渲染，而不是只信「vitest 全绿」。

为什么需要：
  vitest 跑在 jsdom 里，看不到真实 Chrome 渲染、CSS 可见性、叠层阻塞、点击
  跳转。这份带截图 PDF 是「模拟人工测试」的可视证据，回传给 Claude 审核。

设计原则：
  - 零新依赖：仅用 Pillow（已装）把 PNG 截图合成 PDF
  - 中文标注用系统自带文泉驿正黑字体
  - 任何一步 FAIL 都在该页横幅标红，PDF 文件名带 FAILED 前缀，便于一眼识别

输出位置：
  backend/data/ui_reports/{report_name}_{timestamp}.pdf
"""
from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 系统自带 CJK 字体（容器内 /usr/share/fonts/truetype/wqy/wqy-zenhei.ttc）
_CJK_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/etc/alternatives/fonts-japanese-gothic.ttf",
]

_STATUS_COLORS = {
    "ok": (22, 163, 74),       # 绿
    "fail": (220, 38, 38),     # 红
    "info": (71, 85, 105),     # 灰蓝
    "warn": (217, 119, 6),     # 琥珀
}


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _CJK_FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


@dataclass
class _Shot:
    png: bytes
    label: str
    status: str
    note: str


@dataclass
class UIReporter:
    """累积截图，finalize 时合成一份 PDF。

    用法：
        rep = UIReporter("dd_wizard_smoke")
        rep.capture(page, "登录后主页", status="ok")
        rep.capture(page, "尽调向导 Step1", status="ok", note="材料库路径可见")
        rep.fail(page, "导出按钮缺失", note="点击后无反应")
        pdf_path = rep.finalize()
    """

    report_name: str
    shots: list[_Shot] = field(default_factory=list)
    any_fail: bool = False

    def capture(self, page, label: str, status: str = "ok", note: str = "") -> None:
        """对当前页面截图并附标注。status: ok / fail / info / warn。"""
        if status == "fail":
            self.any_fail = True
        png = page.screenshot(full_page=False)
        self.shots.append(_Shot(png=png, label=label, status=status, note=note))

    def fail(self, page, label: str, note: str = "") -> None:
        """便捷：截一张 FAIL 图。"""
        self.capture(page, label, status="fail", note=note)

    def _render_page(self, shot: _Shot, index: int, total: int) -> Image.Image:
        """单张截图 + 顶部中文标注横幅，返回 RGB 图。"""
        screenshot = Image.open(io.BytesIO(shot.png)).convert("RGB")
        w = screenshot.width
        banner_h = 96
        canvas = Image.new("RGB", (w, screenshot.height + banner_h), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)

        color = _STATUS_COLORS.get(shot.status, _STATUS_COLORS["info"])
        draw.rectangle([0, 0, w, banner_h], fill=color)

        title_font = _load_font(30)
        note_font = _load_font(22)
        badge = {"ok": "✅ PASS", "fail": "❌ FAIL",
                 "warn": "⚠️ WARN", "info": "ℹ️ INFO"}.get(shot.status, "INFO")
        draw.text((16, 12), f"[{index}/{total}] {badge}  {shot.label}",
                  fill=(255, 255, 255), font=title_font)
        if shot.note:
            draw.text((16, 56), shot.note, fill=(255, 255, 255), font=note_font)

        canvas.paste(screenshot, (0, banner_h))
        return canvas

    def finalize(self, out_dir: Path | None = None) -> Path | None:
        """合成 PDF，返回路径。无截图则返回 None。"""
        if not self.shots:
            return None
        out_dir = out_dir or (Path(__file__).parent.parent / "data" / "ui_reports")
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = time.strftime("%Y%m%d_%H%M%S")
        prefix = "FAILED_" if self.any_fail else ""
        out_path = out_dir / f"{prefix}{self.report_name}_{ts}.pdf"

        total = len(self.shots)
        pages = [self._render_page(s, i + 1, total) for i, s in enumerate(self.shots)]
        pages[0].save(out_path, save_all=True, append_images=pages[1:],
                      resolution=100.0)
        return out_path
