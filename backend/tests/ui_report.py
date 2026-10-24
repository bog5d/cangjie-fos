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
    png: bytes | None
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

    def mark_failed(self, label: str, note: str = "", png: bytes | None = None) -> None:
        """记录一次「pytest 判定失败」——即使测试没主动调 fail()（如 Timeout、登录阶段就崩）。

        由 conftest 的 pytest_runtest_makereport 钩子调用，保证 PDF 总览与 pytest
        真实结果一致，不再出现「pytest 失败但报告显示全 PASS」。png 为空时生成纯文字失败页。
        """
        self.any_fail = True
        self.shots.append(_Shot(png=png, label=label, status="fail", note=note))

    def _render_page(self, shot: _Shot, index: int, total: int) -> Image.Image:
        """单张截图 + 顶部中文标注横幅，返回 RGB 图。无截图时生成纯文字失败页。"""
        banner_h = 96
        if shot.png:
            screenshot = Image.open(io.BytesIO(shot.png)).convert("RGB")
            w, body_h = screenshot.width, screenshot.height
        else:
            screenshot = None
            w, body_h = 1000, 280

        canvas = Image.new("RGB", (w, body_h + banner_h), (255, 255, 255))
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

        if screenshot is not None:
            canvas.paste(screenshot, (0, banner_h))
        else:
            draw.text((16, banner_h + 24),
                      "（无截图：页面无法截屏，或测试在截图前已崩溃 / 超时）",
                      fill=(120, 120, 120), font=note_font)
        return canvas

    def _render_summary(self) -> Image.Image:
        """首页总览：整体结论 + PASS/FAIL 计数 + 失败明细。一眼判定真实结果。"""
        total = len(self.shots)
        fails = sum(1 for s in self.shots if s.status == "fail")
        passes = sum(1 for s in self.shots if s.status == "ok")
        w, h = 1000, 760
        canvas = Image.new("RGB", (w, h), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        color = _STATUS_COLORS["fail"] if self.any_fail else _STATUS_COLORS["ok"]
        draw.rectangle([0, 0, w, 110], fill=color)
        verdict = "❌ 存在失败（FAILED）" if self.any_fail else "✅ 全部通过（PASS）"
        draw.text((24, 30), f"模拟人工测试总览 — {verdict}",
                  fill=(255, 255, 255), font=_load_font(34))

        body = _load_font(24)
        y = 140
        for ln in [
            f"报告：{self.report_name}",
            f"总帧数：{total}    ✅ PASS：{passes}    ❌ FAIL：{fails}",
            "",
            ("失败明细：" if fails else "无失败步骤。"),
        ]:
            draw.text((24, y), ln, fill=(30, 30, 30), font=body)
            y += 38
        for s in self.shots:
            if s.status == "fail" and y < h - 40:
                line = f"  ❌ {s.label}" + (f"  · {s.note}" if s.note else "")
                draw.text((24, y), line[:80], fill=(180, 30, 30), font=body)
                y += 36
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
        pages = [self._render_summary()]
        pages += [self._render_page(s, i + 1, total) for i, s in enumerate(self.shots)]
        pages[0].save(out_path, save_all=True, append_images=pages[1:],
                      resolution=100.0)
        return out_path
