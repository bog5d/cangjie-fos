import React, { useState, useCallback, useRef, useEffect } from "react";

interface Candidate {
  file_path: string;
  filename: string;
  confidence: number;
  reason: string;
}

interface DDItem {
  id: string;
  item_no: string;
  category: string;
  requirement: string;
  field_kind: string;
  matched_file_path: string | null;
  matched_filename: string | null;
  confidence: number | null;
  match_reason: string | null;
  draft_answer: string;
  user_confirmed: number;
  user_skipped: number;
  candidates_json: string | null;
  extra_files_json: string | null;
  is_encrypted?: number;
  unlock_password?: string;
  verdict?: string | null;
  evidence?: string | null;
}

type Scenario = "dd" | "post_investment";

interface SessionSummary {
  session_id: string;
  checklist_name: string | null;
  institution_name: string;
  status: string;
  created_at: number;
  item_count: number;
  confirmed_count: number;
  scenario?: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  /** 从轻量匹配器升级时预填的清单文本 */
  initialChecklistText?: string;
  /** 从轻量匹配器升级时预填的机构名称 */
  initialInstitution?: string;
}

type Step = 1 | 2 | 3;

/** 调用后端原生文件夹选取框，返回路径字符串（取消则返回空串）。 */
async function pickFolder(initialDir = ""): Promise<string> {
  const params = initialDir ? `?initial_dir=${encodeURIComponent(initialDir)}` : "";
  const r = await fetch(`/api/v1/dd/pick-folder${params}`);
  if (!r.ok) return "";
  const data: { path: string; cancelled: boolean } = await r.json();
  return data.cancelled ? "" : data.path;
}

/** 调用后端原生文件选取框，返回路径字符串（取消则返回空串）。 */
async function pickFile(initialDir = ""): Promise<string> {
  const params = initialDir ? `?initial_dir=${encodeURIComponent(initialDir)}` : "";
  const r = await fetch(`/api/v1/dd/pick-file${params}`);
  if (!r.ok) return "";
  const data: { path: string; cancelled: boolean } = await r.json();
  return data.cancelled ? "" : data.path;
}

