import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DueDiligenceWizard from "../DueDiligenceWizard";

/**
 * gk 模式 F2/F5 前端：按问题归档导出 + 命名确认表。
 * 点「按问题归档」→ 出命名确认表（默认「问题NN_需求」），改名后
 * 「确认并按问题导出」POST /export-by-question 带 folder_name_overrides。
 */
const SESSION = {
  session_id: "sess-1", checklist_name: "尽调清单", institution_name: "红杉资本",
  status: "done", created_at: 0, item_count: 1, confirmed_count: 0,
};
const ITEM = {
  id: "item-1", item_no: "1", category: "财务", requirement: "近三年财报",
  matched_file_path: "/docs/2024财报.xlsx", matched_filename: "2024财报.xlsx",
  confidence: 0.9, match_reason: "", user_confirmed: 1, user_skipped: 0,
  candidates_json: null, extra_files_json: null, is_encrypted: 0, unlock_password: "",
};

describe("DueDiligenceWizard 按问题归档", () => {
  let exportBody: any = null;
  beforeEach(() => {
    exportBody = null;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, opts?: RequestInit) => {
        const u = String(url);
        if (u.includes("/export-by-question")) {
          exportBody = JSON.parse(String(opts?.body));
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ exported: 1, missing: 0, output_path: "/out" }) });
        }
        if (u.includes("/api/v1/dd/sessions/") && u.includes("/items")) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve([ITEM]) });
        }
        if (u.includes("/api/v1/dd/sessions")) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve([SESSION]) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("命名确认表默认问题名，改名后按问题导出回传 overrides", async () => {
    const user = userEvent.setup();
    render(<DueDiligenceWizard open onClose={() => {}} />);
    await user.click(await screen.findByRole("button", { name: "恢复" }));

    // 填导出路径
    await user.type(screen.getByPlaceholderText(/选择.*手动输入导出路径/), "/out");
    // 点按问题归档 → 出命名确认表
    await user.click(screen.getByRole("button", { name: "📁 按问题归档…" }));

    const nameInput = await screen.findByLabelText("文件夹名-1") as HTMLInputElement;
    expect(nameInput.value).toContain("问题1_近三年财报");

    // 改名
    await user.clear(nameInput);
    await user.type(nameInput, "Q1_机构要的财报");
    await user.click(screen.getByRole("button", { name: "✅ 确认并按问题导出" }));

    expect(exportBody.output_dir).toBe("/out");
    expect(exportBody.folder_name_overrides["item-1"]).toBe("Q1_机构要的财报");
  });
});
