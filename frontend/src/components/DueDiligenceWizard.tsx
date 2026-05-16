import React, { useState, useCallback, useRef, useEffect } from "react";

interface DDItem {
  id: string;
  item_no: string;
  category: string;
  requirement: string;
  matched_file_path: string | null;
  matched_filename: string | null;
  confidence: number | null;
  match_reason: string | null;
  user_confirmed: number;
  user_skipped: number;
}

interface SessionSummary {
  session_id: string;
  checklist_name: string | null;
  institution_name: string;
  status: string;
  created_at: number;
  item_count: number;
  confirmed_count: number;
}

interface Props {
  open: boolean;
  onClose: () => void;
}

type Step = 1 | 2 | 3;

export default function DueDiligenceWizard({ open, onClose }: Props) {
  // Step 1 state
  const [folderPath, setFolderPath] = useState("");
  const [scanStatus, setScanStatus] = useState<string>("idle");
  const [scanResult, setScanResult] = useState<string>("");
  const pollRef = useRef<number | null>(null);

  // Session history
  const [recentSessions, setRecentSessions] = useState<SessionSummary[]>([]);

  // Step 2 state
  const [checklistText, setChecklistText] = useState("");
  const [checklistFile, setChecklistFile] = useState<File | null>(null);
  const [institutionName, setInstitutionName] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [parsing, setParsing] = useState(false);
  const [matchStatus, setMatchStatus] = useState<string>("idle");
  const [matchError, setMatchError] = useState<string>("");
  const pollMatchRef = useRef<number | null>(null);

  // Step 3 state
  const [items, setItems] = useState<DDItem[]>([]);
  const [bulkConfirming, setBulkConfirming] = useState(false);
  const [manualInputItem, setManualInputItem] = useState<string | null>(null);
  const [manualPath, setManualPath] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportResult, setExportResult] = useState<string>("");
  const [exportError, setExportError] = useState<string>("");
  const [outputDir, setOutputDir] = useState("");

  const [step, setStep] = useState<Step>(1);

  // ── 清理所有 interval（组件卸载时）──────────────────────────
  useEffect(() => {
    return () => {
      if (pollRef.current !== null) clearInterval(pollRef.current);
      if (pollMatchRef.current !== null) clearInterval(pollMatchRef.current);
    };
  }, []);

  // ── 向导打开时加载历史会话 ───────────────────────────────────
  useEffect(() => {
    if (!open) return;
    fetch("/api/v1/dd/sessions?tenant_id=default&limit=5")
      .then((r) => (r.ok ? r.json() : []))
      .then((data: SessionSummary[]) => setRecentSessions(data))
      .catch(() => {});
  }, [open]);

  // ── 恢复历史会话 ─────────────────────────────────────────────
  const handleRestoreSession = useCallback(async (sid: string) => {
    try {
      const r = await fetch(`/api/v1/dd/sessions/${sid}/items`);
      if (!r.ok) return;
      const itemList: DDItem[] = await r.json();
      setSessionId(sid);
      setItems(itemList);
      setMatchStatus("done");
      setStep(3);
    } catch (_) {}
  }, []);

  // ── Step 1: 扫描文件夹 ────────────────────────────────────────
  const handleScan = useCallback(async () => {
    if (!folderPath.trim()) return;
    setScanStatus("running");
    setScanResult("");
    let data: { scan_id: string };
    try {
      const resp = await fetch("/api/v1/dd/index", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ folder_path: folderPath.trim(), tenant_id: "default" }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        setScanStatus("error");
        setScanResult(`❌ 扫描请求失败：${err.detail || resp.statusText}`);
        return;
      }
      data = await resp.json();
    } catch (e) {
      setScanStatus("error");
      setScanResult(`❌ 网络错误：${e instanceof Error ? e.message : "请求失败"}`);
      return;
    }
    let attempts = 0;
    const MAX_SCAN = 120;
    pollRef.current = window.setInterval(async () => {
      attempts++;
      try {
        const r = await fetch(`/api/v1/dd/index/status/${data.scan_id}`);
        const s = await r.json();
        if (s.status === "done") {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setScanStatus("done");
          setScanResult(`✅ 扫描完成：共索引 ${s.indexed} 个文件，${s.failed} 个失败`);
        } else if (s.status === "error") {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setScanStatus("error");
          setScanResult(`❌ 扫描失败：${s.error}`);
        } else if (attempts >= MAX_SCAN) {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setScanStatus("error");
          setScanResult("❌ 扫描超时（超过3分钟），请检查文件夹或减少文件数量");
        }
      } catch (_) {}
    }, 1500);
  }, [folderPath]);

  // ── Step 2: 解析清单 + 触发匹配 ──────────────────────────────
  const handleParseAndMatch = useCallback(async () => {
    setParsing(true);
    setMatchError("");
    const formData = new FormData();
    formData.append("tenant_id", "default");
    formData.append("folder_root", folderPath.trim());
    formData.append("institution_name", institutionName.trim());
    if (checklistFile) {
      formData.append("file", checklistFile);
    } else {
      formData.append("text", checklistText);
    }
    let sessionData: { session_id: string };
    try {
      const resp = await fetch("/api/v1/dd/sessions", { method: "POST", body: formData });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        setParsing(false);
        setMatchError(`❌ 清单解析失败：${err.detail || resp.statusText}`);
        return;
      }
      sessionData = await resp.json();
    } catch (e) {
      setParsing(false);
      setMatchError(`❌ 网络错误：${e instanceof Error ? e.message : "请求失败"}`);
      return;
    }
    setSessionId(sessionData.session_id);
    setParsing(false);
    setMatchStatus("running");
    try {
      const matchResp = await fetch(
        `/api/v1/dd/sessions/${sessionData.session_id}/match?folder_root=${encodeURIComponent(folderPath.trim())}`,
        { method: "POST" }
      );
      if (!matchResp.ok) {
        setMatchStatus("error");
        setMatchError("❌ 触发匹配失败，请刷新后重试");
        return;
      }
    } catch (e) {
      setMatchStatus("error");
      setMatchError(`❌ 网络错误：${e instanceof Error ? e.message : "请求失败"}`);
      return;
    }
    let attempts = 0;
    const MAX_MATCH = 30;
    const sid = sessionData.session_id;
    pollMatchRef.current = window.setInterval(async () => {
      attempts++;
      try {
        const r = await fetch(`/api/v1/dd/sessions/${sid}/items`);
        if (!r.ok) {
          if (attempts >= MAX_MATCH) {
            clearInterval(pollMatchRef.current!);
            pollMatchRef.current = null;
            setMatchStatus("error");
            setMatchError("⚠️ AI 匹配超时，请检查材料库是否已扫描后重试");
          }
          return;
        }
        const itemList: DDItem[] = await r.json();
        const hasResults = itemList.some((i) => i.confidence !== null);
        if (hasResults || attempts >= MAX_MATCH) {
          clearInterval(pollMatchRef.current!);
          pollMatchRef.current = null;
          if (itemList.length === 0) {
            setMatchStatus("error");
            setMatchError("⚠️ 未解析到任何需求项，请检查清单格式后重试");
          } else {
            setItems(itemList);
            setMatchStatus("done");
            setStep(3);
          }
        }
      } catch (_) {
        if (attempts >= MAX_MATCH) {
          clearInterval(pollMatchRef.current!);
          pollMatchRef.current = null;
          setMatchStatus("error");
          setMatchError("❌ 网络连接中断，请检查服务是否在运行");
        }
      }
    }, 2000);
  }, [folderPath, checklistFile, checklistText, institutionName]);

  // ── Step 3: 批量确认 ──────────────────────────────────────────
  const handleBulkConfirm = useCallback(async () => {
    if (!sessionId) return;
    setBulkConfirming(true);
    try {
      const resp = await fetch(
        `/api/v1/dd/sessions/${sessionId}/items/bulk-confirm?min_confidence=0.8`,
        { method: "POST" }
      );
      if (!resp.ok) return;
      const r = await fetch(`/api/v1/dd/sessions/${sessionId}/items`);
      if (r.ok) setItems(await r.json());
    } catch (_) {
    } finally {
      setBulkConfirming(false);
    }
  }, [sessionId]);

  // ── Step 3: 手动指定文件 ──────────────────────────────────────
  const handleManualFile = useCallback(async (itemId: string) => {
    if (!sessionId || !manualPath.trim()) return;
    const parts = manualPath.trim().replace(/\\/g, "/").split("/");
    const filename = parts[parts.length - 1] || manualPath.trim();
    try {
      await fetch(`/api/v1/dd/sessions/${sessionId}/items/${itemId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          matched_file_path: manualPath.trim(),
          matched_filename: filename,
          confidence: 1.0,
        }),
      });
      setItems((prev) =>
        prev.map((i) =>
          i.id === itemId
            ? { ...i, matched_file_path: manualPath.trim(), matched_filename: filename, confidence: 1.0 }
            : i
        )
      );
      setManualInputItem(null);
      setManualPath("");
    } catch (_) {}
  }, [sessionId, manualPath]);

  // ── Step 3: 确认 / 标记缺失 ───────────────────────────────────
  const handleSkip = useCallback(async (itemId: string) => {
    if (!sessionId) return;
    try {
      await fetch(`/api/v1/dd/sessions/${sessionId}/items/${itemId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_skipped: true }),
      });
      setItems((prev) => prev.map((i) => (i.id === itemId ? { ...i, user_skipped: 1 } : i)));
    } catch (_) {}
  }, [sessionId]);

  const handleConfirm = useCallback(async (itemId: string) => {
    if (!sessionId) return;
    try {
      await fetch(`/api/v1/dd/sessions/${sessionId}/items/${itemId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_confirmed: true }),
      });
      setItems((prev) => prev.map((i) => (i.id === itemId ? { ...i, user_confirmed: 1 } : i)));
    } catch (_) {}
  }, [sessionId]);

  // ── Step 3: 导出 ──────────────────────────────────────────────
  const handleExport = useCallback(async () => {
    if (!sessionId || !outputDir.trim()) return;
    setExporting(true);
    setExportError("");
    try {
      const resp = await fetch(`/api/v1/dd/sessions/${sessionId}/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ output_dir: outputDir.trim() }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        setExportError(`❌ 导出失败：${err.detail || resp.statusText}`);
        return;
      }
      const result = await resp.json();
      setExportResult(
        `✅ 导出完成：${result.exported} 个文件已复制，${result.missing} 个缺失。文件夹：${result.output_path}`
      );
    } catch (e) {
      setExportError(`❌ 网络错误：${e instanceof Error ? e.message : "导出失败"}`);
    } finally {
      setExporting(false);
    }
  }, [sessionId, outputDir]);

  // ── 置信度颜色 ────────────────────────────────────────────────
  const confidenceColor = (conf: number | null): string => {
    if (conf === null) return "bg-gray-100 text-gray-500";
    if (conf >= 0.8) return "bg-green-50 text-green-700";
    if (conf >= 0.5) return "bg-yellow-50 text-yellow-700";
    return "bg-red-50 text-red-600";
  };

  const sortedItems = [...items].sort((a, b) => {
    if (a.user_confirmed !== b.user_confirmed) return a.user_confirmed - b.user_confirmed;
    return (a.confidence ?? 0) - (b.confidence ?? 0);
  });

  // 必须在所有 hooks 之后才能 early return
  if (!open) return null;

  const highConfCount = items.filter((i) => (i.confidence ?? 0) >= 0.8 && !i.user_confirmed && !i.user_skipped).length;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      style={{ pointerEvents: "auto" }}
    >
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="text-lg font-semibold text-gray-800">📋 尽调响应台</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">✕</button>
        </div>

        {/* Step indicators */}
        <div className="flex px-6 py-3 gap-4 border-b bg-gray-50 text-sm">
          {[1, 2, 3].map((s) => (
            <div
              key={s}
              className={`flex items-center gap-1 ${step === s ? "text-blue-600 font-semibold" : "text-gray-400"}`}
            >
              <span
                className={`w-6 h-6 rounded-full flex items-center justify-center text-xs ${
                  step === s ? "bg-blue-600 text-white" : step > s ? "bg-green-500 text-white" : "bg-gray-200"
                }`}
              >
                {step > s ? "✓" : s}
              </span>
              {s === 1 ? "扫描材料库" : s === 2 ? "上传清单" : "审核 & 导出"}
            </div>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5">

          {/* ── Step 1 ── */}
          {step === 1 && (
            <div className="space-y-4">
              <p className="text-sm text-gray-600">
                指定你的材料库文件夹路径（系统会扫描并建立索引，供后续匹配用）。
              </p>
              <div className="flex gap-2">
                <input
                  className="flex-1 border rounded px-3 py-2 text-sm"
                  placeholder="例如：D:\zt2025-01-17\资料包"
                  value={folderPath}
                  onChange={(e) => setFolderPath(e.target.value)}
                />
                <button
                  onClick={() => void handleScan()}
                  disabled={!folderPath.trim() || scanStatus === "running"}
                  className="px-4 py-2 bg-blue-600 text-white rounded text-sm disabled:opacity-50"
                >
                  {scanStatus === "running" ? "扫描中…" : "开始扫描"}
                </button>
              </div>
              {scanResult && (
                <p className={`text-sm ${scanStatus === "error" ? "text-red-500" : "text-green-600"}`}>
                  {scanResult}
                </p>
              )}
              {scanStatus === "done" && (
                <button
                  onClick={() => setStep(2)}
                  className="mt-2 px-4 py-2 bg-blue-600 text-white rounded text-sm"
                >
                  下一步：上传清单 →
                </button>
              )}

              {/* 历史会话列表 */}
              {recentSessions.length > 0 && (
                <div className="mt-4 border-t pt-4">
                  <p className="text-xs text-gray-500 mb-2">📂 历史会话（点击恢复）</p>
                  <div className="space-y-1">
                    {recentSessions.map((s) => (
                      <div
                        key={s.session_id}
                        className="flex items-center justify-between bg-gray-50 rounded px-3 py-2 text-sm"
                      >
                        <div>
                          <span className="font-medium text-gray-700">
                            {s.institution_name || s.checklist_name || "无名称"}
                          </span>
                          <span className="ml-2 text-gray-400 text-xs">
                            共{s.item_count}条 · 已确认{s.confirmed_count}条
                          </span>
                        </div>
                        <button
                          onClick={() => void handleRestoreSession(s.session_id)}
                          className="text-xs px-2 py-1 bg-indigo-100 text-indigo-700 rounded hover:bg-indigo-200"
                        >
                          恢复
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── Step 2 ── */}
          {step === 2 && (
            <div className="space-y-4">
              <p className="text-sm text-gray-600">
                上传机构发来的尽调清单（支持 Excel/Word/PDF），或直接粘贴文字。
              </p>

              {/* 机构名称（可选） */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  机构名称 <span className="text-gray-400 font-normal">（可选，自动更新 Pipeline 阶段为"尽调"）</span>
                </label>
                <input
                  className="w-full border rounded px-3 py-2 text-sm"
                  placeholder="例如：高瓴资本、IDG资本"
                  value={institutionName}
                  onChange={(e) => setInstitutionName(e.target.value)}
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">上传文件</label>
                <input
                  type="file"
                  accept=".xlsx,.xls,.docx,.doc,.pdf"
                  onChange={(e) => setChecklistFile(e.target.files?.[0] || null)}
                  className="block text-sm text-gray-600"
                />
              </div>
              <div className="flex items-center gap-2 text-gray-400 text-sm">
                <hr className="flex-1" /> 或 <hr className="flex-1" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">粘贴清单文字</label>
                <textarea
                  className="w-full border rounded px-3 py-2 text-sm h-32"
                  placeholder="直接粘贴机构发来的尽调需求列表文字…"
                  value={checklistText}
                  onChange={(e) => setChecklistText(e.target.value)}
                />
              </div>
              {matchError && (
                <p className="text-sm text-red-500 bg-red-50 border border-red-200 rounded px-3 py-2">
                  {matchError}
                </p>
              )}
              <div className="flex gap-2 flex-wrap">
                <button onClick={() => setStep(1)} className="px-4 py-2 border rounded text-sm text-gray-600">
                  ← 上一步
                </button>
                <button
                  onClick={() => void handleParseAndMatch()}
                  disabled={parsing || matchStatus === "running" || (!checklistFile && !checklistText.trim())}
                  className="px-4 py-2 bg-blue-600 text-white rounded text-sm disabled:opacity-50"
                >
                  {parsing ? "解析中…" : matchStatus === "running" ? "AI 匹配中…" : "解析 & 开始匹配"}
                </button>
                {matchStatus === "error" && (
                  <button
                    onClick={() => { setMatchStatus("idle"); setMatchError(""); }}
                    className="px-4 py-2 border rounded text-sm text-gray-600"
                  >
                    重置重试
                  </button>
                )}
              </div>
            </div>
          )}

          {/* ── Step 3 ── */}
          {step === 3 && (
            <div className="space-y-4">
              {/* 统计栏 + 批量操作 */}
              <div className="flex items-center gap-3 text-sm text-gray-600 flex-wrap">
                <span>共 <b>{items.length}</b> 条需求</span>
                <span className="text-green-600">
                  🟢 高置信 {items.filter((i) => (i.confidence ?? 0) >= 0.8).length}
                </span>
                <span className="text-yellow-600">
                  🟡 待确认 {items.filter((i) => (i.confidence ?? 0) >= 0.5 && (i.confidence ?? 0) < 0.8).length}
                </span>
                <span className="text-red-500">
                  🔴 未匹配 {items.filter((i) => (i.confidence ?? 0) < 0.5).length}
                </span>
                {highConfCount > 0 && (
                  <button
                    onClick={() => void handleBulkConfirm()}
                    disabled={bulkConfirming}
                    className="ml-auto px-3 py-1 bg-green-600 text-white rounded text-xs disabled:opacity-50 hover:bg-green-700"
                  >
                    {bulkConfirming ? "确认中…" : `✓ 一键确认高置信（${highConfCount}条）`}
                  </button>
                )}
              </div>

              <div className="border rounded overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 text-gray-500 text-xs">
                    <tr>
                      <th className="px-3 py-2 text-left w-8">#</th>
                      <th className="px-3 py-2 text-left">需求</th>
                      <th className="px-3 py-2 text-left">匹配文件</th>
                      <th className="px-3 py-2 text-center w-20">置信度</th>
                      <th className="px-3 py-2 text-center w-32">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedItems.map((item) => (
                      <React.Fragment key={item.id}>
                        <tr
                          className={`border-t ${item.user_skipped ? "opacity-40" : ""} ${confidenceColor(item.confidence)}`}
                        >
                          <td className="px-3 py-2 text-gray-400">{item.item_no}</td>
                          <td className="px-3 py-2">
                            <div className="font-medium">{item.requirement}</div>
                            {item.category && (
                              <div className="text-xs text-gray-400">{item.category}</div>
                            )}
                          </td>
                          <td className="px-3 py-2">
                            {item.matched_filename ? (
                              <span title={item.match_reason || ""}>{item.matched_filename}</span>
                            ) : (
                              <span className="text-gray-400 italic">无匹配</span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-center">
                            {item.confidence !== null ? `${Math.round(item.confidence * 100)}%` : "—"}
                          </td>
                          <td className="px-3 py-2 text-center space-x-1">
                            {!item.user_skipped && !item.user_confirmed && (
                              <>
                                <button
                                  onClick={() => void handleConfirm(item.id)}
                                  className="text-xs px-2 py-0.5 bg-green-100 text-green-700 rounded"
                                >
                                  ✓
                                </button>
                                <button
                                  onClick={() => void handleSkip(item.id)}
                                  className="text-xs px-2 py-0.5 bg-red-100 text-red-600 rounded"
                                >
                                  缺
                                </button>
                                {!item.matched_filename && (
                                  <button
                                    onClick={() => {
                                      setManualInputItem(item.id);
                                      setManualPath("");
                                    }}
                                    className="text-xs px-2 py-0.5 bg-blue-100 text-blue-700 rounded"
                                  >
                                    📂
                                  </button>
                                )}
                              </>
                            )}
                            {item.user_confirmed === 1 && (
                              <span className="text-xs text-green-600">已确认</span>
                            )}
                            {item.user_skipped === 1 && (
                              <span className="text-xs text-gray-400">标记缺失</span>
                            )}
                          </td>
                        </tr>
                        {/* 手动指定文件的内联输入行 */}
                        {manualInputItem === item.id && (
                          <tr className="border-t bg-blue-50">
                            <td colSpan={5} className="px-3 py-2">
                              <div className="flex gap-2 items-center">
                                <span className="text-xs text-blue-700 whitespace-nowrap">📂 文件路径：</span>
                                <input
                                  className="flex-1 border rounded px-2 py-1 text-xs"
                                  placeholder="例如：D:\资料包\财务\审计报告2023.pdf"
                                  value={manualPath}
                                  onChange={(e) => setManualPath(e.target.value)}
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter") void handleManualFile(item.id);
                                  }}
                                  autoFocus
                                />
                                <button
                                  onClick={() => void handleManualFile(item.id)}
                                  disabled={!manualPath.trim()}
                                  className="text-xs px-2 py-1 bg-blue-600 text-white rounded disabled:opacity-50"
                                >
                                  确认
                                </button>
                                <button
                                  onClick={() => setManualInputItem(null)}
                                  className="text-xs px-2 py-1 border rounded text-gray-500"
                                >
                                  取消
                                </button>
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex gap-2 items-center pt-2">
                <input
                  className="flex-1 border rounded px-3 py-2 text-sm"
                  placeholder="导出文件夹路径，例如：D:\尽调材料包\XX机构"
                  value={outputDir}
                  onChange={(e) => setOutputDir(e.target.value)}
                />
                <button
                  onClick={() => void handleExport()}
                  disabled={exporting || !outputDir.trim()}
                  className="px-4 py-2 bg-blue-600 text-white rounded text-sm disabled:opacity-50"
                >
                  {exporting ? "导出中…" : "导出文件夹"}
                </button>
              </div>
              {exportResult && <p className="text-sm text-green-600">{exportResult}</p>}
              {exportError && <p className="text-sm text-red-500">{exportError}</p>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
