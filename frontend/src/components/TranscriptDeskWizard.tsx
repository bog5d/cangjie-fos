/**
 * 文字稿工作台（脱敏优先）
 *
 * 团队改用离线设备转写录音，音频不进系统。文字稿在进入分析前先脱敏：
 *   粘贴文字稿 → 一键脱敏（身份/商密/涉军）→ 人工复核命中 → 用脱敏稿去生成会议纪要
 * 只脱身份类，绝不动业务数字（金额/产品数）。
 */
import { useCallback, useState } from "react";
import { api } from "../api/client";

interface Hit {
  category: string;
  type: string;
  original: string;
  masked: string;
}

interface PreviewResp {
  masked_text: string;
  hits: Hit[];
  count: number;
}

interface Props {
  open: boolean;
  onClose: () => void;
  tenantId: string;
}

const CAT_LABEL: Record<string, string> = {
  identity: "身份",
  secret: "商密",
  military: "涉军",
};

export function TranscriptDeskWizard({ open, onClose, tenantId }: Props) {
  const [raw, setRaw] = useState("");
  const [masked, setMasked] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [meetingTitle, setMeetingTitle] = useState("");
  const [newTerm, setNewTerm] = useState("");
  const [newCat, setNewCat] = useState("secret");
  const [done, setDone] = useState("");

  const reset = useCallback(() => {
    setRaw(""); setMasked(""); setHits([]); setError("");
    setMeetingTitle(""); setNewTerm(""); setDone("");
  }, []);

  const handleClose = useCallback(() => { reset(); onClose(); }, [reset, onClose]);

  const runDesensitize = useCallback(async () => {
    setError("");
    if (!raw.trim()) { setError("请先粘贴文字稿。"); return; }
    setBusy(true);
    try {
      const { data } = await api.post<PreviewResp>("/api/v1/desensitize/preview", {
        text: raw, tenant_id: tenantId,
      });
      setMasked(data.masked_text);
      setHits(data.hits);
    } catch (e) {
      setError(`脱敏失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }, [raw, tenantId]);

  const addTerm = useCallback(async () => {
    if (!newTerm.trim()) return;
    setBusy(true);
    try {
      await api.post("/api/v1/desensitize/terms", {
        tenant_id: tenantId, category: newCat, term: newTerm.trim(),
      });
      setNewTerm("");
      await runDesensitize();  // 加词后重跑
    } catch (e) {
      setError(`加词失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }, [newTerm, newCat, tenantId, runDesensitize]);

  const copyMasked = useCallback(() => {
    void navigator.clipboard?.writeText(masked);
    setDone("已复制脱敏稿到剪贴板");
    setTimeout(() => setDone(""), 2500);
  }, [masked]);

  const toMeetingMinutes = useCallback(async () => {
    setBusy(true);
    try {
      const params = new URLSearchParams({
        tenant_id: tenantId, meeting_title: meetingTitle.trim() || "会议纪要",
      });
      params.set("transcript_text", masked);
      await api.post(`/api/v1/meeting/start?${params.toString()}`);
      setDone("已用脱敏稿提交生成会议纪要，去「📝 会议纪要」查看结果");
    } catch (e) {
      setError(`提交失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }, [masked, meetingTitle, tenantId]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-2xl bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-bold text-gray-800">🛡️ 文字稿工作台 · 脱敏优先</h2>
          <button type="button" onClick={handleClose} className="text-gray-400 hover:text-gray-700">✕</button>
        </div>

        <div className="px-6 py-5 space-y-4">
          <p className="text-sm text-gray-600">
            离线转写好的文字稿粘进来 → 一键脱敏（身份 / 商密 / 涉军）→ 复核后用脱敏稿去分析。
            <span className="font-medium text-amber-700">金额、产品数等业务数字不会被脱。</span>
          </p>

          {error && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
          {done && <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{done}</div>}

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">原始文字稿</label>
            <textarea
              value={raw}
              onChange={(e) => setRaw(e.target.value)}
              rows={6}
              placeholder="把离线转写好的文字稿粘贴到这里…"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800"
            />
          </div>

          <button
            type="button"
            disabled={busy}
            onClick={runDesensitize}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {busy ? "处理中…" : "🛡️ 一键脱敏"}
          </button>

          {/* 团队脱敏词典：加词 */}
          <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
            <span className="text-xs text-gray-500">词典没覆盖到？加一个：</span>
            <select value={newCat} onChange={(e) => setNewCat(e.target.value)}
                    className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-800">
              <option value="identity">身份/人名</option>
              <option value="secret">商业秘密</option>
              <option value="military">涉军</option>
            </select>
            <input value={newTerm} onChange={(e) => setNewTerm(e.target.value)}
                   placeholder="要脱敏的词（如 波总 / 代号X）"
                   className="flex-1 rounded border border-gray-300 px-2 py-1 text-xs text-gray-800" />
            <button type="button" onClick={addTerm} disabled={busy}
                    className="rounded bg-gray-700 px-3 py-1 text-xs text-white hover:bg-gray-800 disabled:opacity-50">
              加入词典并重跑
            </button>
          </div>

          {masked && (
            <>
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <label className="text-sm font-medium text-gray-700">脱敏后（可直接编辑）</label>
                  <span className="text-xs text-gray-500">命中 {hits.length} 处</span>
                </div>
                <textarea
                  value={masked}
                  onChange={(e) => setMasked(e.target.value)}
                  rows={6}
                  className="w-full rounded-lg border border-emerald-300 bg-emerald-50/40 px-3 py-2 text-sm text-gray-800"
                />
              </div>

              {hits.length > 0 && (
                <div className="rounded-lg border border-gray-200 p-3">
                  <p className="mb-2 text-xs font-bold text-gray-600">命中清单（复核用）</p>
                  <div className="flex flex-wrap gap-1">
                    {hits.map((h, i) => (
                      <span key={i} className="rounded border border-gray-300 bg-gray-50 px-1.5 py-0.5 text-[11px] text-gray-600">
                        {CAT_LABEL[h.category] ?? h.category}·{h.type}: {h.original} → {h.masked}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-3 border-t border-gray-100 pt-3">
                <input value={meetingTitle} onChange={(e) => setMeetingTitle(e.target.value)}
                       placeholder="会议标题（可选）"
                       className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-800" />
                <button type="button" onClick={toMeetingMinutes} disabled={busy}
                        className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-700 disabled:opacity-50">
                  📝 用脱敏稿生成会议纪要
                </button>
                <button type="button" onClick={copyMasked}
                        className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">
                  复制脱敏稿
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default TranscriptDeskWizard;
