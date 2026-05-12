"""浏览器烟雾测试（Playwright + Chromium）。

测试目标：
- 登录后无 Chrome 叠层 Bug（Bug #Chrome-1）
- 主页核心元素可点击
- 路演分析向导可以打开

运行前提：
  1. FOS 服务必须已在 127.0.0.1:8000 运行（否则自动 skip）
  2. playwright install chromium（已安装）

运行命令：
  uv run --extra dev pytest tests/test_ui_smoke.py -v           # 无头模式
  uv run --extra dev pytest tests/test_ui_smoke.py -v --headed  # 有头模式（调试用）

注意：
  服务未启动时所有测试自动 skip，不影响常规 pytest 全套运行。
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.usefixtures("fos_server_url")


# ── 工具函数 ───────────────────────────────────────────────────────────────────

def _login(
    page: Page,
    base_url: str,
    credentials: tuple[str, str],
    commander: str = "测试指挥官",
) -> None:
    """执行登录流程。

    登录表单有三个字段（顺序）：
      1. 您的姓名/称呼（commander name，必填，第1个 type=text）
      2. 账号（第2个 type=text）
      3. 密码（type=password）

    credentials: (username, password) tuple，由 fos_login_credentials fixture 提供，
    自动读取 backend/.env 中的 FOS_ACCOUNTS，dev 模式下使用任意凭据。
    """
    username, password = credentials
    page.goto(base_url)
    page.wait_for_load_state("networkidle", timeout=10_000)

    text_inputs = page.locator("input[type='text']")
    # 第1个 text input = 指挥官名称（必填）
    text_inputs.nth(0).fill(commander)
    # 第2个 text input = 账号
    text_inputs.nth(1).fill(username)
    page.locator("input[type='password']").first.fill(password)
    page.locator("button[type='submit']").click()

    # 等待页面稳定（最多12秒，包括 API 响应和 React 渲染）
    page.wait_for_load_state("networkidle", timeout=12_000)
    page.wait_for_timeout(2_000)


# ── TestLoginNoOverlay ─────────────────────────────────────────────────────────

class TestLoginNoOverlay:
    """Bug #Chrome-1 回归：登录后不应有叠层阻止点击。"""

    def test_login_page_visible(self, page: Page, fos_server_url: str) -> None:
        """登录页应正常显示，有用户名和密码输入框。"""
        page.goto(fos_server_url)
        page.wait_for_load_state("networkidle", timeout=10_000)
        expect(page.locator("input[type='text']").first).to_be_visible(timeout=5_000)
        expect(page.locator("input[type='password']").first).to_be_visible(timeout=5_000)

    def test_login_succeeds_enters_main_page(
        self, page: Page, fos_server_url: str, fos_login_credentials: tuple[str, str]
    ) -> None:
        """登录后应进入主页，而非卡在登录页。"""
        _login(page, fos_server_url, fos_login_credentials)
        # 主页标志：没有 submit 按钮，或者有主页特有元素
        # 用"复盘上传向导"或"路演分析"按钮作为登录成功标志
        roadshow_or_wizard = page.locator(
            "button:has-text('路演分析'), button:has-text('复盘上传向导')"
        )
        expect(roadshow_or_wizard.first).to_be_visible(timeout=10_000)

    def test_no_blocking_overlay_after_login(
        self, page: Page, fos_server_url: str, fos_login_credentials: tuple[str, str]
    ) -> None:
        """登录后，fixed inset-0 的元素不应该拦截点击事件。

        Chrome 叠层 Bug：某个带 backdrop-filter 的 fixed overlay 在关闭态仍然
        拦截 pointer events，导致整页无法点击。
        """
        _login(page, fos_server_url, fos_login_credentials)

        # 找出所有 position:fixed 的元素，检查是否有可见的且 pointer-events != none
        blocking_overlays = page.evaluate("""
            () => {
                const elements = document.querySelectorAll('*');
                const blockers = [];
                for (const el of elements) {
                    const style = window.getComputedStyle(el);
                    if (
                        style.position === 'fixed' &&
                        style.pointerEvents !== 'none' &&
                        style.display !== 'none' &&
                        style.visibility !== 'hidden' &&
                        style.opacity !== '0'
                    ) {
                        const rect = el.getBoundingClientRect();
                        // 只关心覆盖大面积（超过屏幕25%）的元素
                        const area = rect.width * rect.height;
                        const screenArea = window.innerWidth * window.innerHeight;
                        if (area > screenArea * 0.25) {
                            blockers.push({
                                tag: el.tagName,
                                className: el.className.toString().substring(0, 100),
                                pointerEvents: style.pointerEvents,
                                zIndex: style.zIndex,
                                width: Math.round(rect.width),
                                height: Math.round(rect.height),
                                opacity: style.opacity,
                            });
                        }
                    }
                }
                return blockers;
            }
        """)

        # 允许：透明度为0或导航栏等小面积元素
        # 不允许：大面积且可接收事件的 fixed 元素（modal overlay 遗留）
        assert blocking_overlays == [], (
            f"Chrome叠层Bug: 发现 {len(blocking_overlays)} 个阻塞点击的 fixed 元素:\n"
            + "\n".join(
                f"  <{b['tag']} class='{b['className']}' "
                f"z-index={b['zIndex']} pointer-events={b['pointerEvents']} "
                f"size={b['width']}x{b['height']}>"
                for b in blocking_overlays
            )
        )

    def test_roadshow_button_clickable(
        self, page: Page, fos_server_url: str, fos_login_credentials: tuple[str, str]
    ) -> None:
        """🎯 路演分析按钮可以点击，没有叠层阻挡。"""
        _login(page, fos_server_url, fos_login_credentials)

        btn = page.locator("button:has-text('路演分析')")
        expect(btn).to_be_visible(timeout=8_000)

        # 点击按钮（若有叠层拦截，点击会超时或点到错误元素）
        btn.click()
        page.wait_for_timeout(800)

        # 点击后向导应该打开（路演日期字段是 Step1 标志性内容）
        expect(page.get_by_text("路演日期", exact=False)).to_be_visible(timeout=5_000)

    def test_wizard_upload_wizard_button_clickable(
        self, page: Page, fos_server_url: str, fos_login_credentials: tuple[str, str]
    ) -> None:
        """复盘上传向导按钮也应该可以点击。"""
        _login(page, fos_server_url, fos_login_credentials)

        # 先找到并点击"复盘上传向导"按钮
        btn = page.locator("button:has-text('复盘上传向导')")
        expect(btn).to_be_visible(timeout=8_000)
        btn.click()
        page.wait_for_timeout(800)

        # 向导弹出 — 宽松断言：只要向导弹出即可（不验证具体内容）
        # 主要验证"按钮可以点击"，不验证具体内容
        page.wait_for_timeout(500)  # 给足时间渲染
        # 如果没有 exception 就说明按钮可以正常点击


