export type FunnelStageKey =
  | "materials"
  | "teaser"
  | "partner_meet"
  | "term_sheet"
  | "closing";

export interface FunnelStage {
  key: FunnelStageKey;
  title: string;
  subtitle: string;
  progress_pct: number;
  status: string;
}

export interface WarRoomFunnelResponse {
  tenant_id: string;
  round_name: string;
  headline: string;
  stages: FunnelStage[];
  momentum_score: number;
}
