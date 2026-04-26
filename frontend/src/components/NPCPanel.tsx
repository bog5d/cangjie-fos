import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { NPC_DISPLAY_NAME } from "../constants/npc";
import { DoudouPresence, type DoudouNpcUiState, MessageSideAvatar } from "./DoudouAvatar";
import { PitchReportPreviewModal } from "./PitchReportPreviewModal";
import { TaskRail } from "./TaskRail";

type NpcUiState = DoudouNpcUiState;

export interface ChatLine {
  id: string;
  role: string;
  text: string;
  proactive?: boolean;
  isAi?: boolean;
  traceId?: string;
  /** 非空时在本条气泡下展示「查看报告」入口（L1 弹层） */
  reportJobId?: string;
}

interface Props {
  tenantId: string;
  /** Exp 总线：积分条 + Toast + HUD 文案 */
  onExpEvent: (delta: number, reason: string, hint?: string) => void;
  /** 录音复盘等落盘后刷新左侧大盘 + 机构列表 */
  onPipelineDataChanged?: () => void;
  /** Phase 6.1：当前指挥官，注入 /api/pitch/chat */
  userName?: string;
  /** 打开复盘上传向导（统一入口） */
  onOpenWizard?: () => void;
}

function threadStorageKey(tenantId: string) {
  return `fos_pitch_thread:${tenantId}`;
}

function mapServerMessagesToLines(messages: { role: string; content: string }[]): ChatLine[] {
  return messages.map((m, i) => ({
    id: `hist-${i}-${m.role}`,
    role:
      m.role === "user" ? "你" : m.role === "assistant" ? NPC_DISPLAY_NAME : m.role === "system" ? "系统" : m.role,
    text: m.content,
    isAi: m.role === "assistant",
  }));
}

