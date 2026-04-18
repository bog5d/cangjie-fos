import { AnimatePresence, motion } from "framer-motion";

interface Props {
  open: boolean;
  title: string;
  subtitle: string;
  onClose: () => void;
}

/** 资料健康度等里程碑达成时的轻量成就层 */
export function AchievementFlash({ open, title, subtitle, onClose }: Props) {
  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/55 px-4 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            className="max-w-md rounded-3xl border border-ember/40 bg-gradient-to-br from-ember/25 via-black/80 to-plasma/20 p-8 text-center shadow-2xl shadow-ember/20"
            initial={{ scale: 0.85, y: 24, opacity: 0 }}
            animate={{ scale: 1, y: 0, opacity: 1 }}
            exit={{ scale: 0.9, y: 16, opacity: 0 }}
            transition={{ type: "spring", stiffness: 260, damping: 22 }}
            onClick={(e) => e.stopPropagation()}
          >
            <p className="font-display text-[10px] uppercase tracking-[0.45em] text-amber-200/90">Achievement</p>
            <h3 className="mt-3 font-display text-2xl font-bold text-white">{title}</h3>
            <p className="mt-2 text-sm text-slate-300">{subtitle}</p>
            <button
              type="button"
              className="mt-6 rounded-full bg-white/90 px-6 py-2 text-xs font-bold uppercase tracking-widest text-black hover:bg-white"
              onClick={onClose}
            >
              收下
            </button>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
