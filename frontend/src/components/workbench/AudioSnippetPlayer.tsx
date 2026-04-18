// WorkbenchContext 由 ReviewWorkbench.tsx 提供
import { useContext, useState, useCallback } from "react";
import { WorkbenchContext } from "./WorkbenchContext";
import { useAudio } from "./AudioContext";
import type { AudioSnippetPlayerProps } from "../../types/review";

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function AudioSnippetPlayer({
  jobId,
  startWordIndex,
  endWordIndex,
  isManualEntry = false,
}: AudioSnippetPlayerProps) {
  // All hooks must be called unconditionally before any early returns
  const { wordsMap } = useContext(WorkbenchContext);
  const { playSegment, stopAudio, audioRef } = useAudio();
  const [isPlaying, setIsPlaying] = useState(false);

  const startWord = wordsMap.get(startWordIndex);
  const endWord = wordsMap.get(endWordIndex);

  const playStart = startWord ? Math.max(0, startWord.start_time - 1.5) : 0;
  const playEnd = endWord ? endWord.end_time + 8.0 : 0;
  const audioSrc = `/api/pitch/jobs/${jobId}/audio`;

  const handleToggle = useCallback(() => {
    if (isPlaying) {
      stopAudio();
      setIsPlaying(false);
    } else {
      // Sync isPlaying state back to false when segment ends or user pauses
      const audio = audioRef.current;
      if (!audio) return;
      const onPause = () => {
        setIsPlaying(false);
        audio.removeEventListener("pause", onPause);
      };
      audio.addEventListener("pause", onPause);

      playSegment(audioSrc, playStart, playEnd);
      setIsPlaying(true);
    }
  }, [isPlaying, stopAudio, playSegment, audioSrc, playStart, playEnd, audioRef]);

  // Guard: manual entry — no playback anchor available
  if (isManualEntry) {
    return (
      <span className="text-xs text-slate-500 italic">
        人工条目，无词级锚点
      </span>
    );
  }

  // Guard: word indices out of range
  if (!startWord || !endWord) {
    return (
      <span className="text-xs text-red-400/70 italic">
        索引越界，无法定位
      </span>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={handleToggle}
        className="rounded border border-cyan-800/40 bg-cyan-900/60 px-2 py-1 text-xs text-cyan-300 transition-colors hover:bg-cyan-800/80 active:bg-cyan-700/80"
        aria-label={isPlaying ? "暂停" : "播放片段"}
      >
        {isPlaying ? "⏸ 暂停" : "▶ 播放片段"}
      </button>
      <span className="text-xs text-slate-400 tabular-nums">
        {formatTime(startWord.start_time)}
        {" — "}
        {formatTime(endWord.end_time)}
      </span>
    </div>
  );
}
