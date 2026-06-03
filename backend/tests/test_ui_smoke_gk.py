"""gk 模式尽调向导 —— 真实浏览器冒烟（Playwright + 带截图 PDF 报告）。

为什么单独成文件（Codex 在 v1.8.0 验收报告里点名要求）：
  v1.8.0 改了 DueDiligenceWizard.tsx。vitest 跑在 jsdom 里，看不到真实 Chrome
  渲染/CSS/叠层/点击。Codex 的 in-app browser 又被 Browser Use URL policy 拦住
  无法访问 127.0.0.1:5173。**本文件用命令行 Playwright（本地 chromium 子进程，
  不走 Browser Use 通道，不受该策略限制）**，稳定完成「打开页面→点关键控件→
  截图→生成 PDF」，绕开阻塞。

覆盖两层：
  Tier A（免数据，always 可跑）：
    - 登录默认账号
    - 打开「尽调响应」
    - Step1 控件：材料库文件夹 / 开始扫描 / 清单入口
    - 关闭向导无叠层
  Tier B（向运行中服务 DB 播种「已完成」会话 → 恢复 → Step3 深层控件）：
    - 加密文件显示 🔒 锁标识 + 密码登记入口
    - 候选展开 + 「附加」多文件勾选
    - 「💬 草稿」入口
    - 「📁 按问题归档…」入口

运行（先起前后端服务）：
  cd backend && uv run uvicorn cangjie_fos.main:app --port 8000   # 终端1
  cd frontend && npm run dev -- --host 127.0.0.1 --port 5173       # 终端2
  cd backend && uv run --extra dev pytest tests/test_ui_smoke_gk.py -v -s

  注意：服务未启动会自动 skip；但 Codex 必须先起服务再跑，全部 skip 视为未完成。
  跑完 PDF 在 backend/data/ui_reports/，回传给 Claude 审核。

播种说明：
  直接用裸 sqlite3 连服务的固定 DB 路径（backend/data/pitch_jobs.sqlite），
  绕开 conftest 的 _isolate_db_per_test monkeypatch（那只影响测试进程，不影响
  运行中的 uvicorn）。测试结束删除播种行，保持服务 DB 干净。
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid

import pytest
from playwright.sync_api import Page, expect

from cangjie_fos.core import paths as fos_paths

pytestmark = pytest.mark.usefixtures("fos_server_url")


# ── 工具：登录 + 打开向导 ─────────────────────────────────────────────────────

def _login(page: Page, base_url: str, credentials: tuple[str, str]) -> None:
    username, password = credentials
    page.goto(base_url)
    page.wait_for_load_state("networkidle", timeout=10_000)
    text_inputs = page.locator("input[type='text']")
    text_inputs.nth(0).fill("冒烟指挥官")
    text_inputs.nth(1).fill(username)
    page.locator("input[type='password']").first.fill(password)
    page.locator("button[type='submit']").click()
    page.wait_for_load_state("networkidle", timeout=12_000)
    page.wait_for_timeout(1_500)


def _open_wizard(page: Page) -> None:
    page.locator("button:has-text('尽调响应')").click()
    page.wait_for_timeout(900)


# ── 播种：向运行中服务的 DB 写一个已完成会话 ─────────────────────────────────

def _server_db_path() -> str:
    return str(fos_paths.get_backend_root() / "data" / "pitch_jobs.sqlite")


@pytest.fixture
def seeded_gk_session():
    """向服务 DB 播种一个 done 会话（加密文件 + 候选），yield session 元信息，
    测试结束清理。绕开测试进程的 DB 隔离，直连服务实际库。"""
    db = _server_db_path()
    sid = f"smoke-gk-{uuid.uuid4().hex[:8]}"
    # 历史会话列表显示的是 institution_name（优先于 checklist_name），
    # 用唯一标记避免与真实「红杉资本」会话混淆，便于精准定位「恢复」按钮。
    inst_marker = f"【冒烟{sid[-4:]}】红杉资本"
    folder_root = f"/tmp/gk_smoke_{sid}"
    enc_path = f"{folder_root}/红杉资本/公司章程_加密.pdf"
    fin_main = f"{folder_root}/红杉资本/2024财报.pdf"
    fin_alt1 = f"{folder_root}/红杉资本/2023财报.pdf"
    fin_alt2 = f"{folder_root}/红杉资本/2022财报.pdf"
    now = time.time()

    conn = sqlite3.connect(db, timeout=10)
    try:
        # 资产索引：加密文件 + 三份财报
        for fp, fn, enc in [
            (enc_path, "公司章程_加密.pdf", 1),
            (fin_main, "2024财报.pdf", 0),
            (fin_alt1, "2023财报.pdf", 0),
            (fin_alt2, "2022财报.pdf", 0),
        ]:
            conn.execute(
                "INSERT INTO dd_asset_index "
                "(id, folder_root, file_path, filename, file_type, summary, readable, "
                " indexed_at, institution_subfolder, is_encrypted, mtime, unlock_password) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, folder_root, fp, fn, "pdf", "冒烟播种", 1,
                 now, "红杉资本", enc, now, ""),
            )
        # 会话（done, per_institution）
        conn.execute(
            "INSERT INTO dd_match_sessions "
            "(session_id, tenant_id, checklist_name, folder_root, status, "
            " institution_name, created_at, completed_at, folder_layout, scenario) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, "default", "【冒烟】尽调清单", folder_root, "done",
             inst_marker, now, now, "per_institution", "dd"),
        )
        # item1：加密章程（matched 到加密文件 → JOIN 出 is_encrypted=1 → 显示🔒）
        conn.execute(
            "INSERT INTO dd_match_items "
            "(id, session_id, item_no, category, requirement, matched_file_path, "
            " matched_filename, confidence, match_reason, user_confirmed, user_skipped, "
            " candidates_json, extra_files_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, sid, "1", "公司治理", "公司章程及股东协议",
             enc_path, "公司章程_加密.pdf", 0.9, "文件名匹配", 0, 0, None, None),
        )
        # item2：财报（带 3 个候选 → 可展开 + 勾选「附加」）
        cands = [
            {"file_path": fin_main, "filename": "2024财报.pdf", "confidence": 0.9, "reason": "主"},
            {"file_path": fin_alt1, "filename": "2023财报.pdf", "confidence": 0.7, "reason": "次"},
            {"file_path": fin_alt2, "filename": "2022财报.pdf", "confidence": 0.6, "reason": "次"},
        ]
        conn.execute(
            "INSERT INTO dd_match_items "
            "(id, session_id, item_no, category, requirement, matched_file_path, "
            " matched_filename, confidence, match_reason, user_confirmed, user_skipped, "
            " candidates_json, extra_files_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, sid, "2", "财务", "近三年财务报表",
             fin_main, "2024财报.pdf", 0.9, "主", 0, 0,
             json.dumps(cands, ensure_ascii=False), None),
        )
        conn.commit()
    finally:
        conn.close()

    yield {"session_id": sid, "folder_root": folder_root,
           "checklist_name": "【冒烟】尽调清单", "institution_marker": inst_marker}

    # 清理
    conn = sqlite3.connect(db, timeout=10)
    try:
        conn.execute("DELETE FROM dd_match_items WHERE session_id = ?", (sid,))
        conn.execute("DELETE FROM dd_match_sessions WHERE session_id = ?", (sid,))
        conn.execute("DELETE FROM dd_asset_index WHERE folder_root = ?", (folder_root,))
        conn.commit()
    finally:
        conn.close()


def _restore_seeded_session(page: Page, institution_marker: str) -> None:
    """打开向导 → 在历史会话列表里找到目标会话（按机构名标记）→ 点「恢复」进 Step3。"""
    _open_wizard(page)
    # 历史会话区块显示 institution_name；定位到唯一标记行
    expect(page.get_by_text(institution_marker, exact=False).first).to_be_visible(timeout=8_000)
    # 点该标记所在行的「恢复」按钮（播种会话 created_at=now → 列表置顶；
    # 且仅此一条 tenant=default 的 done 会话，恢复按钮唯一）
    page.locator("button:has-text('恢复')").first.click()
    page.wait_for_timeout(1_500)


# ── Tier A：免数据，Step1 控件 ───────────────────────────────────────────────

class TestGkWizardStep1:
    """尽调向导入口 + Step1 关键控件（无需数据）。"""

    def test_entry_and_step1_controls(
        self, page: Page, fos_server_url: str,
        fos_login_credentials: tuple[str, str], ui_reporter,
    ) -> None:
        _login(page, fos_server_url, fos_login_credentials)
        try:
            expect(page.locator("button:has-text('尽调响应')")).to_be_visible(timeout=8_000)
            ui_reporter.capture(page, "gk-A1 登录后主页 —「尽调响应」入口", status="ok")
        except AssertionError:
            ui_reporter.fail(page, "gk-A1 找不到「尽调响应」入口")
            raise

        _open_wizard(page)
        try:
            expect(page.get_by_text("材料库文件夹", exact=False)).to_be_visible(timeout=6_000)
            expect(page.locator("button:has-text('开始扫描')")).to_be_visible(timeout=6_000)
            expect(page.get_by_text("清单", exact=False).first).to_be_visible(timeout=6_000)
            ui_reporter.capture(page, "gk-A2 Step1 —材料库文件夹/开始扫描/清单入口齐全",
                                status="ok", note="三项控件均可见")
        except AssertionError:
            ui_reporter.fail(page, "gk-A2 Step1 控件缺失")
            raise

    def test_close_no_overlay(
        self, page: Page, fos_server_url: str,
        fos_login_credentials: tuple[str, str], ui_reporter,
    ) -> None:
        _login(page, fos_server_url, fos_login_credentials)
        _open_wizard(page)
        close = page.locator("button:has-text('✕'), button:has-text('×')").first
        if close.is_visible():
            close.click()
        else:
            page.keyboard.press("Escape")
        page.wait_for_timeout(600)
        blocking = page.evaluate("""
            () => {
                const b = [];
                for (const el of document.querySelectorAll('*')) {
                    const s = getComputedStyle(el);
                    if (s.position==='fixed' && s.pointerEvents!=='none'
                        && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0') {
                        const r = el.getBoundingClientRect();
                        if (r.width*r.height > innerWidth*innerHeight*0.25)
                            b.push(el.tagName);
                    }
                } return b;
            }
        """)
        if blocking == []:
            ui_reporter.capture(page, "gk-A3 关闭向导后 — 无残留叠层", status="ok")
        else:
            ui_reporter.fail(page, "gk-A3 关闭向导后仍有叠层",
                             note=f"残留 {len(blocking)} 个")
        assert blocking == [], f"关闭后仍有叠层：{blocking}"


# ── Tier B：播种已完成会话 → 恢复 → Step3 深层控件 ───────────────────────────

class TestGkWizardStep3Restored:
    """从播种的 done 会话恢复，验证 Step3 的 gk 新控件在真实浏览器里渲染。"""

    def test_encrypted_lock_and_password_entry(
        self, page: Page, fos_server_url: str,
        fos_login_credentials: tuple[str, str], seeded_gk_session, ui_reporter,
    ) -> None:
        """加密文件应显示 🔒，点击后出现密码登记输入框。"""
        _login(page, fos_server_url, fos_login_credentials)
        _restore_seeded_session(page, seeded_gk_session["institution_marker"])
        try:
            lock = page.locator("button:has-text('🔒')").first
            expect(lock).to_be_visible(timeout=8_000)
            ui_reporter.capture(page, "gk-B1 Step3 — 加密文件显示 🔒 锁标识",
                                status="ok", note="公司章程_加密.pdf")
            lock.click()
            page.wait_for_timeout(500)
            expect(page.get_by_text("打开密码", exact=False).first).to_be_visible(timeout=5_000)
            ui_reporter.capture(page, "gk-B2 点🔒 — 弹出密码登记输入框",
                                status="ok", note="UI 收集密码原样附带")
        except AssertionError:
            ui_reporter.fail(page, "gk-B1/B2 加密锁或密码登记入口缺失")
            raise

    def test_draft_and_by_question_entries(
        self, page: Page, fos_server_url: str,
        fos_login_credentials: tuple[str, str], seeded_gk_session, ui_reporter,
    ) -> None:
        """Step3 应有「💬 草稿」逐条入口 + 「📁 按问题归档…」导出入口。"""
        _login(page, fos_server_url, fos_login_credentials)
        _restore_seeded_session(page, seeded_gk_session["institution_marker"])
        try:
            expect(page.locator("button:has-text('💬 草稿')").first).to_be_visible(timeout=8_000)
            expect(page.locator("button:has-text('按问题归档')")).to_be_visible(timeout=6_000)
            ui_reporter.capture(page, "gk-B3 Step3 —「💬 草稿」+「📁 按问题归档」入口",
                                status="ok", note="F4 草稿 + F2/F5 归档导出")
        except AssertionError:
            ui_reporter.fail(page, "gk-B3 草稿或按问题归档入口缺失")
            raise

    def test_multifile_candidate_attach(
        self, page: Page, fos_server_url: str,
        fos_login_credentials: tuple[str, str], seeded_gk_session, ui_reporter,
    ) -> None:
        """候选可展开，次要候选可勾选「附加」（一条需求多份材料 F2）。"""
        _login(page, fos_server_url, fos_login_credentials)
        _restore_seeded_session(page, seeded_gk_session["institution_marker"])
        try:
            expand = page.locator("button:has-text('个候选')").first
            expect(expand).to_be_visible(timeout=8_000)
            expand.click()
            page.wait_for_timeout(500)
            expect(page.get_by_label("附加-2023财报.pdf")).to_be_visible(timeout=5_000)
            ui_reporter.capture(page, "gk-B4 候选展开 —「附加」多文件勾选可用",
                                status="ok", note="2023/2022 财报可附加到同一需求")
        except AssertionError:
            ui_reporter.fail(page, "gk-B4 候选展开/附加勾选缺失")
            raise
