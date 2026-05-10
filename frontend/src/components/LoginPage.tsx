import { useState } from "react";
import { api, saveSession, type FosSession } from "../api/client";

interface LoginResponse {
  token: string;
  username: string;
  tenant_id: string;
  message: string;
}

interface Props {
  onLogin: (session: FosSession) => void;
}

export function LoginPage({ onLogin }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pulling, setPulling] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError("请输入账号和密码");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api.post<LoginResponse>("/api/auth/login", {
        username: username.trim(),
        password: password.trim(),
      });
      const session: FosSession = {
        token: res.data.token,
        username: res.data.username,
        tenant_id: res.data.tenant_id,
      };
      saveSession(session);
      setPulling(true);
      // 等待 2 秒让后台 pull 启动（友好提示）
      await new Promise((r) => setTimeout(r, 2000));
      onLogin(session);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "登录失败，请检查账号密码";
      setError(msg);
      setLoading(false);
      setPulling(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-950 px-4">
      <div className="w-full max-w-sm">
        {/* Logo 区 */}
        <div className="mb-10 text-center">
          <p className="font-display text-xs uppercase tracking-[0.4em] text-slate-500">
            CangJie FOS
          </p>
          <h1 className="mt-1 font-display text-3xl font-bold text-white">
            融资作战系统
          </h1>
          <p className="mt-2 text-sm text-slate-500">
            请使用团队账号登录
          </p>
        </div>

        {/* 登录卡片 */}
        <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-8 shadow-2xl">
          {pulling ? (
            <div className="text-center py-6">
              <div className="mb-4 text-4xl animate-pulse">🔄</div>
              <p className="text-sm font-semibold text-white">正在同步最新数据…</p>
              <p className="mt-1 text-xs text-slate-400">从 GitHub 拉取团队历史数据</p>
              <div className="mt-4 h-1 rounded-full bg-white/10 overflow-hidden">
                <div className="h-full rounded-full bg-cyan-500 animate-[progress_2s_linear_forwards]" style={{width: "100%", transformOrigin: "left"}} />
              </div>
            </div>
          ) : (
            <form onSubmit={(e) => void handleSubmit(e)} className="space-y-5">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-400">
                  账号
                </label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="例：zt001"
                  autoComplete="username"
                  autoFocus
                  className="w-full rounded-xl border border-white/15 bg-black/40 px-3 py-2.5 text-sm text-white placeholder:text-slate-600 focus:border-cyan-500/50 focus:outline-none focus:ring-1 focus:ring-cyan-500/30"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-400">
                  密码
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••"
                  autoComplete="current-password"
                  className="w-full rounded-xl border border-white/15 bg-black/40 px-3 py-2.5 text-sm text-white placeholder:text-slate-600 focus:border-cyan-500/50 focus:outline-none focus:ring-1 focus:ring-cyan-500/30"
                />
              </div>

              {error && (
                <div className="rounded-lg border border-red-500/30 bg-red-950/20 px-3 py-2 text-xs text-red-400">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full rounded-xl bg-gradient-to-r from-cyan-600 to-cyan-500 py-2.5 font-display text-sm font-bold tracking-wide text-white shadow-lg shadow-cyan-500/25 transition hover:brightness-110 disabled:opacity-50"
              >
                {loading ? "登录中…" : "登 录"}
              </button>
            </form>
          )}
        </div>

        <p className="mt-6 text-center text-[11px] text-slate-600">
          数据在本地处理 · 分析结果同步至团队数据库
        </p>
      </div>
    </div>
  );
}
