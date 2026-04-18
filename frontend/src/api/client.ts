import axios from "axios";

/** 默认不锁 Content-Type，便于 JSON 与 multipart 共用 */
export const api = axios.create({
  baseURL: "",
  timeout: 120000,
});
