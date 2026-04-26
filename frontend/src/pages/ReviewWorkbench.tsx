import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { AudioProvider } from "../components/workbench/AudioContext";
import { WorkbenchContext } from "../components/workbench/WorkbenchContext";
import WorkbenchHeader from "../components/workbench/WorkbenchHeader";
import WorkbenchBody from "../components/workbench/WorkbenchBody";
import SceneHeaderFields from "../components/workbench/left/SceneHeaderFields";
import { RiskPointList } from "../components/workbench/left/RiskPointList";
import AddRiskPointForm from "../components/workbench/left/AddRiskPointForm";
import JobInfoPanel from "../components/workbench/right/JobInfoPanel";
import WorkbenchNPCChat from "../components/workbench/right/WorkbenchNPCChat";
import HtmlReportPreview from "../components/workbench/right/HtmlReportPreview";
import type {
  AnalysisReport,
  PitchReviewResponse,
  PitchReviewCommitRequest,
  RiskPoint,
  TranscriptionWord,
} from "../types/review";

const DEFAULT_TENANT = "demo-tenant";

const PROCESSING_STATUSES = ["pending", "transcribing", "evaluating"];
const STATUS_LABELS: Record<string, string> = {
  pending: "排队等待中…",
  transcribing: "语音转写中…",
  evaluating: "LangGraph 评估中…",
};

function deepClone<T>(obj: T): T {
  return JSON.parse(JSON.stringify(obj)) as T;
}

function getTenant(): string {
  const q = new URLSearchParams(window.location.search).get("tenant");
  return q && q.length > 0 ? q : DEFAULT_TENANT;
}

function getUserName(): string {
  try {
    return localStorage.getItem("fos_commander_name") ?? "";
  } catch {
    return "";
  }
}

