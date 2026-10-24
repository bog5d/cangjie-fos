import { render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WarRoomMap } from "../WarRoomMap";
import { api } from "../../api/client";

/**
 * P0 回归（Codex v1.3.0 PARTIAL D）：
 * 编辑机构保存后，App 通过 milestoneRefreshKey +1 通知 WarRoomMap，
 * WarRoomMap 必须立即重新拉取 /api/v1/pipeline/milestone-stats（即时刷新成就墙）。
 * 这条用例锁住「保存→成就墙即时刷新」不只在创建机构时生效。
 */
describe("WarRoomMap 成就墙即时刷新", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  function milestoneCalls(spy: ReturnType<typeof vi.spyOn>): number {
    return spy.mock.calls.filter(
      (c) => String(c[0]).includes("/api/v1/pipeline/milestone-stats"),
    ).length;
  }

  it("milestoneRefreshKey 变化时重新拉取 milestone-stats", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({
      data: {
        total_contacted: 1,
        nda_signed: 0,
        offline_meetings: 0,
        offline_meeting_sum: 0,
        project_approved: 0,
        onsite_dd_done: 0,
        external_dd_done: 0,
        committee_approved: 0,
        agreement_signed: 0,
        deal_closed: 0,
        top_referrals: [],
        pipeline_counts: [],
        recent_roadshows: [],
        pending_followups: [],
      },
      status: 200,
      statusText: "OK",
      headers: {},
      config: {} as never,
    });

    const { rerender } = render(
      <WarRoomMap dashboard={null} loading error={null} tenantId="t1" milestoneRefreshKey={0} />,
    );

    // 初次挂载拉取一次
    await waitFor(() => expect(milestoneCalls(getSpy)).toBe(1));

    // 模拟「编辑保存」→ 父级把 key +1
    rerender(
      <WarRoomMap dashboard={null} loading error={null} tenantId="t1" milestoneRefreshKey={1} />,
    );

    // key 变化必须触发再次拉取（即时刷新，无需手动刷新页面）
    await waitFor(() => expect(milestoneCalls(getSpy)).toBe(2));
  });

  it("milestoneRefreshKey 不变时不会重复拉取", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({
      data: { total_contacted: 0, top_referrals: [], pipeline_counts: [], recent_roadshows: [], pending_followups: [] },
      status: 200,
      statusText: "OK",
      headers: {},
      config: {} as never,
    });

    const { rerender } = render(
      <WarRoomMap dashboard={null} loading error={null} tenantId="t1" milestoneRefreshKey={3} />,
    );
    await waitFor(() => expect(milestoneCalls(getSpy)).toBe(1));

    // 重渲染但 key 不变（例如父级其他 state 改变）→ 不应重复拉取
    rerender(
      <WarRoomMap dashboard={null} loading error={null} tenantId="t1" milestoneRefreshKey={3} />,
    );
    // 给一帧时间，确认没有第二次调用
    await new Promise((r) => setTimeout(r, 30));
    expect(milestoneCalls(getSpy)).toBe(1);
  });
});
