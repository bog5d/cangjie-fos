import type { TranscriptionWord } from "../types/review";

/** 统计某词段内说话人 id 出现次数，用于 HITL 风险点副标题。 */
export function inferRiskPointSpeakers(
  wordsMap: Map<number, TranscriptionWord>,
  start: number,
  end: number,
): { dominant: string | null; uniqueIds: string[]; multiSpeaker: boolean } {
  const counts = new Map<string, number>();
  for (let i = start; i <= end; i++) {
    const w = wordsMap.get(i);
    const sid = (w?.speaker_id || "").trim();
    const key = sid || "";
    if (!key) continue;
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  const entries = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  const uniqueIds = entries.map(([k]) => k);
  const multiSpeaker = uniqueIds.length > 1;
  const dominant = entries.length ? entries[0][0] : null;
  return { dominant, uniqueIds, multiSpeaker };
}

export function formatSpeakerIdForUi(id: string | null | undefined): string {
  if (!id || !id.trim()) return "（无说话人标签）";
  return id.trim();
}
