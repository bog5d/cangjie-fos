export type PipelineStage = "targeted" | "pitched" | "dd" | "term_sheet";

export interface InstitutionProfile {
  institution_id: string;
  tenant_id: string;
  name: string;
  stage: PipelineStage;
  thermal: string;
  preferences: string;
  concerns: string;
  ai_summary: string;
  updated_at: number;
  source_trace_id?: string | null;
  contact_name: string;
  contact_title: string;
  valuation: string;
  deal_size: string;
  probability: number;
  legal_status: string;
  // 里程碑字段（v1.3.0）
  nda_signed: boolean;
  offline_meeting_count: number;
  project_approved: boolean;
  committee_approved: boolean;
  onsite_dd_done: boolean;
  external_dd_done: boolean;
  agreement_signed: boolean;
  deal_closed: boolean;
  referral_source: string;
}

export interface MilestoneStats {
  total_contacted: number;
  nda_signed: number;
  offline_meetings: number;
  project_approved: number;
  onsite_dd_done: number;
  external_dd_done: number;
  committee_approved: number;
  agreement_signed: number;
  deal_closed: number;
  top_referrals: Array<{ source: string; count: number }>;
}
