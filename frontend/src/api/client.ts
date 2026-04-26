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
