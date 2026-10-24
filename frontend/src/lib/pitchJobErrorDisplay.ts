/**
 * Task Rail / 列表：首屏只展示「说人话」摘要；若仅有 legacy error 且疑似 JSON，则降级为固定句。
 */
export function summaryForJobRow(row: {
  error_summary?: string | null;
  error?: string | null;
}): string {
  const s = (row.error_summary ?? "").trim();
  if (s) {
    return s;
  }
  const e = (row.error ?? "").trim();
  if (!e) {
    return "任务失败";
  }
  if (e.startsWith("{") || e.startsWith("[") || /request_id/i.test(e)) {
    return "处理失败，请展开查看详情或联系管理员";
  }
  return e.length > 140 ? `${e.slice(0, 138)}…` : e;
}
