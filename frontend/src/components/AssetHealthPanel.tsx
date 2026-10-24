import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";

interface SceneItem {
  scene: string;
  count: number;
  pct: number;
}

interface TrendItem {
  snapshot_at: string;
  score: number;
  total_files: number;
}

interface HealthDashboard {
  score: number;
  coverage_score: number;
  vitality_score: number;
  total_files: number;
  missing_cats: string[];
  present_cats: string[];
  high_active: number;
  sleep_count: number;
  zombie_count: number;
  zombie_files: string[];
  scene_distribution: SceneItem[];
  trend: TrendItem[];
  has_data: boolean;
  snapshot_at?: string;
}

function ScoreRing({ score, label }: { score: number; label?: string }) {
  const color =
    score >= 80 ? "text-emerald-400" : score >= 50 ? "text-yellow-400" : "text-red-400";
  const ring =
    score >= 80 ? "border-emerald-500/60" : score >= 50 ? "border-yellow-500/60" : "border-red-500/60";
  return (
    <div className="flex flex-col items-center gap-1">
      <div className={`flex h-20 w-20 flex-shrink-0 items-center justify-center rounded-full border-4 ${ring} bg-black/30`}>
        <span className={`text-2xl font-bold tabular-nums ${color}`}>{score}</span>
      </div>
      {label && <span className="text-[10px] text-slate-500">{label}</span>}
    </div>
  );
}

function MiniBar({ pct, color = "bg-cyan-500/50" }: { pct: number; color?: string }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-white/10">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
      <span className="w-8 text-right text-[11px] tabular-nums text-slate-500">{pct}%</span>
    </div>
  );
}

