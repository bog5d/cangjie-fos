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
  /** Coach 侧「本条事实摘要」，约 30 字内 */
  problem_summary?: string;
  /** 如：数据含糊、口径偏离 */
  risk_type?: string;
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
  original_report: AnyReport;
  edited_report: AnyReport | null;
  committed_at: number | null;
  words_summary: {
    total_words: number;
    duration_sec: number;
  };
  audio_available?: boolean;
  /** 上传向导中的被访谈人；简单上传无此项 */
  interviewee?: string | null;
}

// ── 路演情报报告类型 ────────────────────────────────────────────────────────

export interface IntelQuestion {
  speaker_id?: string;
  verbatim: string;
  underlying_concern: string;
  priority: "high" | "medium" | "low";
}

export interface IntelSignal {
  speaker_id?: string;
  verbatim: string;
  signal_type: "positive" | "concern" | "neutral";
  interpretation: string;
}

export interface IntelAction {
  source: "commitment" | "suggestion";
  actor?: string;
  action: string;
  priority: "urgent" | "normal" | "optional";
}

export interface RoadshowIntelReport {
  report_type: "roadshow_intel";
  meeting_atmosphere: "hot" | "warm" | "cold";
  meeting_stage: "first_contact" | "deep_discussion" | "pre_dd" | "unknown";
  atmosphere_summary: string;
  key_questions: IntelQuestion[];
  interest_signals: IntelSignal[];
  hidden_concerns: string[];
  key_verbatim_moments: string[];
  institution_update: string;
  next_actions: IntelAction[];
}

export type AnyReport = AnalysisReport | RoadshowIntelReport;

export function isRoadshowReport(r: AnyReport | null | undefined): r is RoadshowIntelReport {
  return (r as RoadshowIntelReport)?.report_type === "roadshow_intel";
}

export interface PitchReviewCommitRequest {
  edited_report: AnalysisReport;
}

export interface PitchReviewCommitResponse {
  job_id: string;
  committed_at: number;
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
