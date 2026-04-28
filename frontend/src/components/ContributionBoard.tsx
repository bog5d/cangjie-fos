import { useEffect, useState } from "react";
import { api } from "../api/client";

interface ContributionScore {
  contributor: string;
  score: number;
  job_count: number;
}

interface ContributionsResponse {
  total: number;
  scores: ContributionScore[];
}

export function ContributionBoard({ tenantId, limit = 10 }: { tenantId?: string; limit?: number }) {
  const [data, setData] = useState<ContributionsResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams({ limit: String(limit) });
    if (tenantId) params.set("tenant_id", tenantId);
    api
      .get<ContributionsResponse>(`/api/contributions?${params.toString()}`)
      .then((res) => setData(res.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [tenantId, limit]);

  if (loading) {
    return (
      <div className="mt-6 rounded-2xl border border-white/10 bg-white/3 p-5">
        <p className="text-sm text-slate-500">加载贡献度排行榜…</p>
      </div>
    );
  }

  if (!data || data.total === 0) {
    return (
      <div className="mt-6 rounded-2xl border border-white/10 bg-white/3 p-5">
        <h3 className="mb-2 font-display text-base font-bold text-white">贡献度排行榜</h3>
        <p className="text-xs text-slate-500">暂无贡献数据，路演提交后自动积累。</p>
      </div>
    );
  }

  return (
    <div className="mt-6 rounded-2xl border border-white/10 bg-white/3 p-5">
      <h3 className="mb-3 font-display text-base font-bold text-white">
        贡献度排行榜
        <span className="ml-2 text-xs font-normal text-slate-500">共 {data.total} 位贡献者</span>
      </h3>
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-white/10 text-xs font-semibold uppercase tracking-wider text-slate-500">
            <th className="pb-2 pr-3 w-8">名次</th>
            <th className="pb-2 pr-3">贡献者</th>
            <th className="pb-2 pr-3 text-right">得分</th>
            <th className="pb-2 text-right">路演数</th>
          </tr>
        </thead>
        <tbody>
          {data.scores.map((item, idx) => (
            <tr key={item.contributor} className="border-b border-white/5 transition hover:bg-white/5">
              <td className="py-2 pr-3 text-slate-500 tabular-nums">
                {idx === 0 ? "🥇" : idx === 1 ? "🥈" : idx === 2 ? "🥉" : `${idx + 1}`}
              </td>
              <td className="py-2 pr-3 font-medium text-white">{item.contributor}</td>
              <td className="py-2 pr-3 text-right tabular-nums text-cyan-300">
                {item.score.toFixed(1)}
              </td>
              <td className="py-2 text-right tabular-nums text-slate-400">{item.job_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