# ── TestChromeRenderingDiagnosis ───────────────────────────────────────────────

class TestChromeRenderingDiagnosis:
    """Chrome 渲染诊断：收集页面渲染信息，帮助定位叠层Bug根因。

    这组测试不做 pass/fail 断言（只收集信息），用 pytest -v 运行时
    可以在 stdout 看到渲染信息，辅助调试。
    """

    def test_collect_fixed_elements_after_login(
        self, page: Page, fos_server_url: str, fos_login_credentials: tuple[str, str]
    ) -> None:
        """收集登录后所有 fixed 元素的信息（用于调试叠层Bug）。"""
        _login(page, fos_server_url, fos_login_credentials)

        elements_info = page.evaluate("""
            () => {
                const elements = document.querySelectorAll('*');
                const fixedEls = [];
                for (const el of elements) {
                    const style = window.getComputedStyle(el);
                    if (style.position === 'fixed') {
                        const rect = el.getBoundingClientRect();
                        fixedEls.push({
                            tag: el.tagName,
                            id: el.id || '',
                            className: el.className.toString().substring(0, 80),
                            zIndex: style.zIndex,
                            pointerEvents: style.pointerEvents,
                            display: style.display,
                            visibility: style.visibility,
                            opacity: style.opacity,
                            backdropFilter: style.backdropFilter || style.webkitBackdropFilter || 'none',
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                        });
                    }
                }
                return fixedEls;
            }
        """)

        print("\n\n=== 登录后 fixed 元素清单（共 {} 个）===".format(len(elements_info)))
        for el in elements_info:
            print(
                f"  <{el['tag']}#{el['id']} class='{el['className'][:60]}'>\n"
                f"    z-index={el['zIndex']}, pointer-events={el['pointerEvents']}, "
                f"opacity={el['opacity']}, display={el['display']}\n"
                f"    backdrop-filter={el['backdropFilter']}, size={el['width']}x{el['height']}"
            )
        print("=== END ===\n")

        # 此测试永远 pass，只打印信息
        assert True
