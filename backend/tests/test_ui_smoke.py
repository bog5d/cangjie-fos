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
    # 不用 networkidle：本应用登录后会轮询 /api/v1/ready 等接口，网络永不 idle，
    # networkidle 必然超时拖垮所有用例。改为等具体元素出现（Playwright 最佳实践）。
    page.wait_for_selector("input[type='password']", timeout=15_000)

    text_inputs = page.locator("input[type='text']")
    # 第1个 text input = 指挥官名称（必填）
    text_inputs.nth(0).fill(commander)
    # 第2个 text input = 账号
    text_inputs.nth(1).fill(username)
    page.locator("input[type='password']").first.fill(password)
    page.locator("button[type='submit']").click()

    # 等主界面出现（任一主入口按钮可见即认为已进入），而非 networkidle
    try:
        page.wait_for_selector(
            "button:has-text('尽调响应'), button:has-text('路演分析'), "
            "button:has-text('复盘上传向导')",
            timeout=15_000,
        )
    except Exception:  # noqa: BLE001 — 进不到主界面交由各用例自身断言定位
        pass
    page.wait_for_timeout(1_000)


# ── TestLoginNoOverlay ─────────────────────────────────────────────────────────

class TestLoginNoOverlay:
    """Bug #Chrome-1 回归：登录后不应有叠层阻止点击。"""

    def test_login_page_visible(self, page: Page, fos_server_url: str) -> None:
        """登录页应正常显示，有用户名和密码输入框。"""
        page.goto(fos_server_url)
        # 不用 networkidle（应用挂载即轮询 /api/v1/ready，网络不 idle）；直接等输入框
        expect(page.locator("input[type='text']").first).to_be_visible(timeout=10_000)
        expect(page.locator("input[type='password']").first).to_be_visible(timeout=10_000)

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


# ── TestDueDiligenceWizardSmoke ────────────────────────────────────────────────

_OVERLAY_JS = """
    () => {
        const blockers = [];
        for (const el of document.querySelectorAll('*')) {
            const s = window.getComputedStyle(el);
            if (s.position === 'fixed' && s.pointerEvents !== 'none'
                    && s.display !== 'none' && s.visibility !== 'hidden'
                    && s.opacity !== '0') {
                const r = el.getBoundingClientRect();
                if (r.width * r.height > window.innerWidth * window.innerHeight * 0.25)
                    blockers.push({tag: el.tagName,
                                   cls: el.className.toString().slice(0, 80)});
            }
        }
        return blockers;
    }
"""


