/**
 * 从音频主文件名推断批量模式下的被访谈人与备注（与 AI_Pitch_Coach `audio_filename_hints.py` 对齐）。
 */

const DATE_TAIL = /^(.+?)(\d{8})$/;

export function guessBatchFieldsFromStem(stem: string): [string, string] {
  const s = (stem || "").trim();
  if (!s) {
    return ["", ""];
  }
  if (!s.includes("-")) {
    return [s, ""];
  }
  const dash = s.indexOf("-");
  const org = s.slice(0, dash).trim();
  let rest = s.slice(dash + 1).trim();
  if (!rest) {
    return [org, org ? `机构：${org}` : ""];
  }
  const m = DATE_TAIL.exec(rest);
  if (m) {
    const name = m[1].trim();
    const ymd = m[2];
    const notes = org ? `机构：${org}；录音文件名日期：${ymd}` : `录音文件名日期：${ymd}`;
    return [name || rest, notes];
  }
  const notes = org ? `机构：${org}` : "";
  return [rest, notes];
}

/** 从完整文件名得到主文件名（无扩展名），与 Python `Path.stem` 一致 */
export function stemFromAudioFilename(filename: string): string {
  const f = filename || "";
  const base = f.split(/[/\\]/).pop() ?? f;
  const dot = base.lastIndexOf(".");
  return dot > 0 ? base.slice(0, dot) : base;
}

/**
 * 是否应将自动猜测值写入「被访谈人」（BUG-C）。
 */
export function shouldAutofillIv(currentIv: string, lastAutofilled: string | null | undefined): boolean {
  if (!currentIv) {
    return true;
  }
  if (lastAutofilled == null) {
    return false;
  }
  return currentIv === lastAutofilled;
}
