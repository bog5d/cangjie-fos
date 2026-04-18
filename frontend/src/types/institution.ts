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
}
