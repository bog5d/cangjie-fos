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

export function getSession(): FosSession | null {
  try {
    const raw = localStorage.getItem("fos_session");
    return raw ? (JSON.parse(raw) as FosSession) : null;
  } catch { return null; }
}

export function saveSession(s: FosSession): void {
  try {
    localStorage.setItem("fos_session", JSON.stringify(s));
    localStorage.setItem("fos_token", s.token);
  } catch { /* ignore */ }
}

export function clearSession(): void {
  try {
    localStorage.removeItem("fos_session");
    localStorage.removeItem("fos_token");
  } catch { /* ignore */ }
}