export default function DueDiligenceWizard({ open, onClose, initialChecklistText, initialInstitution }: Props) {
  // Step 1 state
  const [folderPath, setFolderPath] = useState("");
  const [scanStatus, setScanStatus] = useState<string>("idle");
  const [scanResult, setScanResult] = useState<string>("");
  const [layoutInfo, setLayoutInfo] = useState<{ layout: string; institutionCount: number } | null>(null);
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
  const [matchProgress, setMatchProgress] = useState<{ done: number; total: number } | null>(null);
  const [matchStage, setMatchStage] = useState<string>("");
  const pollMatchRef = useRef<number | null>(null);

  // Step 3 state
  const [items, setItems] = useState<DDItem[]>([]);
  const [bulkConfirming, setBulkConfirming] = useState(false);
  const [expandedCandidates, setExpandedCandidates] = useState<string | null>(null);
  const [manualInputItem, setManualInputItem] = useState<string | null>(null);
  const [manualPath, setManualPath] = useState("");
  const [pwdInputItem, setPwdInputItem] = useState<string | null>(null);
  const [pwdDraft, setPwdDraft] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportResult, setExportResult] = useState<string>("");
  const [exportError, setExportError] = useState<string>("");
  const [outputDir, setOutputDir] = useState("");
  const [byQuestionMode, setByQuestionMode] = useState(false);
  const [folderNames, setFolderNames] = useState<Record<string, string>>({});
  const [extraSelections, setExtraSelections] = useState<Record<string, Set<string>>>({});
  // F4 历史问答复用
  const [qaExtracting, setQaExtracting] = useState(false);
  const [qaExtractMsg, setQaExtractMsg] = useState("");
  const [draftItem, setDraftItem] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, { text: string; matched: boolean; confidence: number; source: string }>>({});
  const [draftLoading, setDraftLoading] = useState(false);
  const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(new Set());

  const [step, setStep] = useState<Step>(1);
  const [scenario, setScenario] = useState<Scenario>("dd");
  const [reportOutputPath, setReportOutputPath] = useState("");
  const [reportExporting, setReportExporting] = useState(false);
  const [reportExportResult, setReportExportResult] = useState("");
  const [reportExportError, setReportExportError] = useState("");

  // ── 清理所有 interval（组件卸载时）──────────────────────────
  useEffect(() => {
    return () => {
      if (pollRef.current !== null) clearInterval(pollRef.current);
      if (pollMatchRef.current !== null) clearInterval(pollMatchRef.current);
    };
  }, []);

  // ── 向导打开时加载历史会话 + 预填来自轻量匹配器的数据 ───────────
  useEffect(() => {
    if (!open) return;
    fetch("/api/v1/dd/sessions?tenant_id=default&limit=5")
      .then((r) => (r.ok ? r.json() : []))
      .then((data: SessionSummary[]) => setRecentSessions(data))
      .catch(() => {});
    if (initialChecklistText) {
      // 从轻量匹配器"升级"进来：预填清单文本和机构名，跳到 Step 2
      setChecklistText(initialChecklistText);
      if (initialInstitution) setInstitutionName(initialInstitution);
      setStep(2);
    } else {
      // 正常打开：重置到 Step 1，避免残留上次进度
      setStep(1);
    }
  }, [open, initialChecklistText, initialInstitution]);

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
    setLayoutInfo(null);
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
    // 最多等 10 分钟（400 × 1.5s）—— 大文件夹（3000+文件）跳过 LLM 后仍需数分钟 IO
    const MAX_SCAN = 400;
    pollRef.current = window.setInterval(async () => {
      attempts++;
      try {
        const r = await fetch(`/api/v1/dd/index/status/${data.scan_id}`);
        const s = await r.json();
        if (s.status === "done") {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setScanStatus("done");
          const llmNote = s.total > 200 ? "（文件数较多，已跳过AI摘要，仅靠文件名匹配）" : "";
          setScanResult(`✅ 扫描完成：共索引 ${s.indexed} 个文件，${s.failed} 个失败${llmNote}`);
          if (s.folder_layout) {
            setLayoutInfo({ layout: s.folder_layout, institutionCount: s.institution_count ?? 0 });
          }
        } else if (s.status === "error") {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setScanStatus("error");
          setScanResult(`❌ 扫描失败：${s.error}`);
        } else if (attempts >= MAX_SCAN) {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setScanStatus("error");
          setScanResult("❌ 扫描超时（超过10分钟），请检查文件夹路径是否正确");
        } else if (s.done !== undefined && s.total !== undefined && s.total > 0) {
          // 展示实时进度
          const pct = Math.round((s.done / s.total) * 100);
          setScanResult(`⏳ 扫描中… ${s.done}/${s.total} 文件 (${pct}%)`);
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
    formData.append("scenario", scenario);
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
    setMatchProgress(null);
    setMatchStage("matching");
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
    const MAX_MATCH = 120;  // 最多等 4 分钟（120 × 2s）
    const sid = sessionData.session_id;
    pollMatchRef.current = window.setInterval(async () => {
      attempts++;
      try {
        // 先拉进度（不等 items 全部完成）
        const progressResp = await fetch(`/api/v1/dd/sessions/${sid}/match-status`);
        if (progressResp.ok) {
          const ps: { status: string; done: number; total: number; stage?: string } = await progressResp.json();
          if (ps.total > 0) {
            setMatchProgress({ done: ps.done, total: ps.total });
          }
          if (ps.stage) setMatchStage(ps.stage);
          if (ps.status === "done") {
            clearInterval(pollMatchRef.current!);
            pollMatchRef.current = null;
            // 拉最终结果
            const r = await fetch(`/api/v1/dd/sessions/${sid}/items`);
            if (!r.ok) {
              setMatchStatus("error");
              setMatchError("⚠️ 匹配完成但加载结果失败，请刷新后重试");
              return;
            }
            const itemList: DDItem[] = await r.json();
            if (itemList.length === 0) {
              setMatchStatus("error");
              setMatchError("⚠️ 未解析到任何需求项，请检查清单格式后重试");
            } else {
              setItems(itemList);
              setMatchStatus("done");
              setMatchProgress(null);
              setStep(3);
            }
            return;
          }
        }
        // 降级：match-status 不可用时回退到查 items 是否有结果
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
            setMatchProgress(null);
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
  }, [folderPath, checklistFile, checklistText, institutionName, scenario]);

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

  // ── Step 3: 选用备选候选 ──────────────────────────────────────
  const handleSelectCandidate = useCallback(async (itemId: string, cand: Candidate) => {
    if (!sessionId) return;
    try {
      await fetch(`/api/v1/dd/sessions/${sessionId}/items/${itemId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          matched_file_path: cand.file_path,
          matched_filename: cand.filename,
          confidence: cand.confidence,
        }),
      });
      setItems((prev) =>
        prev.map((i) =>
          i.id === itemId
            ? { ...i, matched_file_path: cand.file_path, matched_filename: cand.filename, confidence: cand.confidence, match_reason: cand.reason }
            : i
        )
      );
      setExpandedCandidates(null);
    } catch (_) {}
  }, [sessionId]);

  // ── Step 3: 多文件附加（F2）──────────────────────────────────
  /** 勾选/取消勾选某候选作为「附加文件」（一条需求对应多份材料）。 */
  const toggleExtraFile = useCallback((itemId: string, filePath: string) => {
    setExtraSelections((prev) => {
      const cur = new Set(prev[itemId] ?? []);
      if (cur.has(filePath)) cur.delete(filePath); else cur.add(filePath);
      return { ...prev, [itemId]: cur };
    });
  }, []);

  /** 把勾选的候选写入 extra_files_json，导出时随主文件一起拷入同一文件夹。 */
  const handleSaveExtraFiles = useCallback(async (item: DDItem) => {
    if (!sessionId) return;
    const cands: Candidate[] = item.candidates_json ? JSON.parse(item.candidates_json) : [];
    const checked = extraSelections[item.id] ?? new Set<string>();
    const extras = cands
      .filter((c) => checked.has(c.file_path) && c.file_path !== item.matched_file_path)
      .map((c) => ({ file_path: c.file_path, filename: c.filename }));
    const extraJson = JSON.stringify(extras);
    try {
      await fetch(`/api/v1/dd/sessions/${sessionId}/items/${item.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ extra_files_json: extraJson }),
      });
      setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, extra_files_json: extraJson } : i)));
      setExpandedCandidates(null);
    } catch (_) {}
  }, [sessionId, extraSelections]);

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

  // ── Step 3: 为加密文件登记密码（gk F3，UI 收集，导出原样附带）───
  const handleSavePassword = useCallback(async (item: DDItem) => {
    if (!item.matched_file_path) return;
    try {
      const resp = await fetch("/api/v1/dd/index/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_path: item.matched_file_path, password: pwdDraft }),
      });
      if (!resp.ok) return;
      setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, unlock_password: pwdDraft } : i)));
      setPwdInputItem(null);
      setPwdDraft("");
    } catch (_) {}
  }, [pwdDraft]);

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

  // ── Step 3: 按问题归档导出（F2/F5）─────────────────────────────
  /** 进入命名确认：用「问题NN_需求」预填每条有匹配项的文件夹名。 */
  const enterByQuestionMode = useCallback(() => {
    const defaults: Record<string, string> = {};
    for (const it of items) {
      if (it.matched_filename && !it.user_skipped) {
        defaults[it.id] = `问题${it.item_no}_${it.requirement}`.slice(0, 40);
      }
    }
    setFolderNames(defaults);
    setByQuestionMode(true);
  }, [items]);

  const handleExportByQuestion = useCallback(async () => {
    if (!sessionId || !outputDir.trim()) return;
    setExporting(true);
    setExportError("");
    try {
      const resp = await fetch(`/api/v1/dd/sessions/${sessionId}/export-by-question`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ output_dir: outputDir.trim(), folder_name_overrides: folderNames }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        setExportError(`❌ 导出失败：${err.detail || resp.statusText}`);
        return;
      }
      const result = await resp.json();
      setExportResult(
        `✅ 按问题归档完成：${result.exported} 个文件，${result.missing} 条缺失。文件夹：${result.output_path}`
      );
      setByQuestionMode(false);
    } catch (e) {
      setExportError(`❌ 网络错误：${e instanceof Error ? e.message : "导出失败"}`);
    } finally {
      setExporting(false);
    }
  }, [sessionId, outputDir, folderNames]);

  // ── Step 3: F4 历史问答复用 ───────────────────────────────────
  /** 从材料库的「补充/问答/答复」类文件扒取历史问答对，存入知识库。 */
  const handleExtractQA = useCallback(async () => {
    if (!folderPath.trim()) { setQaExtractMsg("⚠️ 缺少材料库路径，无法扒取"); return; }
    setQaExtracting(true);
    setQaExtractMsg("");
    try {
      const resp = await fetch("/api/v1/dd/qa/extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ folder_root: folderPath.trim(), tenant_id: "default" }),
      });
      if (!resp.ok) { setQaExtractMsg("❌ 扒取失败，请重试"); return; }
      const r = await resp.json();
      setQaExtractMsg(`✅ 已从历史资料扒取 ${r.extracted} 条问答，可点各需求「💬 草稿」生成答复`);
    } catch (e) {
      setQaExtractMsg(`❌ 网络错误：${e instanceof Error ? e.message : "扒取失败"}`);
    } finally {
      setQaExtracting(false);
    }
  }, [folderPath]);

  /** 为某需求生成答复草稿（命中历史问答带出答案+置信度，无命中留空待人工）。 */
  const handleLoadDraft = useCallback(async (item: DDItem) => {
    if (draftItem === item.id) { setDraftItem(null); return; }
    setDraftItem(item.id);
    if (drafts[item.id]) return;  // 已加载过，直接展开
    setDraftLoading(true);
    try {
      const params = new URLSearchParams({ requirement: item.requirement, folder_root: folderPath.trim() });
      const resp = await fetch(`/api/v1/dd/qa/draft?${params.toString()}`);
      if (!resp.ok) return;
      const d: { matched: boolean; answer: string; confidence: number; source_question: string } = await resp.json();
      setDrafts((prev) => ({
        ...prev,
        [item.id]: { text: d.answer, matched: d.matched, confidence: d.confidence, source: d.source_question },
      }));
    } catch (_) {
    } finally {
      setDraftLoading(false);
    }
  }, [draftItem, drafts, folderPath]);

  // ── 切换场景（重置向导状态）────────────────────────────────────
  const handleScenarioChange = useCallback((s: Scenario) => {
    setScenario(s);
    setStep(1);
    setSessionId(null);
    setItems([]);
    setMatchStatus("idle");
    setMatchError("");
    setChecklistText("");
    setChecklistFile(null);
    setReportOutputPath("");
    setReportExportResult("");
    setReportExportError("");
  }, []);

  // ── Step 3 (投后): 导出季报初稿 ────────────────────────────────
  const handleExportReport = useCallback(async () => {
    if (!sessionId || !reportOutputPath.trim()) return;
    setReportExporting(true);
    setReportExportError("");
    try {
      const resp = await fetch(`/api/v1/dd/sessions/${sessionId}/export-report`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ output_path: reportOutputPath.trim() }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        setReportExportError(`❌ 导出失败：${err.detail || resp.statusText}`);
        return;
      }
      const result = await resp.json();
      setReportExportResult(
        `✅ 季报初稿已生成：已填 ${result.filled}/${result.total} 个空格。路径：${result.output_path}`
      );
    } catch (e) {
      setReportExportError(`❌ 网络错误：${e instanceof Error ? e.message : "导出失败"}`);
    } finally {
      setReportExporting(false);
    }
  }, [sessionId, reportOutputPath]);


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
          <div className="flex items-center gap-4">
            <h2 className="text-lg font-semibold text-gray-800">
              {scenario === "post_investment" ? "📄 投后响应台" : "📋 尽调响应台"}
            </h2>
            {/* 场景切换 */}
            <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm">
              <button
                onClick={() => handleScenarioChange("dd")}
                className={`px-3 py-1.5 transition-colors ${
                  scenario === "dd"
                    ? "bg-blue-600 text-white font-medium"
                    : "bg-white text-gray-600 hover:bg-gray-50"
                }`}
              >
                尽调
              </button>
              <button
                onClick={() => handleScenarioChange("post_investment")}
                className={`px-3 py-1.5 border-l border-gray-200 transition-colors ${
                  scenario === "post_investment"
                    ? "bg-blue-600 text-white font-medium"
                    : "bg-white text-gray-600 hover:bg-gray-50"
                }`}
              >
                投后
              </button>
            </div>
          </div>
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
              {s === 1
                ? "扫描材料库"
                : s === 2
                  ? scenario === "post_investment" ? "上传季报模板" : "上传清单"
                  : scenario === "post_investment" ? "填充审核 & 导出" : "审核 & 导出"}
            </div>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5">

          {/* ── Step 1 ── */}
          {step === 1 && (
            <div className="space-y-4">
              <p className="text-sm text-gray-600">
                选择你的材料库文件夹（系统会扫描并建立索引，供后续匹配用）。
              </p>
              <div className="flex gap-2">
                <input
                  className="flex-1 border rounded px-3 py-2 text-sm text-gray-900"
                  placeholder="点击「📁 选择文件夹」或手动输入路径"
                  value={folderPath}
                  onChange={(e) => setFolderPath(e.target.value)}
                />
                <button
                  onClick={async () => {
                    const p = await pickFolder(folderPath);
                    if (p) setFolderPath(p);
                  }}
                  disabled={scanStatus === "running"}
                  className="px-3 py-2 bg-gray-100 text-gray-700 border rounded text-sm hover:bg-gray-200 disabled:opacity-50 whitespace-nowrap"
                >
                  📁 选择文件夹
                </button>
                <button
                  onClick={() => void handleScan()}
                  disabled={!folderPath.trim() || scanStatus === "running"}
                  className="px-4 py-2 bg-blue-600 text-white rounded text-sm disabled:opacity-50 whitespace-nowrap"
                >
                  {scanStatus === "running" ? "扫描中…" : "开始扫描"}
                </button>
              </div>
              {scanResult && (
                <p className={`text-sm ${scanStatus === "error" ? "text-red-500" : "text-green-600"}`}>
                  {scanResult}
                </p>
              )}
              {layoutInfo && scanStatus === "done" && (
                <div className="flex items-center gap-2 text-sm">
                  {layoutInfo.layout === "per_institution" ? (
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-indigo-100 text-indigo-700 text-xs font-medium">
                      🏢 按机构分类 · {layoutInfo.institutionCount} 家机构
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-gray-100 text-gray-600 text-xs font-medium">
                      📄 平铺材料库
                    </span>
                  )}
                </div>
              )}
              {scanStatus === "done" && (
                <button
                  onClick={() => setStep(2)}
                  className="mt-2 px-4 py-2 bg-blue-600 text-white rounded text-sm"
                >
                  {scenario === "post_investment" ? "下一步：上传季报模板 →" : "下一步：上传清单 →"}
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
                {scenario === "post_investment"
                  ? "上传投后季报模板（支持 Word/PDF/文字），系统将提取所有【】空格和填写项。"
                  : "上传机构发来的尽调清单（支持 Excel/Word/PDF），或直接粘贴文字。"}
              </p>

              {/* 机构名称（影响飞轮学习效果，建议填写） */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  机构名称
                  {!institutionName.trim() && (
                    <span className="ml-1 text-amber-500 font-normal text-xs">
                      ⚠️ 建议填写 — 确认记录将关联此机构，未填则不进入学习飞轮
                    </span>
                  )}
                </label>
                <input
                  className="w-full border rounded px-3 py-2 text-sm text-gray-900"
                  placeholder="例如：高瓴资本、IDG资本"
                  value={institutionName}
                  onChange={(e) => setInstitutionName(e.target.value)}
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {scenario === "post_investment" ? "上传季报模板文件" : "上传文件"}
                </label>
                <input
                  type="file"
                  accept={scenario === "post_investment" ? ".docx,.doc,.pdf" : ".xlsx,.xls,.docx,.doc,.pdf"}
                  onChange={(e) => setChecklistFile(e.target.files?.[0] || null)}
                  className="block text-sm text-gray-600"
                />
              </div>
              <div className="flex items-center gap-2 text-gray-400 text-sm">
                <hr className="flex-1" /> 或 <hr className="flex-1" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {scenario === "post_investment" ? "粘贴季报模板文字" : "粘贴清单文字"}
                </label>
                <textarea
                  className="w-full border rounded px-3 py-2 text-sm h-32 text-gray-900"
                  placeholder={
                    scenario === "post_investment"
                      ? "直接粘贴季报模板文字（含【】空格占位符）…"
                      : "直接粘贴机构发来的尽调需求列表文字…"
                  }
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
                  {parsing
                    ? "解析中…"
                    : matchStatus === "running"
                      ? matchProgress && matchProgress.total > 0
                        ? `匹配中… ${matchProgress.done}/${matchProgress.total} 项`
                        : scenario === "post_investment" ? "AI 匹配 & 填充中…" : "AI 匹配中…"
                      : scenario === "post_investment" ? "解析模板 & 开始匹配" : "解析 & 开始匹配"}
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
              {matchStatus === "running" && (() => {
                // 工作流步骤条：让人看到 AI 一步步在干什么，而不是闷头转圈
                const order = ["parse", "matching", "verifying", "confirm"];
                const cur = parsing ? "parse" : (matchStage || "matching");
                const curIdx = order.indexOf(cur);
                const steps = [
                  { key: "parse", label: "解析清单" },
                  { key: "matching", label: "AI 粗筛匹配" },
                  { key: "verifying", label: "读正文精判验证" },
                  { key: "confirm", label: "待人工确认" },
                ];
                return (
                  <div className="mt-3 flex items-center gap-1 text-xs">
                    {steps.map((s, i) => {
                      const done = i < curIdx;
                      const active = i === curIdx;
                      return (
                        <div key={s.key} className="flex items-center gap-1">
                          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 ${
                            done ? "bg-green-100 text-green-700"
                              : active ? "bg-blue-100 text-blue-700 font-medium"
                                : "bg-gray-100 text-gray-400"
                          }`}>
                            {done ? "✓" : active ? "●" : "○"} {s.label}
                          </span>
                          {i < steps.length - 1 && <span className="text-gray-300">→</span>}
                        </div>
                      );
                    })}
                  </div>
                );
              })()}
            </div>
          )}

          {/* ── Step 3 ── */}
          {step === 3 && (
            <div className="space-y-4">
              {/* ── 缺口摘要 header ── */}
              {(() => {
                const confirmed = items.filter((i) => i.user_confirmed === 1).length;
                const missing = items.filter((i) => i.user_skipped === 1 || ((i.confidence ?? 0) === 0 && !i.matched_filename)).length;
                const pending = items.length - confirmed - missing;
                const pct = items.length > 0 ? Math.round((confirmed / items.length) * 100) : 0;
                return (
                  <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 space-y-2">
                    <div className="flex items-center gap-4 text-sm flex-wrap">
                      <span className="flex items-center gap-1.5 font-medium text-green-700">
                        <span className="inline-block w-2.5 h-2.5 rounded-full bg-green-500" />
                        已确认 {confirmed} 条
                      </span>
                      <span className="flex items-center gap-1.5 font-medium text-amber-600">
                        <span className="inline-block w-2.5 h-2.5 rounded-full bg-amber-400" />
                        需人工 {pending} 条
                      </span>
                      <span className="flex items-center gap-1.5 font-medium text-red-600">
                        <span className="inline-block w-2.5 h-2.5 rounded-full bg-red-400" />
                        无材料 {missing} 条
                      </span>
                      <span className="ml-auto text-xs text-gray-500">共 {items.length} 条</span>
                    </div>
                    {/* 进度条 */}
                    <div className="h-1.5 w-full rounded-full bg-gray-200 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-green-500 transition-all duration-500"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-400">确认进度 {pct}%</span>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => void handleExtractQA()}
                          disabled={qaExtracting}
                          className="px-3 py-1 bg-purple-100 text-purple-700 rounded text-xs disabled:opacity-50 hover:bg-purple-200"
                          title="从历史补充资料扒取问答，供「💬 草稿」复用"
                        >
                          {qaExtracting ? "扒取中…" : "🔍 扒取历史问答"}
                        </button>
                        {highConfCount > 0 && (
                          <button
                            onClick={() => void handleBulkConfirm()}
                            disabled={bulkConfirming}
                            className="px-3 py-1 bg-green-600 text-white rounded text-xs disabled:opacity-50 hover:bg-green-700"
                          >
                            {bulkConfirming ? "确认中…" : `✓ 一键确认高置信（${highConfCount}条）`}
                          </button>
                        )}
                      </div>
                    </div>
                    {qaExtractMsg && <p className="text-xs text-gray-500">{qaExtractMsg}</p>}
                  </div>
                );
              })()}

              {/* ── 分类折叠表格 ── */}
              {(() => {
                // 按 category 分组，保持原有 sort 顺序
                const catOrder: string[] = [];
                const catMap = new Map<string, DDItem[]>();
                for (const item of sortedItems) {
                  const cat = item.category?.trim() || "其他";
                  if (!catMap.has(cat)) { catMap.set(cat, []); catOrder.push(cat); }
                  catMap.get(cat)!.push(item);
                }
                // 单分类时不显示折叠头，直接展平（避免只有"其他"时多余层级）
                const showGroups = catOrder.length > 1;

                const renderItemRows = (item: DDItem) => (
                  <React.Fragment key={item.id}>
                    <tr className={`border-t ${item.user_skipped ? "opacity-40" : ""}`}>
                      <td className="px-3 py-2 text-gray-400 text-xs">{item.item_no}</td>
                      <td className="px-3 py-2">
                        <div className="text-sm font-medium text-gray-800">{item.requirement}</div>
                      </td>
                      <td className="px-3 py-2 text-sm">
                        {item.matched_filename ? (
                          <div>
                            {item.is_encrypted === 1 && (
                              <button
                                onClick={() => { setPwdInputItem(pwdInputItem === item.id ? null : item.id); setPwdDraft(item.unlock_password || ""); }}
                                title={item.unlock_password ? `已登记密码：${item.unlock_password}` : "加密文件 — 点击登记打开密码"}
                                className={`mr-1 text-xs ${item.unlock_password ? "text-green-600" : "text-amber-500"}`}
                              >
                                {item.unlock_password ? "🔓" : "🔒"}
                              </button>
                            )}
                            <span className="text-gray-700" title={item.match_reason || ""}>{item.matched_filename}</span>
                            {item.candidates_json && (() => {
                              try {
                                const cands: Candidate[] = JSON.parse(item.candidates_json);
                                if (cands.length > 1) return (
                                  <button
                                    onClick={() => setExpandedCandidates(expandedCandidates === item.id ? null : item.id)}
                                    className="ml-2 text-xs text-indigo-500 hover:text-indigo-700"
                                  >
                                    {expandedCandidates === item.id ? "▲" : `▼ ${cands.length}个候选`}
                                  </button>
                                );
                              } catch (_) {}
                              return null;
                            })()}
                            {/* 机器验证：精判后的原文证据片段（让人工终审更快） */}
                            {item.evidence && (
                              <div className="mt-0.5 text-xs text-gray-500 flex items-start gap-1">
                                <span>{item.verdict === "green" ? "🟢" : item.verdict === "yellow" ? "🟡" : item.verdict === "red" ? "🔴" : "🔎"}</span>
                                <span className="italic">{item.evidence}</span>
                              </div>
                            )}
                          </div>
                        ) : (
                          <span className="text-gray-400 italic text-xs">无匹配</span>
                        )}
                      </td>
                      {/* 草稿填充值（投后模式）*/}
                      {scenario === "post_investment" && (
                        <td className="px-3 py-2 text-xs text-gray-700 max-w-[120px]">
                          {item.draft_answer ? (
                            <span className="text-green-700 font-medium">{item.draft_answer}</span>
                          ) : (
                            <span className="text-gray-300 italic">待填写</span>
                          )}
                        </td>
                      )}
                      {/* 置信度彩色徽章 */}
                      <td className="px-3 py-2 text-center">
                        {item.user_confirmed === 1 ? (
                          <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">已确认</span>
                        ) : item.user_skipped === 1 ? (
                          <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-500">缺失</span>
                        ) : item.confidence === null || item.confidence === undefined ? (
                          <span className="inline-block px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-400">—</span>
                        ) : item.confidence >= 0.8 ? (
                          <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">{Math.round(item.confidence * 100)}%</span>
                        ) : item.confidence >= 0.5 ? (
                          <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700">{Math.round(item.confidence * 100)}%</span>
                        ) : (
                          <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-600">{Math.round(item.confidence * 100)}%</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-center space-x-1">
                        {!item.user_skipped && !item.user_confirmed && (
                          <>
                            <button onClick={() => void handleConfirm(item.id)} className="text-xs px-2 py-0.5 bg-green-100 text-green-700 rounded">✓</button>
                            <button onClick={() => void handleSkip(item.id)} className="text-xs px-2 py-0.5 bg-red-100 text-red-600 rounded">缺</button>
                            <button
                              onClick={() => { setManualInputItem(item.id); setManualPath(""); setExpandedCandidates(null); }}
                              className="text-xs px-2 py-0.5 bg-blue-100 text-blue-700 rounded whitespace-nowrap"
                              title="手动指定要替换的文件"
                            >📂 替换</button>
                          </>
                        )}
                        <button
                          onClick={() => void handleLoadDraft(item)}
                          className="text-xs px-2 py-0.5 bg-purple-100 text-purple-700 rounded whitespace-nowrap"
                          title="从历史问答生成答复草稿"
                        >💬 草稿</button>
                      </td>
                    </tr>
                    {/* 备选候选展开行 */}
                    {expandedCandidates === item.id && item.candidates_json && (() => {
                      try {
                        const cands: Candidate[] = JSON.parse(item.candidates_json);
                        return (
                          <tr className="border-t bg-indigo-50">
                            <td colSpan={scenario === "post_investment" ? 6 : 5} className="px-3 py-2">
                              <p className="text-xs text-indigo-600 mb-1 font-medium">备选文件（「选用」设为主文件 · 勾选「附加」可多份材料归一条需求）：</p>
                              <div className="space-y-1">
                                {cands.map((cand, idx) => {
                                  const isPrimary = cand.file_path === item.matched_file_path;
                                  const checked = (extraSelections[item.id]?.has(cand.file_path)) ?? false;
                                  return (
                                  <div key={idx} className="flex items-center gap-2 text-xs">
                                    <label className={`flex items-center gap-1 ${isPrimary ? "opacity-30" : "cursor-pointer"}`} title="附加为该需求的额外材料">
                                      <input
                                        type="checkbox"
                                        aria-label={`附加-${cand.filename}`}
                                        disabled={isPrimary}
                                        checked={checked}
                                        onChange={() => toggleExtraFile(item.id, cand.file_path)}
                                      />
                                      附加
                                    </label>
                                    <span className={`w-8 text-center rounded px-1 ${cand.confidence >= 0.8 ? "bg-green-100 text-green-700" : cand.confidence >= 0.5 ? "bg-amber-100 text-amber-700" : "bg-red-100 text-red-600"}`}>
                                      {Math.round(cand.confidence * 100)}%
                                    </span>
                                    <span className="flex-1 text-gray-700" title={cand.reason}>{cand.filename}</span>
                                    {!isPrimary && (
                                      <button onClick={() => void handleSelectCandidate(item.id, cand)} className="px-2 py-0.5 bg-indigo-100 text-indigo-700 rounded hover:bg-indigo-200">选用</button>
                                    )}
                                    {isPrimary && <span className="text-gray-400 italic">（当前主文件）</span>}
                                  </div>
                                  );
                                })}
                              </div>
                              {(extraSelections[item.id]?.size ?? 0) > 0 && (
                                <button
                                  onClick={() => void handleSaveExtraFiles(item)}
                                  className="mt-2 px-2 py-1 bg-indigo-600 text-white rounded text-xs"
                                >
                                  附加 {extraSelections[item.id]!.size} 份材料到本需求
                                </button>
                              )}
                            </td>
                          </tr>
                        );
                      } catch (_) { return null; }
                    })()}
                    {/* 加密文件密码登记行 */}
                    {pwdInputItem === item.id && (
                      <tr className="border-t bg-amber-50">
                        <td colSpan={scenario === "post_investment" ? 6 : 5} className="px-3 py-2">
                          <div className="flex gap-2 items-center">
                            <span className="text-xs text-amber-700 whitespace-nowrap">🔒 打开密码：</span>
                            <input
                              className="flex-1 border rounded px-2 py-1 text-xs text-gray-900"
                              placeholder="输入该加密文件的打开密码（导出时随附说明，不解密）"
                              value={pwdDraft}
                              onChange={(e) => setPwdDraft(e.target.value)}
                              onKeyDown={(e) => { if (e.key === "Enter") void handleSavePassword(item); }}
                              autoFocus
                            />
                            <button onClick={() => void handleSavePassword(item)} className="text-xs px-2 py-1 bg-amber-600 text-white rounded">保存密码</button>
                            <button onClick={() => setPwdInputItem(null)} className="text-xs px-2 py-1 border rounded text-gray-500">取消</button>
                          </div>
                        </td>
                      </tr>
                    )}
                    {/* 手动指定文件的内联输入行 */}
                    {manualInputItem === item.id && (
                      <tr className="border-t bg-blue-50">
                        <td colSpan={scenario === "post_investment" ? 6 : 5} className="px-3 py-2">
                          <div className="flex gap-2 items-center">
                            <span className="text-xs text-blue-700 whitespace-nowrap">📂 指定文件：</span>
                            <input
                              className="flex-1 border rounded px-2 py-1 text-xs text-gray-900"
                              placeholder="点击「选择文件」或手动输入路径"
                              value={manualPath}
                              onChange={(e) => setManualPath(e.target.value)}
                              onKeyDown={(e) => { if (e.key === "Enter") void handleManualFile(item.id); }}
                              autoFocus
                            />
                            <button
                              onClick={async () => { const p = await pickFile(folderPath || ""); if (p) setManualPath(p); }}
                              className="text-xs px-2 py-1 bg-gray-100 border rounded text-gray-700 hover:bg-gray-200 whitespace-nowrap"
                            >📁 选择文件</button>
                            <button onClick={() => void handleManualFile(item.id)} disabled={!manualPath.trim()} className="text-xs px-2 py-1 bg-blue-600 text-white rounded disabled:opacity-50">确认</button>
                            <button onClick={() => setManualInputItem(null)} className="text-xs px-2 py-1 border rounded text-gray-500">取消</button>
                          </div>
                        </td>
                      </tr>
                    )}
                    {/* F4 答复草稿审核行 */}
                    {draftItem === item.id && (
                      <tr className="border-t bg-purple-50">
                        <td colSpan={scenario === "post_investment" ? 6 : 5} className="px-3 py-2">
                          {draftLoading && !drafts[item.id] ? (
                            <p className="text-xs text-purple-600">⏳ 正在生成草稿…</p>
                          ) : (() => {
                            const d = drafts[item.id];
                            if (!d) return <p className="text-xs text-gray-400">无草稿</p>;
                            return (
                              <div className="space-y-1">
                                <div className="flex items-center gap-2 text-xs">
                                  <span className="font-medium text-purple-700">💬 答复草稿</span>
                                  {d.matched ? (
                                    <span className="px-1.5 py-0.5 rounded bg-green-100 text-green-700">
                                      命中历史 · 置信 {Math.round(d.confidence * 100)}%
                                    </span>
                                  ) : (
                                    <span className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">
                                      无历史命中，请人工填写
                                    </span>
                                  )}
                                  {d.matched && d.source && (
                                    <span className="text-gray-400" title={d.source}>来源问：{d.source.slice(0, 20)}…</span>
                                  )}
                                </div>
                                <textarea
                                  aria-label={`草稿-${item.item_no}`}
                                  className="w-full border rounded px-2 py-1 text-xs text-gray-900 h-20"
                                  placeholder="可编辑答复草稿…"
                                  value={d.text}
                                  onChange={(e) => setDrafts((prev) => ({ ...prev, [item.id]: { ...prev[item.id], text: e.target.value } }))}
                                />
                              </div>
                            );
                          })()}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );

                const tableHead = (
                  <thead className="bg-gray-50 text-gray-500 text-xs sticky top-0">
                    <tr>
                      <th className="px-3 py-2 text-left w-8">#</th>
                      <th className="px-3 py-2 text-left">
                        {scenario === "post_investment" ? "填充项" : "需求"}
                      </th>
                      <th className="px-3 py-2 text-left">匹配文件</th>
                      {scenario === "post_investment" && (
                        <th className="px-3 py-2 text-left w-32">草稿填充值</th>
                      )}
                      <th className="px-3 py-2 text-center w-24">置信度</th>
                      <th className="px-3 py-2 text-center w-32">操作</th>
                    </tr>
                  </thead>
                );

                if (!showGroups) {
                  return (
                    <div className="border rounded overflow-hidden">
                      <table className="w-full text-sm">{tableHead}<tbody>{sortedItems.map(renderItemRows)}</tbody></table>
                    </div>
                  );
                }

                return (
                  <div className="space-y-2">
                    {catOrder.map((cat) => {
                      const catItems = catMap.get(cat)!;
                      const catConfirmed = catItems.filter((i) => i.user_confirmed === 1).length;
                      const catMissing = catItems.filter((i) => i.user_skipped === 1 || ((i.confidence ?? 0) === 0 && !i.matched_filename)).length;
                      const isCollapsed = collapsedCategories.has(cat);
                      return (
                        <div key={cat} className="border rounded overflow-hidden">
                          {/* 分类折叠头 */}
                          <button
                            type="button"
                            onClick={() => setCollapsedCategories((prev) => {
                              const next = new Set(prev);
                              if (next.has(cat)) next.delete(cat); else next.add(cat);
                              return next;
                            })}
                            className="w-full flex items-center gap-3 px-4 py-2.5 bg-gray-100 hover:bg-gray-200 text-left text-sm font-medium text-gray-700 transition-colors"
                          >
                            <span className="text-gray-400 text-xs w-3">{isCollapsed ? "▶" : "▼"}</span>
                            <span className="flex-1">{cat}</span>
                            <span className="text-xs text-gray-500">{catItems.length} 条</span>
                            {catConfirmed > 0 && (
                              <span className="text-xs text-green-600 font-medium">✓ {catConfirmed}/{catItems.length}</span>
                            )}
                            {catMissing > 0 && (
                              <span className="text-xs text-red-500">缺 {catMissing}</span>
                            )}
                            {/* 分类内迷你进度条 */}
                            <div className="w-16 h-1 rounded-full bg-gray-200 overflow-hidden">
                              <div
                                className="h-full rounded-full bg-green-400"
                                style={{ width: `${Math.round((catConfirmed / catItems.length) * 100)}%` }}
                              />
                            </div>
                          </button>
                          {!isCollapsed && (
                            <table className="w-full text-sm">{tableHead}<tbody>{catItems.map(renderItemRows)}</tbody></table>
                          )}
                        </div>
                      );
                    })}
                  </div>
                );
              })()}

              {/* ── 投后模式：生成季报初稿 ── */}
              {scenario === "post_investment" ? (
                <div className="pt-2 space-y-2">
                  <p className="text-xs text-gray-500">
                    AI 已从材料中提取填充值（草稿），请审核上方表格后生成初稿文本文件。
                  </p>
                  <div className="flex gap-2 items-center">
                    <input
                      className="flex-1 border rounded px-3 py-2 text-sm text-gray-900"
                      placeholder="点击「📁 选择」或手动输入季报初稿保存路径（如 /tmp/季报初稿.txt）"
                      value={reportOutputPath}
                      onChange={(e) => setReportOutputPath(e.target.value)}
                    />
                    <button
                      onClick={async () => {
                        const p = await pickFile(reportOutputPath);
                        if (p) setReportOutputPath(p);
                      }}
                      disabled={reportExporting}
                      className="px-3 py-2 bg-gray-100 text-gray-700 border rounded text-sm hover:bg-gray-200 disabled:opacity-50 whitespace-nowrap"
                    >
                      📁 选择
                    </button>
                    <button
                      onClick={() => void handleExportReport()}
                      disabled={reportExporting || !reportOutputPath.trim()}
                      className="px-4 py-2 bg-green-600 text-white rounded text-sm disabled:opacity-50 whitespace-nowrap"
                    >
                      {reportExporting ? "生成中…" : "📄 生成季报初稿"}
                    </button>
                  </div>
                  {reportExportResult && <p className="text-sm text-green-600">{reportExportResult}</p>}
                  {reportExportError && <p className="text-sm text-red-500">{reportExportError}</p>}
                </div>
              ) : (
                <div className="flex gap-2 items-center pt-2">
                <input
                  className="flex-1 border rounded px-3 py-2 text-sm text-gray-900"
                  placeholder="点击「📁 选择」或手动输入导出路径"
                  value={outputDir}
                  onChange={(e) => setOutputDir(e.target.value)}
                />
                <button
                  onClick={async () => {
                    const p = await pickFolder(outputDir);
                    if (p) setOutputDir(p);
                  }}
                  disabled={exporting}
                  className="px-3 py-2 bg-gray-100 text-gray-700 border rounded text-sm hover:bg-gray-200 disabled:opacity-50 whitespace-nowrap"
                >
                  📁 选择
                </button>
                <button
                  onClick={() => void handleExport()}
                  disabled={exporting || !outputDir.trim()}
                  className="px-4 py-2 bg-blue-600 text-white rounded text-sm disabled:opacity-50 whitespace-nowrap"
                  title="按材料分类归档（默认）"
                >
                  {exporting ? "导出中…" : "按分类导出"}
                </button>
                <button
                  onClick={enterByQuestionMode}
                  disabled={exporting}
                  className="px-4 py-2 bg-indigo-600 text-white rounded text-sm disabled:opacity-50 whitespace-nowrap"
                  title="每条机构问题一个文件夹，可统一改名"
                >
                  📁 按问题归档…
                </button>
              </div>
              )}

              {/* ── F5 命名确认表（仅尽调模式）── */}
              {scenario !== "post_investment" && byQuestionMode && (
                <div className="rounded-lg border border-indigo-200 bg-indigo-50/50 p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium text-indigo-700">📁 命名确认 — 每条问题一个文件夹（可改名为对方问题原话）</p>
                    <button onClick={() => setByQuestionMode(false)} className="text-xs text-gray-400 hover:text-gray-600">✕ 收起</button>
                  </div>
                  <div className="max-h-60 overflow-y-auto border rounded bg-white">
                    <table className="w-full text-xs">
                      <thead className="bg-gray-50 text-gray-500 sticky top-0">
                        <tr>
                          <th className="px-2 py-1.5 text-left w-8">#</th>
                          <th className="px-2 py-1.5 text-left">我方需求</th>
                          <th className="px-2 py-1.5 text-left">导出文件夹名（可编辑）</th>
                        </tr>
                      </thead>
                      <tbody>
                        {items.filter((i) => i.matched_filename && !i.user_skipped).map((i) => (
                          <tr key={i.id} className="border-t">
                            <td className="px-2 py-1.5 text-gray-400">{i.item_no}</td>
                            <td className="px-2 py-1.5 text-gray-600">{i.requirement}</td>
                            <td className="px-2 py-1.5">
                              <input
                                aria-label={`文件夹名-${i.item_no}`}
                                className="w-full border rounded px-2 py-1 text-xs text-gray-900"
                                value={folderNames[i.id] ?? ""}
                                onChange={(e) => setFolderNames((prev) => ({ ...prev, [i.id]: e.target.value }))}
                              />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <button
                    onClick={() => void handleExportByQuestion()}
                    disabled={exporting || !outputDir.trim()}
                    className="px-4 py-2 bg-indigo-600 text-white rounded text-sm disabled:opacity-50"
                  >
                    {exporting ? "导出中…" : "✅ 确认并按问题导出"}
                  </button>
                  {!outputDir.trim() && <span className="ml-2 text-xs text-amber-500">请先在上方填写导出路径</span>}
                </div>
              )}
              {scenario !== "post_investment" && exportResult && <p className="text-sm text-green-600">{exportResult}</p>}
              {scenario !== "post_investment" && exportError && <p className="text-sm text-red-500">{exportError}</p>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
