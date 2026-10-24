"""pytest 全局夹具。

包含 Playwright 浏览器 E2E 测试所需的 live_server fixture。
普通的 API 集成测试不依赖这里（它们用自己的 TestClient）。

使用方式：
  # 普通测试套件（无需启动服务）
  uv run --extra dev pytest tests/ -q

  # 浏览器烟雾测试（需要先在另一个终端启动服务）
  uv run uvicorn cangjie_fos.main:app --port 8000
  uv run --extra dev pytest tests/test_ui_smoke.py -v
"""
from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def fos_server_url() -> str:
    """
    返回正在运行的 FOS 服务地址（默认 http://127.0.0.1:8000）。
    如果服务未运行，直接 skip（不影响普通测试套件）。

    浏览器测试运行前需手动启动服务：
      uv run uvicorn cangjie_fos.main:app --port 8000
    """
    host, port = "127.0.0.1", 8000
    try:
        with socket.create_connection((host, port), timeout=1):
            return f"http://{host}:{port}"
    except OSError:
        pytest.skip(
            f"FOS 服务未运行（{host}:{port}）。"
            "浏览器烟雾测试需要先启动服务：uv run uvicorn cangjie_fos.main:app --port 8000"
        )


@pytest.fixture(scope="session")
def fos_login_credentials() -> tuple[str, str]:
    """
    返回可用的登录凭据 (username, password)。

    优先级：
      1. 环境变量 FOS_ACCOUNTS（与运行中服务一致时）
      2. backend/.env 的 FOS_ACCOUNTS（格式：user:pass:tenant,...）
      3. auth 模块内置默认账号（_BUILTIN_ACCOUNTS，当前 gk001:123456）
    —— 后端默认就有内置账号（非 dev 放行模式），所以不能回退 dev/dev。
    """
    def _first(raw: str) -> tuple[str, str] | None:
        raw = raw.strip()
        if not raw:
            return None
        parts = raw.split(",")[0].strip().split(":")
        if len(parts) >= 2:
            return parts[0].strip(), parts[1].strip()
        return None

    # 1. 环境变量
    env_val = os.getenv("FOS_ACCOUNTS", "")
    if (cred := _first(env_val)):
        return cred
    # 2. .env 文件
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("FOS_ACCOUNTS="):
                if (cred := _first(line[len("FOS_ACCOUNTS="):])):
                    return cred
    # 3. 内置默认账号（从 auth 模块取，避免硬编码漂移）
    try:
        from cangjie_fos.api.routes.auth import _BUILTIN_ACCOUNTS
        if (cred := _first(_BUILTIN_ACCOUNTS)):
            return cred
    except Exception:
        pass
    return "gk001", "123456"


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """浏览器启动参数兜底。

    正常环境下用 `playwright install chromium` 安装的默认浏览器即可，本 fixture
    透传原参数。若环境里 Playwright 默认浏览器版本不匹配/未安装，可设环境变量
    PW_CHROME_EXECUTABLE 指向已有 chromium 可执行文件，避免被下载策略阻塞。
    """
    exe = os.environ.get("PW_CHROME_EXECUTABLE")
    if exe and Path(exe).exists():
        return {**browser_type_launch_args, "executable_path": exe}
    return browser_type_launch_args


