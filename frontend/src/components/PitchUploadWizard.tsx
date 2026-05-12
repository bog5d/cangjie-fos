import axios from "axios";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { NPC_DISPLAY_NAME } from "../constants/npc";
import { COACH_OTHER_SCENE, COACH_SCENE_PLACEHOLDER, COACH_SCENES } from "../constants/pitchCoachScenes";
import {
  guessBatchFieldsFromStem,
  shouldAutofillIv,
  stemFromAudioFilename,
} from "../lib/audioFilenameHints";

type Sniper = { quote: string; reason: string };

const AUDIO_WARN_BYTES = 300 * 1024 * 1024; // 300 MB

type LocalTrack = {
  id: string;
  audio: File | null;
  interviewee: string;
  sniper: Sniper[];
  qaFiles: File[];
  speakerHint: string;
};

export type PitchUploadWizardProps = {
  open: boolean;
  onClose: () => void;
  tenantId: string;
  userName: string;
  onPipelineDataChanged?: () => void;
  /** 非空时禁止最终提交（环境未就绪时由 App 注入） */
  uploadBlockedReason?: string | null;
};

const QA_WARN_CHARS = 28000;
const QA_HARD_CHARS = 30000;

function newTrack(): LocalTrack {
  return {
    id: crypto.randomUUID(),
    audio: null,
    interviewee: "",
    sniper: [{ quote: "", reason: "" }],
    qaFiles: [],
    speakerHint: "",
  };
}

function estimateQaChars(files: File[]): number {
  let n = 0;
  for (const f of files) {
    const name = f.name.toLowerCase();
    if (name.endsWith(".txt") || name.endsWith(".md")) {
      n += f.size;
    } else {
      n += Math.min(f.size, 2_000_000) / 2;
    }
  }
  return Math.floor(n);
}

function TrackAudioPreview({ file }: { file: File | null }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!file) {
      setUrl(null);
      return;
    }
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => {
      URL.revokeObjectURL(u);
    };
  }, [file]);
  if (!url) return null;
  return <audio controls src={url} className="mt-2 w-full max-w-full rounded-lg border border-white/10 bg-black/40" />;
}

type FieldErr = {
  category?: boolean;
  institution?: boolean;
  customRoles?: boolean;
  tracks?: Record<number, { audio?: boolean; interviewee?: boolean }>;
};

