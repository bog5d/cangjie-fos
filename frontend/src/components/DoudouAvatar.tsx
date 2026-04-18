import { useCallback, useState } from "react";
import { NPC_DISPLAY_NAME } from "../constants/npc";

export type DoudouNpcUiState = "idle" | "listening" | "thinking" | "proactive_push";

type AvatarSize = "sm" | "md" | "lg";

const sizeClass: Record<AvatarSize, string> = {
  sm: "h-7 w-7 min-h-7 min-w-7",
  md: "h-10 w-10 min-h-10 min-w-10",
  lg: "h-14 w-14 min-h-14 min-w-14",
};

const coreInset: Record<AvatarSize, string> = {
  sm: "inset-[24%]",
  md: "inset-[26%]",
  lg: "inset-[26%]",
};

function HudRays() {
  const rays = [0, 45, 90, 135, 180, 225, 270, 315];
  return (
    <svg
      className="pointer-events-none absolute inset-0 h-full w-full motion-safe:animate-hudTick"
      viewBox="0 0 100 100"
      aria-hidden
    >
      {rays.map((deg) => {
        const rad = (deg * Math.PI) / 180;
        const x2 = 50 + 41 * Math.cos(rad);
        const y2 = 50 + 41 * Math.sin(rad);
        return (
          <line
            key={deg}
            x1="50"
            y1="50"
            x2={x2}
            y2={y2}
            stroke="rgba(46,196,182,0.11)"
            strokeWidth={0.55}
            vectorEffect="non-scaling-stroke"
          />
        );
      })}
    </svg>
  );
}

export type DoudouAvatarProps = {
  size?: AvatarSize;
  npcState?: DoudouNpcUiState;
  className?: string;
};

/**
 * 轨道环 + 柔光晕 + 中心 **`/doudou-core.png`** 光核（图缺失时回退「豆」字）。
 */
export function DoudouAvatar({ size = "md", npcState = "listening", className = "" }: DoudouAvatarProps) {
  const thinking = npcState === "thinking";
  const proactive = npcState === "proactive_push";
  const listening = npcState === "listening";
  const [imgBroken, setImgBroken] = useState(false);
  const onImgError = useCallback(() => setImgBroken(true), []);

  return (
    <div
      className={`relative ${sizeClass[size]} ${className}`}
      title={NPC_DISPLAY_NAME}
      role="img"
      aria-label={NPC_DISPLAY_NAME}
    >
      <div
        className={`pointer-events-none absolute inset-0 rounded-full border border-cyan/18 ${
          thinking ? "motion-safe:animate-orbitDrift" : ""
        } ${proactive ? "motion-safe:animate-emberSoft border-ember/25" : ""} ${
          listening && !thinking && !proactive ? "border-cyan/14" : ""
        }`}
        style={thinking ? { borderStyle: "dashed", borderDasharray: "1 5" } : undefined}
      />
      {thinking ? (
        <div
          className="pointer-events-none absolute inset-[2px] rounded-full border border-cyan/10 motion-safe:animate-orbitDriftSlow"
          style={{ borderDasharray: "2 9" }}
        />
      ) : null}
      {thinking ? <HudRays /> : null}

      <div
        className={`pointer-events-none absolute inset-[14%] rounded-full bg-gradient-to-br from-plasma/35 via-cyan/22 to-plasma/25 blur-md ${
          thinking ? "motion-safe:animate-haloDeepBreath" : "opacity-[0.42]"
        }`}
      />

      <div
        className={`absolute ${coreInset[size]} z-[1] overflow-hidden rounded-full ring-1 ring-cyan/20 ring-offset-0 ring-offset-black/30`}
      >
        {!imgBroken ? (
          <img
            src="/doudou-core.png"
            alt=""
            className="h-full w-full object-cover"
            draggable={false}
            onError={onImgError}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-gradient-to-b from-[#16122a] to-[#060812] font-display text-[10px] font-semibold text-cyan-100/90">
            豆
          </div>
        )}
      </div>
    </div>
  );
}

export type DoudouPresenceProps = {
  npcState: DoudouNpcUiState;
  subtitle?: string;
};

export function DoudouPresence({ npcState, subtitle }: DoudouPresenceProps) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <DoudouAvatar size="lg" npcState={npcState} className="shrink-0" />
      <div className="min-w-0">
        <p className="font-display text-[10px] uppercase tracking-[0.28em] text-plasma/90">
          {subtitle ?? "主动 NPC · 灵能中枢"}
        </p>
        <h2 className="truncate font-display text-lg font-semibold tracking-tight text-white">{NPC_DISPLAY_NAME}</h2>
      </div>
    </div>
  );
}

export type MessageSideAvatarProps = {
  variant: "npc" | "user";
  npcState?: DoudouNpcUiState;
  userInitial?: string;
};

export function MessageSideAvatar({ variant, npcState = "listening", userInitial }: MessageSideAvatarProps) {
  if (variant === "npc") {
    return <DoudouAvatar size="sm" npcState={npcState} className="opacity-95" />;
  }
  const ch = (userInitial?.trim()?.[0] || "指").toUpperCase();
  return (
    <div
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-white/12 bg-gradient-to-br from-slate-700/90 to-slate-950 font-display text-[11px] font-bold text-slate-100 shadow-inner"
      aria-hidden
    >
      {ch}
    </div>
  );
}