@pytest.fixture(scope="session")
def ui_reporter(request):
    """浏览器「模拟人工测试」截图报告器（session 级，跑完合成 PDF）。

    用法（在 Playwright 测试里）：
        def test_xxx(self, page, fos_server_url, fos_login_credentials, ui_reporter):
            _login(page, fos_server_url, fos_login_credentials)
            ui_reporter.capture(page, "登录后主页", status="ok")

    session 结束时自动把所有截图合成一份 PDF，路径打印到 stdout，
    并写入 backend/data/ui_reports/。任一步 status='fail' → 文件名带 FAILED_ 前缀。
    """
    try:
        from tests.ui_report import UIReporter
    except ModuleNotFoundError:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from ui_report import UIReporter

    reporter = UIReporter(report_name="ui_smoke")
    global _LIVE_UI_REPORTER
    _LIVE_UI_REPORTER = reporter

    def _finalize() -> None:
        global _LIVE_UI_REPORTER
        pdf_path = reporter.finalize()
        if pdf_path is not None:
            fails = sum(1 for s in reporter.shots if s.status == "fail")
            print(f"\n\n📄 模拟人工测试报告（带截图 PDF）已生成：\n   {pdf_path}\n"
                  f"   共 {len(reporter.shots)} 帧"
                  f"{f'，含 {fails} 个 FAIL ❌' if reporter.any_fail else '，全部 PASS ✅'}\n")
        _LIVE_UI_REPORTER = None

    request.addfinalizer(_finalize)
    return reporter


# 当前活跃的 UI 报告器（session 级，供 makereport 钩子在测试真实失败时标红）
_LIVE_UI_REPORTER = None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """让 PDF 总览与 pytest 真实结果对齐。

    根因修复：UIReporter 此前只统计测试主动调用的 fail()；但 Playwright TimeoutError、
    按钮被禁用、_login 阶段就崩等情况是 AssertionError 之外的异常，测试根本走不到 fail()，
    导致 pytest 失败而 PDF 仍显示「全部 PASS」。这里在任一用了 ui_reporter 的测试 setup/call
    阶段失败时，自动补一帧失败截图并标红。
    """
    outcome = yield
    report = outcome.get_result()
    if report.when not in ("setup", "call") or not report.failed:
        return
    if _LIVE_UI_REPORTER is None:
        return
    if "ui_reporter" not in getattr(item, "fixturenames", []):
        return
    png = None
    page = getattr(item, "funcargs", {}).get("page")
    if page is not None:
        try:
            png = page.screenshot(full_page=False)
        except Exception:  # noqa: BLE001
            png = None
    _LIVE_UI_REPORTER.mark_failed(
        label=item.name,
        note=f"pytest 判定失败（{report.when} 阶段）",
        png=png,
    )


@pytest.fixture(autouse=True)
def _isolate_db_per_test(request, tmp_path, monkeypatch):
    """每个测试获得独立的 SQLite 数据库实例（自动启用）。

    monkeypatch pitch_job_db._db_path 到临时目录，
    确保测试间完全隔离，杜绝并行测试时的全局状态泄漏。

    测试可通过 ``@pytest.mark.real_db`` 声明自己需要真实 DB：
    - 使用 module/class 级 fixture 预写数据的 E2E 测试
    - 已有自己的 isolated_db fixture 需要避免双重 monkeypatch

    对不使用 DB 的测试无副作用（只有首次 _connect() 时才创建文件）。
    """
    # ``@pytest.mark.real_db`` 标记的测试自行管理 DB，跳过隔离
    if request.node.get_closest_marker("real_db"):
        return

    import cangjie_fos.services.pitch_job_db as db_module  # noqa: PLC0415

    db_file = tmp_path / "test_fos.db"
    monkeypatch.setattr(db_module, "_db_path", lambda: str(db_file))

    # ── 阻止后台线程在测试期间访问 DB（防 "database is locked" flaky 失败）──────
    # main.py lifespan 检查 CANGJIE_DISABLE_STARTUP_SYNC=1 时跳过 github-pull 和
    # institution-sync 两个 daemon 线程的启动。这两个线程调用 _connect() 访问 DB，
    # 与测试主线程竞争同一 tmp SQLite 文件，导致 PRAGMA journal_mode=WAL 锁冲突。
    # 环境变量方案不影响直接测试这两个函数的测试文件（它们不走 lifespan）。
    monkeypatch.setenv("CANGJIE_DISABLE_STARTUP_SYNC", "1")


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """每个测试前清空限流器的请求记录，防止全套测试时误触发 429。"""
    import cangjie_fos.middleware.request_context as _mw  # noqa: PLC0415
    _mw._rate_hits.clear()
    yield
    _mw._rate_hits.clear()
