import { useCallback, useState } from "react";
import { api } from "../api/client";

// ─── 类型 ─────────────────────────────────────────────────────────────────────

interface MatchCandidate {
  asset: { filename: string; relative_path: string; summary: string; tags: string[] };
  score: number;
  color: "green" | "yellow" | "red" | "gray";
  matched_fields: string[];
}

interface MatchResultRow {
  requirement: { description: string; scene_type: string; time_range: string };
  candidates: MatchCandidate[];
  color: string;
}

interface MatchSessionResponse {
  session_id: string;
  institution: string;
  req_count: number;
  results: MatchResultRow[];
}

// ─── 子组件 ──────────────────────────────────────────────────────────────────

const COLOR_BADGE: Record<string, string> = {
  green:  "border-emerald-500/60 bg-emerald-500/10 text-emerald-300",
  yellow: "border-yellow-500/60 bg-yellow-500/10 text-yellow-300",
  red:    "border-red-500/50 bg-red-500/10 text-red-300",
  gray:   "border-white/20 bg-white/5 text-slate-500",
};

const COLOR_LABEL: Record<string, string> = {
  green: "✅ 绿", yellow: "⚠️ 黄", red: "🔴 红", gray: "⬜ 灰",
};

function ColorBadge({ color }: { color: string }) {
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${COLOR_BADGE[color] ?? COLOR_BADGE.gray}`}>
      {COLOR_LABEL[color] ?? color}
    </span>
  );
}

function ResultRow({
  row,
  checked,
  onToggle,
}: {
  row: MatchResultRow;
  checked: boolean;
  onToggle: () => void;
}) {
  const best = row.candidates[0];
  return (
    <tr className="border-b border-white/5 transition hover:bg-white/5">
      <td className="py-2.5 pr-3 align-top">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          disabled={row.color === "gray"}
          className="accent-cyan-400"
        />
      </td>
      <td className="py-2.5 pr-4 align-top">
        <p className="text-sm text-white">{row.requirement.description}</p>
        {row.requirement.scene_type && (
          <p className="mt-0.5 text-[11px] text-slate-500">{row.requirement.scene_type}</p>
        )}
      </td>
      <td className="py-2.5 pr-4 align-top">
        <ColorBadge color={row.color} />
      </td>
      <td className="py-2.5 pr-4 align-top text-sm text-slate-300">
        {best ? best.asset.filename : <span className="text-slate-600">——</span>}
      </td>
      <td className="py-2.5 align-top text-xs text-slate-500 tabular-nums">
        {best ? `${Math.round(best.score * 100)}%` : "—"}
      </td>
    </tr>
  );
}

// ─── 主面板 ──────────────────────────────────────────────────────────────────

export function MatchMakerPanel() {
  const [institution, setInstitution] = useState("");
  const [reqText, setReqText] = useState("");
  const [session, setSession] = useState<MatchSessionResponse | null>(null);
  const [matching, setMatching] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmMsg, setConfirmMsg] = useState<string | null>(null);
  const [checkedRows, setCheckedRows] = useState<boolean[]>([]);

  const handleMatch = useCallback(async () => {
    if (!reqText.trim()) {
      setError("请粘贴尽调需求文本");
      return;
    }
    setMatching(true);
    setError(null);
    setConfirmMsg(null);
    setSession(null);
    try {
      const res = await api.post<MatchSessionResponse>("/api/v1/assets/match", {
        institution: institution.trim(),
        req_text: reqText.trim(),
        use_llm: false,
        top_n: 3,
      });
      setSession(res.data);
      setCheckedRows(
        res.data.results.map((r) => r.color === "green")
      );
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "匹配失败";
      setError(msg);
    } finally {
      setMatching(false);
    }
  }, [institution, reqText]);

  const handleConfirm = useCallback(async () => {
    if (!session) return;
    const confirmed = session.results
      .filter((_, i) => checkedRows[i])
      .flatMap((r) => r.candidates.slice(0, 1).map((c) => c.asset));

    setConfirming(true);
    setConfirmMsg(null);
    try {
      await api.post(`/api/v1/assets/match/${session.session_id}/confirm`, {
        confirmed_files: confirmed,
      });
      setConfirmMsg(`已确认 ${confirmed.length} 个文件`);
    } catch {
      setConfirmMsg("提交失败，请重试");
    } finally {
      setConfirming(false);
    }
  }, [session, checkedRows]);

  const toggleRow = useCallback((i: number) => {
    setCheckedRows((prev) => prev.map((v, idx) => (idx === i ? !v : v)));
  }, []);

  const checkedCount = checkedRows.filter(Boolean).length;

  return (
    <section className="mt-8 rounded-2xl border border-white/10 bg-white/3 p-6">
      <div className="mb-5">
        <h2 className="font-display text-lg font-bold text-white">尽调响应台</h2>
        <p className="mt-0.5 text-xs text-slate-500">
          粘贴机构发来的尽调需求 → 自动匹配资产库 → 四色确认 → 提交
        </p>
      </div>

      {/* 输入区 */}
      <div className="space-y-3">
        <input
          value={institution}
          onChange={(e) => setInstitution(e.target.value)}
          placeholder="机构名称（可选）"
          className="w-full rounded-xl border border-white/15 bg-black/40 px-3 py-2 text-sm text-white placeholder:text-slate-600 sm:max-w-xs"
        />
        <textarea
          value={reqText}
          onChange={(e) => setReqText(e.target.value)}
          placeholder={"粘贴尽调需求清单，每行一条，例如：\n1. 近三年审计报告\n2. 股权结构图\n3. 核心团队简历"}
          rows={6}
          className="w-full rounded-xl border border-white/15 bg-black/40 px-3 py-2 text-sm text-white placeholder:text-slate-600 focus:border-cyan/40 focus:outline-none"
        />
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void handleMatch()}
            disabled={matching}
            className="rounded-xl bg-cyan-600 px-5 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
          >
            {matching ? "匹配中…" : "解析并匹配"}
          </button>
          {session && (
            <button
              type="button"
              onClick={() => void handleConfirm()}
              disabled={confirming || checkedCount === 0}
              className="rounded-xl border border-cyan/40 px-5 py-2 text-sm text-cyan-300 hover:border-cyan-400 disabled:opacity-40"
            >
              {confirming ? "提交中…" : `提交确认（${checkedCount}）`}
            </button>
          )}
        </div>
        {error && <p className="text-xs text-red-400">{error}</p>}
        {confirmMsg && <p className="text-xs text-cyan-400/90">{confirmMsg}</p>}
      </div>

      {/* 结果表 */}
      {session && session.results.length > 0 && (
        <div className="mt-6 overflow-x-auto">
          <div className="mb-2 flex gap-4 text-xs text-slate-500">
            <span>共 {session.req_count} 条需求</span>
            <span className="text-emerald-400/80">
              ✅ 绿 {session.results.filter((r) => r.color === "green").length}
            </span>
            <span className="text-yellow-400/80">
              ⚠️ 黄 {session.results.filter((r) => r.color === "yellow").length}
            </span>
            <span className="text-red-400/80">
              🔴 红 {session.results.filter((r) => r.color === "red").length}
            </span>
            <span className="text-slate-600">
              ⬜ 灰 {session.results.filter((r) => r.color === "gray").length}
            </span>
          </div>
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-white/10 text-[11px] uppercase tracking-wider text-slate-500">
                <th className="pb-2 pr-3 w-8" />
                <th className="pb-2 pr-4">需求描述</th>
                <th className="pb-2 pr-4">状态</th>
                <th className="pb-2 pr-4">最佳匹配</th>
                <th className="pb-2">分数</th>
              </tr>
            </thead>
            <tbody>
              {session.results.map((row, i) => (
                <ResultRow
                  key={i}
                  row={row}
                  checked={checkedRows[i] ?? false}
                  onToggle={() => toggleRow(i)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
