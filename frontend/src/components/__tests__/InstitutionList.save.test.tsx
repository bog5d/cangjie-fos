import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { InstitutionList } from "../InstitutionList";
import { api } from "../../api/client";
import type { InstitutionProfile } from "../../types/institution";

/**
 * P0 回归（Codex v1.3.0 PARTIAL D）：
 * 编辑已有机构并保存后，InstitutionList 必须调用 onMilestonesChanged，
 * 让父级 +1 milestoneRefreshKey，从而驱动成就墙即时刷新。
 * 锁住「保存→刷新」不只在创建机构时生效，也覆盖编辑保存路径。
 */
function makeProfile(over: Partial<InstitutionProfile> = {}): InstitutionProfile {
  return {
    institution_id: "inst-1",
    tenant_id: "t1",
    name: "红杉资本",
    stage: "dd",
    thermal: "hot",
    preferences: "",
    concerns: "",
    ai_summary: "",
    updated_at: 0,
    contact_name: "",
    contact_title: "",
    valuation: "",
    deal_size: "",
    probability: 0,
    legal_status: "",
    nda_signed: false,
    offline_meeting_count: 0,
    project_approved: false,
    committee_approved: false,
    onsite_dd_done: false,
    external_dd_done: false,
    agreement_signed: false,
    deal_closed: false,
    referral_source: "",
    ...over,
  };
}

describe("InstitutionList 编辑保存触发成就墙刷新", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("保存编辑后调用 onMilestonesChanged", async () => {
    // 挂载时 pitch-stats 拉取 → 返回空
    vi.spyOn(api, "get").mockResolvedValue({
      data: [],
      status: 200,
      statusText: "OK",
      headers: {},
      config: {} as never,
    });
    const saved = makeProfile({ nda_signed: true });
    const patchSpy = vi.spyOn(api, "patch").mockResolvedValue({
      data: saved,
      status: 200,
      statusText: "OK",
      headers: {},
      config: {} as never,
    });

    const onMilestonesChanged = vi.fn();
    const user = userEvent.setup();

    render(
      <InstitutionList
        tenantId="t1"
        items={[makeProfile()]}
        onMilestonesChanged={onMilestonesChanged}
      />,
    );

    // 点击机构卡片 → 打开编辑弹层
    await user.click(screen.getByText("红杉资本"));
    const saveBtn = await screen.findByRole("button", { name: /保存/ });
    await user.click(saveBtn);

    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1));
    expect(onMilestonesChanged).toHaveBeenCalledTimes(1);
  });
});