export function NPCPanel({ tenantId, onExpEvent, onPipelineDataChanged, userName = "", onOpenWizard }: Props) {
  const [uiState, setUiState] = useState<NpcUiState>("idle");
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [reportModalJobId, setReportModalJobId] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState<ChatLine | null>(null);
  const [correctionText, setCorrectionText] = useState("");
  /** 实时通道：不向聊天流写入底层错误；首帧即「连接中」避免误显示「重连」 */
  const [wsPhase, setWsPhase] = useState<"connecting" | "open" | "closed">("connecting");

  const wsUrl = useMemo(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/api/ws/npc?tenant_id=${encodeURIComponent(tenantId)}`;
  }, [tenantId]);

  const pushLine = useCallback((ln: ChatLine) => {
    setLines((prev) => [...prev.slice(-80), ln]);
  }, []);

  /** 切换租户时：从 localStorage 恢复 thread_id，并拉取 LangGraph checkpoint 历史 */
  useEffect(() => {
    setLines([]);
    let saved: string | null = null;
    try {
      const raw = localStorage.getItem(threadStorageKey(tenantId));
      saved = raw?.trim() ? raw.trim() : null;
    } catch {
      saved = null;
    }
    setThreadId(saved);
    if (!saved) return;

    let cancelled = false;
    void (async () => {
      try {
        const { data } = await api.get<{
          thread_id: string;
          messages: { role: string; content: string }[];
        }>(`/api/pitch/threads/${encodeURIComponent(saved)}/messages`);
        if (cancelled) return;
        setLines(mapServerMessagesToLines(data.messages).slice(-80));
      } catch {
        if (!cancelled) {
          try {
            localStorage.removeItem(threadStorageKey(tenantId));
          } catch {
            /* ignore */
          }
          setThreadId(null);
          setLines([]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  useEffect(() => {
    setWsPhase("connecting");
  }, [tenantId]);

  useEffect(() => {
    const h = (e: Event) => {
      const ce = e as CustomEvent<{ text?: string }>;
      const t = ce.detail?.text;
      if (!t) return;
      pushLine({
        id: `echo-${Date.now()}`,
        role: NPC_DISPLAY_NAME,
        text: t,
        isAi: true,
      });
    };
    window.addEventListener("fos-npc-echo", h);
    return () => window.removeEventListener("fos-npc-echo", h);
  }, [pushLine]);

  useEffect(() => {
    let dead = false;
    let socket: WebSocket | null = null;
    let reconnectTimer = 0;
    const attemptRef = { n: 0 };

    const clearReconnect = () => {
      if (reconnectTimer) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = 0;
      }
    };

    const handleMessage = (raw: string) => {
      try {
        const msg = JSON.parse(raw) as {
          type?: string;
          text?: string;
          message?: string;
          role?: string;
          proactive?: boolean;
          delta?: number;
          reason?: string;
          job_ids?: string[];
        };
        if (msg.type === "upload_job_started" && msg.message) {
          /** 禁止在任务未完成时挂载 reportJobId，否则会出现「查看报告」→ 弹窗无 report 的竞态 */
          pushLine({
            id: `ws-up-${Date.now()}`,
            role: NPC_DISPLAY_NAME,
            text: String(msg.message),
            isAi: true,
          });
        }
        if (msg.type === "npc_prompt" && msg.text) {
          pushLine({
            id: `ws-${Date.now()}`,
            role: msg.role ?? "NPC",
            text: msg.text,
            proactive: msg.proactive,
            isAi: true,
          });
          setUiState(msg.proactive ? "proactive_push" : "listening");
          window.setTimeout(() => setUiState("listening"), 1600);
        }
        if (msg.type === "score_delta" && msg.delta != null && msg.reason) {
          onExpEvent(msg.delta, msg.reason);
        }
        /** hello 不写入聊天流，避免与顶栏状态重复占位首屏 */
      } catch {
        /* ignore */
      }
    };

    const connect = () => {
      if (dead) return;
      clearReconnect();
      setWsPhase("connecting");
      try {
        socket = new WebSocket(wsUrl);
      } catch {
        if (!dead) {
          setWsPhase("closed");
          const delay = Math.min(20_000, 600 * Math.pow(1.45, attemptRef.n++));
          reconnectTimer = window.setTimeout(connect, delay);
        }
        return;
      }

      socket.onopen = () => {
        if (dead) return;
        attemptRef.n = 0;
        setWsPhase("open");
      };

      socket.onmessage = (ev) => {
        handleMessage(String(ev.data));
      };

      socket.onerror = () => {
        /** 不向聊天流推送「暂不可用」；浏览器通常会继续触发 onclose 并走重连 */
      };

      socket.onclose = () => {
        if (dead) return;
        socket = null;
        setWsPhase("closed");
        const delay = Math.min(20_000, 600 * Math.pow(1.45, attemptRef.n++));
        reconnectTimer = window.setTimeout(connect, delay);
      };
    };

    setUiState("listening");
    connect();

    return () => {
      dead = true;
      clearReconnect();
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.close(1000, "npc panel unmount");
      } else if (socket) {
        try {
          socket.close();
        } catch {
          /* ignore */
        }
      }
      socket = null;
    };
  }, [wsUrl, onExpEvent, pushLine]);

  const sendChat = async () => {
    const t = input.trim();
    if (!t) return;
    setInput("");
    pushLine({ id: `u-${Date.now()}`, role: "你", text: t, isAi: false });
    setUiState("thinking");
    try {
      const { data } = await api.post<{
        reply: string;
        trace_id: string;
        thread_id: string;
        exp_delta: number;
        exp_reason: string;
      }>("/api/pitch/chat", {
        tenant_id: tenantId,
        message: t,
        ...(threadId ? { thread_id: threadId } : {}),
        ...(userName.trim() ? { user_name: userName.trim() } : {}),
      });
      if (data.thread_id) {
        setThreadId(data.thread_id);
        try {
          localStorage.setItem(threadStorageKey(tenantId), data.thread_id);
        } catch {
          /* ignore */
        }
      }
      pushLine({
        id: data.trace_id,
        role: NPC_DISPLAY_NAME,
        text: data.reply,
        isAi: true,
        traceId: data.trace_id,
      });
      if (data.exp_delta) {
        onExpEvent(data.exp_delta, data.exp_reason);
      }
    } catch (e) {
      pushLine({
        id: `e-${Date.now()}`,
        role: "系统",
        text: e instanceof Error ? e.message : "对话请求失败",
        isAi: false,
      });
    } finally {
      setUiState("listening");
    }
  };

  const submitCorrection = async () => {
    if (!correcting?.text) return;
    const userText = correctionText.trim();
    if (!userText) return;
    try {
      const { data } = await api.post<{
        exp_delta?: number;
        status: string;
      }>("/api/v1/feedback/text-diff", {
        tenant_id: tenantId,
        trace_id: correcting.traceId ?? correcting.id,
        ai_text: correcting.text,
        user_text: userText,
      });
      pushLine({
        id: `fb-${Date.now()}`,
        role: "系统",
        text: `已记录错题本（${data.status}），进化队列 pending_reflection。`,
        isAi: false,
      });
      const ed = typeof data.exp_delta === "number" ? data.exp_delta : 18;
      onExpEvent(ed, "纠错已入库");
    } catch (e) {
      pushLine({
        id: `fbc-${Date.now()}`,
        role: "系统",
        text: e instanceof Error ? e.message : "纠错提交失败",
        isAi: false,
      });
    } finally {
      setCorrecting(null);
      setCorrectionText("");
    }
  };

  const onTaskRailJobCompleted = useCallback(
    (jid: string) => {
      pushLine({
        id: `rail-done-${jid}`,
        role: NPC_DISPLAY_NAME,
        text: "一条复盘任务刚跑完，战局数据已刷新。需要的话直接打开报告摘要。",
        isAi: true,
        reportJobId: jid,
      });
    },
    [pushLine],
  );

  return (
    <div className="flex flex-col rounded-3xl border border-white/10 bg-gradient-to-b from-plasma/15 to-black/40 p-0 shadow-2xl backdrop-blur-xl" style={{ maxHeight: "min(900px, 90vh)" }}>
      <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
        <DoudouPresence npcState={uiState} subtitle="Phase 6.3 · 复盘向导 + SQLite" />
        <div className="flex flex-col items-end gap-2">
          <NpcStateBadge state={uiState} />
          <button
            type="button"
            className="text-[10px] font-bold uppercase tracking-wider text-slate-400 hover:text-white"
            onClick={() => {
              try {
                localStorage.removeItem(threadStorageKey(tenantId));
              } catch {
                /* ignore */
              }
              setThreadId(null);
              setLines([]);
            }}
          >
            新会话
          </button>
        </div>
      </div>

      <TaskRail
        tenantId={tenantId}
        onJobCompleted={onTaskRailJobCompleted}
        onOpenReport={(jid) => setReportModalJobId(jid)}
      />

      {wsPhase !== "open" ? (
        <div
          className="mx-4 mt-2 rounded-lg border border-cyan/15 bg-cyan/5 px-3 py-2 text-center text-[10px] leading-snug text-slate-400"
          role="status"
        >
          灵能同步链路{wsPhase === "connecting" ? "接入中" : "重连中"}… 不影响下方 HTTP 对话与任务条。
        </div>
      ) : null}

      <div className="flex flex-1 flex-col gap-3 overflow-y-auto px-5 py-4">
        {lines.length === 0 && (
          <p className="text-sm text-slate-500">
            输入文字即走真实 `/api/pitch/chat`（LangGraph + SQLite checkpoint）；刷新页面后会从本机恢复同一线程。
          </p>
        )}
        {lines.map((ln) => {
          const isSystem = ln.role === "系统";
          const isUser = !isSystem && !ln.isAi;
          const isNpc = !isSystem && ln.isAi;
          return (
            <div key={ln.id} className={isSystem ? "w-full" : "flex gap-2"}>
              {!isSystem ? (
                <div className="flex w-8 shrink-0 justify-center pt-1.5">
                  {isUser ? (
                    <MessageSideAvatar variant="user" userInitial={userName} />
                  ) : (
                    <MessageSideAvatar variant="npc" npcState="listening" />
                  )}
                </div>
              ) : null}
              <div className={`min-w-0 flex-1 ${isSystem ? "max-w-full" : "max-w-[calc(100%-2.5rem)]"}`}>
                <div
                  className={`rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-md ${
                    ln.proactive
                      ? "border border-ember/35 bg-ember/15 text-amber-50"
                      : ln.isAi
                        ? "border border-plasma/30 bg-plasma/10 text-slate-100"
                        : isSystem
                          ? "border border-white/5 bg-black/25 text-slate-400"
                          : "border border-white/10 bg-white/5 text-slate-100"
                  }`}
                >
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
                      {ln.role}
                    </span>
                    {ln.isAi ? (
                      <button
                        type="button"
                        className="text-[10px] font-bold uppercase tracking-wider text-cyan hover:text-white"
                        onClick={() => {
                          setCorrecting(ln);
                          setCorrectionText("");
                        }}
                      >
                        纠错
                      </button>
                    ) : null}
                  </div>
                  {ln.text}
                  {ln.reportJobId ? (
                    <div className="mt-2">
                      <button
                        type="button"
                        className="rounded-lg border border-emerald-400/50 bg-emerald-500/15 px-3 py-1 text-[11px] font-bold text-emerald-100 hover:bg-emerald-500/25"
                        onClick={() => setReportModalJobId(ln.reportJobId ?? null)}
                      >
                        查看报告
                      </button>
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <PitchReportPreviewModal
        open={reportModalJobId != null}
        jobId={reportModalJobId}
        onClose={() => setReportModalJobId(null)}
      />

      {correcting ? (
        <div className="border-t border-white/10 px-5 py-3">
          <p className="mb-2 text-xs text-slate-400">纠正 AI 原文要点（将写入错题本 / pending_reflection）</p>
          <textarea
            className="mb-2 w-full rounded-xl border border-white/15 bg-black/40 p-2 text-sm text-white"
            rows={3}
            value={correctionText}
            onChange={(e) => setCorrectionText(e.target.value)}
            placeholder="例如：不对，红杉问的是产能，不是估值。"
          />
          <div className="flex gap-2">
            <button
              type="button"
              className="rounded-lg bg-cyan/80 px-3 py-1.5 text-xs font-bold text-black"
              onClick={() => void submitCorrection()}
            >
              提交纠错
            </button>
            <button
              type="button"
              className="rounded-lg border border-white/20 px-3 py-1.5 text-xs text-slate-300"
              onClick={() => setCorrecting(null)}
            >
              取消
            </button>
          </div>
        </div>
      ) : null}

      <div className="border-t border-white/10 px-5 py-3">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => onOpenWizard?.()}
            className="rounded-lg border border-ember/40 bg-ember/15 px-3 py-1.5 text-xs font-bold text-amber-100 hover:bg-ember/25"
            title="打开复盘上传向导（填写机构名称、场景类型后上传录音）"
          >
            上传录音
          </button>
        </div>
        <div className="flex gap-2">
          <input
            className="min-w-0 flex-1 rounded-xl border border-white/15 bg-black/40 px-3 py-2 text-sm text-white placeholder:text-slate-600"
            placeholder={`问${NPC_DISPLAY_NAME}…（真实 LLM）`}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void sendChat();
              }
            }}
          />
          <button
            type="button"
            disabled={uiState === "thinking"}
            onClick={() => void sendChat()}
            className="rounded-xl bg-gradient-to-r from-plasma to-cyan px-4 py-2 text-xs font-bold text-white disabled:opacity-40"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  );
}

function NpcStateBadge({ state }: { state: NpcUiState }) {
  const label =
    state === "proactive_push"
      ? "主动追问"
      : state === "thinking"
        ? "推理中"
        : state === "listening"
          ? "聆听中"
          : "待命";
  const cls =
    state === "proactive_push"
      ? "bg-ember/25 text-amber-100 ring-ember/50 animate-pulse"
      : state === "thinking"
        ? "bg-plasma/30 text-plasma-100 ring-plasma/50 animate-pulse"
        : state === "listening"
          ? "bg-cyan/20 text-cyan-100 ring-cyan/40"
          : "bg-slate-700/50 text-slate-300 ring-white/10";
  return (
    <span
      className={`rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-wider ring-1 ${cls}`}
    >
      {label}
    </span>
  );
}
