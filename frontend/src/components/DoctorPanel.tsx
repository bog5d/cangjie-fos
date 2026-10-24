import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";

interface DoctorResult {
  python_version: string;
  ffmpeg_available: boolean;
  data_dir_writable: boolean;
  port_8000_self: boolean;
  db_writable: boolean;
  env_exists: boolean;
  issues: string[];
  fix_suggestions: string[];
}

interface DoctorPanelProps {
  open: boolean;
  onClose: () => void;
}

function StatusRow({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2 py-1">
      <span className={ok ? "text-emerald-400" : "text-red-400"} aria-hidden="true">
        {ok ? "✅" : "❌"}
      </span>
      <span className="text-xs text-slate-300">{label}</span>
    </div>
  );
}

export function DoctorPanel({ open, onClose }: DoctorPanelProps) {
  const [data, setData] = useState<DoctorResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDiag = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.get<DoctorResult>("/api/v1/doctor");
      setData(r.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "请求失败，请确认后端已启动");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) void fetchDiag();
  }, [open, fetchDiag]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-4 pointer-events-none">
      {/* backdrop — pointer-events-auto 绑在有背景色元素上，避免 Chrome 透明外层拦截点击 */}
      <button
        type="button"
        className="absolute inset-0 bg-black/75 backdrop-blur-sm pointer-events-auto"
        aria-label="关闭系统诊断"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="系统诊断"
        className="relative w-full max-w-md rounded-2xl border border-slate-700 bg-[#0d0d1a] p-6 shadow-2xl pointer-events-auto"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-sm font-semibold uppercase tracking-widest text-cyan-400">
            系统诊断
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-500 hover:text-white transition text-lg leading-none"
            aria-label="关闭"
          >
            ✕
          </button>
        </div>

        {loading && (
          <p className="text-xs text-slate-400 text-center py-6">正在检测系统状态…</p>
        )}

        {error && (
          <p className="text-xs text-red-400 text-center py-4">{error}</p>
        )}

        {!loading && !error && data && (
          <>
            <div className="mb-4 space-y-0.5">
              <StatusRow ok={true} label={`后端运行中（端口 8000）`} />
              <StatusRow ok={data.ffmpeg_available} label="FFmpeg（语音转写）" />
              <StatusRow ok={data.data_dir_writable} label="data/ 目录可写" />
              <StatusRow ok={data.db_writable} label="SQLite 可写" />
              <StatusRow ok={data.env_exists} label="backend/.env 已配置" />
            </div>

            <div className="mb-3 rounded-lg bg-black/30 px-3 py-2">
              <p className="text-[10px] text-slate-500 font-mono truncate">
                {data.python_version.split(" ").slice(0, 2).join(" ")}
              </p>
            </div>

            {data.issues.length > 0 ? (
              <div className="space-y-3">
                <p className="text-xs font-semibold text-amber-300">
                  发现 {data.issues.length} 个问题：
                </p>
                {data.issues.map((issue, i) => (
                  <div key={i} className="rounded-lg border border-red-900/50 bg-red-950/30 p-3">
                    <p className="text-xs text-red-300">{issue}</p>
                    {data.fix_suggestions[i] && (
                      <p className="mt-1 text-[11px] text-slate-400">
                        → {data.fix_suggestions[i]}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-emerald-400 text-center py-1">
                ✅ 所有检查通过，系统就绪
              </p>
            )}

            <button
              type="button"
              onClick={() => void fetchDiag()}
              className="mt-4 w-full rounded-lg border border-slate-700 bg-white/5 px-3 py-2 text-xs text-slate-300 hover:bg-white/10 transition"
            >
              重新检测
            </button>
          </>
        )}
      </div>
    </div>
  );
}
