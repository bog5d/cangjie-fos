export interface TranscriptionWord {
  word_index: number;
  text: string;
  start_time: number;
  end_time: number;
  speaker_id?: string;
}

export interface SceneAnalysis {
  scene_type: string;
  speaker_roles: string;
}

export interface RiskPoint {
  _rid?: string;
  risk_level: "严重" | "一般" | "轻微";
  tier1_general_critique: string;
  tier2_qa_alignment: string;
  improvement_suggestion: string;
  original_text: string;
  start_word_index: number;
  end_word_index: number;
  score_deduction: number;
  deduction_reason: string;
  is_manual_entry?: boolean;
}

export interface AnalysisReport {
  scene_analysis: SceneAnalysis;
  total_score: number;
  total_score_deduction_reason: string;
  risk_points: RiskPoint[];
  positive_highlights?: string[];
}

export interface PitchReviewResponse {
  job_id: string;
  status: string;
  original_report: AnalysisReport;
  edited_report: AnalysisReport | null;
  committed_at: number | null;
  words_summary: {
    total_words: number;
    duration_sec: number;
  };
}

export interface PitchReviewCommitRequest {
  edited_report: AnalysisReport;
}

export interface PitchReviewCommitResponse {
  job_id: string;
  committed_at: number;
  diff_summary: {
    risk_points_added: number;
    risk_points_removed: number;
    fields_changed: number;
  };
}

export interface ReviewWorkbenchState {
  jobId: string;
  originalReport: AnalysisReport;
  draftReport: AnalysisReport;
  isDirty: boolean;
  isCommitted: boolean;
  committedAt: string | null;
  wordsMap: Map<number, TranscriptionWord>;
}

/** Props for AudioSnippetPlayer — defined here so parallel agents can import without circular deps */
export interface AudioSnippetPlayerProps {
  jobId: string;
  startWordIndex: number;
  endWordIndex: number;
  isManualEntry?: boolean;
}
