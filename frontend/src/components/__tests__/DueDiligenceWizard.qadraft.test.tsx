import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DueDiligenceWizard from "../DueDiligenceWizard";

/**
 * gk 模式 F4 前端：历史问答复用草稿面板。
 * 恢复会话进 Step3 后，点某需求「💬 草稿」→ GET /qa/draft →
 * 命中显示历史答案 + 置信度徽章，可编辑。
 */
const SESSION = {
  session_id: "sess-1", checklist_name: "尽调清单", institution_name: "红杉资本",
  status: "done", created_at: 0, item_count: 1, confirmed_count: 0,
};
const ITEM = {
  id: "item-1", item_no: "1", category: "团队", requirement: "请说明团队规模",
  matched_file_path: null, matched_filename: null,
  confidence: 0.0, match_reason: "", user_confirmed: 0, user_skipped: 0,
  candidates_json: null, extra_files_json: null, is_encrypted: 0, unlock_password: "",
};

describe("DueDiligenceWizard 问答草稿", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        const u = String(url);
        if (u.includes("/qa/draft")) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
              matched: true, answer: "核心团队50人", confidence: 0.8,
              source_question: "公司团队规模有多大？",
            }),
          });
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

  it("点草稿命中历史问答，显示答案+置信度且可编辑", async () => {
    const user = userEvent.setup();
    render(<DueDiligenceWizard open onClose={() => {}} />);
    await user.click(await screen.findByRole("button", { name: "恢复" }));

    await user.click(await screen.findByRole("button", { name: "💬 草稿" }));

    // 命中徽章 + 历史答案落入可编辑文本框
    expect(await screen.findByText(/命中历史 · 置信 80%/)).toBeTruthy();
    const ta = screen.getByLabelText("草稿-1") as HTMLTextAreaElement;
    expect(ta.value).toBe("核心团队50人");

    // 可编辑
    await user.type(ta, "（已补充）");
    expect((screen.getByLabelText("草稿-1") as HTMLTextAreaElement).value).toContain("已补充");
  });
});
