import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DueDiligenceWizard from "../DueDiligenceWizard";

/**
 * gk 模式 F2 前端：一条需求多份材料。
 * 候选展开行勾选「附加」→ 保存 → PATCH extra_files_json 含勾选文件。
 */
const SESSION = {
  session_id: "sess-1", checklist_name: "尽调清单", institution_name: "红杉资本",
  status: "done", created_at: 0, item_count: 1, confirmed_count: 0,
};
const CANDIDATES = [
  { file_path: "/docs/2024财报.pdf", filename: "2024财报.pdf", confidence: 0.9, reason: "主" },
  { file_path: "/docs/2023财报.pdf", filename: "2023财报.pdf", confidence: 0.7, reason: "次" },
  { file_path: "/docs/2022财报.pdf", filename: "2022财报.pdf", confidence: 0.6, reason: "次" },
];
const ITEM = {
  id: "item-1", item_no: "1", category: "财务", requirement: "近三年财报",
  matched_file_path: "/docs/2024财报.pdf", matched_filename: "2024财报.pdf",
  confidence: 0.9, match_reason: "主", user_confirmed: 0, user_skipped: 0,
  candidates_json: JSON.stringify(CANDIDATES), extra_files_json: null,
  is_encrypted: 0, unlock_password: "",
};

describe("DueDiligenceWizard 多文件附加", () => {
  let patchBody: any = null;
  beforeEach(() => {
    patchBody = null;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, opts?: RequestInit) => {
        const u = String(url);
        if (u.match(/\/items\/item-1$/) && opts?.method === "PATCH") {
          patchBody = JSON.parse(String(opts?.body));
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
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

  it("勾选附加两份候选 → PATCH extra_files_json", async () => {
    const user = userEvent.setup();
    render(<DueDiligenceWizard open onClose={() => {}} />);
    await user.click(await screen.findByRole("button", { name: "恢复" }));

    // 展开候选
    await user.click(await screen.findByRole("button", { name: /3个候选/ }));

    // 勾选两份次要候选
    await user.click(await screen.findByLabelText("附加-2023财报.pdf"));
    await user.click(screen.getByLabelText("附加-2022财报.pdf"));

    // 保存
    await user.click(screen.getByRole("button", { name: /附加 2 份材料到本需求/ }));

    const extras = JSON.parse(patchBody.extra_files_json);
    const names = extras.map((e: any) => e.filename).sort();
    expect(names).toEqual(["2022财报.pdf", "2023财报.pdf"]);
  });
});