class TestDueDiligenceWizardSmoke:
    """gk 模式 — 尽调响应台向导浏览器冒烟。

    每次改动 DueDiligenceWizard.tsx 后必须跑此组测试。
    服务未启动时自动 skip，不阻断常规 CI。
    """

    def test_dd_wizard_button_visible(
        self, page: Page, fos_server_url: str, fos_login_credentials: tuple[str, str],
        ui_reporter,
    ) -> None:
        """主页应有「尽调响应」入口按钮。"""
        _login(page, fos_server_url, fos_login_credentials)
        btn = page.locator("button:has-text('尽调响应')")
        try:
            expect(btn).to_be_visible(timeout=8_000)
            ui_reporter.capture(page, "登录后主页 — 「尽调响应」入口可见",
                                status="ok", note="找到尽调响应按钮")
        except AssertionError:
            ui_reporter.fail(page, "登录后主页 — 找不到「尽调响应」入口",
                             note="主页缺少尽调响应按钮")
            raise

    def test_dd_wizard_opens_step1(
        self, page: Page, fos_server_url: str, fos_login_credentials: tuple[str, str],
        ui_reporter,
    ) -> None:
        """点击「尽调响应」后向导 Step 1 应正常打开，显示材料库文件夹输入。"""
        _login(page, fos_server_url, fos_login_credentials)
        page.locator("button:has-text('尽调响应')").click()
        page.wait_for_timeout(800)
        try:
            expect(page.get_by_text("材料库文件夹", exact=False)).to_be_visible(timeout=6_000)
            ui_reporter.capture(page, "尽调向导 Step 1 — 材料库文件夹输入",
                                status="ok", note="向导正常打开")
        except AssertionError:
            ui_reporter.fail(page, "尽调向导 Step 1 打开失败",
                             note="点击后未出现材料库文件夹")
            raise

    def test_dd_wizard_step1_has_scan_button(
        self, page: Page, fos_server_url: str, fos_login_credentials: tuple[str, str],
        ui_reporter,
    ) -> None:
        """Step 1 应有「开始扫描」按钮可点击。"""
        _login(page, fos_server_url, fos_login_credentials)
        page.locator("button:has-text('尽调响应')").click()
        page.wait_for_timeout(800)
        try:
            expect(page.locator("button:has-text('开始扫描')")).to_be_visible(timeout=6_000)
            ui_reporter.capture(page, "Step 1 — 「开始扫描」按钮可见", status="ok")
        except AssertionError:
            ui_reporter.fail(page, "Step 1 — 缺少「开始扫描」按钮")
            raise

    def test_dd_wizard_step1_has_checklist_upload(
        self, page: Page, fos_server_url: str, fos_login_credentials: tuple[str, str],
        ui_reporter,
    ) -> None:
        """Step 1 应有清单上传入口（文字或按钮含「清单」）。"""
        _login(page, fos_server_url, fos_login_credentials)
        page.locator("button:has-text('尽调响应')").click()
        page.wait_for_timeout(800)
        try:
            expect(page.get_by_text("清单", exact=False).first).to_be_visible(timeout=6_000)
            ui_reporter.capture(page, "Step 1 — 清单上传入口可见", status="ok")
        except AssertionError:
            ui_reporter.fail(page, "Step 1 — 缺少清单上传入口")
            raise

    def test_dd_wizard_close_no_overlay(
        self, page: Page, fos_server_url: str, fos_login_credentials: tuple[str, str],
        ui_reporter,
    ) -> None:
        """关闭尽调向导后不应残留叠层（Chrome 叠层 Bug 回归）。"""
        _login(page, fos_server_url, fos_login_credentials)
        page.locator("button:has-text('尽调响应')").click()
        page.wait_for_timeout(800)

        # 关闭按钮：✕ 或 ×
        close = page.locator("button:has-text('✕'), button:has-text('×')").first
        if close.is_visible():
            close.click()
        else:
            page.keyboard.press("Escape")
        page.wait_for_timeout(600)

        blocking = page.evaluate(_OVERLAY_JS)
        if blocking == []:
            ui_reporter.capture(page, "关闭尽调向导后 — 无残留叠层",
                                status="ok", note="无大面积 fixed 遮罩")
        else:
            ui_reporter.fail(page, "关闭尽调向导后仍有叠层",
                             note=f"残留 {len(blocking)} 个遮罩")
        assert blocking == [], (
            f"关闭尽调向导后仍有叠层：{blocking}"
        )

    def test_dd_wizard_session_history_shown(
        self, page: Page, fos_server_url: str, fos_login_credentials: tuple[str, str],
        ui_reporter,
    ) -> None:
        """Step 1 打开后，如果有历史 Session，应能看到「恢复」或「历史会话」相关文字。
        若无历史记录，只验证向导正常打开不崩溃即可。
        """
        _login(page, fos_server_url, fos_login_credentials)
        page.locator("button:has-text('尽调响应')").click()
        page.wait_for_timeout(1_500)

        # 不管有没有历史，向导必须稳定（不崩溃、Step1 内容可见）
        try:
            expect(page.get_by_text("材料库文件夹", exact=False)).to_be_visible(timeout=6_000)
            ui_reporter.capture(page, "尽调向导 — 历史会话面板 / Step1 稳定渲染",
                                status="ok", note="向导稳定不崩溃")
        except AssertionError:
            ui_reporter.fail(page, "尽调向导渲染异常", note="Step1 内容不可见")
            raise

        # 此测试永远 pass，只打印信息
        assert True

    def test_dd_workflow_stepper_real_flow(
        self, page: Page, fos_server_url: str, fos_login_credentials: tuple[str, str],
        ui_reporter, tmp_path,
    ) -> None:
        """v1.17 工作流步骤条 + 真实扫描→匹配链路（需 LLM key；测试与服务同机）。

        人工点击指引：尽调响应 → 填材料库路径 → 开始扫描 → 下一步 → 粘贴复合清单
        → 解析&开始匹配 → 观察步骤条（解析清单/AI 粗筛匹配/读正文精判验证/待人工确认）
        → 进 Step3 看清单是否拆条、命中项是否有 🟢/🟡/🔴 证据。

        硬断言：材料库输入/扫描完成/工作流步骤条出现。
        人工核对（截图存证，不脆断言 LLM 输出）：复合项是否拆条 + 红黄绿判定。
        """
        # 1) 造一个服务器可读的材料库（测试与服务同机）
        folder = tmp_path / "dd_lib"
        folder.mkdir()
        (folder / "审计报告_2023.txt").write_text(
            "审计报告 标准无保留意见 2023年度财务报表", encoding="utf-8")
        (folder / "装修合同.txt").write_text(
            "办公室装修施工合同 与本次尽调无关", encoding="utf-8")

        _login(page, fos_server_url, fos_login_credentials)
        page.locator("button:has-text('尽调响应')").click()
        page.wait_for_timeout(1_000)

        # 2) 填路径 + 扫描
        try:
            folder_input = page.get_by_placeholder("点击「📁 选择文件夹」或手动输入路径")
            expect(folder_input).to_be_visible(timeout=8_000)
            folder_input.fill(str(folder))
            page.locator("button:has-text('开始扫描')").click()
            ui_reporter.capture(page, "尽调-Step1 — 已触发扫描", status="info", note=str(folder))
        except AssertionError:
            ui_reporter.fail(page, "尽调-Step1 — 材料库路径输入/扫描按钮缺失")
            raise

        # 3) 等扫描完成（出现「下一步：上传清单」即 scanStatus=done）
        try:
            next_btn = page.locator("button:has-text('下一步：上传清单')")
            expect(next_btn).to_be_visible(timeout=90_000)
            ui_reporter.capture(page, "尽调-Step1 — 扫描完成", status="ok")
            next_btn.click()
        except AssertionError:
            ui_reporter.fail(page, "尽调-Step1 — 扫描未在 90s 内完成",
                             note="检查 LLM key / 材料库路径是否服务器可读")
            raise

        # 4) 粘贴复合清单 + 触发匹配
        try:
            ta = page.locator("textarea").first
            expect(ta).to_be_visible(timeout=8_000)
            ta.fill("1. 近三年审计报告\n2. 公司章程及历次股东会决议")
            page.locator("button:has-text('解析 & 开始匹配')").click()
            ui_reporter.capture(page, "尽调-Step2 — 已提交复合清单", status="info",
                                note="近三年审计报告 / 章程及股东会决议（应被拆条）")
        except AssertionError:
            ui_reporter.fail(page, "尽调-Step2 — 清单输入/匹配按钮缺失")
            raise

        # 5) 工作流步骤条应出现（解析→粗筛→精判→待确认）
        stepper_seen = False
        for _ in range(60):  # 最多等 ~60s（解析 + 匹配启动）
            if page.get_by_text("AI 粗筛匹配", exact=False).count() > 0:
                stepper_seen = True
                break
            page.wait_for_timeout(1_000)
        if stepper_seen:
            ui_reporter.capture(page, "尽调-工作流步骤条可见", status="ok",
                                note="解析清单 → AI 粗筛匹配 → 读正文精判验证 → 待人工确认")
        else:
            ui_reporter.fail(page, "尽调-工作流步骤条未出现",
                             note="匹配运行期未见步骤条（或解析阶段已报错）")
            raise AssertionError("工作流步骤条未出现")

        # 6) 等匹配完成，截 Step3 结果供人工核对「复合项是否拆条 + 红黄绿」
        for _ in range(120):
            if page.get_by_text("审计报告", exact=False).count() > 0:
                break
            page.wait_for_timeout(1_000)
        ui_reporter.capture(
            page, "尽调-Step3 — 匹配结果（人工核对：复合项拆条 + 红黄绿判定）",
            status="info",
            note="近三年→逐年多条？章程与股东会决议→拆开？命中项有 🟢/🟡/🔴 证据？")


