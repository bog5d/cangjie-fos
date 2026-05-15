import React, { useState, useCallback, useRef } from "react";

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

interface Props {
  open: boolean;
  onClose: () => void;
}

type Step = 1 | 2 | 3;

export default function DueDiligenceWizard({ open, onClose }: Props) {
  // Step 1 state
  const [folderPath, setFolderPath] = useState("");
  const [scanId, setScanId] = useState<string | null>(null);
  const [scanStatus, setScanStatus] = useState<string>("idle"); // idle | running | done | error
  const [scanResult, setScanResult] = useState<string>("");
  const pollRef = useRef<number | null>(null);

  // Step 2 state
  const [checklistText, setChecklistText] = useState("");
  const [checklistFile, setChecklistFile] = useState<File | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [parsing, setParsing] = useState(false);
  const [matchStatus, setMatchStatus] = useState<string>("idle"); // idle | running | done

  // Step 3 state
  const [items, setItems] = useState<DDItem[]>([]);
  const [exporting, setExporting] = useState(false);
  const [exportResult, setExportResult] = useState<string>("");
  const [outputDir, setOutputDir] = useState("");

  const [step, setStep] = useState<Step>(1);

  // ── Step 1: 扫描文件夹 ──────────────────────────────────────
  const handleScan = useCallback(async () => {
    if (!folderPath.trim()) return;
    setScanStatus("running");
    setScanResult("");

    const resp = await fetch("/api/v1/dd/index", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder_path: folderPath.trim(), tenant_id: "default" }),
    });
    const data = await resp.json();
    setScanId(data.scan_id);

    // 轮询进度
    pollRef.current = window.setInterval(async () => {
      const r = await fetch(`/api/v1/dd/index/status/${data.scan_id}`);
      const s = await r.json();
      if (s.status === "done") {
        clearInterval(pollRef.current!);
        setScanStatus("done");
        setScanResult(`✅ 扫描完成：共索引 ${s.indexed} 个文件，${s.failed} 个失败`);
      } else if (s.status === "error") {
        clearInterval(pollRef.current!);
        setScanStatus("error");
        setScanResult(`❌ 扫描失败：${s.error}`);
      }
    }, 1500);
  }, [folderPath]);

  // ── Step 2: 解析清单 + 触发匹配 ────────────────────────────
  const handleParseAndMatch = useCallback(async () => {
    setParsing(true);
    const formData = new FormData();
    formData.append("tenant_id", "default");
    formData.append("folder_root", folderPath.trim());
    if (checklistFile) {
      formData.append("file", checklistFile);
    } else {
      formData.append("text", checklistText);
    }

    const resp = await fetch("/api/v1/dd/sessions", { method: "POST", body: formData });
    const data = await resp.json();
    setSessionId(data.session_id);
    setParsing(false);

    // 触发匹配
    setMatchStatus("running");
    await fetch(`/api/v1/dd/sessions/${data.session_id}/match?folder_root=${encodeURIComponent(folderPath.trim())}`, {
      method: "POST",
    });

    // 轮询匹配（每2秒拉一次，最多30次）
    let attempts = 0;
    const pollMatch = window.setInterval(async () => {
      attempts++;
      const r = await fetch(`/api/v1/dd/sessions/${data.session_id}/items`);
      const itemList: DDItem[] = await r.json();
      const hasResults = itemList.some((i) => i.confidence !== null);
      if (hasResults || attempts >= 30) {
        clearInterval(pollMatch);
        setItems(itemList);
        setMatchStatus("done");
        setStep(3);
      }
    }, 2000);
  }, [folderPath, checklistFile, checklistText]);

  // ── Step 3: 审核 + 导出 ────────────────────────────────────
  const handleSkip = useCallback(async (itemId: string) => {
    if (!sessionId) return;
    await fetch(`/api/v1/dd/sessions/${sessionId}/items/${itemId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_skipped: true }),
    });
    setItems((prev) => prev.map((i) => i.id === itemId ? { ...i, user_skipped: 1 } : i));
  }, [sessionId]);

  const handleConfirm = useCallback(async (itemId: string) => {
    if (!sessionId) return;
    await fetch(`/api/v1/dd/sessions/${sessionId}/items/${itemId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_confirmed: true }),
    });
    setItems((prev) => prev.map((i) => i.id === itemId ? { ...i, user_confirmed: 1 } : i));
  }, [sessionId]);

  const handleExport = useCallback(async () => {
    if (!sessionId || !outputDir.trim()) return;
    setExporting(true);
    const resp = await fetch(`/api/v1/dd/sessions/${sessionId}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ output_dir: outputDir.trim() }),
    });
    const result = await resp.json();
    setExporting(false);
    setExportResult(`✅ 导出完成：${result.exported} 个文件已复制，${result.missing} 个缺失。文件夹：${result.output_path}`);
  }, [sessionId, outputDir]);

  // ── 置信度颜色 ──────────────────────────────────────────────
  const confidenceColor = (conf: number | null): string => {
    if (conf === null) return "bg-gray-100 text-gray-500";
    if (conf >= 0.8) return "bg-green-50 text-green-700";
    if (conf >= 0.5) return "bg-yellow-50 text-yellow-700";
    return "bg-red-50 text-red-600";
  };

  // 低置信度排前面
  const sortedItems = [...items].sort((a, b) => {
    const ca = a.confidence ?? 0;
    const cb = b.confidence ?? 0;
    if (a.user_confirmed !== b.user_confirmed) return a.user_confirmed - b.user_confirmed;
    return ca - cb;
  });

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" style={{ pointerEvents: "auto" }}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="text-lg font-semibold text-gray-800">📋 尽调响应台</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">✕</button>
        </div>

        {/* Step indicators */}
        <div className="flex px-6 py-3 gap-4 border-b bg-gray-50 text-sm">
          {[1, 2, 3].map((s) => (
            <div key={s} className={`flex items-center gap-1 ${step === s ? "text-blue-600 font-semibold" : "text-gray-400"}`}>
              <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs ${step === s ? "bg-blue-600 text-white" : step > s ? "bg-green-500 text-white" : "bg-gray-200"}`}>{step > s ? "✓" : s}</span>
              {s === 1 ? "扫描材料库" : s === 2 ? "上传清单" : "审核 & 导出"}
            </div>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5">

          {/* ── Step 1 ── */}
          {step === 1 && (
            <div className="space-y-4">
              <p className="text-sm text-gray-600">指定你的材料库文件夹路径（系统会扫描并建立索引，供后续匹配用）。</p>
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
              {scanResult && <p className={`text-sm ${scanStatus === "error" ? "text-red-500" : "text-green-600"}`}>{scanResult}</p>}
              {scanStatus === "done" && (
                <button onClick={() => setStep(2)} className="mt-2 px-4 py-2 bg-blue-600 text-white rounded text-sm">
                  下一步：上传清单 →
                </button>
              )}
            </div>
          )}

          {/* ── Step 2 ── */}
          {step === 2 && (
            <div className="space-y-4">
              <p className="text-sm text-gray-600">上传机构发来的尽调清单（支持 Excel/Word/PDF），或直接粘贴文字。</p>
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
              <div className="flex gap-2">
                <button onClick={() => setStep(1)} className="px-4 py-2 border rounded text-sm text-gray-600">← 上一步</button>
                <button
                  onClick={() => void handleParseAndMatch()}
                  disabled={parsing || matchStatus === "running" || (!checklistFile && !checklistText.trim())}
                  className="px-4 py-2 bg-blue-600 text-white rounded text-sm disabled:opacity-50"
                >
                  {parsing ? "解析中…" : matchStatus === "running" ? "AI 匹配中…" : "解析 & 开始匹配"}
                </button>
              </div>
            </div>
          )}

          {/* ── Step 3 ── */}
          {step === 3 && (
            <div className="space-y-4">
              <div className="flex items-center gap-3 text-sm text-gray-600">
                <span>共 <b>{items.length}</b> 条需求</span>
                <span className="text-green-600">🟢 高置信 {items.filter(i => (i.confidence ?? 0) >= 0.8).length}</span>
                <span className="text-yellow-600">🟡 待确认 {items.filter(i => (i.confidence ?? 0) >= 0.5 && (i.confidence ?? 0) < 0.8).length}</span>
                <span className="text-red-500">🔴 未匹配 {items.filter(i => (i.confidence ?? 0) < 0.5).length}</span>
              </div>

              <div className="border rounded overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 text-gray-500 text-xs">
                    <tr>
                      <th className="px-3 py-2 text-left w-8">#</th>
                      <th className="px-3 py-2 text-left">需求</th>
                      <th className="px-3 py-2 text-left">匹配文件</th>
                      <th className="px-3 py-2 text-center w-20">置信度</th>
                      <th className="px-3 py-2 text-center w-24">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedItems.map((item) => (
                      <tr key={item.id} className={`border-t ${item.user_skipped ? "opacity-40" : ""} ${confidenceColor(item.confidence)}`}>
                        <td className="px-3 py-2 text-gray-400">{item.item_no}</td>
                        <td className="px-3 py-2">
                          <div className="font-medium">{item.requirement}</div>
                          {item.category && <div className="text-xs text-gray-400">{item.category}</div>}
                        </td>
                        <td className="px-3 py-2">
                          {item.matched_filename
                            ? <span title={item.match_reason || ""}>{item.matched_filename}</span>
                            : <span className="text-gray-400 italic">无匹配</span>}
                        </td>
                        <td className="px-3 py-2 text-center">
                          {item.confidence !== null ? `${Math.round(item.confidence * 100)}%` : "—"}
                        </td>
                        <td className="px-3 py-2 text-center space-x-1">
                          {!item.user_skipped && !item.user_confirmed && (
                            <>
                              <button onClick={() => void handleConfirm(item.id)} className="text-xs px-2 py-0.5 bg-green-100 text-green-700 rounded">✓</button>
                              <button onClick={() => void handleSkip(item.id)} className="text-xs px-2 py-0.5 bg-red-100 text-red-600 rounded">缺</button>
                            </>
                          )}
                          {item.user_confirmed === 1 && <span className="text-xs text-green-600">已确认</span>}
                          {item.user_skipped === 1 && <span className="text-xs text-gray-400">标记缺失</span>}
                        </td>
                      </tr>
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
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
