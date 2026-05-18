import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, getSession, clearSession, type FosSession } from "./api/client";
import { LoginPage } from "./components/LoginPage";
import { AchievementFlash } from "./components/AchievementFlash";
import { DoctorPanel } from "./components/DoctorPanel";
import { ExpHud } from "./components/ExpHud";
import { NPCPanel } from "./components/NPCPanel";
import { ScoreToastStack, type ScoreToastItem } from "./components/ScoreToast";
import { PitchJobHistory, type JobRow } from "./components/PitchJobHistory";
import { InstitutionList } from "./components/InstitutionList";
import { FollowUpWidget } from "./components/FollowUpWidget";
import { PitchUploadWizard } from "./components/PitchUploadWizard";
import { RoadshowWizard } from "./components/RoadshowWizard";
import DueDiligenceWizard from "./components/DueDiligenceWizard";
import { ParticipantConfirmModal } from "./components/ParticipantConfirmModal";
import { SettingsPanel } from "./components/SettingsPanel";

const AssetLibrary = lazy(() =>
  import("./components/AssetLibrary").then((m) => ({ default: m.AssetLibrary }))
);
const WarRoomMap = lazy(() =>
  import("./components/WarRoomMap").then((m) => ({ default: m.WarRoomMap }))
);
import type { DashboardStatus } from "./types/dashboard";
import type { InstitutionProfile } from "./types/institution";
import type { ReadyPayload } from "./types/ready";

const DEFAULT_TENANT = "demo-tenant";

// ── 同步数据按钮 ──────────────────────────────────────────────────────────────
function SyncButton() {
  const [state, setState] = useState<"idle" | "syncing" | "done" | "err">("idle");
  const [msg, setMsg] = useState("");
  const [fullMsg, setFullMsg] = useState("");

  const handleSync = async () => {
    setState("syncing");
    setFullMsg("");
    try {
      const r = await api.post<{ ok: boolean; message: string; pitch_imported: number; match_imported: number }>(
        "/api/sync/pull"
      );
      const d = r.data;
      if (d.ok) {
        const added = d.pitch_imported + d.match_imported;
        setMsg(added > 0 ? `新增 ${added} 条` : "已是最新");
      } else {
        // 截断显示，完整原因放 title（hover 可见）
        const full = d.message || "同步失败";
        setFullMsg(full);
        setMsg(full.length > 20 ? full.slice(0, 18) + "…" : full);
      }
      setState(d.ok ? "done" : "err");
    } catch {
      const full = "网络错误，请检查后端是否正常运行";
      setFullMsg(full);
      setMsg("网络错误");
      setState("err");
    } finally {
      setTimeout(() => { setState("idle"); setFullMsg(""); }, 3000);
    }
  };

  return (
    <button
      type="button"
      disabled={state === "syncing"}
      onClick={() => void handleSync()}
      title={state === "err" && fullMsg ? fullMsg : "从 GitHub 拉取团队最新数据"}
      className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1 text-[11px] transition hover:border-cyan-500/30 hover:text-cyan-300 disabled:opacity-50"
    >
      {state === "syncing" ? (
        <span className="animate-spin">🔄</span>
      ) : state === "done" ? (
        <span className="text-emerald-400">✓</span>
      ) : state === "err" ? (
        <span className="text-red-400">✗</span>
      ) : (
        <span>☁️</span>
      )}
      <span className={state === "done" ? "text-emerald-400" : state === "err" ? "text-red-400" : "text-slate-400"}>
        {state === "syncing" ? "同步中…" : state === "done" || state === "err" ? msg : "同步数据"}
      </span>
    </button>
  );
}

// ── 顶层入口：只负责登录门控，不包含任何业务 hooks ─────────────────────────
export default function App() {
  const [session, setSession] = useState<FosSession | null>(() => getSession());
  const [accountsConfigured, setAccountsConfigured] = useState<boolean | null>(null);

  useEffect(() => {
    void api.get<{ configured: boolean }>("/api/auth/accounts-configured")
      .then(r => setAccountsConfigured(r.data.configured))
      .catch(() => setAccountsConfigured(false));
  }, []);

  const [syncNotice, setSyncNotice] = useState<string>("");

  const handleLogin = (s: FosSession, _commanderName: string) => {
    setSession(s);
    // 登录后触发 GitHub 同步，并给用户一个可见提示
    setSyncNotice("⏳ 正在从 GitHub 同步最新数据…");
    api.post<{ ok: boolean; pitch_imported: number; match_imported: number }>("/api/sync/pull")
      .then(r => {
        const d = r.data;
        if (d.ok) {
          const n = d.pitch_imported + d.match_imported;
          setSyncNotice(n > 0 ? `✅ 已同步 ${n} 条新数据` : "✅ 数据已是最新");
        } else {
          setSyncNotice("");
        }
      })
      .catch(() => setSyncNotice(""))
      .finally(() => setTimeout(() => setSyncNotice(""), 4000));
  };
  const handleLogout = () => {
    void api.post("/api/auth/logout").catch(() => {});
    clearSession();
    setSession(null);
  };

  // 未登录 → 始终显示登录页（无论后端是否配置了 FOS_ACCOUNTS）
  if (!session) {
    return <LoginPage onLogin={handleLogin} />;
  }

  // 等待配置检查完成（短暂空白过渡）
  if (accountsConfigured === null) return null;

  return <MainApp session={session} onLogout={handleLogout} syncNotice={syncNotice} />;
}