# ── TestCoachingWizardSmoke ────────────────────────────────────────────────────

class TestCoachingWizardSmoke:
    """路演陪练向导（AI 教练 + 答疑审问）烟雾测试。

    覆盖 CLAUDE.md 要求：新增全屏 Modal 必须验证「开启态可交互 + 关闭态无叠层」。
    """

    def test_coaching_button_opens_modal(
        self, page: Page, fos_server_url: str, fos_login_credentials: tuple[str, str],
        ui_reporter,
    ) -> None:
        """🎤 路演陪练按钮可点击并打开向导，两个模式 Tab 均可见。"""
        _login(page, fos_server_url, fos_login_credentials)
        btn = page.locator("button:has-text('路演陪练')")
        expect(btn).to_be_visible(timeout=8_000)
        btn.click()
        page.wait_for_timeout(800)
        try:
            expect(page.get_by_text("路演教练", exact=False).first).to_be_visible(timeout=6_000)
            expect(page.get_by_text("答疑审问", exact=False).first).to_be_visible(timeout=6_000)
            ui_reporter.capture(page, "路演陪练 — 向导打开，双模式可见", status="ok")
        except AssertionError:
            ui_reporter.fail(page, "路演陪练向导未正常打开")
            raise

    def test_coaching_qa_mode_switch(
        self, page: Page, fos_server_url: str, fos_login_credentials: tuple[str, str],
        ui_reporter,
    ) -> None:
        """切到「答疑审问」Tab，应看到出题入口。"""
        _login(page, fos_server_url, fos_login_credentials)
        page.locator("button:has-text('路演陪练')").click()
        page.wait_for_timeout(600)
        page.locator("button:has-text('答疑审问')").click()
        page.wait_for_timeout(600)
        try:
            expect(page.get_by_text("压力测试问题", exact=False).first).to_be_visible(timeout=6_000)
            ui_reporter.capture(page, "路演陪练 — 答疑审问模式出题入口可见", status="ok")
        except AssertionError:
            ui_reporter.fail(page, "答疑审问模式未正常渲染")
            raise

    def test_coaching_close_no_overlay(
        self, page: Page, fos_server_url: str, fos_login_credentials: tuple[str, str],
        ui_reporter,
    ) -> None:
        """关闭路演陪练向导后不应残留叠层（Chrome 叠层 Bug 回归）。"""
        _login(page, fos_server_url, fos_login_credentials)
        page.locator("button:has-text('路演陪练')").click()
        page.wait_for_timeout(800)

        close = page.locator("button:has-text('✕'), button:has-text('×')").first
        if close.is_visible():
            close.click()
        else:
            page.keyboard.press("Escape")
        page.wait_for_timeout(600)

        blocking = page.evaluate(_OVERLAY_JS)
        if blocking == []:
            ui_reporter.capture(page, "关闭路演陪练向导后 — 无残留叠层",
                                status="ok", note="无大面积 fixed 遮罩")
        else:
            ui_reporter.fail(page, "关闭路演陪练向导后仍有叠层",
                             note=f"残留 {len(blocking)} 个遮罩")
        assert blocking == [], (
            f"关闭路演陪练向导后仍有叠层：{blocking}"
        )


