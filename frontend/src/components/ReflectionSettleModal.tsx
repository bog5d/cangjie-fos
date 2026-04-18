import { AnimatePresence, motion } from "framer-motion";

interface Props {
  open: boolean;
  busy: boolean;
  guideline: string;
  processed: number;
  onClose: () => void;
}

export function ReflectionSettleModal({ open, busy, guideline, processed, onClose }: Props) {
  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 px-4 backdrop-blur-md"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-3xl border border-plasma/35 bg-gradient-to-b from-plasma/15 to-black/90 p-8 shadow-2xl shadow-plasma/25"
            initial={{ scale: 0.88, y: 28, opacity: 0 }}
            animate={{ scale: 1, y: 0, opacity: 1 }}
            exit={{ scale: 0.92, y: 20, opacity: 0 }}
            transition={{ type: "spring", stiffness: 240, damping: 24 }}
            onClick={(e) => e.stopPropagation()}
          >
            <p className="font-display text-[10px] uppercase tracking-[0.4em] text-plasma/90">进化结算</p>
            <h3 className="mt-2 font-display text-xl font-bold text-white">这段时间它变聪明了一点</h3>
            <p className="mt-1 text-xs text-slate-500">已处理 pending 样本：{processed} 条</p>
            <div className="mt-5 rounded-2xl border border-white/10 bg-black/40 p-4 text-left text-sm leading-relaxed text-slate-100 whitespace-pre-wrap">
              {busy ? "结算中…" : guideline || "（暂无新的进化摘要，可先提交几条文本纠错）"}
            </div>
            <button
              type="button"
              className="mt-6 w-full rounded-full border border-white/20 bg-white/10 py-2 text-xs font-bold uppercase tracking-widest text-slate-200 hover:bg-white/20"
              onClick={onClose}
            >
              关闭
            </button>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
