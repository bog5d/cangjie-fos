/**
 * 路演分析向导（Phase 7.5）
 *
 * 5步流程：
 *   Step 1 — 上传素材（音频 or 文字稿）+ 基本信息
 *   Step 2 — ASR转写进行中（等待 awaiting_speakers）
 *   Step 3 — 说话人身份确认（AI预推测 + 人工填写）
 *   Step 4 — AI分析进行中（等待 completed）
 *   Step 5 — 路演情报报告展示
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";

// ── 类型定义 ──────────────────────────────────────────────────────────────────

interface SpeakerPreviewItem {
  speaker_id: string;
  sample_lines: string[];
  word_count: number;
  guessed_role: string;
  guess_reason: string;
}

interface ConfirmedSpeaker {
  speaker_id: string;
  real_name: string;
  institution: string;
  role: string;
  title: string;
}

interface NextAction {
  action: string;
  owner: string;
  deadline: string;
  priority: string;
}

interface KeyQuestion {
  question: string;
  theme: string;
  asked_by: string;
}

interface InterestSignal {
  signal: string;
  speaker_id: string;
  sentiment: string;
}

interface KeyVerbatim {
  speaker_id: string;
  text: string;
  significance: string;
}

interface RoadshowReport {
  meeting_atmosphere: string;
  meeting_stage: string;
  key_questions: KeyQuestion[];
  interest_signals: InterestSignal[];
  hidden_concerns: string[];
  key_verbatim_moments: KeyVerbatim[];
  institution_update: string;
  next_actions: NextAction[];
  referrer: string;
  dominant_speaker: string;
  competitor_mentions: string[];
  timeline_signals: string;
}

interface JobStatus {
  job_id: string;
  status: string;
  substatus: string | null;
  has_report: boolean;
  report: RoadshowReport | null;
  referrer: string;
}

// ── 角色选项 ──────────────────────────────────────────────────────────────────

const ROLE_OPTIONS = [
  "引荐方",
  "企业方创始人",
  "企业方高管",
  "企业方投融资",
  "GP执行",
  "LP投资方",
  "政府招商",
  "其他",
];

// ── 辅助组件 ──────────────────────────────────────────────────────────────────

function AtmosphereTag({ value }: { value: string }) {
  const config: Record<string, { emoji: string; label: string; cls: string }> = {
    hot: { emoji: "🔥", label: "热情高涨", cls: "bg-red-500/20 text-red-300 border-red-500/30" },
    warm: { emoji: "☀️", label: "态度积极", cls: "bg-amber-500/20 text-amber-300 border-amber-500/30" },
    cold: { emoji: "🧊", label: "较为冷淡", cls: "bg-blue-500/20 text-blue-300 border-blue-500/30" },
  };
  const c = config[value] ?? { emoji: "❓", label: value || "未知", cls: "bg-slate-500/20 text-slate-300 border-slate-500/30" };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-sm font-semibold ${c.cls}`}>
      {c.emoji} {c.label}
    </span>
  );
}

function StageTag({ value }: { value: string }) {
  const labels: Record<string, string> = {
    first_contact: "初次接触",
    deep_discussion: "深度探讨",
    pre_dd: "尽调前期",
    unknown: "阶段不明",
  };
  return (
    <span className="rounded-full border border-purple-500/30 bg-purple-500/10 px-3 py-1 text-sm text-purple-300">
      {labels[value] ?? value}
    </span>
  );
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-4">
      <h3 className="mb-3 text-sm font-semibold text-slate-300">{title}</h3>
      {children}
    </div>
  );
}

// ── 主向导组件 ────────────────────────────────────────────────────────────────

export interface RoadshowWizardProps {
  open: boolean;
  onClose: () => void;
  tenantId: string;
  userName: string;
  onPipelineDataChanged?: () => void;
  institutions?: string[];
}

export function RoadshowWizard({
  open,
  onClose,
  tenantId,
  userName,
  onPipelineDataChanged,
  institutions = [],
}: RoadshowWizardProps) {
  const [step, setStep] = useState(1);

  // Step 1 字段
  const [mode, setMode] = useState<"audio" | "text">("audio");
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [transcriptText, setTranscriptText] = useState("");
  const [roadshowDate, setRoadshowDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [institutionName, setInstitutionName] = useState("");
  const [referrer, setReferrer] = useState("");
  const [instSuggestions, setInstSuggestions] = useState<string[]>([]);

  // 通用状态
  const [jobId, setJobId] = useState<string | null>(null);
  const [substatus, setSubstatus] = useState("");
  const [err, setErr] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Step 3
  const [speakerPreviews, setSpeakerPreviews] = useState<SpeakerPreviewItem[]>([]);
  const [confirmedSpeakers, setConfirmedSpeakers] = useState<ConfirmedSpeaker[]>([]);

  // Step 5
  const [report, setReport] = useState<RoadshowReport | null>(null);
  const [reportSpeakers, setReportSpeakers] = useState<ConfirmedSpeaker[]>([]);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── 重置 ──────────────────────────────────────────────────────────────────
  const resetAll = useCallback(() => {
    setStep(1);
    setMode("audio");
    setAudioFile(null);
    setTranscriptText("");
    setRoadshowDate(new Date().toISOString().slice(0, 10));
    setInstitutionName("");
    setReferrer("");
    setJobId(null);
    setSubstatus("");
    setErr("");
    setSubmitting(false);
    setSpeakerPreviews([]);
    setConfirmedSpeakers([]);
    setReport(null);
    setReportSpeakers([]);
    if (pollRef.current) clearInterval(pollRef.current);
  }, []);

  useEffect(() => {
    if (!open) {
      if (pollRef.current) clearInterval(pollRef.current);
    }
  }, [open]);

  // ── 机构 autocomplete ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!institutionName.trim()) {
      setInstSuggestions([]);
      return;
    }
    const q = institutionName.toLowerCase();
    setInstSuggestions(institutions.filter((i) => i.toLowerCase().includes(q)).slice(0, 6));
  }, [institutionName, institutions]);

  // ── Step 1: 提交上传 ──────────────────────────────────────────────────────
  const handleStart = async () => {
    if (!roadshowDate) { setErr("请填写路演日期"); return; }
    if (mode === "audio" && !audioFile) { setErr("请选择音频文件"); return; }
    if (mode === "text" && !transcriptText.trim()) { setErr("请粘贴文字稿内容"); return; }

    setErr("");
    setSubmitting(true);
    try {
      const params = new URLSearchParams({
        tenant_id: tenantId,
        roadshow_date: roadshowDate,
        institution_name: institutionName,
        referrer,
        confirmed_by: userName,
      });

      let data: { job_id: string; status: string; message: string };

      if (mode === "audio" && audioFile) {
        const fd = new FormData();
        fd.append("file", audioFile);
        const r = await api.post<typeof data>(
          `/api/v1/roadshow/start?${params.toString()}`,
          fd,
          { headers: { "Content-Type": "multipart/form-data" } },
        );
        data = r.data;
      } else {
        params.set("transcript_text", transcriptText.trim());
        const r = await api.post<typeof data>(`/api/v1/roadshow/start?${params.toString()}`);
        data = r.data;
      }

      setJobId(data.job_id);
      setSubstatus(data.message);

      if (data.status === "awaiting_speakers") {
        await loadSpeakerPreview(data.job_id);
        setStep(3);
      } else {
        setStep(2);
        startPollingForSpeakers(data.job_id);
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "上传失败，请重试";
      setErr(msg);
    } finally {
      setSubmitting(false);
    }
  };

  // ── Step 2: 轮询等待 ASR ──────────────────────────────────────────────────
  const startPollingForSpeakers = useCallback((jid: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const { data } = await api.get<JobStatus>(`/api/v1/roadshow/jobs/${jid}/status`);
        if (data.substatus) setSubstatus(data.substatus);
        if (data.status === "awaiting_speakers") {
          clearInterval(pollRef.current!);
          await loadSpeakerPreview(jid);
          setStep(3);
        } else if (data.status === "failed") {
          clearInterval(pollRef.current!);
          setErr("ASR转写失败，请检查音频文件格式后重试");
        }
      } catch {
        /* ignore transient errors */
      }
    }, 3000);
  }, []);

  // ── 加载说话人预览 ────────────────────────────────────────────────────────
  const loadSpeakerPreview = async (jid: string) => {
    const { data } = await api.get<SpeakerPreviewItem[]>(`/api/v1/roadshow/jobs/${jid}/speaker-preview`);
    setSpeakerPreviews(data);
    setConfirmedSpeakers(
      data.map((sp) => ({
        speaker_id: sp.speaker_id,
        real_name: "",
        institution: institutionName,
        role: sp.guessed_role,
        title: "",
      })),
    );
  };

  // ── Step 3: 更新说话人字段 ─────────────────────────────────────────────────
  const updateSpeaker = (idx: number, field: keyof ConfirmedSpeaker, value: string) => {
    setConfirmedSpeakers((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], [field]: value };
      return next;
    });
  };

  // ── Step 3: 确认说话人，触发分析 ──────────────────────────────────────────
  const handleConfirmSpeakers = async () => {
    if (!jobId) return;
    setErr("");
    setSubmitting(true);
    try {
      await api.post(
        `/api/v1/roadshow/jobs/${jobId}/confirm-speakers?tenant_id=${tenantId}`,
        { confirmed_by: userName || "指挥官", speakers: confirmedSpeakers },
      );
      setStep(4);
      startPollingForReport(jobId);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "提交失败";
      setErr(msg);
    } finally {
      setSubmitting(false);
    }
  };

  // ── Step 4: 轮询等待报告 ──────────────────────────────────────────────────
  const startPollingForReport = useCallback((jid: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const { data } = await api.get<JobStatus>(`/api/v1/roadshow/jobs/${jid}/status`);
        if (data.substatus) setSubstatus(data.substatus);
        if (data.status === "completed" && data.has_report) {
          clearInterval(pollRef.current!);
          const { data: reportData } = await api.get<{
            report: RoadshowReport;
            confirmed_speakers: ConfirmedSpeaker[];
          }>(`/api/v1/roadshow/jobs/${jid}/report`);
          setReport(reportData.report);
          setReportSpeakers(reportData.confirmed_speakers);
          onPipelineDataChanged?.();
          setStep(5);
        } else if (data.status === "failed") {
          clearInterval(pollRef.current!);
          setErr("AI分析失败，请联系管理员");
        }
      } catch {
        /* ignore */
      }
    }, 3000);
  }, [onPipelineDataChanged]);

  // ── 说话人名称查找 ────────────────────────────────────────────────────────
  const speakerName = (sid: string) => {
    const sp = reportSpeakers.find((s) => s.speaker_id === sid);
    if (!sp) return `说话人${sid}`;
    return sp.real_name || sp.role || `说话人${sid}`;
  };

  if (!open) return null;

  // ── 渲染 ──────────────────────────────────────────────────────────────────
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="relative flex w-full max-w-2xl flex-col rounded-2xl border border-white/10 bg-[#0f1117] shadow-2xl">
        {/* 标题栏 */}
        <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
          <div>
            <h2 className="text-lg font-bold text-white">🎯 路演分析</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              步骤 {step}/5 —{" "}
              {["", "上传素材", "转写中…", "确认说话人", "AI分析中…", "情报报告"][step]}
            </p>
          </div>
          <button
            type="button"
            onClick={() => { resetAll(); onClose(); }}
            className="rounded-lg p-1.5 text-slate-500 hover:text-white"
          >
            ✕
          </button>
        </div>

        {/* 步骤指示器 */}
        <div className="flex gap-1 px-6 pt-3">
          {[1, 2, 3, 4, 5].map((s) => (
            <div
              key={s}
              className={`h-1 flex-1 rounded-full transition-all ${
                s < step ? "bg-cyan-500" : s === step ? "bg-cyan-400" : "bg-white/10"
              }`}
            />
          ))}
        </div>

        {/* 内容区 */}
        <div className="flex-1 overflow-y-auto px-6 py-5" style={{ maxHeight: "70vh" }}>
          {/* ── Step 1 ── */}
          {step === 1 && (
            <div className="space-y-4">
              {/* 模式切换 */}
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setMode("audio")}
                  className={`flex-1 rounded-xl border py-2.5 text-sm font-medium transition ${
                    mode === "audio"
                      ? "border-cyan-500/50 bg-cyan-500/10 text-cyan-300"
                      : "border-white/10 text-slate-400 hover:border-white/20"
                  }`}
                >
                  🎵 上传音频文件
                </button>
                <button
                  type="button"
                  onClick={() => setMode("text")}
                  className={`flex-1 rounded-xl border py-2.5 text-sm font-medium transition ${
                    mode === "text"
                      ? "border-cyan-500/50 bg-cyan-500/10 text-cyan-300"
                      : "border-white/10 text-slate-400 hover:border-white/20"
                  }`}
                >
                  📝 粘贴文字稿
                </button>
              </div>

              {/* 音频上传 */}
              {mode === "audio" && (
                <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-white/15 py-8 transition hover:border-cyan-500/40">
                  <span className="text-3xl">🎙️</span>
                  <span className="text-sm text-slate-400">
                    {audioFile ? audioFile.name : "点击选择或拖拽音频（mp3 / m4a / wav）"}
                  </span>
                  {audioFile && (
                    <span className="text-xs text-slate-600">
                      {(audioFile.size / 1024 / 1024).toFixed(1)} MB
                    </span>
                  )}
                  <input
                    type="file"
                    accept="audio/*,.mp3,.m4a,.wav,.ogg,.flac"
                    className="hidden"
                    onChange={(e) => setAudioFile(e.target.files?.[0] ?? null)}
                  />
                </label>
              )}

              {/* 文字稿 */}
              {mode === "text" && (
                <div>
                  <p className="mb-1.5 text-xs text-slate-500">
                    支持格式：「说话人A：内容」「Speaker 1: 内容」「[A] 内容」等，也可直接粘贴无标记文本
                  </p>
                  <textarea
                    value={transcriptText}
                    onChange={(e) => setTranscriptText(e.target.value)}
                    placeholder="粘贴对话文字稿…"
                    rows={8}
                    className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-cyan-500/50"
                  />
                  {transcriptText && (
                    <p className="mt-1 text-right text-xs text-slate-600">
                      已输入 {transcriptText.length} 字符
                    </p>
                  )}
                </div>
              )}

              {/* 路演日期 */}
              <div>
                <label className="mb-1 block text-xs text-slate-400">路演日期 *</label>
                <input
                  type="date"
                  value={roadshowDate}
                  onChange={(e) => setRoadshowDate(e.target.value)}
                  className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-cyan-500/50"
                />
              </div>

              {/* 目标机构 */}
              <div className="relative">
                <label className="mb-1 block text-xs text-slate-400">目标机构（可选，稍后确认）</label>
                <input
                  type="text"
                  value={institutionName}
                  onChange={(e) => setInstitutionName(e.target.value)}
                  placeholder="机构名称…"
                  className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-cyan-500/50"
                />
                {instSuggestions.length > 0 && (
                  <ul className="absolute left-0 top-full z-10 mt-1 w-full rounded-xl border border-white/10 bg-[#1a1f2e] py-1 shadow-xl">
                    {instSuggestions.map((s) => (
                      <li key={s}>
                        <button
                          type="button"
                          className="w-full px-3 py-2 text-left text-sm text-slate-300 hover:bg-white/5"
                          onClick={() => { setInstitutionName(s); setInstSuggestions([]); }}
                        >
                          {s}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* 引荐方 */}
              <div>
                <label className="mb-1 block text-xs text-slate-400">引荐方机构（可选）</label>
                <input
                  type="text"
                  value={referrer}
                  onChange={(e) => setReferrer(e.target.value)}
                  placeholder="FA机构 / 朋友介绍…"
                  className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-cyan-500/50"
                />
              </div>

              {err && <p className="rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">{err}</p>}

              <button
                type="button"
                disabled={submitting}
                onClick={() => void handleStart()}
                className="w-full rounded-xl bg-gradient-to-r from-cyan-600 to-cyan-500 py-3 text-sm font-bold text-white shadow-lg transition hover:brightness-110 disabled:opacity-50"
              >
                {submitting ? "上传中…" : "开始分析 →"}
              </button>
            </div>
          )}

          {/* ── Step 2 ── */}
          {step === 2 && (
            <div className="flex flex-col items-center justify-center gap-6 py-12">
              <div className="text-5xl animate-bounce">🎙️</div>
              <div className="text-center">
                <p className="text-base font-semibold text-white">ASR 转写中，请稍候…</p>
                <p className="mt-2 max-w-xs text-sm text-slate-400">{substatus || "正在处理音频，通常需要1-3分钟"}</p>
              </div>
              <div className="flex gap-1">
                {[0, 1, 2].map((i) => (
                  <div
                    key={i}
                    className="h-2 w-2 rounded-full bg-cyan-500 opacity-70"
                    style={{ animation: `bounce 1.2s ease-in-out ${i * 0.2}s infinite` }}
                  />
                ))}
              </div>
            </div>
          )}

          {/* ── Step 3 ── */}
          {step === 3 && (
            <div className="space-y-4">
              <p className="text-sm text-slate-400">
                转写完成 — 请核对每位说话人的身份信息，AI已基于台词特征做了初步推测：
              </p>

              {speakerPreviews.map((sp, idx) => {
                const cs = confirmedSpeakers[idx];
                return (
                  <div key={sp.speaker_id} className="rounded-xl border border-white/10 bg-white/5 p-4 space-y-3">
                    <div className="flex items-center gap-3">
                      <span className="rounded-full bg-cyan-500/20 px-2.5 py-0.5 text-xs font-mono text-cyan-300">
                        说话人 {sp.speaker_id}
                      </span>
                      <span className="text-xs text-slate-500">{sp.word_count} 词</span>
                      <span className="ml-auto rounded-full border border-purple-500/30 bg-purple-500/10 px-2 py-0.5 text-xs text-purple-300">
                        AI推测：{sp.guessed_role}
                      </span>
                    </div>

                    {/* 样本台词 */}
                    {sp.sample_lines.length > 0 && (
                      <div className="space-y-1">
                        {sp.sample_lines.map((line, li) => (
                          <p key={li} className="rounded-lg bg-black/20 px-3 py-1.5 text-xs text-slate-400 italic">
                            「{line}」
                          </p>
                        ))}
                        {sp.guess_reason && (
                          <p className="text-xs text-slate-600">推测依据：{sp.guess_reason}</p>
                        )}
                      </div>
                    )}

                    {/* 填写表单 */}
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="mb-0.5 block text-xs text-slate-500">姓名</label>
                        <input
                          type="text"
                          value={cs?.real_name ?? ""}
                          onChange={(e) => updateSpeaker(idx, "real_name", e.target.value)}
                          placeholder="真实姓名…"
                          className="w-full rounded-lg border border-white/10 bg-black/30 px-2.5 py-1.5 text-xs text-white placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-cyan-500/50"
                        />
                      </div>
                      <div>
                        <label className="mb-0.5 block text-xs text-slate-500">职位</label>
                        <input
                          type="text"
                          value={cs?.title ?? ""}
                          onChange={(e) => updateSpeaker(idx, "title", e.target.value)}
                          placeholder="职位头衔…"
                          className="w-full rounded-lg border border-white/10 bg-black/30 px-2.5 py-1.5 text-xs text-white placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-cyan-500/50"
                        />
                      </div>
                      <div>
                        <label className="mb-0.5 block text-xs text-slate-500">所属机构</label>
                        <input
                          type="text"
                          value={cs?.institution ?? ""}
                          onChange={(e) => updateSpeaker(idx, "institution", e.target.value)}
                          placeholder="机构名称…"
                          className="w-full rounded-lg border border-white/10 bg-black/30 px-2.5 py-1.5 text-xs text-white placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-cyan-500/50"
                        />
                      </div>
                      <div>
                        <label className="mb-0.5 block text-xs text-slate-500">角色</label>
                        <select
                          value={cs?.role ?? "其他"}
                          onChange={(e) => updateSpeaker(idx, "role", e.target.value)}
                          className="w-full rounded-lg border border-white/10 bg-[#1a1f2e] px-2.5 py-1.5 text-xs text-white focus:outline-none focus:ring-1 focus:ring-cyan-500/50"
                        >
                          {ROLE_OPTIONS.map((r) => (
                            <option key={r} value={r}>{r}</option>
                          ))}
                        </select>
                      </div>
                    </div>
                  </div>
                );
              })}

              {speakerPreviews.length === 0 && (
                <p className="rounded-xl border border-white/10 bg-white/5 px-4 py-6 text-center text-sm text-slate-500">
                  未检测到说话人数据
                </p>
              )}

              {err && <p className="rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">{err}</p>}

              <button
                type="button"
                disabled={submitting}
                onClick={() => void handleConfirmSpeakers()}
                className="w-full rounded-xl bg-gradient-to-r from-cyan-600 to-cyan-500 py-3 text-sm font-bold text-white shadow-lg transition hover:brightness-110 disabled:opacity-50"
              >
                {submitting ? "提交中…" : "确认身份，开始AI分析 →"}
              </button>
            </div>
          )}

          {/* ── Step 4 ── */}
          {step === 4 && (
            <div className="flex flex-col items-center justify-center gap-6 py-12">
              <div className="text-5xl">🧠</div>
              <div className="text-center">
                <p className="text-base font-semibold text-white">AI 分析路演情报中…</p>
                <p className="mt-2 max-w-xs text-sm text-slate-400">{substatus || "正在深度解析会议内容，通常需要30-90秒"}</p>
              </div>
              <div className="h-1 w-48 overflow-hidden rounded-full bg-white/10">
                <div className="h-full w-1/2 animate-pulse rounded-full bg-gradient-to-r from-cyan-500 to-purple-500" />
              </div>
            </div>
          )}

          {/* ── Step 5 ── */}
          {step === 5 && report && (
            <div className="space-y-5">
              {/* 会议温度 */}
              <div className="flex flex-wrap items-center gap-3">
                <AtmosphereTag value={report.meeting_atmosphere} />
                <StageTag value={report.meeting_stage} />
                {report.referrer && (
                  <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-400">
                    🤝 引荐：{report.referrer}
                  </span>
                )}
              </div>

              {/* 主导决策人 */}
              {report.dominant_speaker && (
                <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3">
                  <p className="text-xs text-amber-400">
                    🎯 主导决策人（AI推测）：
                    <span className="ml-1 font-semibold text-amber-300">
                      {speakerName(report.dominant_speaker)}
                    </span>
                  </p>
                </div>
              )}

              {/* 核心关注点 */}
              {report.key_questions.length > 0 && (
                <SectionCard title="🔍 机构核心关注点">
                  <ul className="space-y-2">
                    {report.key_questions.map((q, i) => (
                      <li key={i} className="rounded-lg bg-black/20 p-3">
                        <div className="flex items-start gap-2">
                          <span className="mt-0.5 shrink-0 rounded bg-blue-500/20 px-1.5 py-0.5 text-xs text-blue-300">
                            {q.theme || "问题"}
                          </span>
                          <p className="text-sm text-slate-200">{q.question}</p>
                        </div>
                        {q.asked_by && (
                          <p className="mt-1 text-xs text-slate-600">
                            — {speakerName(q.asked_by)}
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                </SectionCard>
              )}

              {/* 兴趣信号 */}
              {report.interest_signals.length > 0 && (
                <SectionCard title="📡 兴趣信号">
                  <ul className="space-y-1.5">
                    {report.interest_signals.map((s, i) => (
                      <li key={i} className="flex items-start gap-2 rounded-lg bg-black/20 px-3 py-2">
                        <span className={`mt-0.5 text-sm ${s.sentiment === "positive" ? "text-emerald-400" : s.sentiment === "negative" ? "text-red-400" : "text-slate-400"}`}>
                          {s.sentiment === "positive" ? "✓" : s.sentiment === "negative" ? "✗" : "○"}
                        </span>
                        <span className="text-sm text-slate-300">{s.signal}</span>
                      </li>
                    ))}
                  </ul>
                </SectionCard>
              )}

              {/* 隐性顾虑 */}
              {report.hidden_concerns.length > 0 && (
                <SectionCard title="⚠️ 隐性顾虑（未明说）">
                  <ul className="space-y-1.5">
                    {report.hidden_concerns.map((c, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-amber-200/80">
                        <span className="shrink-0 text-amber-500">•</span>
                        {c}
                      </li>
                    ))}
                  </ul>
                </SectionCard>
              )}

              {/* 关键原话 */}
              {report.key_verbatim_moments.length > 0 && (
                <SectionCard title="💬 关键原话">
                  <div className="space-y-3">
                    {report.key_verbatim_moments.map((v, i) => (
                      <div key={i} className="rounded-lg border border-white/5 bg-black/20 p-3">
                        <p className="text-sm text-slate-200 italic">「{v.text}」</p>
                        <div className="mt-1.5 flex items-center gap-2">
                          <span className="text-xs text-slate-500">— {speakerName(v.speaker_id)}</span>
                          {v.significance && (
                            <span className="text-xs text-cyan-600">{v.significance}</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </SectionCard>
              )}

              {/* 约定行动项 */}
              {report.next_actions.length > 0 && (
                <SectionCard title="✅ 约定行动项">
                  <ul className="space-y-2">
                    {report.next_actions.map((a, i) => (
                      <li key={i} className="flex items-start gap-3 rounded-lg bg-black/20 px-3 py-2.5">
                        <span className="mt-0.5 shrink-0 text-cyan-500">→</span>
                        <div className="flex-1">
                          <p className="text-sm text-slate-200">{a.action}</p>
                          <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-500">
                            {a.owner && <span>负责：{a.owner}</span>}
                            {a.deadline && <span>DDL：{a.deadline}</span>}
                            {a.priority && (
                              <span className={`rounded px-1 ${a.priority === "high" ? "bg-red-500/20 text-red-300" : "bg-slate-500/20"}`}>
                                {a.priority === "high" ? "紧急" : a.priority === "medium" ? "中" : "低"}
                              </span>
                            )}
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                </SectionCard>
              )}

              {/* 竞品提及 */}
              {report.competitor_mentions.length > 0 && (
                <SectionCard title="⚔️ 竞品提及">
                  <div className="flex flex-wrap gap-2">
                    {report.competitor_mentions.map((c, i) => (
                      <span key={i} className="rounded-full border border-red-500/20 bg-red-500/10 px-2.5 py-0.5 text-xs text-red-300">
                        {c}
                      </span>
                    ))}
                  </div>
                </SectionCard>
              )}

              {/* 时间线信号 */}
              {report.timeline_signals && (
                <SectionCard title="⏱️ 投资时间线">
                  <p className="text-sm text-slate-300">{report.timeline_signals}</p>
                </SectionCard>
              )}

              {/* 机构画像更新 */}
              {report.institution_update && (
                <SectionCard title="📋 机构画像更新建议">
                  <p className="text-sm text-slate-300">{report.institution_update}</p>
                </SectionCard>
              )}

              <button
                type="button"
                onClick={() => { resetAll(); onClose(); }}
                className="w-full rounded-xl bg-gradient-to-r from-emerald-600 to-emerald-500 py-3 text-sm font-bold text-white shadow-lg transition hover:brightness-110"
              >
                完成 ✓
              </button>
            </div>
          )}

          {/* 全局错误（步骤2/4失败时） */}
          {(step === 2 || step === 4) && err && (
            <div className="mt-4 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">{err}</div>
          )}
        </div>
      </div>
    </div>
  );
}