export function PitchUploadWizard({
  open,
  onClose,
  tenantId,
  userName,
  onPipelineDataChanged,
  uploadBlockedReason = null,
}: PitchUploadWizardProps) {
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<FieldErr>({});

  const [category, setCategory] = useState<string>(COACH_SCENE_PLACEHOLDER);
  const [institutionName, setInstitutionName] = useState("");
  const [batchLabel, setBatchLabel] = useState("");
  const [investorName, setInvestorName] = useState("");
  const [customRoles, setCustomRoles] = useState("");
  const [memoryCompanyId, setMemoryCompanyId] = useState("");
  const [companyBackground, setCompanyBackground] = useState("");
  const [sensitiveRaw, setSensitiveRaw] = useState("福创投, 迪策, 净利润");
  const [hotWordsRaw, setHotWordsRaw] = useState("");
  const [enableAsrPolish, setEnableAsrPolish] = useState(true);
  const [useLanggraphV1, setUseLanggraphV1] = useState(false);
  const [tracks, setTracks] = useState<LocalTrack[]>(() => [newTrack()]);
  // ── 机构路演快速模式 ──────────────────────────────────────────────────────────
  const [roadshowDate, setRoadshowDate] = useState<string>(() => new Date().toISOString().slice(0, 10));
  const [transcriptTab, setTranscriptTab] = useState<"audio" | "text">("audio");
  const [transcriptText, setTranscriptText] = useState("");
  /** BUG-C：与旧版一致，用 ref 避免连续选文件时闭包读到过期的「上次自动填充」 */
  const lastAutofilledIvRef = useRef<Record<string, string | null>>({});
  const [filenameMagic, setFilenameMagic] = useState<
    Record<string, { stem: string; intervieweeGuess: string; note: string } | null>
  >({});

  const drawerRef = useRef<HTMLDivElement>(null);

  const reset = useCallback(() => {
    setStep(0);
    setErr(null);
    setFieldErr({});
    setCategory(COACH_SCENE_PLACEHOLDER);
    setInstitutionName("");
    setBatchLabel("");
    setInvestorName("");
    setCustomRoles("");
    setMemoryCompanyId("");
    setCompanyBackground("");
    setSensitiveRaw("福创投, 迪策, 净利润");
    setHotWordsRaw("");
    setEnableAsrPolish(true);
    setUseLanggraphV1(false);
    setTracks([newTrack()]);
    lastAutofilledIvRef.current = {};
    setFilenameMagic({});
    setRoadshowDate(new Date().toISOString().slice(0, 10));
    setTranscriptTab("audio");
    setTranscriptText("");
  }, []);

  const close = () => {
    if (!busy) {
      reset();
      onClose();
    }
  };

  const qaTotals = useMemo(() => {
    let total = 0;
    for (const t of tracks) {
      total += estimateQaChars(t.qaFiles);
    }
    return total;
  }, [tracks]);

  const scrollToFirstInvalid = useCallback(() => {
    const root = drawerRef.current;
    if (!root) return;
    const el = root.querySelector("[data-invalid='1']");
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  const isRoadshow = category === "01_机构路演";

  const validateStep0 = useCallback((): FieldErr | null => {
    const e: FieldErr = {};
    if (category === COACH_SCENE_PLACEHOLDER) {
      e.category = true;
    }
    if (category === COACH_OTHER_SCENE && !customRoles.trim()) {
      e.customRoles = true;
    }
    // 机构路演模式：机构名自动填充，不校验
    if (!isRoadshow && !institutionName.trim()) {
      e.institution = true;
    }
    return Object.keys(e).length ? e : null;
  }, [category, customRoles, institutionName, isRoadshow]);

  const validateStep1 = useCallback((): FieldErr | null => {
    // 机构路演文字稿模式：只校验文字稿非空
    if (isRoadshow && transcriptTab === "text") {
      return transcriptText.trim() ? null : { tracks: { 0: { audio: true } } };
    }
    const te: Record<number, { audio?: boolean; interviewee?: boolean }> = {};
    for (let i = 0; i < tracks.length; i++) {
      const t = tracks[i];
      const row: { audio?: boolean; interviewee?: boolean } = {};
      if (!t.audio) {
        row.audio = true;
      }
      // 机构路演模式：被访谈人自动填充，不校验
      if (!isRoadshow && !t.interviewee.trim()) {
        row.interviewee = true;
      }
      if (row.audio || row.interviewee) {
        te[i] = row;
      }
    }
    return Object.keys(te).length ? { tracks: te } : null;
  }, [tracks, isRoadshow, transcriptTab, transcriptText]);

  const validateAll = useCallback((): string | null => {
    const a = validateStep0();
    const b = validateStep1();
    if (a || b) {
      setFieldErr({ ...(a ?? {}), ...(b ?? {}) });
      return "请修正标红项后再提交";
    }
    setFieldErr({});
    return null;
  }, [validateStep0, validateStep1]);

  const goToStep = useCallback(
    (target: number) => {
      if (target < 0 || target > 2) return;
      if (target < step) {
        setStep(target);
        setFieldErr({});
        return;
      }
      if (target === step) return;
      let s = step;
      while (s < target) {
        if (s === 0) {
          const e0 = validateStep0();
          if (e0) {
            setFieldErr(e0);
            setErr("请完成必填项（标红）");
            void Promise.resolve().then(scrollToFirstInvalid);
            return;
          }
          setFieldErr({});
          setErr(null);
          s = 1;
          setStep(1);
          continue;
        }
        if (s === 1) {
          const e1 = validateStep1();
          if (e1) {
            setFieldErr(e1);
            setErr("请完成每条轨道的音频与被访谈人（标红）");
            void Promise.resolve().then(scrollToFirstInvalid);
            return;
          }
          setFieldErr({});
          setErr(null);
          s = 2;
          setStep(2);
          continue;
        }
        break;
      }
    },
    [step, validateStep0, validateStep1, scrollToFirstInvalid],
  );

  const applyAudioFile = (ti: number, f: File | null) => {
    setTracks((prev) => {
      const cur = prev[ti];
      if (!cur) return prev;
      if (!f) {
        setFilenameMagic((m) => ({ ...m, [cur.id]: null }));
        return prev.map((x, j) => (j === ti ? { ...x, audio: null } : x));
      }
      const stem = stemFromAudioFilename(f.name);
      const [ivGuess, note] = guessBatchFieldsFromStem(stem);
      if (f.size > AUDIO_WARN_BYTES) {
        const mb = Math.round(f.size / (1024 * 1024));
        setErr(
          `⚠️ 音频文件 ${mb} MB，上传可能需要数分钟。` +
          `建议提前压缩：手机上用「录音转文字」类 App 导出 MP3，` +
          `电脑上用格式工厂或 Audacity 另存为 MP3（64kbps，语音清晰）。` +
          `上传后系统会再次自动压缩。可直接提交，不影响复盘质量。`
        );
      }
      setFilenameMagic((m) => ({
        ...m,
        [cur.id]: { stem, intervieweeGuess: ivGuess, note },
      }));
      const last = lastAutofilledIvRef.current[cur.id] ?? null;
      let nextIv = cur.interviewee;
      if (shouldAutofillIv(cur.interviewee, last)) {
        nextIv = ivGuess;
        lastAutofilledIvRef.current[cur.id] = ivGuess;
      }
      return prev.map((x, j) => (j === ti ? { ...x, audio: f, interviewee: nextIv } : x));
    });
  };

  const submitAll = async () => {
    const v = validateAll();
    if (v) {
      setErr(v);
      void Promise.resolve().then(scrollToFirstInvalid);
      return;
    }
    if (qaTotals >= QA_HARD_CHARS) {
      setErr(
        `参考 QA 合并后预计超过 ${QA_HARD_CHARS} 字符上限，提交可能被静默截断。请删减 QA 文件或拆分批次后再试。`,
      );
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      // 机构路演自动填充
      const autoInstitution = isRoadshow ? `待确认_${roadshowDate}` : institutionName.trim();
      const autoInterviewee = isRoadshow ? `路演_${roadshowDate}` : "";
      // 文字稿模式：把粘贴内容打包成 .txt 文件
      const isTextMode = isRoadshow && transcriptTab === "text";
      const textTracks = isTextMode
        ? [{ ...tracks[0], audio: new File([transcriptText], `transcript_${roadshowDate}.txt`, { type: "text/plain" }), interviewee: autoInterviewee }]
        : tracks;

      const body = {
        tenant_id: tenantId,
        user_name: userName.trim(),
        memory_company_id: memoryCompanyId.trim(),
        category,
        institution_name: autoInstitution,
        batch_label: batchLabel.trim() || (isRoadshow ? roadshowDate : ""),
        investor_name: investorName.trim(),
        custom_roles_other: customRoles.trim(),
        company_background: companyBackground,
        sensitive_words_raw: sensitiveRaw,
        hot_words_raw: hotWordsRaw,
        enable_asr_polish: enableAsrPolish,
        use_langgraph_v1: useLanggraphV1,
        tracks: textTracks.map((t) => ({
          client_temp_id: t.id,
          interviewee: isRoadshow ? autoInterviewee : t.interviewee.trim(),
          sniper_rows: t.sniper
            .filter((s) => (s.quote || "").trim() || (s.reason || "").trim())
            .map((s) => ({ quote: s.quote.trim(), reason: s.reason.trim() })),
          speaker_hint: t.speakerHint.trim(),
        })),
      };
      const { data: sess } = await api.post<{ session_id: string; track_count: number }>(
        "/api/v1/pitch/upload-sessions",
        body,
      );
      const sid = sess.session_id;
      for (let i = 0; i < textTracks.length; i++) {
        const fd = new FormData();
        fd.append("file", textTracks[i].audio as File);
        await api.post(`/api/v1/pitch/upload-sessions/${sid}/tracks/${i}/audio`, fd);
        for (const qf of textTracks[i].qaFiles) {
          const qfd = new FormData();
          qfd.append("file", qf);
          await api.post(`/api/v1/pitch/upload-sessions/${sid}/tracks/${i}/qa`, qfd);
        }
      }
      const { data: done } = await api.post<{ job_ids: string[]; assistant_echo: string }>(
        `/api/v1/pitch/upload-sessions/${sid}/commit`,
      );
      window.dispatchEvent(
        new CustomEvent("fos-npc-echo", { detail: { text: done.assistant_echo } }),
      );
      onPipelineDataChanged?.();
      reset();
      onClose();
    } catch (e: unknown) {
      let msg = "提交失败";
      if (axios.isAxiosError(e)) {
        const d = e.response?.data as { detail?: string } | undefined;
        msg = (d?.detail && String(d.detail)) || e.message;
      } else if (e instanceof Error) {
        msg = e.message;
      }
      setErr(msg);
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  const stepLabels = ["全局与背景", "逐条录音", "确认提交"];
  const qaWarn = qaTotals >= QA_WARN_CHARS;
  const qaHard = qaTotals >= QA_HARD_CHARS;

  return (
    <div className="fixed inset-0 z-50 flex pointer-events-none">
      {/* backdrop — pointer-events-auto 只在暗色遮罩上，避免 Chrome 透明外层 bug */}
      <button
        type="button"
        className="absolute inset-0 bg-black/75 backdrop-blur-sm pointer-events-auto"
        aria-label="关闭"
        onClick={() => close()}
      />
      <aside
        ref={drawerRef}
        className="relative ml-auto flex h-full w-full max-w-lg flex-col border-l border-cyan/25 bg-gradient-to-b from-[#070712] via-[#06061a] to-black shadow-[0_0_48px_rgba(34,211,238,0.15)] pointer-events-auto"
        role="dialog"
        aria-modal="true"
      >
        <header className="flex items-center justify-between border-b border-white/10 px-5 py-4">
          <div>
            <p className="font-display text-[10px] uppercase tracking-[0.35em] text-cyan/80">Phase 6.3</p>
            <h2 className="font-display text-lg font-semibold text-white">复盘上传向导</h2>
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={() => close()}
            className="rounded-lg border border-white/15 px-3 py-1 text-xs text-slate-300 hover:border-cyan/40 hover:text-white"
          >
            关闭
          </button>
        </header>

        <div className="flex gap-1 border-b border-white/5 px-4 py-3">
          {stepLabels.map((lb, i) => (
            <button
              key={lb}
              type="button"
              disabled={busy}
              onClick={() => goToStep(i)}
              className={`flex-1 rounded-lg px-2 py-2 text-center text-[11px] font-bold uppercase tracking-wider transition ${
                step === i
                  ? "bg-gradient-to-r from-cyan/30 to-plasma/25 text-white shadow-inner shadow-cyan/10"
                  : "text-slate-500 hover:text-slate-200"
              }`}
            >
              {i + 1}. {lb}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 text-sm text-slate-200">
          {err ? (
            <p
              className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-rose-100"
              role="alert"
            >
              {err}
            </p>
          ) : null}

          {uploadBlockedReason ? (
            <p
              className="mb-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-100"
              role="status"
            >
              {uploadBlockedReason}
            </p>
          ) : null}

          {qaWarn ? (
            <p
              className={`mb-3 rounded-lg border px-3 py-2 text-xs ${
                qaHard
                  ? "border-rose-500/50 bg-rose-500/15 text-rose-100"
                  : "border-amber-500/40 bg-amber-500/10 text-amber-100"
              }`}
              role="status"
            >
              参考 QA 体量预估约 {qaTotals} 字符（Coach 合并上限 {QA_HARD_CHARS}
              ）。{qaHard ? "已超过上限，请勿直接提交。" : "接近上限，提交后可能被截断，建议删减。"}
            </p>
          ) : null}

          {step === 0 ? (
            <div className="flex flex-col gap-4">
              {/* 场景选择 */}
              <label className="flex flex-col gap-1">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-400">业务大类</span>
                <select
                  data-invalid={fieldErr.category ? "1" : undefined}
                  value={category}
                  onChange={(e) => {
                    setCategory(e.target.value);
                    setFieldErr((fe) => ({ ...fe, category: undefined }));
                  }}
                  className={`rounded-xl border bg-black/40 px-3 py-2 text-white outline-none focus:border-cyan/50 ${
                    fieldErr.category ? "border-rose-500 ring-1 ring-rose-500/50" : "border-white/10"
                  }`}
                >
                  <option value={COACH_SCENE_PLACEHOLDER}>{COACH_SCENE_PLACEHOLDER}</option>
                  {COACH_SCENES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </label>

              {/* ── 机构路演快速模式：只填日期 ────────────────────────────────── */}
              {isRoadshow ? (
                <>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs font-bold text-slate-400">路演日期</span>
                    <input
                      type="date"
                      value={roadshowDate}
                      onChange={(e) => setRoadshowDate(e.target.value)}
                      className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-white outline-none focus:border-cyan/50"
                    />
                  </label>
                  <p className="rounded-lg border border-cyan/20 bg-cyan/5 px-3 py-2 text-xs text-cyan-100/80">
                    🚀 机构路演快速模式：机构名称和参与人将在分析完成后确认，现在只需上传录音或粘贴文字稿。
                  </p>
                </>
              ) : (
                /* ── 其他场景：完整表单 ───────────────────────────────────────── */
                <>
                  {category === COACH_OTHER_SCENE ? (
                    <label className="flex flex-col gap-1">
                      <span className="text-xs font-bold text-slate-400">具体双方身份（必填）</span>
                      <input
                        data-invalid={fieldErr.customRoles ? "1" : undefined}
                        value={customRoles}
                        onChange={(e) => {
                          setCustomRoles(e.target.value);
                          setFieldErr((fe) => ({ ...fe, customRoles: undefined }));
                        }}
                        placeholder="例如：供应商质量负责人 vs 买方投资机构"
                        className={`rounded-xl border bg-black/40 px-3 py-2 text-white outline-none focus:border-cyan/50 ${
                          fieldErr.customRoles ? "border-rose-500 ring-1 ring-rose-500/50" : "border-white/10"
                        }`}
                      />
                    </label>
                  ) : null}
                  <label className="flex flex-col gap-1">
                    <span className="text-xs font-bold text-slate-400">投资机构名称（必填）</span>
                    <input
                      data-invalid={fieldErr.institution ? "1" : undefined}
                      value={institutionName}
                      onChange={(e) => {
                        setInstitutionName(e.target.value);
                        setFieldErr((fe) => ({ ...fe, institution: undefined }));
                      }}
                      className={`rounded-xl border bg-black/40 px-3 py-2 text-white outline-none focus:border-cyan/50 ${
                        fieldErr.institution ? "border-rose-500 ring-1 ring-rose-500/50" : "border-white/10"
                      }`}
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs font-bold text-slate-400">项目批次备注</span>
                    <input
                      value={batchLabel}
                      onChange={(e) => setBatchLabel(e.target.value)}
                      placeholder="尽调第2轮、2026Q1"
                      className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-white outline-none focus:border-cyan/50"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs font-bold text-slate-400">接待投资人姓名</span>
                    <input
                      value={investorName}
                      onChange={(e) => setInvestorName(e.target.value)}
                      className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-white outline-none focus:border-cyan/50"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs font-bold text-slate-400">Coach memory_company_id（可空，空则等同 tenant）</span>
                    <input
                      value={memoryCompanyId}
                      onChange={(e) => setMemoryCompanyId(e.target.value)}
                      placeholder="与旧版侧边栏公司 ID 对齐"
                      className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-white outline-none focus:border-cyan/50"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs font-bold text-slate-400">公司背景（注入复盘）</span>
                    <textarea
                      value={companyBackground}
                      onChange={(e) => setCompanyBackground(e.target.value)}
                      rows={5}
                      className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-white outline-none focus:border-cyan/50"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs font-bold text-slate-400">保密词汇黑名单</span>
                    <textarea
                      value={sensitiveRaw}
                      onChange={(e) => setSensitiveRaw(e.target.value)}
                      rows={3}
                      className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-white outline-none focus:border-cyan/50"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs font-bold text-slate-400">ASR 专有名词热词（逗号分隔）</span>
                    <textarea
                      value={hotWordsRaw}
                      onChange={(e) => setHotWordsRaw(e.target.value)}
                      rows={2}
                      className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-white outline-none focus:border-cyan/50"
                    />
                  </label>
                  <label className="flex cursor-pointer items-center gap-2 text-slate-300">
                    <input
                      type="checkbox"
                      checked={enableAsrPolish}
                      onChange={(e) => setEnableAsrPolish(e.target.checked)}
                      className="h-4 w-4 accent-cyan"
                    />
                    开启错别字轻修正（默认勾选，对应 Coach ASR 润色）
                  </label>
                  <label className="flex cursor-pointer items-center gap-2 text-slate-300">
                    <input
                      type="checkbox"
                      checked={useLanggraphV1}
                      onChange={(e) => setUseLanggraphV1(e.target.checked)}
                      className="h-4 w-4 accent-cyan"
                    />
                    实验：LangGraph V1 评估链路
                  </label>
                </>
              )}
              <p className="text-xs text-slate-500">指挥官：「{userName || "未填写"}」将写入任务日志。</p>
            </div>
          ) : null}

          {step === 1 ? (
            <div className="flex flex-col gap-6">
              {/* ── 机构路演：录音/文字稿 tab 切换 ─────────────────────────── */}
              {isRoadshow ? (
                <>
                  <div className="flex rounded-xl border border-white/10 bg-white/[0.03] p-1">
                    <button
                      type="button"
                      onClick={() => setTranscriptTab("audio")}
                      className={`flex-1 rounded-lg py-2 text-xs font-bold uppercase tracking-wider transition ${
                        transcriptTab === "audio"
                          ? "bg-gradient-to-r from-cyan/30 to-plasma/25 text-white"
                          : "text-slate-500 hover:text-slate-200"
                      }`}
                    >
                      🎵 录音文件
                    </button>
                    <button
                      type="button"
                      onClick={() => setTranscriptTab("text")}
                      className={`flex-1 rounded-lg py-2 text-xs font-bold uppercase tracking-wider transition ${
                        transcriptTab === "text"
                          ? "bg-gradient-to-r from-cyan/30 to-plasma/25 text-white"
                          : "text-slate-500 hover:text-slate-200"
                      }`}
                    >
                      📝 文字稿
                    </button>
                  </div>

                  {transcriptTab === "text" ? (
                    <div className="flex flex-col gap-3">
                      <p className="text-xs text-slate-400">
                        支持手机 ASR 说话人格式：<code className="text-cyan/80">说话人A: xxx</code>、<code className="text-cyan/80">Speaker 1: xxx</code>，或直接粘贴无说话人标记的文字。
                      </p>
                      <textarea
                        data-invalid={fieldErr.tracks?.[0]?.audio ? "1" : undefined}
                        value={transcriptText}
                        onChange={(e) => {
                          setTranscriptText(e.target.value);
                          setFieldErr((fe) => ({ ...fe, tracks: undefined }));
                        }}
                        rows={14}
                        placeholder={"说话人A: 你们的商业模式是怎么样的？\n说话人B: 我们主要做SaaS订阅，核心客户是中大型企业…"}
                        className={`rounded-xl border bg-black/40 px-3 py-2 font-mono text-xs text-white outline-none focus:border-cyan/50 ${
                          fieldErr.tracks?.[0]?.audio ? "border-rose-500 ring-1 ring-rose-500/50" : "border-white/10"
                        }`}
                      />
                      <p className="text-xs text-slate-500">字符数：{transcriptText.length}</p>
                    </div>
                  ) : null}
                </>
              ) : null}

              {/* ── 录音文件轨道列表（非文字稿模式均显示） ────────────────────── */}
              {(!isRoadshow || transcriptTab === "audio") ? <>
              {tracks.map((t, ti) => {
                const terr = fieldErr.tracks?.[ti];
                const magic = filenameMagic[t.id];
                return (
                  <div
                    key={t.id}
                    className="rounded-2xl border border-plasma/20 bg-white/[0.03] p-4 shadow-inner shadow-black/40"
                  >
                    <p className="mb-3 font-display text-xs uppercase tracking-widest text-plasma/90">
                      录音 {ti + 1}
                    </p>
                    <label className="mb-2 flex flex-col gap-1">
                      <span className="text-xs text-slate-400">音频文件</span>
                      <input
                        data-invalid={terr?.audio ? "1" : undefined}
                        type="file"
                        accept="audio/*,.m4a,.mp3,.wav,.mp4,.webm"
                        onChange={(e) => {
                          const f = e.target.files?.[0] ?? null;
                          applyAudioFile(ti, f);
                          setFieldErr((fe) => {
                            const next = { ...fe, tracks: { ...fe.tracks } };
                            if (next.tracks?.[ti]) {
                              const row = { ...next.tracks[ti], audio: undefined };
                              next.tracks[ti] = row;
                              if (!row.interviewee) delete next.tracks[ti];
                            }
                            if (next.tracks && !Object.keys(next.tracks).length) {
                              delete next.tracks;
                            }
                            return next;
                          });
                        }}
                        className={`text-xs text-slate-300 file:mr-2 file:rounded-lg file:border-0 file:bg-cyan/20 file:px-2 file:py-1 file:text-cyan ${
                          terr?.audio ? "rounded-lg ring-1 ring-rose-500/60" : ""
                        }`}
                      />
                    </label>
                    {magic ? (
                      <div className="mb-2 rounded-lg border border-cyan/25 bg-cyan/5 px-2 py-2 text-[11px] text-cyan-100/95">
                        <p className="font-mono text-[10px] text-slate-500">stem: {magic.stem}</p>
                        <p>
                          推断被访谈人：<strong className="text-white">{magic.intervieweeGuess || "—"}</strong>
                        </p>
                        {magic.note ? <p className="mt-1 text-slate-300">备注：{magic.note}</p> : null}
                        {magic.note && !t.speakerHint.trim() ? (
                          <button
                            type="button"
                            className="mt-2 rounded border border-cyan/40 px-2 py-0.5 text-[10px] font-bold text-cyan hover:bg-cyan/10"
                            onClick={() =>
                              setTracks((prev) =>
                                prev.map((x, j) => (j === ti ? { ...x, speakerHint: magic.note } : x)),
                              )
                            }
                          >
                            把文件名备注填入说话人映射
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                    <TrackAudioPreview file={t.audio} />
                    {!isRoadshow ? (
                      <label className="mb-2 mt-2 flex flex-col gap-1">
                        <span className="text-xs text-slate-400">被访谈人（必填）</span>
                        <input
                          data-invalid={terr?.interviewee ? "1" : undefined}
                          value={t.interviewee}
                          onChange={(e) => {
                            const v = e.target.value;
                            setTracks((prev) =>
                              prev.map((x, j) => (j === ti ? { ...x, interviewee: v } : x)),
                            );
                            setFieldErr((fe) => {
                              const next = { ...fe, tracks: { ...fe.tracks } };
                              if (next.tracks?.[ti]) {
                                const row = { ...next.tracks[ti], interviewee: undefined };
                                next.tracks[ti] = row;
                                if (!row.audio) delete next.tracks[ti];
                              }
                              if (next.tracks && !Object.keys(next.tracks).length) {
                                delete next.tracks;
                              }
                              return next;
                            });
                          }}
                          className={`rounded-lg border bg-black/40 px-2 py-1.5 text-white outline-none focus:border-cyan/50 ${
                            terr?.interviewee ? "border-rose-500 ring-1 ring-rose-500/50" : "border-white/10"
                          }`}
                        />
                      </label>
                    ) : null}
                    <label className="mb-2 flex flex-col gap-1">
                      <span className="text-xs text-slate-400">说话人映射（可选，并入 session_notes）</span>
                      <input
                        value={t.speakerHint}
                        onChange={(e) =>
                          setTracks((prev) =>
                            prev.map((x, j) => (j === ti ? { ...x, speakerHint: e.target.value } : x)),
                          )
                        }
                        className="rounded-lg border border-white/10 bg-black/40 px-2 py-1.5 text-white outline-none focus:border-cyan/50"
                      />
                    </label>
                    <p className="mb-1 text-xs text-slate-500">狙击清单（原文引用 / 找茬疑点）</p>
                    {t.sniper.map((s, si) => (
                      <div key={si} className="mb-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                        <input
                          placeholder="原文引用"
                          value={s.quote}
                          onChange={(e) =>
                            setTracks((prev) =>
                              prev.map((x, j) =>
                                j === ti
                                  ? {
                                      ...x,
                                      sniper: x.sniper.map((row, ri) =>
                                        ri === si ? { ...row, quote: e.target.value } : row,
                                      ),
                                    }
                                  : x,
                              ),
                            )
                          }
                          className="rounded border border-white/10 bg-black/30 px-2 py-1 text-xs text-white"
                        />
                        <input
                          placeholder="找茬疑点"
                          value={s.reason}
                          onChange={(e) =>
                            setTracks((prev) =>
                              prev.map((x, j) =>
                                j === ti
                                  ? {
                                      ...x,
                                      sniper: x.sniper.map((row, ri) =>
                                        ri === si ? { ...row, reason: e.target.value } : row,
                                      ),
                                    }
                                  : x,
                              ),
                            )
                          }
                          className="rounded border border-white/10 bg-black/30 px-2 py-1 text-xs text-white"
                        />
                      </div>
                    ))}
                    <button
                      type="button"
                      className="mb-2 text-[11px] font-bold uppercase tracking-wider text-cyan hover:text-white"
                      onClick={() =>
                        setTracks((prev) =>
                          prev.map((x, j) =>
                            j === ti ? { ...x, sniper: [...x.sniper, { quote: "", reason: "" }] } : x,
                          ),
                        )
                      }
                    >
                      + 增加狙击行
                    </button>
                    <label className="flex flex-col gap-1">
                      <span className="text-xs text-slate-400">本条参考 QA（可多选文件）</span>
                      <input
                        type="file"
                        multiple
                        accept=".txt,.md,.pdf,.docx,.xlsx"
                        onChange={(e) => {
                          const fs = e.target.files ? Array.from(e.target.files) : [];
                          setTracks((prev) => prev.map((x, j) => (j === ti ? { ...x, qaFiles: fs } : x)));
                        }}
                        className="text-xs text-slate-300 file:mr-2 file:rounded-lg file:border-0 file:bg-plasma/20 file:px-2 file:py-1"
                      />
                    </label>
                  </div>
                );
              })}
              <button
                type="button"
                onClick={() => {
                  const nt = newTrack();
                  setTracks((x) => [...x, nt]);
                }}
                className="rounded-xl border border-dashed border-cyan/40 py-2 text-xs font-bold uppercase tracking-widest text-cyan hover:bg-cyan/10"
              >
                + 添加一条录音轨道
              </button>
              </> : null}
            </div>
          ) : null}

          {step === 2 ? (
            <div className="flex flex-col gap-3 text-slate-300">
              {isRoadshow ? (
                <>
                  <p>
                    路演日期：<strong className="text-white">{roadshowDate}</strong>
                    {transcriptTab === "text"
                      ? <>　文字稿 <strong className="text-cyan">{transcriptText.length}</strong> 字</>
                      : <>　录音文件 <strong className="text-white">{tracks.filter((t) => t.audio).length}</strong> 条</>}
                  </p>
                  <p className="rounded-lg border border-cyan/20 bg-cyan/5 px-3 py-2 text-xs text-cyan-100/80">
                    机构名将自动标记为「待确认_{roadshowDate}」，分析完成后可在复盘记录中确认每位参与人的身份。
                  </p>
                </>
              ) : (
                <p>
                  共 <strong className="text-white">{tracks.length}</strong> 条轨道；机构{" "}
                  <strong className="text-plasma">{institutionName || "—"}</strong>
                </p>
              )}
              <p className="text-xs text-slate-500">
                提交后将创建后台任务，{NPC_DISPLAY_NAME}
                会在聊天区提示进度；Task Rail 可查看各 job；完成后可直接打开 L1 报告摘要。
              </p>
            </div>
          ) : null}
        </div>

        <footer className="flex items-center justify-between border-t border-white/10 px-5 py-4">
          <button
            type="button"
            disabled={busy || step === 0}
            onClick={() => {
              setErr(null);
              setStep((s) => Math.max(0, s - 1));
            }}
            className="rounded-xl border border-white/15 px-4 py-2 text-xs font-bold uppercase tracking-wider text-slate-300 hover:border-white/30"
          >
            上一步
          </button>
          {step < 2 ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => goToStep(step + 1)}
              className="rounded-xl bg-gradient-to-r from-cyan/80 to-plasma/70 px-5 py-2 text-xs font-bold uppercase tracking-widest text-white shadow-lg shadow-cyan/20"
            >
              下一步
            </button>
          ) : (
            <button
              type="button"
              disabled={busy || qaHard || !!uploadBlockedReason}
              onClick={() => void submitAll()}
              className="rounded-xl bg-gradient-to-r from-plasma/90 to-ember/80 px-5 py-2 text-xs font-bold uppercase tracking-widest text-white shadow-lg shadow-plasma/25 disabled:opacity-40"
            >
              {busy ? "提交中…" : "确认提交复盘"}
            </button>
          )}
        </footer>
      </aside>
    </div>
  );
}
