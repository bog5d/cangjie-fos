import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DueDiligenceWizard from "../DueDiligenceWizard";

/**
 * P1 回归（Codex v1.3.0 PARTIAL C）：
 * Step3 审核表里，未确认 / 未标缺的行必须同时渲染
 * 「✓」「缺」「📂 替换」三个文字按钮，且点「📂 替换」展开内联输入行。
 * 通过「恢复历史会话」路径喂入一条未确认 item，免去真实扫描/匹配的浏览器不稳定。
 */
const SESSION = {
  session_id: "sess-1",
  checklist_name: "尽调清单",
  institution_name: "红杉资本",
  status: "done",
  created_at: 0,
  item_count: 1,
  confirmed_count: 0,
};

const UNCONFIRMED_ITEM = {
  id: "item-1",
  item_no: "1",
  category: "财务",
  requirement: "近三年审计报告",
  matched_file_path: "/docs/audit.pdf",
  matched_filename: "audit.pdf",
  confidence: 0.9,
  match_reason: "文件名包含审计",
  user_confirmed: 0,
  user_skipped: 0,
  candidates_json: null,
  extra_files_json: null,
};

describe("DueDiligenceWizard Step3 未确认行按钮", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        const u = String(url);
        if (u.includes("/api/v1/dd/sessions/") && u.includes("/items")) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve([UNCONFIRMED_ITEM]) });
        }
        if (u.includes("/api/v1/dd/sessions")) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve([SESSION]) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("恢复会话后未确认行显示「缺」和「📂 替换」，点击替换展开输入行", async () => {
    const user = userEvent.setup();
    render(<DueDiligenceWizard open onClose={() => {}} />);

    // 历史会话出现 → 点「恢复」进入 Step3
    const restoreBtn = await screen.findByRole("button", { name: "恢复" });
    await user.click(restoreBtn);

    // 未确认行三按钮齐全
    expect(await screen.findByRole("button", { name: "缺" })).toBeTruthy();
    const replaceBtn = screen.getByRole("button", { name: "📂 替换" });
    expect(replaceBtn).toBeTruthy();
    expect(screen.getByRole("button", { name: "✓" })).toBeTruthy();

    // 点「📂 替换」→ 展开内联输入行
    await user.click(replaceBtn);
    expect(await screen.findByPlaceholderText(/选择文件.*手动输入路径/)).toBeTruthy();
  });
});
