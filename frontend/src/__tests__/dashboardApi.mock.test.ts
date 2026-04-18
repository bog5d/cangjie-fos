import { describe, expect, it, vi } from "vitest";
import { api } from "../api/client";

describe("dashboard API 契约（Mock Axios 实例）", () => {
  it("GET /api/dashboard/status 解析为 Dashboard 形状", async () => {
    const payload = {
      tenant_id: "ut",
      funnel: {
        tenant_id: "ut",
        round_name: "Series A",
        headline: "h",
        stages: [],
        momentum_score: 1,
      },
      docs_health_pct: 80,
      data_room_completeness_pct: 70,
      headline: "x",
      exp_hint: "y",
    };
    vi.spyOn(api, "get").mockResolvedValueOnce({
      data: payload,
      status: 200,
      statusText: "OK",
      headers: {},
      config: {} as never,
    });

    const { data } = await api.get("/api/dashboard/status", { params: { tenant_id: "ut" } });
    expect(data.tenant_id).toBe("ut");
    expect(data.docs_health_pct).toBe(80);
    expect(data.funnel.momentum_score).toBe(1);
  });
});
