import { motion } from "framer-motion";

interface Props {
  totalExp: number;
  lastHint: string;
}

export function ExpHud({ totalExp, lastHint }: Props) {
  return (
    <div className="fixed left-1/2 top-4 z-40 flex -translate-x-1/2 flex-col items-center gap-1">
      <div className="flex items-center gap-3 rounded-full border border-plasma/40 bg-black/60 px-5 py-2 font-display text-xs uppercase tracking-[0.25em] text-plasma/90 shadow-lg backdrop-blur-md">
        <span>Exp</span>
        <motion.span
          key={totalExp}
          className="text-lg font-bold text-white tabular-nums"
          initial={{ scale: 1.14, y: -3, color: "#a5f3fc" }}
          animate={{ scale: 1, y: 0, color: "#ffffff" }}
          transition={{ type: "spring", stiffness: 420, damping: 26 }}
        >
          {totalExp}
        </motion.span>
      </div>
      {lastHint ? (
        <p className="max-w-md text-center text-[11px] text-slate-500">{lastHint}</p>
      ) : null}
    </div>
  );
}