export default function ReviewWorkbench() {
  const { job_id: jobId = "" } = useParams<{ job_id: string }>();
  const navigate = useNavigate();
  const tenantId = getTenant();
  const userName = getUserName();

  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [reviewData, setReviewData] = useState<PitchReviewResponse | null>(null);
  const [draftReport, setDraftReport] = useState<AnalysisReport | null>(null);
  const [wordsMap, setWordsMap] = useState<Map<number, TranscriptionWord>>(new Map());
  const [isDirty, setIsDirty] = useState(false);
  const [committing, setCommitting] = useState(false);
  const originalRef = useRef<AnalysisReport | null>(null);

  // Load review data
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    setLoading(true);
    setErr(null);
    void (async () => {
      try {
        const { data } = await api.get<PitchReviewResponse>(`/api/pitch/jobs/${jobId}/review`);
        if (cancelled) return;
        setReviewData(data);
        const base = data.edited_report ?? data.original_report;
        originalRef.current = data.original_report;
        setDraftReport(deepClone(base));
      } catch (e: unknown) {
        if (!cancelled) setErr(e instanceof Error ? e.message : "加载失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [jobId]);

  // Lazy load words map
  useEffect(() => {
    if (!jobId) return;
    void (async () => {
      try {
        const { data } = await api.get<TranscriptionWord[]>(`/api/pitch/jobs/${jobId}/words`);
        const m = new Map<number, TranscriptionWord>();
        for (const w of data) m.set(w.word_index, w);
        setWordsMap(m);
      } catch {
        // words 加载失败不影响主流程，音频联动降级
      }
    })();
  }, [jobId]);

  useEffect(() => {
    if (!reviewData) return;
    if (!PROCESSING_STATUSES.includes(reviewData.status)) return;
    const timer = setInterval(async () => {
      try {
        const { data } = await api.get<PitchReviewResponse>(`/api/pitch/jobs/${jobId}/review`);
        setReviewData(data);
        const base = data.edited_report ?? data.original_report;
        if (base) {
          originalRef.current = data.original_report;
          setDraftReport(deepClone(base));
        }
      } catch { }
    }, 5000);
    return () => clearInterval(timer);
  }, [reviewData?.status, jobId]);

  const updateDraft = useCallback((updater: (prev: AnalysisReport) => AnalysisReport) => {
    setDraftReport((prev) => {
      if (!prev) return prev;
      const next = updater(prev);
      setIsDirty(true);
      return next;
    });
  }, []);

  const handleSceneChange = useCallback(
    (field: "scene_type" | "speaker_roles", value: string) => {
      updateDraft((prev) => ({
        ...prev,
        scene_analysis: { ...prev.scene_analysis, [field]: value },
      }));
    },
    [updateDraft],
  );

  const handleScoreChange = useCallback(
    (score: number, reason: string) => {
      updateDraft((prev) => ({
        ...prev,
        total_score: score,
        total_score_deduction_reason: reason,
      }));
    },
    [updateDraft],
  );

  const handleRiskChange = useCallback(
    (index: number, updated: RiskPoint) => {
      updateDraft((prev) => {
        const pts = [...prev.risk_points];
        pts[index] = updated;
        return { ...prev, risk_points: pts };
      });
    },
    [updateDraft],
  );

  const handleRiskDelete = useCallback(
    (index: number) => {
      updateDraft((prev) => ({
        ...prev,
        risk_points: prev.risk_points.filter((_, i) => i !== index),
      }));
    },
    [updateDraft],
  );

  const handleAddRisk = useCallback(
    (point: Omit<RiskPoint, "_rid">) => {
      updateDraft((prev) => ({
        ...prev,
        risk_points: [...prev.risk_points, { ...point, _rid: `manual-${Date.now()}` }],
      }));
    },
    [updateDraft],
  );

  const handleCommit = useCallback(async () => {
    if (!draftReport || !jobId) return;
    setCommitting(true);
    try {
      const body: PitchReviewCommitRequest = { edited_report: draftReport };
      await api.patch(`/api/pitch/jobs/${jobId}/review`, body);
      setReviewData((prev) =>
        prev ? { ...prev, committed_at: Date.now() / 1000, edited_report: draftReport } : prev,
      );
      setIsDirty(false);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "提交失败，请重试");
    } finally {
      setCommitting(false);
    }
  }, [draftReport, jobId]);

  const isCommitted = reviewData?.committed_at != null;
  const committedAt = reviewData?.committed_at
    ? new Date(reviewData.committed_at * 1000).toLocaleString("zh-CN")
    : null;

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#0a0a14] text-slate-400 text-sm">
        载入审查台…
      </div>
    );
  }

  if (reviewData && PROCESSING_STATUSES.includes(reviewData.status)) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4 bg-[#0a0a14]">
        <div className="w-8 h-8 border-2 border-cyan-400/40 border-t-cyan-400 rounded-full animate-spin" />
        <p className="text-slate-300 text-sm">{STATUS_LABELS[reviewData.status] ?? "处理中…"}</p>
        <p className="text-slate-600 text-xs">每 5 秒自动刷新，完成后自动显示</p>
        <button type="button" onClick={() => navigate(-1)} className="text-xs text-cyan-400 hover:text-cyan-300 mt-2">← 返回</button>
      </div>
    );
  }

  if (err || !draftReport || !reviewData) {
    const isFailed = reviewData?.status === "failed";
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4 bg-[#0a0a14]">
        <p className="text-rose-300 text-sm">
          {isFailed ? "任务执行失败" : err ?? "数据异常"}
        </p>
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="text-xs text-cyan-400 hover:text-cyan-300"
        >
          ← 返回
        </button>
      </div>
    );
  }

  const leftPanel = (
    <div className="space-y-0">
      <SceneHeaderFields
        sceneType={draftReport.scene_analysis.scene_type}
        speakerRoles={draftReport.scene_analysis.speaker_roles}
        totalScore={draftReport.total_score}
        totalScoreDeductionReason={draftReport.total_score_deduction_reason}
        isReadonly={isCommitted}
        onSceneChange={handleSceneChange}
        onScoreChange={handleScoreChange}
      />
      <RiskPointList
        points={draftReport.risk_points}
        isReadonly={isCommitted}
        onChange={handleRiskChange}
        onDelete={handleRiskDelete}
        intervieweeName={reviewData?.interviewee}
      />
      <AddRiskPointForm onAdd={handleAddRisk} disabled={isCommitted} />
    </div>
  );

  const rightPanel = (
    <>
      <JobInfoPanel
        jobId={jobId}
        status={reviewData.status}
        totalWords={reviewData.words_summary.total_words}
        durationSec={reviewData.words_summary.duration_sec}
        originalScore={reviewData.original_report.total_score}
        currentScore={draftReport.total_score}
        committedAt={reviewData.committed_at}
        interviewee={reviewData.interviewee}
      />
      <WorkbenchNPCChat tenantId={tenantId} jobId={jobId} userName={userName} />
      <HtmlReportPreview jobId={jobId} isDirty={isDirty} onCommitFirst={handleCommit} />
    </>
  );

  return (
    <AudioProvider>
      <WorkbenchContext.Provider value={{ jobId, wordsMap }}>
        <div className="flex h-screen flex-col bg-[#0a0a14] text-white overflow-hidden">
          <WorkbenchHeader
            jobId={jobId}
            status={reviewData.status}
            isCommitted={isCommitted}
            committedAt={committedAt}
            isDirty={isDirty}
            onBack={() => navigate(-1)}
            onCommit={() => void handleCommit()}
            committing={committing}
          />
          <WorkbenchBody leftPanel={leftPanel} rightPanel={rightPanel} />
        </div>
      </WorkbenchContext.Provider>
    </AudioProvider>
  );
}
