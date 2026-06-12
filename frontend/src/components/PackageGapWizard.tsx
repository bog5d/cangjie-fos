import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";

// ── 后端契约类型 ───────────────────────────────────────────────────────────────
type GapState = "have" | "update" | "missing" | "pending";

interface PackageItem {
  id: string;
  item_no: string;
  category: string;
  requirement: string;
  importance: "core" | "normal";
  matched_filename: string | null;
  confidence: number | null;
  match_reason: string | null;
  gap_state: GapState;
  draft_answer: string;
  user_fragments: string;
}

interface GapSummary {
  total: number;
  have: number;
  update: number;
  missing: number;
  pending: number;
  score: number;
  core_missing: number;
  by_category: Record<string, { have: number; update: number; missing: number; pending: number; total: number }>;
}

interface TemplateMeta {
  template_id: string;
  name: string;
  is_builtin: number;
  item_count: number;
}

interface TemplateRow {
  category: string;
  requirement: string;
  importance: "core" | "normal";
}

interface Props {
  open: boolean;
  onClose: () => void;
  tenantId: string;
}

type View = "setup" | "template" | "analyzing" | "results";

const STATE_META: Record<GapState, { label: string; cls: string; dot: string }> = {
  have: { label: "已有", cls: "text-emerald-700 bg-emerald-50 border-emerald-200", dot: "bg-emerald-500" },
  update: { label: "需更新", cls: "text-amber-700 bg-amber-50 border-amber-200", dot: "bg-amber-500" },
  missing: { label: "缺失", cls: "text-red-700 bg-red-50 border-red-200", dot: "bg-red-500" },
  pending: { label: "待分析", cls: "text-gray-500 bg-gray-50 border-gray-200", dot: "bg-gray-300" },
};

function scoreColor(s: number): string {
  if (s >= 80) return "text-emerald-600";
  if (s >= 60) return "text-amber-600";
  return "text-red-600";
}

function extractErr(e: unknown, fallback: string): string {
  if (e && typeof e === "object" && "response" in e) {
    const resp = (e as { response?: { data?: { detail?: string } } }).response;
    if (resp?.data?.detail) return resp.data.detail;
  }
  if (e instanceof Error) return e.message;
  return fallback;
}

