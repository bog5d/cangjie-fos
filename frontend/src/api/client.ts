import axios from "axios";

/** 默认不锁 Content-Type，便于 JSON 与 multipart 共用 */
export const api = axios.create({
  baseURL: "",
  timeout: 120000,
});

const apiKey = import.meta.env.VITE_CANGJIE_API_KEY;
if (apiKey) {
  api.interceptors.request.use((config) => {
    const h = (config.headers ??= {}) as Record<string, string>;
    h["X-API-Key"] = String(apiKey);
    return config;
  });
}

// 登录 token 自动注入
api.interceptors.request.use((config) => {
  try {
    const token = localStorage.getItem("fos_token");
    if (token) {
      const h = (config.headers ??= {}) as Record<string, string>;
      h["X-FOS-Token"] = token;
    }
  } catch { /* ignore */ }
  return config;
});

// ── 登录 session 工具函数 ──────────────────────────────────────────────────────

export interface FosSession {
  token: string;
  username: string;
  tenant_id: string;
}

/** 前端 session 最长保留时长：24 小时（后端 token TTL 为 72 小时） */
const SESSION_MAX_AGE_MS = 24 * 60 * 60 * 1000;

export function getSession(): FosSession | null {
  try {
    const raw = localStorage.getItem("fos_session");
    if (!raw) return null;
    const data = JSON.parse(raw) as FosSession & { saved_at?: number };
    // 超过 24 小时自动清除，强制重新登录
    if (data.saved_at && Date.now() - data.saved_at > SESSION_MAX_AGE_MS) {
      clearSession();
      return null;
    }
    return data;
  } catch { return null; }
}

export function saveSession(s: FosSession): void {
  try {
    const payload = { ...s, saved_at: Date.now() };
    localStorage.setItem("fos_session", JSON.stringify(payload));
    localStorage.setItem("fos_token", s.token);
  } catch { /* ignore */ }
}

export function clearSession(): void {
  try {
    localStorage.removeItem("fos_session");
    localStorage.removeItem("fos_token");
  } catch { /* ignore */ }
}
