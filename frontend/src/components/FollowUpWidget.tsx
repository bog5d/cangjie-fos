/**
 * 待跟进行动项清单（Phase 7 P1）
 *
 * 从 GET /api/v1/follow-ups?tenant_id=X 获取未完成的路演后续行动项。
 * 支持一键标记已完成（PATCH /api/v1/follow-ups/{id}/done）。
 * 可折叠，默认收起。
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";

interface FollowUpItem {
  id: string;
  job_id: string;
  institution_id: string;
  actor: string;
  action: string;
  priority: string;
  source: string;
  done: number;
  created_at: number;
  done_at: number | null;
}

const PRIORITY_BADGE: Record<string, string> = {
  urgent: "bg-rose-500/20 text-rose-300 border-rose-500/30",
  normal: "bg-cyan/10 text-cyan border-cyan/30",
  optional: "bg-slate-600/30 text-slate-400 border-slate-600/30",
};

const PRIORITY_LABEL: Record<string, string> = {
  urgent: "紧急",
  normal: "正常",
  optional: "可选",
};

interface Props {
  tenantId: string;
}

export function FollowUpWidget({ tenantId }: Props) {
  const [items, setItems] = useState<FollowUpItem[]>([]);
  const [collapsed, setCollapsed] = useState(true);
  const [loading, setLoading] = useState(false);
  const [completing, setCompleting] = useState<Set<string>>(new Set());

  const fetchItems = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<FollowUpItem[]>("/api/v1/follow-ups", {
        params: { tenant_id: tenantId, limit: 30 },
      });
      setItems(data);
    } catch {
      // 静默失败：不影响主页
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void fetchItems();
  }, [fetchItems]);

  const handleDone = useCallback(
    async (id: string) => {
      setCompleting((s) => new Set([...s, id]));
      try {
        await api.patch(`/api/v1/follow-ups/${id}/done`);
        setItems((prev) => prev.filter((i) => i.id !== id));
      } catch {
        // ignore
      } finally {
        setCompleting((s) => {
          const next = new Set(s);
          next.delete(id);
          return next;
        });
      }
    },
    [],
  );

  // 没有待跟进项时不渲染
  if (items.length === 0 && !loading) return null;

  return (
    <section className="mt-6 rounded-2xl border border-amber-500/20 bg-amber-500/[0.04]">
      {/* header */}
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-3 text-left"
      >
        <div className="flex items-center gap-2">
          <span className="text-base">📋</span>
          <span className="font-display text-[11px] font-bold uppercase tracking-[0.3em] text-amber-200/80">
            待跟进行动项
          </span>
          {items.length > 0 && (
            <span className="rounded-full border border-amber-500/30 bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-bold text-amber-300">
              {items.length}
            </span>
          )}
        </div>
        <span className="text-slate-600 text-xs">{collapsed ? "▼ 展开" : "▲ 收起"}</span>
      </button>

      {!collapsed && (
        <div className="px-4 pb-4 space-y-2">
          {loading && (
            <p className="text-xs text-slate-500 px-1">加载中…</p>
          )}
          {items.map((item) => (
            <div
              key={item.id}
              className="flex items-start gap-3 rounded-xl border border-white/5 bg-black/20 px-3 py-2.5"
            >
              {/* 优先级 */}
              <span
                className={`shrink-0 inline-block rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${PRIORITY_BADGE[item.priority] ?? PRIORITY_BADGE.normal}`}
              >
                {PRIORITY_LABEL[item.priority] ?? item.priority}
              </span>

              {/* 内容 */}
              <div className="flex-1 min-w-0">
                <p className="text-xs text-slate-200 leading-snug">{item.action}</p>
                <div className="mt-1 flex items-center gap-2 flex-wrap">
                  {item.institution_id && (
                    <span className="text-[10px] text-slate-500">{item.institution_id}</span>
                  )}
                  {item.actor && item.actor !== "我方" && (
                    <span className="text-[10px] text-slate-600">负责：{item.actor}</span>
                  )}
                  <span
                    className={`text-[9px] rounded border px-1 py-0.5 ${
                      item.source === "commitment"
                        ? "border-amber-500/30 text-amber-400/70"
                        : "border-slate-600/30 text-slate-600"
                    }`}
                  >
                    {item.source === "commitment" ? "已承诺" : "建议"}
                  </span>
                </div>
              </div>

              {/* 完成按钮 */}
              <button
                type="button"
                disabled={completing.has(item.id)}
                onClick={() => void handleDone(item.id)}
                className="shrink-0 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-[10px] text-emerald-400 transition hover:bg-emerald-500/20 disabled:opacity-40"
              >
                {completing.has(item.id) ? "…" : "完成 ✓"}
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