export default function PackageGapWizard({ open, onClose, tenantId }: Props) {
  const [view, setView] = useState<View>("setup");
  const [folder, setFolder] = useState("");
  const [title, setTitle] = useState("");

  // 模板
  const [templates, setTemplates] = useState<TemplateMeta[]>([]);
  const [templateId, setTemplateId] = useState("standard");
  const [editRows, setEditRows] = useState<TemplateRow[]>([]);
  const [editingId, setEditingId] = useState("standard");

  // 会话/结果
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "analyzing" | "done" | "failed">("idle");
  const [summary, setSummary] = useState<GapSummary | null>(null);
  const [items, setItems] = useState<PackageItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [questions, setQuestions] = useState<string[]>([]);
  const [fragments, setFragments] = useState("");
  const [draft, setDraft] = useState("");
  const [dropped, setDropped] = useState<string[]>([]);
  const [usedExisting, setUsedExisting] = useState(false);
  const [synthing, setSynthing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [err, setErr] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollCount = useRef(0);

  const stopPoll = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  };
  useEffect(() => () => stopPoll(), []);

  const loadTemplates = useCallback(async () => {
    try {
      const r = await api.get<TemplateMeta[]>(`/api/v1/package/templates?tenant_id=${tenantId}`);
      setTemplates(r.data);
    } catch { /* ignore */ }
  }, [tenantId]);

  useEffect(() => {
    if (open) void loadTemplates();
  }, [open, loadTemplates]);

  const loadItems = useCallback(async (sid: string) => {
    try {
      const r = await api.get<PackageItem[]>(`/api/v1/package/sessions/${sid}/items`);
      setItems(r.data);
    } catch (e) {
      setErr(extractErr(e, "加载缺口明细失败"));
    }
  }, []);

  // ── 缺口分析 ────────────────────────────────────────────────────────────────
  const start = async () => {
    if (!folder.trim()) { setErr("请填写材料库文件夹路径"); return; }
    setErr("");
    setView("analyzing");
    setStatus("analyzing");
    setItems([]); setSummary(null); setActiveId(null);
    pollCount.current = 0;
    try {
      const r = await api.post<{ session_id: string }>("/api/v1/package/sessions", {
        folder_root: folder, tenant_id: tenantId, title, template_id: templateId,
      });
      const sid = r.data.session_id;
      setSessionId(sid);
      stopPoll();
      pollRef.current = setInterval(() => void poll(sid), 1500);
    } catch (e) {
      setView("setup");
      setStatus("failed");
      setErr(extractErr(e, "启动分析失败（材料库路径是否正确？）"));
    }
  };

  const poll = async (sid: string) => {
    pollCount.current += 1;
    if (pollCount.current > 120) {
      stopPoll(); setStatus("failed"); setView("results"); setErr("分析超时，请重试"); return;
    }
    try {
      const r = await api.get<{ status: string; summary: GapSummary }>(`/api/v1/package/sessions/${sid}/status`);
      setSummary(r.data.summary);
      if (r.data.status === "done" || r.data.status === "failed") {
        stopPoll();
        setStatus(r.data.status as "done" | "failed");
        setView("results");
        await loadItems(sid);
      }
    } catch { /* 瞬时错误忽略 */ }
  };

  const openItem = async (it: PackageItem) => {
    setActiveId(it.id);
    setQuestions([]); setFragments(it.user_fragments || ""); setDraft(it.draft_answer || "");
    setDropped([]); setUsedExisting(false);
    if (it.gap_state === "missing" || it.gap_state === "update") {
      try {
        const r = await api.post<{ questions: string[] }>(`/api/v1/package/items/${it.id}/questions`);
        setQuestions(r.data.questions);
      } catch { /* 引导问题失败不阻断 */ }
    }
  };

  const synthesize = async (itemId: string) => {
    if (!fragments.trim()) { setErr("请先把零碎信息/口述填进来"); return; }
    setErr(""); setSynthing(true);
    try {
      const r = await api.post<{ draft: string; dropped_numbers: string[]; used_existing?: boolean }>(
        `/api/v1/package/items/${itemId}/synthesize`, { fragments },
      );
      setDraft(r.data.draft);
      setDropped(r.data.dropped_numbers);
      setUsedExisting(!!r.data.used_existing);
      if (sessionId) void loadItems(sessionId);
    } catch (e) {
      setErr(extractErr(e, "合成失败"));
    } finally {
      setSynthing(false);
    }
  };

  const exportZip = async () => {
    if (!sessionId) return;
    setExporting(true);
    try {
      const r = await api.get(`/api/v1/package/sessions/${sessionId}/export`, { responseType: "blob" });
      const url = URL.createObjectURL(r.data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `数据包_${title || "导出"}.zip`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setErr(extractErr(e, "导出失败"));
    } finally {
      setExporting(false);
    }
  };

  // ── 模板在线编辑 ────────────────────────────────────────────────────────────
  const openEditor = async (id: string) => {
    setErr("");
    try {
      const r = await api.get<{ items: TemplateRow[] }>(`/api/v1/package/templates/${id}?tenant_id=${tenantId}`);
      setEditRows(r.data.items.map((it) => ({
        category: it.category, requirement: it.requirement, importance: it.importance,
      })));
      setEditingId(id);
      setView("template");
    } catch (e) {
      setErr(extractErr(e, "加载模板失败"));
    }
  };

  const saveTemplate = async () => {
    try {
      await api.put(`/api/v1/package/templates/${editingId}/items`, {
        tenant_id: tenantId, items: editRows,
      });
      await loadTemplates();
      setTemplateId(editingId);
      setView("setup");
    } catch (e) {
      setErr(extractErr(e, "保存模板失败（至少需要一条有效条目）"));
    }
  };

  const saveAsNew = async () => {
    const name = window.prompt("新模板命名（如：A轮精简包 / 并购尽调包）");
    if (!name) return;
    try {
      const r = await api.post<{ template_id: string }>("/api/v1/package/templates", {
        name, tenant_id: tenantId, copy_from: editingId,
      });
      await api.put(`/api/v1/package/templates/${r.data.template_id}/items`, {
        tenant_id: tenantId, items: editRows,
      });
      await loadTemplates();
      setTemplateId(r.data.template_id);
      setView("setup");
    } catch (e) {
      setErr(extractErr(e, "另存为失败"));
    }
  };

  const resetBuiltin = async () => {
    if (!window.confirm("把内置标准模板恢复为系统默认内容？你对它的修改将丢失。")) return;
    try {
      await api.post(`/api/v1/package/templates/standard/reset?tenant_id=${tenantId}`);
      await openEditor("standard");
    } catch (e) {
      setErr(extractErr(e, "恢复失败"));
    }
  };

  const reset = () => {
    stopPoll();
    setSessionId(null); setStatus("idle"); setItems([]); setSummary(null);
    setActiveId(null); setQuestions([]); setFragments(""); setDraft("");
    setView("setup");
  };

  if (!open) return null;

  const active = items.find((it) => it.id === activeId) || null;
  const grouped: Record<string, PackageItem[]> = {};
  for (const it of items) (grouped[it.category] ??= []).push(it);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div>
            <h2 className="text-lg font-bold text-gray-800">📦 数据包补全</h2>
            <p className="mt-0.5 text-xs text-gray-500">
              扫描材料库 → 对照标准模板找缺口 → 引导提问 → AI 合成材料 → 一键导出
            </p>
          </div>
          <button onClick={onClose} className="text-xl text-gray-400 hover:text-gray-600">✕</button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 text-gray-800">
          {err && (
            <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>
          )}

          {/* ── 入口：选模板 + 扫描 ── */}
          {view === "setup" && (
            <div className="space-y-3">
              <p className="text-sm text-gray-600">
                填入公司材料库文件夹，对照所选「标准数据包模板」逐项体检：哪些已有、哪些需更新、哪些还缺。
              </p>
              <div className="flex items-end gap-2">
                <label className="flex-1 text-xs text-gray-500">
                  使用模板
                  <select
                    value={templateId}
                    onChange={(e) => setTemplateId(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800"
                  >
                    {templates.map((t) => (
                      <option key={t.template_id} value={t.template_id}>
                        {t.name}（{t.item_count} 项）{t.is_builtin ? " · 内置" : ""}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  onClick={() => void openEditor(templateId)}
                  className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
                >
                  ✏️ 编辑/另存
                </button>
              </div>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="本次标题（可选，如：A轮数据包自检）"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800"
              />
              <input
                value={folder}
                onChange={(e) => setFolder(e.target.value)}
                placeholder="材料库文件夹路径，如 D:\\公司资料 或 /data/company"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800"
              />
              <button
                type="button"
                onClick={() => void start()}
                className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700"
              >
                开始扫描并分析缺口
              </button>
            </div>
          )}

          {/* ── 模板在线编辑 ── */}
          {view === "template" && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-gray-700">
                  编辑模板条目（{editRows.length} 项）
                </h3>
                <div className="flex gap-2 text-xs">
                  {editingId === "standard" && (
                    <button type="button" onClick={() => void resetBuiltin()} className="text-gray-400 hover:text-gray-600">
                      恢复默认
                    </button>
                  )}
                  <button type="button" onClick={() => setView("setup")} className="text-gray-400 hover:text-gray-600">
                    取消
                  </button>
                </div>
              </div>
              <div className="max-h-[48vh] space-y-1 overflow-y-auto">
                {editRows.map((row, i) => (
                  <div key={i} className="flex items-center gap-1.5">
                    <input
                      value={row.category}
                      onChange={(e) => setEditRows((rs) => rs.map((r, j) => j === i ? { ...r, category: e.target.value } : r))}
                      placeholder="维度"
                      className="w-24 rounded border border-gray-300 px-2 py-1 text-xs text-gray-800"
                    />
                    <input
                      value={row.requirement}
                      onChange={(e) => setEditRows((rs) => rs.map((r, j) => j === i ? { ...r, requirement: e.target.value } : r))}
                      placeholder="材料项"
                      className="flex-1 rounded border border-gray-300 px-2 py-1 text-xs text-gray-800"
                    />
                    <select
                      value={row.importance}
                      onChange={(e) => setEditRows((rs) => rs.map((r, j) => j === i ? { ...r, importance: e.target.value as "core" | "normal" } : r))}
                      className="rounded border border-gray-300 px-1 py-1 text-xs text-gray-800"
                    >
                      <option value="core">必备</option>
                      <option value="normal">应备</option>
                    </select>
                    <button
                      type="button"
                      onClick={() => setEditRows((rs) => rs.filter((_, j) => j !== i))}
                      className="px-1 text-gray-400 hover:text-red-500"
                    >✕</button>
                  </div>
                ))}
              </div>
              <button
                type="button"
                onClick={() => setEditRows((rs) => [...rs, { category: "", requirement: "", importance: "normal" }])}
                className="text-sm text-teal-600 hover:text-teal-800"
              >
                + 加一项
              </button>
              <div className="flex gap-2 border-t border-gray-100 pt-3">
                <button type="button" onClick={() => void saveTemplate()} className="rounded-lg bg-teal-600 px-4 py-2 text-sm text-white hover:bg-teal-700">
                  保存
                </button>
                <button type="button" onClick={() => void saveAsNew()} className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">
                  另存为新模板
                </button>
              </div>
            </div>
          )}

          {/* ── 分析中 ── */}
          {view === "analyzing" && (
            <div className="py-10 text-center">
              <div className="mb-3 text-3xl">🔍</div>
              <p className="text-sm text-gray-600">正在扫描材料库并逐项比对标准模板…</p>
              {summary && (
                <p className="mt-2 text-xs text-gray-400">已分析 {summary.total - summary.pending}/{summary.total} 项</p>
              )}
            </div>
          )}

          {/* ── 结果 ── */}
          {view === "results" && (
            <div className="space-y-4">
              {summary && (
                <>
                  <div className="flex flex-wrap items-center gap-4 rounded-xl border border-gray-200 p-3">
                    <div className="text-center">
                      <div className={`text-3xl font-bold ${scoreColor(summary.score)}`}>{summary.score}</div>
                      <div className="text-[11px] text-gray-400">完整度 /100</div>
                    </div>
                    <div className="flex flex-1 flex-wrap gap-2 text-sm">
                      <span className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1 text-emerald-700">已有 {summary.have}</span>
                      <span className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-1 text-amber-700">需更新 {summary.update}</span>
                      <span className="rounded-lg border border-red-200 bg-red-50 px-3 py-1 text-red-700">缺失 {summary.missing}</span>
                      <span className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-1 text-gray-500">共 {summary.total} 项</span>
                    </div>
                    <button
                      type="button"
                      disabled={exporting}
                      onClick={() => void exportZip()}
                      className="rounded-lg bg-teal-600 px-3 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50"
                    >
                      {exporting ? "导出中…" : "⬇ 导出数据包"}
                    </button>
                    <button type="button" onClick={reset} className="text-xs text-gray-400 hover:text-gray-600">← 换材料库</button>
                  </div>
                  {summary.core_missing > 0 && (
                    <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                      ⚠️ 投资人必看项还缺 <b>{summary.core_missing}</b> 个，建议优先补全（下方红点 + 「必备」标记项）。
                    </div>
                  )}
                </>
              )}

              <div className="grid gap-4 md:grid-cols-[1fr_1fr]">
                {/* 左：缺口清单 */}
                <div className="space-y-3 md:max-h-[50vh] md:overflow-y-auto">
                  {Object.entries(grouped).map(([cat, list]) => (
                    <div key={cat}>
                      <h4 className="mb-1 text-xs font-semibold text-gray-500">{cat}</h4>
                      <div className="space-y-1">
                        {list.map((it) => {
                          const meta = STATE_META[it.gap_state];
                          return (
                            <button
                              key={it.id}
                              type="button"
                              onClick={() => void openItem(it)}
                              className={`flex w-full items-center gap-2 rounded-lg border px-2 py-2 text-left text-sm transition ${
                                activeId === it.id ? "border-teal-400 bg-teal-50" : "border-gray-200 hover:bg-gray-50"
                              }`}
                            >
                              <span className={`h-2 w-2 shrink-0 rounded-full ${meta.dot}`} />
                              <span className="flex-1 text-gray-700">
                                {it.requirement}
                                {it.importance === "core" && <span className="ml-1 text-[10px] text-red-400">必备</span>}
                                {(it.draft_answer || "").trim() && <span className="ml-1 text-[10px] text-teal-500">·已起草</span>}
                              </span>
                              <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[11px] ${meta.cls}`}>{meta.label}</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>

                {/* 右：补全工作区 */}
                <div className="md:max-h-[50vh] md:overflow-y-auto">
                  {!active && (
                    <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-gray-200 p-6 text-center text-sm text-gray-400">
                      点左侧任意一项查看详情。<br />缺失/需更新的项可在这里引导补全。
                    </div>
                  )}
                  {active && (
                    <div className="space-y-3">
                      <div className="rounded-xl border border-gray-200 p-3">
                        <p className="text-sm font-medium text-gray-800">{active.requirement}</p>
                        <p className="mt-1 text-xs text-gray-500">
                          {STATE_META[active.gap_state].label}
                          {active.matched_filename && ` · 命中：${active.matched_filename}`}
                          {active.match_reason && ` · ${active.match_reason}`}
                        </p>
                      </div>
                      {active.gap_state === "have" ? (
                        <p className="text-sm text-emerald-700">✅ 这份材料已具备，无需补全。</p>
                      ) : (
                        <>
                          {active.gap_state === "update" && (
                            <p className="text-xs text-amber-700">
                              这份材料已有旧版本，合成时会自动带入旧材料正文，你只需补充「有什么变化/新数据」。
                            </p>
                          )}
                          {questions.length > 0 && (
                            <div className="rounded-xl border border-teal-200 bg-teal-50/60 p-3">
                              <p className="mb-1 text-xs font-semibold text-teal-800">先回答这几个问题：</p>
                              <ul className="list-inside list-disc space-y-0.5 text-sm text-gray-700">
                                {questions.map((q, i) => <li key={i}>{q}</li>)}
                              </ul>
                            </div>
                          )}
                          <textarea
                            value={fragments}
                            onChange={(e) => setFragments(e.target.value)}
                            placeholder="把零碎信息/口述填这里，AI 帮你整理成正式材料初稿…"
                            rows={5}
                            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800"
                          />
                          <button
                            type="button"
                            disabled={synthing}
                            onClick={() => void synthesize(active.id)}
                            className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50"
                          >
                            {synthing ? "合成中…" : "AI 合成材料初稿"}
                          </button>
                          {draft && (
                            <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
                              <p className="mb-1 text-xs font-semibold text-gray-500">
                                材料初稿（可复制后人工定稿）{usedExisting && " · 已并入旧材料正文"}
                              </p>
                              <pre className="whitespace-pre-wrap font-sans text-sm text-gray-800">{draft}</pre>
                              {dropped.length > 0 && (
                                <p className="mt-2 text-xs text-amber-700">
                                  ⚠️ 已自动剔除素材中找不到来源的数字（{dropped.join("、")}），避免 AI 编造，请人工核对补全。
                                </p>
                              )}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
