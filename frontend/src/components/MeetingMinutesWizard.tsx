/**
 * 通用会议纪要向导（非路演场景：高管访谈 / 内部会 / 客户会）
 *
 * 简化的单阶段流程（无需确认发言人）：
 *   Step 1 — 上传录音 or 粘贴文字稿 + 会议标题
 *   Step 2 — ASR + 纪要提炼进行中（轮询 status）
 *   Step 3 — 会议纪要展示（要点 / 决议 / 待办 / 遗留问题）+ 生成 HTML
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";

interface ActionItem {
  source: string;
  actor: string;
  action: string;
  priority: string;
}

interface MinutesReport {
  report_type: string;
  meeting_title: string;
  attendees: string[];
  summary: string;
  key_points: string[];
  decisions: string[];
  action_items: ActionItem[];
  open_questions: string[];
}

interface JobStatus {
  job_id: string;
  status: string;
  substatus: string | null;
  has_report: boolean;
  report: MinutesReport | null;
}

interface Props {
  open: boolean;
  onClose: () => void;
  tenantId: string;
}

type Step = 1 | 2 | 3;

export function MeetingMinutesWizard({ open, onClose, tenantId }: Props) {
  const [step, setStep] = useState<Step>(1);
  const [meetingTitle, setMeetingTitle] = useState("");
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [transcriptText, setTranscriptText] = useState("");
  const [jobId, setJobId] = useState("");
  const [report, setReport] = useState<MinutesReport | null>(null);
  const [substatus, setSubstatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const reset = useCallback(() => {
    setStep(1);
    setMeetingTitle("");
    setAudioFile(null);
    setTranscriptText("");
    setJobId("");
    setReport(null);
    setSubstatus("");
    setError("");
    setBusy(false);
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // 卸载/关闭时清理轮询，避免内存泄漏
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [reset, onClose]);

  const startPolling = useCallback((id: string) => {
    let ticks = 0;
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      ticks += 1;
      if (ticks > 300) {
        // 5 分钟超时保护
        if (pollRef.current) clearInterval(pollRef.current);
        setError("处理超时，请稍后在历史记录中查看，或重试。");
        return;
      }
      try {
        const r = await api.get<JobStatus>(`/api/v1/meeting/jobs/${id}/status`);
        setSubstatus(r.data.substatus || "");
        if (r.data.status === "completed" && r.data.report) {
          if (pollRef.current) clearInterval(pollRef.current);
          setReport(r.data.report);
          setStep(3);
        } else if (r.data.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current);
          setError("处理失败，请检查录音文件或稍后重试。");
        }
      } catch {
        // 单次轮询错误不致命，继续下一轮
      }
    }, 1000);
  }, []);

  const handleStart = useCallback(async () => {
    setError("");
    if (!audioFile && !transcriptText.trim()) {
      setError("请上传录音文件，或粘贴文字稿。");
      return;
    }
    setBusy(true);
    try {
      const params = new URLSearchParams({
        tenant_id: tenantId,
        meeting_title: meetingTitle.trim(),
      });
      let data: JobStatus;
      if (audioFile) {
        const fd = new FormData();
        fd.append("file", audioFile);
        const r = await api.post<JobStatus>(
          `/api/v1/meeting/start?${params.toString()}`,
          fd,
          { headers: { "Content-Type": "multipart/form-data" } },
        );
        data = r.data;
      } else {
        params.set("transcript_text", transcriptText);
        const r = await api.post<JobStatus>(`/api/v1/meeting/start?${params.toString()}`);
        data = r.data;
      }
      setJobId(data.job_id);
      setStep(2);
      startPolling(data.job_id);
    } catch (e) {
      setError(`启动失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }, [audioFile, transcriptText, meetingTitle, tenantId, startPolling]);

  const handleGenerateHtml = useCallback(async () => {
    if (!jobId) return;
    setBusy(true);
    try {
      await api.post(`/api/v1/meeting/jobs/${jobId}/html-report`);
      window.open(`/api/v1/meeting/jobs/${jobId}/html-report`, "_blank");
    } catch (e) {
      setError(`生成 HTML 失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }, [jobId]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-2xl bg-white shadow-2xl">
        {/* 头部 */}
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-bold text-gray-800">📝 会议纪要</h2>
          <button
            type="button"
            onClick={handleClose}
            className="text-gray-400 hover:text-gray-700"
            aria-label="关闭"
          >
            ✕
          </button>
        </div>

        <div className="px-6 py-5">
          {error && (
            <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          {/* Step 1 — 上传 */}
          {step === 1 && (
            <div className="space-y-4">
              <p className="text-sm text-gray-600">
                上传高管访谈 / 内部会 / 客户会的录音，AI 自动转写并提炼成结构化纪要（要点 · 决议 · 待办）。
              </p>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">会议主题</label>
                <input
                  type="text"
                  value={meetingTitle}
                  onChange={(e) => setMeetingTitle(e.target.value)}
                  placeholder="例如：Q3 高管访谈"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  录音文件（mp3/wav/m4a）
                </label>
                <input
                  type="file"
                  accept="audio/*,.mp3,.wav,.m4a"
                  onChange={(e) => setAudioFile(e.target.files?.[0] ?? null)}
                  className="w-full text-sm text-gray-800"
                />
              </div>
              <div className="text-center text-xs text-gray-400">— 或 —</div>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  直接粘贴文字稿（跳过转写）
                </label>
                <textarea
                  value={transcriptText}
                  onChange={(e) => setTranscriptText(e.target.value)}
                  placeholder="把会议文字记录粘贴到这里…"
                  rows={5}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800"
                />
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={handleStart}
                className="w-full rounded-lg bg-indigo-600 px-4 py-2.5 font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {busy ? "启动中…" : "开始生成纪要"}
              </button>
            </div>
          )}

          {/* Step 2 — 处理中 */}
          {step === 2 && (
            <div className="py-10 text-center">
              <div className="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-4 border-indigo-200 border-t-indigo-600" />
              <p className="font-medium text-gray-700">正在生成会议纪要…</p>
              <p className="mt-2 text-sm text-gray-500">{substatus || "处理中，请稍候"}</p>
            </div>
          )}

          {/* Step 3 — 纪要展示 */}
          {step === 3 && report && (
            <div className="space-y-5">
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700">
                AI 初稿 · 待人工审核
              </div>
              {report.meeting_title && (
                <h3 className="text-base font-bold text-gray-800">{report.meeting_title}</h3>
              )}
              {report.attendees?.length > 0 && (
                <p className="text-sm text-gray-500">参会：{report.attendees.join("、")}</p>
              )}
              {report.summary && (
                <p className="rounded-lg bg-gray-50 px-4 py-3 text-sm leading-relaxed text-gray-700">
                  {report.summary}
                </p>
              )}

              {report.key_points?.length > 0 && (
                <section>
                  <h4 className="mb-2 text-sm font-bold text-gray-700">讨论要点</h4>
                  <ul className="space-y-1">
                    {report.key_points.map((p, i) => (
                      <li key={i} className="border-l-2 border-cyan-400 pl-3 text-sm text-gray-700">
                        {p}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {report.decisions?.length > 0 && (
                <section>
                  <h4 className="mb-2 text-sm font-bold text-gray-700">会议决议</h4>
                  <ul className="space-y-1">
                    {report.decisions.map((d, i) => (
                      <li key={i} className="border-l-2 border-emerald-400 pl-3 text-sm text-gray-700">
                        ✅ {d}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {report.action_items?.length > 0 && (
                <section>
                  <h4 className="mb-2 text-sm font-bold text-gray-700">
                    待办行动项（{report.action_items.length}）
                  </h4>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-gray-500">
                        <th className="py-1">行动</th>
                        <th className="py-1">负责方</th>
                        <th className="py-1">优先级</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.action_items.map((a, i) => (
                        <tr key={i} className="border-t border-gray-100 text-gray-700">
                          <td className="py-1.5">{a.action}</td>
                          <td className="py-1.5">{a.actor}</td>
                          <td className="py-1.5">
                            {a.priority === "urgent" ? "🔴 紧急" : a.priority === "optional" ? "⚪ 可选" : "🔵 正常"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              )}

              {report.open_questions?.length > 0 && (
                <section>
                  <h4 className="mb-2 text-sm font-bold text-gray-700">遗留问题</h4>
                  <ul className="space-y-1">
                    {report.open_questions.map((q, i) => (
                      <li key={i} className="border-l-2 border-amber-400 pl-3 text-sm text-gray-700">
                        ⚠ {q}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={handleGenerateHtml}
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  生成 HTML / 下载
                </button>
                <button
                  type="button"
                  onClick={handleClose}
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                >
                  完成
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default MeetingMinutesWizard;
