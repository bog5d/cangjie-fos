import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";

interface NightlySuggestion {
  id: string;
  type: string;
  content: string;
  priority: number;
  created_at: number;
}

interface DigestResponse {
  suggestions: NightlySuggestion[];
  count: number;
}

function fmtDate(ts: number): string {
  try { return new Date(ts * 1000).toISOString().slice(0, 10); } catch { return "—"; }
}

const TYPE_LABEL: Record<string, string> = {
  material_update: "📝 素材更新",
  risk_pattern: "⚠️ 风险模式",
  institution_insight: "🏛 机构洞察",
};

export function DigestBanner() {
  const [suggestions, setSuggestions] = useState<NightlySuggestion[]>([]);
  const [dismissed, setDismissed] = useState(false);

  const load = useCallback(() => {
    void api.get<DigestResponse>("/api/v1/digest/pending")
      .then(r => setSuggestions(r.data.suggestions))
      .catch(() => {/* 静默 */});
  }, []);

  useEffect(() => { load(); }, [load]);

  const consume = useCallback(async (id: string) => {
    try {
      await api.post(`/api/v1/digest/${id}/consume`);
      setSuggestions(prev => prev.filter(s => s.id !== id));
    } catch {/* 静默 */}
  }, []);

  const consumeAll = useCallback(async () => {
    await Promise.all(suggestions.map(s => consume(s.id)));
    setDismissed(true);
  }, [suggestions, consume]);

  if (!suggestions.length || dismissed) return null;

  return (
    <div className="mb-6 rounded-2xl border border-cyan-500/20 bg-cyan-950/15 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-cyan-400">🌙</span>
          <p className="text-sm font-semibold text-white">昨晚系统更新了 {suggestions.length} 条知识</p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => void consumeAll()}
            className="rounded-lg border border-white/10 px-2.5 py-1 text-[11px] text-slate-400 hover:text-white"
          >
            全部已读
          </button>
          <button
            type="button"
            onClick={() => setDismissed(true)}
            className="text-xs text-slate-600 hover:text-slate-400"
          >
            ✕
          </button>
        </div>
      </div>

      <div className="space-y-2">
        {suggestions.map(s => (
          <div
            key={s.id}
            className="flex items-start gap-3 rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2.5"
          >
            <span className="mt-0.5 whitespace-nowrap text-xs text-slate-500">
              {TYPE_LABEL[s.type] ?? s.type}
            </span>
            <p className="flex-1 text-xs text-slate-300">{s.content}</p>
            <span className="whitespace-nowrap text-[10px] text-slate-600">
              {fmtDate(s.created_at)}
            </span>
            <button
              type="button"
              onClick={() => void consume(s.id)}
              className="whitespace-nowrap text-[10px] text-slate-600 hover:text-cyan-400"
            >
              已读 ✓
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
