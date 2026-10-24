export type TranscriptPreview = {
  charCount: number;
  lineCount: number;
  speakerCount: number;
  speakers: string[];
  hasSpeakerLabels: boolean;
  quality: "good" | "warning" | "poor";
  message: string;
};

const SPEAKER_PATTERNS = [
  /^说话人\s*([A-Za-z0-9一-鿿]+)\s*[：:]\s*(.+)$/,
  /^Speaker\s*([A-Za-z0-9]+)\s*[：:]\s*(.+)$/i,
  /^\[([A-Za-z0-9一-鿿]+)\]\s*(.+)$/,
  /^【([A-Za-z0-9一-鿿]+)】\s*(.+)$/,
  /^([A-Za-z一-鿿]{1,6})\s*[：:]\s*(.+)$/,
];

export function analyzeTranscript(text: string): TranscriptPreview {
  const trimmed = text.trim();
  const lines = trimmed.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const speakers = new Set<string>();

  for (const line of lines) {
    for (const pattern of SPEAKER_PATTERNS) {
      const m = pattern.exec(line);
      if (m?.[1]) {
        speakers.add(m[1].trim());
        break;
      }
    }
  }

  const charCount = trimmed.length;
  const hasSpeakerLabels = speakers.size > 0;
  let quality: TranscriptPreview["quality"] = "good";
  let message = `已识别 ${speakers.size} 位说话人，适合直接分析。`;

  if (!trimmed) {
    quality = "poor";
    message = "请粘贴或上传文字稿。";
  } else if (charCount < 80) {
    quality = "poor";
    message = "文字稿偏短，分析结论可能不稳定。";
  } else if (!hasSpeakerLabels) {
    quality = "warning";
    message = "未识别到说话人标签，将按单人连续发言处理。";
  } else if (speakers.size === 1) {
    quality = "warning";
    message = "只识别到 1 位说话人，如是对话请补充说话人标签。";
  }

  return {
    charCount,
    lineCount: lines.length,
    speakerCount: speakers.size,
    speakers: Array.from(speakers).slice(0, 8),
    hasSpeakerLabels,
    quality,
    message,
  };
}

export function transcriptFileLooksReadable(file: File): boolean {
  const name = file.name.toLowerCase();
  return (
    name.endsWith(".txt") ||
    name.endsWith(".md") ||
    name.endsWith(".srt") ||
    name.endsWith(".vtt")
  );
}
