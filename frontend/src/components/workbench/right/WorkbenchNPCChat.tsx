import { useState, useRef, useEffect, type KeyboardEvent } from "react";
import { api } from "../../../api/client";

interface WorkbenchNPCChatProps {
  tenantId: string;
  jobId: string;
  userName?: string;
}

interface ChatLine {
  role: "user" | "ai";
  text: string;
}

interface ChatResponse {
  reply: string;
  thread_id: string;
}

const THREAD_KEY = (tenantId: string) => `fos_pitch_thread:${tenantId}`;

export default function WorkbenchNPCChat({
  tenantId,
  jobId,
  userName,
}: WorkbenchNPCChatProps) {
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines]);

  async function sendMessage() {
    const text = input.trim();
    if (!text || sending) return;

    const threadId = localStorage.getItem(THREAD_KEY(tenantId)) ?? undefined;

    setLines((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setSending(true);
    setError(null);

    try {
      const res = await api.post<ChatResponse>("/api/pitch/chat", {
        tenant_id: tenantId,
        message: text,
        ...(threadId ? { thread_id: threadId } : {}),
        ...(userName ? { user_name: userName } : {}),
        active_job_id: jobId,
      });

      // Persist thread_id for future messages
      if (res.data.thread_id) {
        localStorage.setItem(THREAD_KEY(tenantId), res.data.thread_id);
      }

      setLines((prev) => [...prev, { role: "ai", text: res.data.reply }]);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "发送失败，请重试";
      setError(msg);
    } finally {
      setSending(false);
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  return (
    <div className="bg-white/5 rounded-xl p-4 flex flex-col gap-2">
      <p className="text-[10px] text-slate-500">豆豆·复盘</p>

      {/* Conversation area */}
      <div
        ref={scrollRef}
        className="h-32 overflow-y-auto space-y-1 pr-1"
      >
        {lines.length === 0 && (
          <p className="text-[11px] text-slate-600 italic">
            向豆豆提问，结合当前任务进行复盘…
          </p>
        )}
        {lines.map((line, i) =>
          line.role === "user" ? (
            <p key={i} className="text-xs text-right text-slate-300">
              {line.text}
            </p>
          ) : (
            <p key={i} className="text-xs text-left text-cyan-300">
              <span className="text-slate-600 mr-1">豆豆:</span>
              {line.text}
            </p>
          )
        )}
        {sending && (
          <p className="text-xs text-left text-slate-500 animate-pulse">
            豆豆正在思考…
          </p>
        )}
      </div>

      {error && <p className="text-[11px] text-rose-300">{error}</p>}

      {/* Input row */}
      <div className="flex gap-1.5">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={sending}
          placeholder="问豆豆…"
          className="flex-1 min-w-0 bg-white/5 border border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-500/50 disabled:opacity-50"
        />
        <button
          onClick={sendMessage}
          disabled={sending || !input.trim()}
          className="px-3 py-1.5 rounded-lg bg-cyan-500/20 text-cyan-300 text-xs hover:bg-cyan-500/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
        >
          发送
        </button>
      </div>
    </div>
  );
}
