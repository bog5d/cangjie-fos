import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DueDiligenceWizard from "../DueDiligenceWizard";

/**
 * gk 模式 F3 前端：加密匹配文件显示 🔒，点击展开密码输入行，
 * 保存后 POST /api/v1/dd/index/password 并切换为 🔓。
 */
const SESSION = {
  session_id: "sess-1", checklist_name: "尽调清单", institution_name: "红杉资本",
  status: "done", created_at: 0, item_count: 1, confirmed_count: 0,
};
const ENCRYPTED_ITEM = {
  id: "item-1", item_no: "1", category: "财务", requirement: "近三年财报",
  matched_file_path: "/docs/加密财报.xlsx", matched_filename: "加密财报.xlsx",
  confidence: 0.9, match_reason: "", user_confirmed: 0, user_skipped: 0,
  candidates_json: null, extra_files_json: null,
  is_encrypted: 1, unlock_password: "",
};

describe("DueDiligenceWizard 加密文件密码", () => {
  let passwordPost: { file_path: string; password: string } | null;

  beforeEach(() => {
    passwordPost = null;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, opts?: RequestInit) => {
        const u = String(url);
        if (u.includes("/index/password")) {
          passwordPost = JSON.parse(String(opts?.body));
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
        }
        if (u.includes("/api/v1/dd/sessions/") && u.includes("/items")) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve([ENCRYPTED_ITEM]) });
        }
        if (u.includes("/api/v1/dd/sessions")) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve([SESSION]) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("加密文件显示🔒，登记密码后回传后端", async () => {
    const user = userEvent.setup();
    render(<DueDiligenceWizard open onClose={() => {}} />);

    await user.click(await screen.findByRole("button", { name: "恢复" }));

    // 🔒 标记出现
    const lock = await screen.findByRole("button", { name: "🔒" });
    expect(lock).toBeTruthy();

    // 点开密码输入行
    await user.click(lock);
    const pwdInput = await screen.findByPlaceholderText(/输入该加密文件的打开密码/);
    await user.type(pwdInput, "secret123");
    await user.click(screen.getByRole("button", { name: "保存密码" }));

    // 回传后端正确
    expect(passwordPost).toEqual({ file_path: "/docs/加密财报.xlsx", password: "secret123" });
    // 切换为 🔓
    expect(await screen.findByRole("button", { name: "🔓" })).toBeTruthy();
  });
});
