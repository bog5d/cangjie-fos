import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DueDiligenceWizard from "../DueDiligenceWizard";

/**
 * gk 模式 F1 前端：扫描完成后展示「布局徽章」。
 * per_institution → 显示「按机构分类 · N 家机构」；flat → 显示「平铺材料库」。
 * 用假定时器驱动扫描轮询，断言徽章按 folder_layout / institution_count 渲染。
 */
function mockScan(layout: string, institutionCount: number) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, opts?: RequestInit) => {
      const u = String(url);
      if (u.includes("/api/v1/dd/index") && opts?.method === "POST") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ scan_id: "scan-1" }) });
      }
      if (u.includes("/api/v1/dd/index/status/")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            status: "done", indexed: 5, failed: 0, total: 5,
            folder_layout: layout, institution_count: institutionCount,
          }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    }),
  );
}

async function runScan(path: string) {
  fireEvent.change(screen.getByPlaceholderText(/选择文件夹.*手动输入路径/), {
    target: { value: path },
  });
  // POST /index 是 async，先 flush 微任务再驱动轮询
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "开始扫描" }));
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1600);
  });
}

describe("DueDiligenceWizard 布局徽章", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("per_institution 扫描完成显示机构数徽章", async () => {
    mockScan("per_institution", 3);
    render(<DueDiligenceWizard open onClose={() => {}} />);
    await runScan("/材料库");
    expect(screen.getByText(/按机构分类 · 3 家机构/)).toBeTruthy();
  });

  it("flat 扫描完成显示平铺徽章", async () => {
    mockScan("flat", 0);
    render(<DueDiligenceWizard open onClose={() => {}} />);
    await runScan("/材料库");
    expect(screen.getByText(/平铺材料库/)).toBeTruthy();
  });
});
