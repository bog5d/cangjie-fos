import { useEffect, useState } from "react";

export interface ScoreToastItem {
  id: string;
  delta: number;
  reason: string;
}

interface Props {
  items: ScoreToastItem[];
  onDone: (id: string) => void;
}

export function ScoreToastStack({ items, onDone }: Props) {
  return (
    <div className="pointer-events-none fixed right-6 top-24 z-50 flex flex-col gap-3">
      {items.map((t) => (
        <ScoreToast key={t.id} item={t} onDone={onDone} />
      ))}
    </div>
  );
}

function ScoreToast({
  item,
  onDone,
}: {
  item: ScoreToastItem;
  onDone: (id: string) => void;
}) {
  const [show, setShow] = useState(true);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setShow(false);
      window.setTimeout(() => onDone(item.id), 400);
    }, 2200);
    return () => window.clearTimeout(t);
  }, [item.id, onDone]);

  if (!show) return null;

  const sign = item.delta >= 0 ? "+" : "";
  return (
    <div
      className="animate-scorePop rounded-2xl border border-ember/40 bg-gradient-to-r from-ember/25 to-plasma/20 px-5 py-3 font-display text-sm font-semibold tracking-wide text-amber-100 shadow-lg shadow-ember/20 backdrop-blur-md"
      role="status"
    >
      <span className="text-ember">{sign + item.delta}</span>
      <span className="ml-2 text-slate-200">{item.reason}</span>
    </div>
  );
}