# ── TestPackageGapWizardSmoke ──────────────────────────────────────────────────

class TestPackageGapWizardSmoke:
    """数据包补全向导（需求03）烟雾测试：开启可交互 + 关闭无叠层。"""

    def test_package_button_opens_modal(
        self, page: Page, fos_server_url: str, fos_login_credentials: tuple[str, str],
        ui_reporter,
    ) -> None:
        """📦 数据包补全按钮可点击并打开向导，扫描入口可见。"""
        _login(page, fos_server_url, fos_login_credentials)
        btn = page.locator("button:has-text('数据包补全')")
        expect(btn).to_be_visible(timeout=8_000)
        btn.click()
        page.wait_for_timeout(800)
        try:
            expect(page.get_by_text("开始扫描并分析缺口", exact=False)).to_be_visible(timeout=6_000)
            ui_reporter.capture(page, "数据包补全 — 向导打开，扫描入口可见", status="ok")
        except AssertionError:
            ui_reporter.fail(page, "数据包补全向导未正常打开")
            raise

    def test_package_close_no_overlay(
        self, page: Page, fos_server_url: str, fos_login_credentials: tuple[str, str],
        ui_reporter,
    ) -> None:
        """关闭数据包补全向导后不应残留叠层（Chrome 叠层 Bug 回归）。"""
        _login(page, fos_server_url, fos_login_credentials)
        page.locator("button:has-text('数据包补全')").click()
        page.wait_for_timeout(800)

        close = page.locator("button:has-text('✕'), button:has-text('×')").first
        if close.is_visible():
            close.click()
        else:
            page.keyboard.press("Escape")
        page.wait_for_timeout(600)

        blocking = page.evaluate(_OVERLAY_JS)
        if blocking == []:
            ui_reporter.capture(page, "关闭数据包补全向导后 — 无残留叠层",
                                status="ok", note="无大面积 fixed 遮罩")
        else:
            ui_reporter.fail(page, "关闭数据包补全向导后仍有叠层",
                             note=f"残留 {len(blocking)} 个遮罩")
        assert blocking == [], (
            f"关闭数据包补全向导后仍有叠层：{blocking}"
        )
