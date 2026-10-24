import {
  createContext,
  useContext,
  useRef,
  useCallback,
  type ReactNode,
} from "react";

interface AudioContextValue {
  audioRef: React.RefObject<HTMLAudioElement>;
  playSegment: (src: string, startSec: number, endSec: number) => void;
  stopAudio: () => void;
}

const AudioCtx = createContext<AudioContextValue | null>(null);

export function AudioProvider({ children }: { children: ReactNode }) {
  const audioRef = useRef<HTMLAudioElement>(new Audio());

  const stopAudio = useCallback(() => {
    const audio = audioRef.current;
    audio.pause();
    // Remove any active timeupdate handler by replacing with a no-op
    audio.ontimeupdate = null;
  }, []);

  const playSegment = useCallback(
    (src: string, startSec: number, endSec: number) => {
      const audio = audioRef.current;

      // 1. Pause current playback
      audio.pause();
      audio.ontimeupdate = null;

      // 2. Set src only if it has changed
      if (audio.src !== src) {
        audio.src = src;
      }

      // 3. Seek to start
      audio.currentTime = startSec;

      // 4. Play
      void audio.play();

      // 5. Monitor and stop at endSec
      audio.ontimeupdate = () => {
        if (audio.currentTime >= endSec) {
          audio.pause();
          audio.ontimeupdate = null;
        }
      };
    },
    []
  );

  return (
    <AudioCtx.Provider value={{ audioRef, playSegment, stopAudio }}>
      {children}
    </AudioCtx.Provider>
  );
}

export function useAudio(): AudioContextValue {
  const ctx = useContext(AudioCtx);
  if (!ctx) {
    throw new Error("useAudio must be used within an AudioProvider");
  }
  return ctx;
}
