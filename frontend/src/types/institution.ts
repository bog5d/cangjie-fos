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
}
