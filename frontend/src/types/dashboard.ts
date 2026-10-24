import type { WarRoomFunnelResponse } from "./funnel";

export interface DashboardStatus {
  tenant_id: string;
  funnel: WarRoomFunnelResponse;
  docs_health_pct: number;
  data_room_completeness_pct: number;
  headline: string;
  exp_hint: string;
}
