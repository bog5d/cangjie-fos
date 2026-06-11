import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";

// ── 后端契约类型（对齐 backend/src/cangjie_fos/services/*）──────────────────────
type Weight = "core" | "normal" | "minor";
type CoverStatus = "covered" | "weak" | "missed";

interface KeyPoint {
  point_no: string;
  page_no: number;
  point_text: string;
  weight: Weight;
  status?: CoverStatus;
  evidence?: string;
}

interface RoundReport {
  round_id?: string;
  round_no: number;
  coverage_score: number;
  covered_points: KeyPoint[];
  missed_points: KeyPoint[];
  suggestions: string[];
  duration_sec: number;
  speech_rate: number;
  word_count: number;
  transcript_text?: string;
}

interface ProgressCurve {
  session_id: string;
  rounds: { round_no: number; coverage_score: number }[];
  best_score: number;
  improvement: number;
}

interface QAQuestion {
  question_id: string | number;
  category: string;
  question_text: string;
  answer_points: string[];
  source?: string;
}

interface AnswerGrade {
  score: number;
  hit_points: string[];
  missed_points: string[];
  logic_flaws: string[];
  risk_statements: string[];
  feedback: string;
  transcript?: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  tenantId: string;
}

type Mode = "coach" | "qa";

// ── 浏览器录音 Hook：点一下开讲，再点停。产出 webm Blob（ASR 已支持 .webm）──────
function useRecorder() {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [supported] = useState(
    () => typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined",
  );
  const recRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopTick = () => {
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
  };

  const start = useCallback(async () => {
    if (!supported || recording) return;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const rec = new MediaRecorder(stream);
    chunksRef.current = [];
    rec.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    rec.start();
    recRef.current = rec;
    setSeconds(0);
    setRecording(true);
    tickRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
  }, [supported, recording]);

  const stop = useCallback((): Promise<Blob | null> => {
    return new Promise((resolve) => {
      const rec = recRef.current;
      if (!rec) {
        resolve(null);
        return;
      }
      rec.onstop = () => {
        stopTick();
        setRecording(false);
        rec.stream.getTracks().forEach((t) => t.stop());
        resolve(chunksRef.current.length ? new Blob(chunksRef.current, { type: "audio/webm" }) : null);
      };
      rec.stop();
    });
  }, []);

  useEffect(() => () => stopTick(), []);

  return { supported, recording, seconds, start, stop };
}

const WEIGHT_LABEL: Record<Weight, string> = { core: "必讲", normal: "应讲", minor: "可选" };
const WEIGHT_CLASS: Record<Weight, string> = {
  core: "bg-red-100 text-red-700 border-red-200",
  normal: "bg-amber-100 text-amber-700 border-amber-200",
  minor: "bg-gray-100 text-gray-600 border-gray-200",
};
const STATUS_LABEL: Record<CoverStatus, string> = { covered: "讲到", weak: "弱讲", missed: "漏讲" };
const STATUS_CLASS: Record<CoverStatus, string> = {
  covered: "text-emerald-600",
  weak: "text-amber-600",
  missed: "text-red-600",
};

function scoreColor(s: number): string {
  if (s >= 80) return "text-emerald-600";
  if (s >= 60) return "text-amber-600";
  return "text-red-600";
}

function fmtTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function CoachingWizard({ open, onClose, tenantId }: Props) {
  const [mode, setMode] = useState<Mode>("coach");

  // ── 教练（coach）状态 ──────────────────────────────────────────────────────
  const [bpText, setBpText] = useState("");
  const [bpFile, setBpFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [keyPoints, setKeyPoints] = useState<KeyPoint[]>([]);
  const [creating, setCreating] = useState(false);
  const [rounds, setRounds] = useState<RoundReport[]>([]);
  const [progress, setProgress] = useState<ProgressCurve | null>(null);
  const [scoring, setScoring] = useState(false);

  // ── 审问（qa）状态 ────────────────────────────────────────────────────────
  const [material, setMaterial] = useState("");
  const [sector, setSector] = useState("");
  const [roundStage, setRoundStage] = useState("");
  const [questions, setQuestions] = useState<QAQuestion[]>([]);
  const [genning, setGenning] = useState(false);
  const [activeQ, setActiveQ] = useState<number | null>(null);
  const [answerText, setAnswerText] = useState("");
  const [grades, setGrades] = useState<Record<string, AnswerGrade>>({});
  const [grading, setGrading] = useState(false);

  const [err, setErr] = useState<string>("");
  const coachRec = useRecorder();
  const qaRec = useRecorder();

  // 关闭后重置全部状态，避免下次打开残留
  useEffect(() => {
    if (!open) {
      setErr("");
    }
  }, [open]);

  if (!open) return null;

  const resetCoach = () => {
    setSessionId(null);
    setKeyPoints([]);
    setRounds([]);
    setProgress(null);
    setBpText("");
    setBpFile(null);
    setTitle("");
  };

  // ── 教练：建会话（提炼要点）────────────────────────────────────────────────
  const createSession = async () => {
    if (!bpText.trim() && !bpFile) {
      setErr("请粘贴路演逐字稿，或上传 BP 文件");
      return;
    }
    setErr("");
    setCreating(true);
    try {
      const fd = new FormData();
      if (bpFile) fd.append("file", bpFile);
      if (bpText.trim()) fd.append("bp_text", bpText);
      fd.append("tenant_id", tenantId);
      fd.append("title", title);
      const r = await api.post<{ session_id: string; key_points: KeyPoint[]; count: number }>(
        "/api/v1/coaching/sessions",
        fd,
      );
      setSessionId(r.data.session_id);
      setKeyPoints(r.data.key_points);
      setRounds([]);
      setProgress(null);
    } catch (e) {
      setErr(extractErr(e, "建会话失败"));
    } finally {
      setCreating(false);
    }
  };

  // ── 教练：提交一遍录音（录音 Blob 或文件）────────────────────────────────────
  const submitRound = async (audio: Blob, filename: string) => {
    if (!sessionId) return;
    setErr("");
    setScoring(true);
    try {
      const fd = new FormData();
      fd.append("file", audio, filename);
      const r = await api.post<RoundReport>(`/api/v1/coaching/sessions/${sessionId}/rounds`, fd);
      setRounds((prev) => [...prev, r.data]);
      const p = await api.get<ProgressCurve>(`/api/v1/coaching/sessions/${sessionId}/progress`);
      setProgress(p.data);
    } catch (e) {
      setErr(extractErr(e, "打分失败"));
    } finally {
      setScoring(false);
    }
  };

  const onCoachRecordStop = async () => {
    const blob = await coachRec.stop();
    if (blob) await submitRound(blob, `coach_round_${Date.now()}.webm`);
  };

  // ── 审问：出题 ──────────────────────────────────────────────────────────────
  const genQuestions = async () => {
    if (!material.trim()) {
      setErr("请粘贴 BP / 业务材料，AI 据此出题");
      return;
    }
    setErr("");
    setGenning(true);
    try {
      const r = await api.post<{ questions: QAQuestion[]; count: number }>("/api/v1/coaching/qa/questions", {
        material,
        tenant_id: tenantId,
        sector,
        round_stage: roundStage,
        limit: 12,
      });
      setQuestions(r.data.questions);
      setGrades({});
      setActiveQ(null);
    } catch (e) {
      setErr(extractErr(e, "出题失败"));
    } finally {
      setGenning(false);
    }
  };

  // ── 审问：评估一题（文字）──────────────────────────────────────────────────
  const gradeText = async (q: QAQuestion) => {
    if (!answerText.trim()) {
      setErr("请先作答，再评估");
      return;
    }
    setErr("");
    setGrading(true);
    try {
      const r = await api.post<AnswerGrade>("/api/v1/coaching/qa/grade", {
        question: q.question_text,
        answer_points: q.answer_points,
        transcript: answerText,
        tenant_id: tenantId,
        sector,
        round_stage: roundStage,
        category: q.category,
        persist: true,
      });
      setGrades((g) => ({ ...g, [String(q.question_id)]: r.data }));
    } catch (e) {
      setErr(extractErr(e, "评估失败"));
    } finally {
      setGrading(false);
    }
  };

  // ── 审问：评估一题（录音）──────────────────────────────────────────────────
  const gradeAudio = async (q: QAQuestion, audio: Blob) => {
    setErr("");
    setGrading(true);
    try {
      const fd = new FormData();
      fd.append("file", audio, `qa_${Date.now()}.webm`);
      fd.append("question", q.question_text);
      fd.append("answer_points_json", JSON.stringify(q.answer_points));
      fd.append("tenant_id", tenantId);
      const r = await api.post<AnswerGrade>("/api/v1/coaching/qa/grade-audio", fd);
      setGrades((g) => ({ ...g, [String(q.question_id)]: r.data }));
      if (r.data.transcript) setAnswerText(r.data.transcript);
    } catch (e) {
      setErr(extractErr(e, "录音评估失败"));
    } finally {
      setGrading(false);
    }
  };

  const onQaRecordStop = async (q: QAQuestion) => {
    const blob = await qaRec.stop();
    if (blob) await gradeAudio(q, blob);
  };

  const latest = rounds.length ? rounds[rounds.length - 1] : null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div>
            <h2 className="text-lg font-bold text-gray-800">🎤 路演陪练 · AI 教练 & 答疑审问</h2>
            <p className="mt-0.5 text-xs text-gray-500">
              用 AI 模拟投资人：练讲述（覆盖率打分）、抗追问（答疑评估）
            </p>
          </div>
          <button onClick={onClose} className="text-xl text-gray-400 hover:text-gray-600">
            ✕
          </button>
        </div>

        {/* 模式切换 */}
        <div className="flex gap-2 border-b border-gray-100 px-6 py-3">
          <button
            type="button"
            onClick={() => setMode("coach")}
            className={`rounded-lg px-4 py-1.5 text-sm font-medium transition ${
              mode === "coach"
                ? "bg-cyan-600 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            🎯 路演教练（覆盖率）
          </button>
          <button
            type="button"
            onClick={() => setMode("qa")}
            className={`rounded-lg px-4 py-1.5 text-sm font-medium transition ${
              mode === "qa"
                ? "bg-purple-600 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            🔍 答疑审问（抗压）
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 text-gray-800">
          {err && (
            <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {err}
            </div>
          )}

          {/* ════════════ 教练模式 ════════════ */}
          {mode === "coach" && !sessionId && (
            <div className="space-y-3">
              <p className="text-sm text-gray-600">
                第一步：贴入这次路演要讲的内容（逐字稿），或上传 BP 文件。AI 会提炼出投资人最关心的要点清单，作为打分标尺。
              </p>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="本次陪练标题（可选，如：A轮路演 v3）"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800"
              />
              <textarea
                value={bpText}
                onChange={(e) => setBpText(e.target.value)}
                placeholder="粘贴路演逐字稿 / BP 要点文字…"
                rows={8}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800"
              />
              <div className="flex items-center gap-3 text-sm">
                <label className="cursor-pointer rounded-lg border border-gray-300 px-3 py-1.5 text-gray-700 hover:bg-gray-50">
                  📎 上传 BP 文件
                  <input
                    type="file"
                    className="hidden"
                    accept=".pdf,.doc,.docx,.txt,.md,.ppt,.pptx"
                    onChange={(e) => setBpFile(e.target.files?.[0] ?? null)}
                  />
                </label>
                {bpFile && <span className="text-gray-500">{bpFile.name}</span>}
              </div>
              <button
                type="button"
                disabled={creating}
                onClick={() => void createSession()}
                className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-700 disabled:opacity-50"
              >
                {creating ? "提炼要点中…" : "提炼要点，开始陪练"}
              </button>
            </div>
          )}

          {mode === "coach" && sessionId && (
            <div className="space-y-4">
              {/* 要点清单 */}
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-gray-700">
                    打分标尺 · {keyPoints.length} 个要点
                  </h3>
                  <button
                    type="button"
                    onClick={resetCoach}
                    className="text-xs text-gray-400 hover:text-gray-600"
                  >
                    ← 换一份 BP
                  </button>
                </div>
                <div className="space-y-1">
                  {keyPoints.map((kp) => {
                    const st = latest
                      ? [...latest.covered_points, ...latest.missed_points].find(
                          (p) => p.point_no === kp.point_no,
                        )?.status
                      : undefined;
                    return (
                      <div key={kp.point_no} className="flex items-start gap-2 text-sm">
                        <span className={`mt-0.5 shrink-0 rounded border px-1.5 text-[11px] ${WEIGHT_CLASS[kp.weight]}`}>
                          {WEIGHT_LABEL[kp.weight]}
                        </span>
                        <span className="flex-1 text-gray-700">{kp.point_text}</span>
                        {st && (
                          <span className={`shrink-0 text-xs font-medium ${STATUS_CLASS[st]}`}>
                            {STATUS_LABEL[st]}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* 录音区 */}
              <div className="rounded-xl border border-cyan-200 bg-cyan-50 p-4">
                <p className="mb-2 text-sm font-medium text-gray-700">
                  第 {rounds.length + 1} 遍：对着要点完整讲一遍，AI 给覆盖率打分
                </p>
                <div className="flex flex-wrap items-center gap-3">
                  {coachRec.supported && (
                    <button
                      type="button"
                      disabled={scoring}
                      onClick={() => (coachRec.recording ? void onCoachRecordStop() : void coachRec.start())}
                      className={`rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50 ${
                        coachRec.recording ? "animate-pulse bg-red-600" : "bg-cyan-600 hover:bg-cyan-700"
                      }`}
                    >
                      {coachRec.recording ? `⏹ 停止并打分（${fmtTime(coachRec.seconds)}）` : "🎙 开始讲"}
                    </button>
                  )}
                  <label className="cursor-pointer rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50">
                    📎 上传录音文件
                    <input
                      type="file"
                      className="hidden"
                      accept="audio/*,.wav,.mp3,.m4a,.webm"
                      disabled={scoring}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) void submitRound(f, f.name);
                      }}
                    />
                  </label>
                  {scoring && <span className="text-sm text-cyan-700">⏳ 转写并打分中…</span>}
                </div>
                {!coachRec.supported && (
                  <p className="mt-2 text-xs text-gray-500">
                    当前浏览器不支持直接录音，请上传录音文件（wav/mp3/m4a/webm）。
                  </p>
                )}
              </div>

              {/* 最新一遍报告 */}
              {latest && (
                <div className="rounded-xl border border-gray-200 p-4">
                  <div className="mb-3 flex items-baseline justify-between">
                    <h3 className="text-sm font-semibold text-gray-700">第 {latest.round_no} 遍报告</h3>
                    <span className={`text-2xl font-bold ${scoreColor(latest.coverage_score)}`}>
                      {latest.coverage_score}
                      <span className="text-sm font-normal text-gray-400"> / 100 覆盖率</span>
                    </span>
                  </div>
                  <div className="mb-3 flex gap-4 text-xs text-gray-500">
                    <span>时长 {fmtTime(latest.duration_sec)}</span>
                    <span>语速 {latest.speech_rate} 字/分</span>
                    <span>字数 {latest.word_count}</span>
                  </div>
                  {latest.missed_points.length > 0 && (
                    <div className="mb-2">
                      <p className="mb-1 text-xs font-medium text-red-600">漏讲 / 弱讲：</p>
                      <ul className="space-y-0.5 text-sm text-gray-600">
                        {latest.missed_points.map((m) => (
                          <li key={m.point_no}>· {m.point_text}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {latest.suggestions.length > 0 && (
                    <div className="rounded-lg bg-amber-50 p-2">
                      {latest.suggestions.map((s, i) => (
                        <p key={i} className="text-sm text-amber-800">
                          {s}
                        </p>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* 进步曲线 */}
              {progress && progress.rounds.length >= 1 && (
                <div className="rounded-xl border border-gray-200 p-4">
                  <div className="mb-2 flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-gray-700">进步曲线</h3>
                    <span className="text-xs text-gray-500">
                      最高 {progress.best_score}
                      {progress.rounds.length >= 2 && (
                        <span className={progress.improvement >= 0 ? "ml-2 text-emerald-600" : "ml-2 text-red-600"}>
                          {progress.improvement >= 0 ? "↑" : "↓"} {Math.abs(progress.improvement)}
                        </span>
                      )}
                    </span>
                  </div>
                  <div className="flex items-end gap-2" style={{ height: 80 }}>
                    {progress.rounds.map((r) => (
                      <div key={r.round_no} className="flex flex-1 flex-col items-center justify-end gap-1">
                        <span className="text-[10px] text-gray-500">{r.coverage_score}</span>
                        <div
                          className="w-full rounded-t bg-cyan-500"
                          style={{ height: `${Math.max(4, (r.coverage_score / 100) * 60)}px` }}
                        />
                        <span className="text-[10px] text-gray-400">第{r.round_no}遍</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ════════════ 审问模式 ════════════ */}
          {mode === "qa" && questions.length === 0 && (
            <div className="space-y-3">
              <p className="text-sm text-gray-600">
                贴入 BP / 业务材料，AI 扮演投资人生成压力测试问题（融合历史真实被问到的问题）。再逐题作答，AI 评估命中要点、逻辑漏洞与风险表述。
              </p>
              <div className="flex gap-3">
                <input
                  value={sector}
                  onChange={(e) => setSector(e.target.value)}
                  placeholder="赛道（可选，如：企业服务）"
                  className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800"
                />
                <input
                  value={roundStage}
                  onChange={(e) => setRoundStage(e.target.value)}
                  placeholder="轮次（可选，如：A轮）"
                  className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800"
                />
              </div>
              <textarea
                value={material}
                onChange={(e) => setMaterial(e.target.value)}
                placeholder="粘贴 BP / 业务材料…"
                rows={8}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800"
              />
              <button
                type="button"
                disabled={genning}
                onClick={() => void genQuestions()}
                className="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
              >
                {genning ? "AI 出题中…" : "生成压力测试问题"}
              </button>
            </div>
          )}

          {mode === "qa" && questions.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-gray-700">{questions.length} 道压力测试题</h3>
                <button
                  type="button"
                  onClick={() => {
                    setQuestions([]);
                    setGrades({});
                  }}
                  className="text-xs text-gray-400 hover:text-gray-600"
                >
                  ← 换一份材料
                </button>
              </div>
              {questions.map((q, i) => {
                const grade = grades[String(q.question_id)];
                const isActive = activeQ === i;
                return (
                  <div key={q.question_id} className="rounded-xl border border-gray-200 p-3">
                    <div className="flex items-start gap-2">
                      <span className="shrink-0 rounded bg-purple-100 px-1.5 py-0.5 text-[11px] text-purple-700">
                        {q.category}
                      </span>
                      <p className="flex-1 text-sm font-medium text-gray-800">{q.question_text}</p>
                      {grade && (
                        <span className={`shrink-0 text-lg font-bold ${scoreColor(grade.score)}`}>{grade.score}</span>
                      )}
                    </div>
                    {q.answer_points.length > 0 && (
                      <p className="mt-1 pl-1 text-xs text-gray-400">
                        参考要点：{q.answer_points.join("；")}
                      </p>
                    )}

                    {!isActive && !grade && (
                      <button
                        type="button"
                        onClick={() => {
                          setActiveQ(i);
                          setAnswerText("");
                        }}
                        className="mt-2 text-sm text-purple-600 hover:text-purple-800"
                      >
                        ▶ 作答这道题
                      </button>
                    )}

                    {isActive && (
                      <div className="mt-2 space-y-2">
                        <textarea
                          value={answerText}
                          onChange={(e) => setAnswerText(e.target.value)}
                          placeholder="打字作答，或用下方录音按钮口头回答…"
                          rows={3}
                          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800"
                        />
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            disabled={grading}
                            onClick={() => void gradeText(q)}
                            className="rounded-lg bg-purple-600 px-3 py-1.5 text-sm text-white hover:bg-purple-700 disabled:opacity-50"
                          >
                            {grading ? "评估中…" : "提交评估"}
                          </button>
                          {qaRec.supported && (
                            <button
                              type="button"
                              disabled={grading}
                              onClick={() => (qaRec.recording ? void onQaRecordStop(q) : void qaRec.start())}
                              className={`rounded-lg px-3 py-1.5 text-sm text-white disabled:opacity-50 ${
                                qaRec.recording ? "animate-pulse bg-red-600" : "bg-gray-600 hover:bg-gray-700"
                              }`}
                            >
                              {qaRec.recording ? `⏹ 停止（${fmtTime(qaRec.seconds)}）` : "🎙 口头回答"}
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => setActiveQ(null)}
                            className="text-sm text-gray-400 hover:text-gray-600"
                          >
                            收起
                          </button>
                        </div>
                      </div>
                    )}

                    {grade && (
                      <div className="mt-2 space-y-1.5 rounded-lg bg-gray-50 p-3 text-sm">
                        {grade.feedback && <p className="font-medium text-gray-700">{grade.feedback}</p>}
                        {grade.hit_points.length > 0 && (
                          <p className="text-emerald-700">✓ 命中：{grade.hit_points.join("；")}</p>
                        )}
                        {grade.missed_points.length > 0 && (
                          <p className="text-red-600">✗ 遗漏：{grade.missed_points.join("；")}</p>
                        )}
                        {grade.logic_flaws.length > 0 && (
                          <p className="text-amber-700">⚠ 逻辑漏洞：{grade.logic_flaws.join("；")}</p>
                        )}
                        {grade.risk_statements.length > 0 && (
                          <p className="text-orange-700">🚩 风险表述：{grade.risk_statements.join("；")}</p>
                        )}
                        <button
                          type="button"
                          onClick={() => {
                            setActiveQ(i);
                            setAnswerText("");
                          }}
                          className="text-xs text-purple-600 hover:text-purple-800"
                        >
                          重答
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function extractErr(e: unknown, fallback: string): string {
  if (e && typeof e === "object" && "response" in e) {
    const resp = (e as { response?: { data?: { detail?: string } } }).response;
    if (resp?.data?.detail) return resp.data.detail;
  }
  if (e instanceof Error) return e.message;
  return fallback;
}