// ── 主应用：所有业务 hooks 都在这里，永远不会有条件返回在 hooks 之前 ──────────
function MainApp({ session, onLogout, syncNotice }: { session: FosSession | null; onLogout: () => void; syncNotice?: string }) {
  const [dashboard, setDashboard] = useState<DashboardStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [toasts, setToasts] = useState<ScoreToastItem[]>([]);
  const [totalExp, setTotalExp] = useState(120);
  const [expHint, setExpHint] = useState("");
  const [achOpen, setAchOpen] = useState(false);
  const [institutions, setInstitutions] = useState<InstitutionProfile[]>([]);
  const [commanderName, setCommanderName] = useState("");
  const [wizardOpen, setWizardOpen] = useState(false);
  const [roadshowOpen, setRoadshowOpen] = useState(false);
  const [ddOpen, setDdOpen] = useState(false);
  const [doctorOpen, setDoctorOpen] = useState(false);
  const [ready, setReady] = useState<ReadyPayload | null | undefined>(undefined);
  // ── 参与人确认弹层 ─────────────────────────────────────────────────────────
  const [confirmJob, setConfirmJob] = useState<{ jobId: string; interviewee: string | null } | null>(null);
  const [skippedJobs, setSkippedJobs] = useState<Set<string>>(() => {
    try {
      const raw = sessionStorage.getItem("fos_skipped_jobs");
      return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
    } catch { return new Set(); }
  });
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // skippedJobs 写入 sessionStorage，刷新后不重弹已 skip 过的任务
  useEffect(() => {
    try {
      sessionStorage.setItem("fos_skipped_jobs", JSON.stringify([...skippedJobs]));
    } catch { /* ignore */ }
  }, [skippedJobs]);

  useEffect(() => {
    try {
      const v = localStorage.getItem("fos_commander_name");
      if (v) setCommanderName(v);
    } catch {
      /* ignore */
    }
  }, []);

  const persistCommander = useCallback((v: string) => {
    setCommanderName(v);
    try {
      localStorage.setItem("fos_commander_name", v);
    } catch {
      /* ignore */
    }
  }, []);

  // tenant_id 优先取 URL 参数（调试用），否则用登录 session 里的 tenant_id
  const tenant = useMemo(() => {
    const q = new URLSearchParams(window.location.search).get("tenant");
    if (q && q.length > 0) return q;
    return session?.tenant_id ?? "default";
  }, [session]);

  const uploadBlockedReason = useMemo(() => {
    if (ready === undefined) return "正在检查运行环境（/api/v1/ready）…";
    if (ready === null) return "无法获取就绪状态，请确认后端已启动。";
    if (!ready.pitch_coach_ok) {
      return "AI 评估引擎目录未就绪，点击「🔧 系统诊断」查看修复指引。";
    }
    if (!ready.api_keys_ok) {
      return "API 密钥未配置，点击右上角 ⚙️ 填写 DeepSeek 和 DashScope Key 后即可使用。";
    }
    return null;
  }, [ready]);

  const refreshWarData = useCallback(async () => {
    try {
      const [dash, inst] = await Promise.all([
        api.get<DashboardStatus>("/api/dashboard/status", { params: { tenant_id: tenant } }),
        api.get<InstitutionProfile[]>("/api/v1/pipeline/institutions", { params: { tenant_id: tenant } }),
      ]);
      setDashboard(dash.data);
      setInstitutions(inst.data);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [tenant]);

  useEffect(() => {
    void refreshWarData();
  }, [refreshWarData]);

  const fetchReady = useCallback(() => {
    void api
      .get<ReadyPayload>("/api/v1/ready")
      .then((r) => setReady(r.data))
      .catch(() => setReady(null));
  }, []);

  useEffect(() => {
    fetchReady();
  }, [fetchReady]);

  useEffect(() => {
    if (!dashboard) return;
    if (dashboard.docs_health_pct < 80) return;
    try {
      const k = `fos_ach_docs80:${tenant}`;
      if (sessionStorage.getItem(k)) return;
      sessionStorage.setItem(k, "1");
      setAchOpen(true);
    } catch {
      setAchOpen(true);
    }
  }, [dashboard, tenant]);

  const pushToast = useCallback((delta: number, reason: string) => {
    const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setToasts((t) => [...t, { id, delta, reason }]);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  const onExpEvent = useCallback(
    (delta: number, reason: string, hint?: string) => {
      setTotalExp((x) => Math.max(0, x + delta));
      setExpHint(hint ?? reason);
      pushToast(delta, reason);
    },
    [pushToast],
  );

  // ── 轮询：检查是否有已完成但未确认参与人的 job（2小时内才自动弹出）────────
  useEffect(() => {
    const TWO_HOURS = 2 * 60 * 60 * 1000;
    const poll = async () => {
      if (confirmJob) return; // 弹层已经开着时不重复触发
      try {
        const { data } = await api.get<JobRow[]>("/api/pitch/jobs", {
          params: { tenant_id: tenant, limit: 20 },
        });
        const pending = data.find(
          (j) =>
            j.status === "completed" &&
            !j.participants_confirmed &&
            !skippedJobs.has(j.job_id) &&
            Date.now() - j.created_at * 1000 < TWO_HOURS,
        );
        if (pending) {
          setConfirmJob({ jobId: pending.job_id, interviewee: pending.interviewee ?? null });
        }
      } catch {
        /* ignore */
      }
    };
    void poll();
    pollTimerRef.current = setInterval(() => void poll(), 8000);
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, [tenant, confirmJob, skippedJobs]);

  const demoDryRun = async () => {
    try {
      const { status } = await api.post("/api/pitch/run", {
        tenant_id: tenant,
        dry_run: true,
        words: [
          {
            word_index: 0,
            text: "测",
            start_time: 0,
            end_time: 0.1,
            speaker_id: "S1",
          },
        ],
      });
      if (status === 200) onExpEvent(5, "Dry-run 链路已打通");
      else onExpEvent(-2, "Dry-run 请求异常");
    } catch {
      onExpEvent(-3, "网络异常");
    }
  };

  return (
    <div className="min-h-screen px-4 pb-10 pt-6 md:px-10">
      {ready && !ready.ok ? (
        <div
          className="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100"
          role="status"
        >
          <p className="font-semibold text-amber-200">环境未完全就绪</p>
          <ul className="mt-1 list-inside list-disc text-xs text-amber-100/90">
            {ready.issues
              .filter((i) => i.severity === "error" || i.code.startsWith("E_"))
              .slice(0, 5)
              .map((i) => (
                <li key={i.code + i.message}>
                  <span className="font-mono text-[10px] text-amber-300/90">{i.code}</span> — {i.message}
                </li>
              ))}
          </ul>
          <p className="mt-2 text-xs text-slate-400">详见仓库内 docs/RELEASE_CHECKLIST.md 或同事上手指南。</p>
        </div>
      ) : null}
      <AchievementFlash
        open={achOpen}
        title="资料健康度达标"
        subtitle="团队材料结构已跨过关键水位，继续保持迭代节奏。"
        onClose={() => setAchOpen(false)}
      />
      <ExpHud totalExp={totalExp} lastHint={expHint} />
      <ScoreToastStack items={toasts} onDone={dismissToast} />

      <header className="mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="font-display text-xs uppercase tracking-[0.4em] text-slate-500">
            CangJie FOS
          </p>
          <h1 className="font-display text-3xl font-bold text-white md:text-4xl">
            融资作战指挥台
          </h1>
          <p className="mt-2 max-w-xl text-sm text-slate-400">
            Phase 6：机构 Pipeline CRM · 路演情报自动落盘 · 战前简报 + 机构看板
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-slate-400">
            指挥官
            <input
              value={commanderName}
              onChange={(e) => persistCommander(e.target.value)}
              placeholder="称呼"
              className="w-28 rounded-lg border border-white/15 bg-black/40 px-2 py-1.5 text-sm text-white placeholder:text-slate-600"
            />
          </label>
          <button
            type="button"
            disabled={!!uploadBlockedReason}
            title={uploadBlockedReason ?? undefined}
            onClick={() => setWizardOpen(true)}
            className="rounded-xl border border-cyan/40 bg-cyan/10 px-4 py-2 font-display text-xs font-bold uppercase tracking-widest text-cyan hover:bg-cyan/20 disabled:cursor-not-allowed disabled:opacity-40"
          >
            复盘上传向导
          </button>
          <button
            type="button"
            disabled={!!uploadBlockedReason}
            title={uploadBlockedReason ?? "启动路演情报分析工作流"}
            onClick={() => setRoadshowOpen(true)}
            className="rounded-xl border border-purple-500/40 bg-purple-500/10 px-4 py-2 font-display text-xs font-bold uppercase tracking-widest text-purple-300 hover:bg-purple-500/20 disabled:cursor-not-allowed disabled:opacity-40"
          >
            🎯 路演分析
          </button>
          <button
            type="button"
            onClick={() => setDdOpen(true)}
            className="px-3 py-1.5 text-sm bg-indigo-50 text-indigo-700 border border-indigo-200 rounded-lg hover:bg-indigo-100 transition-colors"
          >
            📋 尽调响应
          </button>
          <button
            type="button"
            onClick={() => onExpEvent(10, "资料补齐")}
            className="rounded-xl bg-gradient-to-r from-cyan/80 to-plasma/80 px-4 py-2 font-display text-xs font-bold uppercase tracking-widest text-white shadow-lg shadow-cyan/25 transition hover:brightness-110"
          >
            模拟 +10 分
          </button>
          <button
            type="button"
            onClick={() => void demoDryRun()}
            title="测试模式：不消耗 API，用固定数据验证系统链路是否正常"
            className="rounded-xl border border-white/20 bg-white/5 px-4 py-2 font-display text-xs font-bold uppercase tracking-widest text-slate-200 transition hover:border-cyan/50 hover:text-white"
          >
            Dry-run /api/pitch/run
          </button>
          <button
            type="button"
            onClick={() => setDoctorOpen(true)}
            title="系统诊断"
            className="rounded-xl border border-white/20 bg-white/5 px-3 py-2 text-xs text-slate-400 transition hover:border-cyan/40 hover:text-cyan-300"
          >
            🔧 系统诊断
          </button>
          <SettingsPanel onKeySaved={fetchReady} />
          {session && (
            <div className="flex items-center gap-2">
              {syncNotice && (
                <span className="text-[11px] text-cyan-300 animate-pulse">
                  {syncNotice}
                </span>
              )}
              <span className="text-xs text-slate-500">
                👤 {session.username}
              </span>
              <SyncButton />
              <button
                type="button"
                onClick={onLogout}
                className="rounded-lg border border-white/10 px-2 py-1 text-[11px] text-slate-600 hover:text-slate-300"
              >
                退出
              </button>
            </div>
          )}
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <Suspense fallback={<div className="text-slate-500 text-xs p-2">加载地图…</div>}>
          <WarRoomMap
            dashboard={dashboard}
            loading={loading}
            error={err}
            tenantId={tenant}
            onRequestRefresh={() => void refreshWarData()}
          />
        </Suspense>
        <NPCPanel
          tenantId={tenant}
          onExpEvent={onExpEvent}
          onPipelineDataChanged={() => void refreshWarData()}
          userName={commanderName}
          onOpenWizard={() => setWizardOpen(true)}
        />
      </div>
      <InstitutionList tenantId={tenant} items={institutions} />
      <PitchJobHistory
        tenantId={tenant}
        onPendingConfirm={(jobId, interviewee) => setConfirmJob({ jobId, interviewee })}
      />
      <FollowUpWidget tenantId={tenant} />
      <Suspense fallback={<div className="text-slate-500 text-xs p-2">加载资料库…</div>}>
        <AssetLibrary />
      </Suspense>
      <PitchUploadWizard
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        tenantId={tenant}
        userName={commanderName}
        onPipelineDataChanged={() => void refreshWarData()}
        uploadBlockedReason={uploadBlockedReason}
      />
      <RoadshowWizard
        open={roadshowOpen}
        onClose={() => setRoadshowOpen(false)}
        tenantId={tenant}
        userName={commanderName}
        onPipelineDataChanged={() => void refreshWarData()}
        institutions={institutions.map((i) => i.name).filter(Boolean)}
      />
      <DoctorPanel open={doctorOpen} onClose={() => setDoctorOpen(false)} />
      <DueDiligenceWizard open={ddOpen} onClose={() => setDdOpen(false)} />
      {confirmJob ? (
        <ParticipantConfirmModal
          jobId={confirmJob.jobId}
          interviewee={confirmJob.interviewee}
          tenantId={tenant}
          confirmedBy={commanderName}
          institutions={institutions.map((i) => i.name).filter(Boolean)}
          onConfirmed={() => setConfirmJob(null)}
          onSkip={() => {
            setSkippedJobs((s) => new Set([...s, confirmJob.jobId]));
            setConfirmJob(null);
          }}
        />
      ) : null}
    </div>
  );
}
