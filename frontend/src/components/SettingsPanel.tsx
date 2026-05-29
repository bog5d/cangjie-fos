/**
 * SettingsPanel — API Key 配置面板
 * 点击右上角齿轮图标打开，支持填写/测试 DeepSeek 和 DashScope API Key。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";

interface Props {
  /** 保存 Key 成功后通知父组件重新拉取就绪状态 */
  onKeySaved?: () => void;
}

interface KeyStatus {
  DEEPSEEK_API_KEY: boolean;
  DASHSCOPE_API_KEY: boolean;
  KIMI_API_KEY: boolean;
  COACH_DATA_GITHUB_TOKEN: boolean;
}

interface TestResult {
  ok: boolean;
  message: string;
}

export function SettingsPanel({ onKeySaved }: Props = {}) {
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  // 当前填写的值（空字符串 = 不修改已有的）
  const [githubToken, setGithubToken] = useState("");
  const [deepseekKey, setDeepseekKey] = useState("");
  const [dashscopeKey, setDashscopeKey] = useState("");
  const [kimiKey, setKimiKey] = useState("");

  // 服务器端各 Key 是否已配置
  const [keyStatus, setKeyStatus] = useState<KeyStatus | null>(null);

  // 测试结果
  const [githubTest, setGithubTest] = useState<TestResult | null>(null);
  const [deepseekTest, setDeepseekTest] = useState<TestResult | null>(null);
  const [dashscopeTest, setDashscopeTest] = useState<TestResult | null>(null);

  const [saving, setSaving] = useState(false);
  const [testingGithub, setTestingGithub] = useState(false);
  const [testingDeepseek, setTestingDeepseek] = useState(false);
  const [testingDashscope, setTestingDashscope] = useState(false);
  const [savedMsg, setSavedMsg] = useState("");

  const loadStatus = useCallback(async () => {
    try {
      const r = await api.get<KeyStatus>("/api/v1/settings/api-keys");
      setKeyStatus(r.data);
    } catch {
      /* 忽略，可能后端未启动 */
    }
  }, []);

  useEffect(() => {
    if (open) {
      void loadStatus();
      setGithubTest(null);
      setDeepseekTest(null);
      setDashscopeTest(null);
      setSavedMsg("");
    }
  }, [open, loadStatus]);

  // 点击面板外关闭
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const handleSave = async () => {
    setSaving(true);
    setSavedMsg("");
    const keys: Record<string, string> = {};
    if (githubToken.trim()) keys["COACH_DATA_GITHUB_TOKEN"] = githubToken.trim();
    if (deepseekKey.trim()) keys["DEEPSEEK_API_KEY"] = deepseekKey.trim();
    if (dashscopeKey.trim()) keys["DASHSCOPE_API_KEY"] = dashscopeKey.trim();
    if (kimiKey.trim()) keys["KIMI_API_KEY"] = kimiKey.trim();

    if (Object.keys(keys).length === 0) {
      setSaving(false);
      setSavedMsg("未填写任何内容");
      return;
    }

    try {
      await api.post("/api/v1/settings/api-keys", { keys });
      setGithubToken("");
      setDeepseekKey("");
      setDashscopeKey("");
      setKimiKey("");
      setSavedMsg("✅ 保存成功，立即生效（无需重启）");
      await loadStatus();
      onKeySaved?.();
    } catch {
      setSavedMsg("❌ 保存失败，请重试");
    } finally {
      setSaving(false);
      setTimeout(() => setSavedMsg(""), 4000);
    }
  };

  const handleTestGithub = async () => {
    setTestingGithub(true);
    setGithubTest(null);
    if (githubToken.trim()) {
      try {
        await api.post("/api/v1/settings/api-keys", {
          keys: { COACH_DATA_GITHUB_TOKEN: githubToken.trim() },
        });
      } catch { /* ignore */ }
    }
    try {
      const r = await api.post<TestResult>("/api/v1/settings/api-keys/test-github");
      setGithubTest(r.data);
    } catch {
      setGithubTest({ ok: false, message: "请求失败，请检查网络" });
    } finally {
      setTestingGithub(false);
    }
  };

  const handleTestDeepseek = async () => {
    setTestingDeepseek(true);
    setDeepseekTest(null);
    // 如果当前输入框有内容，先保存再测试
    if (deepseekKey.trim()) {
      try {
        await api.post("/api/v1/settings/api-keys", {
          keys: { DEEPSEEK_API_KEY: deepseekKey.trim() },
        });
      } catch {
        /* ignore */
      }
    }
    try {
      const r = await api.post<TestResult>("/api/v1/settings/api-keys/test-deepseek");
      setDeepseekTest(r.data);
    } catch {
      setDeepseekTest({ ok: false, message: "请求失败，请检查网络" });
    } finally {
      setTestingDeepseek(false);
    }
  };

  const handleTestDashscope = async () => {
    setTestingDashscope(true);
    setDashscopeTest(null);
    if (dashscopeKey.trim()) {
      try {
        await api.post("/api/v1/settings/api-keys", {
          keys: { DASHSCOPE_API_KEY: dashscopeKey.trim() },
        });
      } catch {
        /* ignore */
      }
    }
    try {
      const r = await api.post<TestResult>("/api/v1/settings/api-keys/test-dashscope");
      setDashscopeTest(r.data);
    } catch {
      setDashscopeTest({ ok: false, message: "请求失败，请检查网络" });
    } finally {
      setTestingDashscope(false);
    }
  };

  const statusDot = (configured: boolean | undefined) => (
    <span className={`inline-block h-2 w-2 rounded-full ${configured ? "bg-emerald-400" : "bg-slate-600"}`} />
  );

  return (
    <div className="relative">
      {/* 齿轮按钮 */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title="API Key 设置"
        className="rounded-lg border border-white/10 px-2.5 py-2 text-slate-400 transition hover:border-cyan/40 hover:text-cyan-300"
      >
        ⚙️
      </button>

      {/* 面板 */}
      {open && (
        <div
          ref={panelRef}
          className="absolute right-0 top-full z-50 mt-2 w-96 rounded-xl border border-white/15 bg-slate-900 p-5 shadow-2xl"
        >
          <h3 className="mb-4 font-display text-sm font-bold uppercase tracking-widest text-white">
            API Key 配置
          </h3>

          <div className="space-y-4">
            {/* GitHub 同步 Token */}
            <div>
              <div className="mb-1 flex items-center gap-2">
                {statusDot(keyStatus?.COACH_DATA_GITHUB_TOKEN)}
                <label className="text-xs font-semibold text-slate-300">
                  GitHub 同步 Token
                </label>
                <span className="ml-auto text-[10px] text-slate-500">
                  {keyStatus?.COACH_DATA_GITHUB_TOKEN ? "已配置" : "未配置"}
                </span>
              </div>
              <p className="mb-1.5 text-[10px] text-slate-500">
                用于拉取/推送路演数据到 coach_data 仓库。填写后同步按钮自动生效。
              </p>
              <div className="flex gap-2">
                <input
                  type="password"
                  value={githubToken}
                  onChange={(e) => setGithubToken(e.target.value)}
                  placeholder="ghp_xxxx（GitHub Fine-grained PAT）"
                  className="flex-1 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs text-gray-800 placeholder:text-gray-400"
                />
                <button
                  type="button"
                  disabled={testingGithub}
                  onClick={() => void handleTestGithub()}
                  className="rounded-lg border border-cyan/30 px-2 py-1.5 text-[11px] text-cyan-400 hover:bg-cyan/10 disabled:opacity-50"
                >
                  {testingGithub ? "…" : "测试"}
                </button>
              </div>
              {githubTest && (
                <p className={`mt-1 text-[11px] ${githubTest.ok ? "text-emerald-400" : "text-red-400"}`}>
                  {githubTest.message}
                </p>
              )}
            </div>

            <hr className="border-white/10" />

            {/* DeepSeek */}
            <div>
              <div className="mb-1 flex items-center gap-2">
                {statusDot(keyStatus?.DEEPSEEK_API_KEY)}
                <label className="text-xs font-semibold text-slate-300">
                  DeepSeek API Key
                </label>
                <span className="ml-auto text-[10px] text-slate-500">
                  {keyStatus?.DEEPSEEK_API_KEY ? "已配置" : "未配置"}
                </span>
              </div>
              <div className="flex gap-2">
                <input
                  type="password"
                  value={deepseekKey}
                  onChange={(e) => setDeepseekKey(e.target.value)}
                  placeholder="sk-xxxx（填写以覆盖现有值）"
                  className="flex-1 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs text-gray-800 placeholder:text-gray-400"
                />
                <button
                  type="button"
                  disabled={testingDeepseek}
                  onClick={() => void handleTestDeepseek()}
                  className="rounded-lg border border-cyan/30 px-2 py-1.5 text-[11px] text-cyan-400 hover:bg-cyan/10 disabled:opacity-50"
                >
                  {testingDeepseek ? "…" : "测试"}
                </button>
              </div>
              {deepseekTest && (
                <p className={`mt-1 text-[11px] ${deepseekTest.ok ? "text-emerald-400" : "text-red-400"}`}>
                  {deepseekTest.message}
                </p>
              )}
            </div>

            {/* DashScope */}
            <div>
              <div className="mb-1 flex items-center gap-2">
                {statusDot(keyStatus?.DASHSCOPE_API_KEY)}
                <label className="text-xs font-semibold text-slate-300">
                  阿里云百炼 ASR Key
                </label>
                <span className="ml-auto text-[10px] text-slate-500">
                  {keyStatus?.DASHSCOPE_API_KEY ? "已配置" : "未配置"}
                </span>
              </div>
              <div className="flex gap-2">
                <input
                  type="password"
                  value={dashscopeKey}
                  onChange={(e) => setDashscopeKey(e.target.value)}
                  placeholder="sk-xxxx（填写以覆盖现有值）"
                  className="flex-1 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs text-gray-800 placeholder:text-gray-400"
                />
                <button
                  type="button"
                  disabled={testingDashscope}
                  onClick={() => void handleTestDashscope()}
                  className="rounded-lg border border-cyan/30 px-2 py-1.5 text-[11px] text-cyan-400 hover:bg-cyan/10 disabled:opacity-50"
                >
                  {testingDashscope ? "…" : "测试"}
                </button>
              </div>
              {dashscopeTest && (
                <p className={`mt-1 text-[11px] ${dashscopeTest.ok ? "text-emerald-400" : "text-red-400"}`}>
                  {dashscopeTest.message}
                </p>
              )}
            </div>

            {/* Kimi（可选） */}
            <div>
              <div className="mb-1 flex items-center gap-2">
                {statusDot(keyStatus?.KIMI_API_KEY)}
                <label className="text-xs font-semibold text-slate-300">
                  Kimi API Key <span className="text-slate-500">（可选）</span>
                </label>
                <span className="ml-auto text-[10px] text-slate-500">
                  {keyStatus?.KIMI_API_KEY ? "已配置" : "未配置"}
                </span>
              </div>
              <input
                type="password"
                value={kimiKey}
                onChange={(e) => setKimiKey(e.target.value)}
                placeholder="sk-xxxx（填写以覆盖现有值）"
                className="w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs text-gray-800 placeholder:text-gray-400"
              />
            </div>
          </div>

          <div className="mt-5 flex items-center gap-3">
            <button
              type="button"
              disabled={saving}
              onClick={() => void handleSave()}
              className="rounded-lg bg-cyan/20 px-4 py-2 text-xs font-bold text-cyan-300 hover:bg-cyan/30 disabled:opacity-50"
            >
              {saving ? "保存中…" : "保存"}
            </button>
            {savedMsg && (
              <span className="text-[11px] text-slate-300">{savedMsg}</span>
            )}
          </div>

          <p className="mt-3 text-[10px] text-slate-600">
            Key 保存后立即生效，无需重启服务。Key 存储于 backend/.env，不会上传到网络。
          </p>
        </div>
      )}
    </div>
  );
}