export function AssetHealthPanel() {
  const [data, setData] = useState<HealthDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [snapshotting, setSnapshotting] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [zombieOpen, setZombieOpen] = useState(false);

  const fetchHealth = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<HealthDashboard>("/api/v1/assets/health");
      setData(res.data);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchHealth();
  }, [fetchHealth]);

  const takeSnapshot = useCallback(async () => {
    setSnapshotting(true);
    setMsg(null);
    try {
      const res = await api.post<{ score: number; indexed: number }>("/api/v1/assets/health/snapshot");
      setMsg(`快照完成，综合活力分：${res.data.score}`);
      void fetchHealth();
    } catch {
      setMsg("快照失败，请先完成一次扫描");
    } finally {
      setSnapshotting(false);
    }
  }, [fetchHealth]);

  if (loading) {
    return (
      <div className="mt-6 rounded-xl border border-white/10 bg-white/3 px-5 py-4 text-xs text-slate-500">
        加载活力雷达…
      </div>
    );
  }

  const noData = !data?.has_data;

  return (
    <div className="mt-6 rounded-xl border border-white/10 bg-white/3 p-5">
      {/* 标题栏 */}
      <div className="mb-4 flex items-center justify-between">
        <div>
          <p className="text-[10px] uppercase tracking-[0.35em] text-slate-500">资产活力雷达</p>
          {data?.snapshot_at && (
            <p className="mt-0.5 text-[11px] text-slate-600">
              {data.snapshot_at.replace("T", " ").slice(0, 19)} UTC
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => void takeSnapshot()}
          disabled={snapshotting}
          className="rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-xs text-slate-300 hover:border-white/30 disabled:opacity-50"
        >
          {snapshotting ? "计算中…" : "刷新快照"}
        </button>
      </div>

      {msg && <p className="mb-3 text-xs text-cyan-400/80">{msg}</p>}

      {noData ? (
        <p className="py-4 text-center text-xs text-slate-500">
          暂无快照 — 点「刷新快照」生成首次活力评分
        </p>
      ) : (
        <div className="space-y-5">

          {/* 第一行：分数环 + 分类覆盖 */}
          <div className="flex items-start gap-5">
            <ScoreRing score={data!.score} label="综合分" />
            <div className="flex flex-1 gap-4">
              <ScoreRing score={data!.coverage_score} label="完整度" />
              <ScoreRing score={data!.vitality_score} label="新鲜度" />
            </div>
          </div>

          {/* 分类覆盖 */}
          <div className="space-y-1">
            {data!.present_cats.length > 0 && (
              <p className="text-[11px] text-emerald-400/80">
                ✅ 已覆盖：{data!.present_cats.join("、")}
              </p>
            )}
            {data!.missing_cats.length > 0 ? (
              <p className="text-[11px] text-red-400/80">
                ❌ 缺失：{data!.missing_cats.join("、")}
              </p>
            ) : (
              <p className="text-[11px] text-emerald-400/80">🎉 全部分类已覆盖</p>
            )}
          </div>

          {/* 时效性：高活 / 休眠 / 僵尸 */}
          <div className="rounded-lg border border-white/8 bg-white/3 px-4 py-3">
            <p className="mb-2 text-[10px] uppercase tracking-widest text-slate-500">文件时效</p>
            <div className="grid grid-cols-3 gap-3 text-center">
              <div>
                <p className="text-lg font-bold text-emerald-400 tabular-nums">{data!.high_active}</p>
                <p className="text-[10px] text-slate-500">30天内更新</p>
              </div>
              <div>
                <p className="text-lg font-bold text-yellow-400 tabular-nums">{data!.sleep_count}</p>
                <p className="text-[10px] text-slate-500">休眠（31-90天）</p>
              </div>
              <div>
                <p className="text-lg font-bold text-red-400 tabular-nums">{data!.zombie_count}</p>
                <p className="text-[10px] text-slate-500">僵尸（&gt;90天）</p>
              </div>
            </div>
            {data!.zombie_count > 0 && (
              <div className="mt-3">
                <button
                  type="button"
                  onClick={() => setZombieOpen((v) => !v)}
                  className="text-[11px] text-slate-500 hover:text-slate-300"
                >
                  ⚠️ 僵尸文件清单（{data!.zombie_count} 项）{zombieOpen ? " ▲" : " ▼"}
                </button>
                {zombieOpen && (
                  <ul className="mt-2 max-h-32 overflow-y-auto space-y-0.5">
                    {data!.zombie_files.map((f) => (
                      <li key={f} className="text-[11px] text-slate-500 truncate pl-2">• {f}</li>
                    ))}
                    {data!.zombie_count > data!.zombie_files.length && (
                      <li className="text-[11px] text-slate-600 pl-2">…还有 {data!.zombie_count - data!.zombie_files.length} 项</li>
                    )}
                  </ul>
                )}
              </div>
            )}
          </div>

          {/* 场景分布 */}
          {data!.scene_distribution.length > 0 && (
            <div className="rounded-lg border border-white/8 bg-white/3 px-4 py-3">
              <p className="mb-2 text-[10px] uppercase tracking-widest text-slate-500">
                场景分布（按目录）
              </p>
              <div className="space-y-2">
                {data!.scene_distribution.map((s) => (
                  <div key={s.scene} className="flex items-center gap-2">
                    <span className="w-24 truncate text-[11px] text-slate-300">{s.scene}</span>
                    <div className="flex-1">
                      <MiniBar
                        pct={s.pct}
                        color={s.pct >= 40 ? "bg-cyan-500/50" : s.pct >= 20 ? "bg-purple-500/50" : "bg-white/20"}
                      />
                    </div>
                    <span className="w-6 text-right text-[11px] tabular-nums text-slate-600">{s.count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 趋势迷你条图 */}
          {data!.trend.length > 1 && (
            <div>
              <p className="mb-1.5 text-[10px] uppercase tracking-widest text-slate-600">近期趋势</p>
              <div className="flex items-end gap-1 h-10">
                {data!.trend
                  .slice()
                  .reverse()
                  .map((t, i) => {
                    const h = Math.max(4, Math.round((t.score / 100) * 40));
                    const color =
                      t.score >= 80 ? "bg-emerald-500/60" : t.score >= 50 ? "bg-yellow-500/60" : "bg-red-500/60";
                    return (
                      <div
                        key={i}
                        title={`${t.snapshot_at.slice(0, 10)}  ${t.score}分`}
                        className={`flex-1 rounded-sm ${color}`}
                        style={{ height: `${h}px` }}
                      />
                    );
                  })}
              </div>
            </div>
          )}

          <p className="text-[11px] text-slate-600">已索引 {data!.total_files} 个文件</p>
        </div>
      )}
    </div>
  );
}
