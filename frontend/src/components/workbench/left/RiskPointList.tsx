import type { RiskPoint } from "../../../types/review";
import { RiskPointCard } from "./RiskPointCard";

interface RiskPointListProps {
  points: RiskPoint[];
  isReadonly: boolean;
  onChange: (index: number, updated: RiskPoint) => void;
  onDelete: (index: number) => void;
}

export function RiskPointList({
  points,
  isReadonly,
  onChange,
  onDelete,
}: RiskPointListProps) {
  return (
    <div>
      <p className="text-xs text-slate-400 mb-3">
        风险点（{points.length}条）
      </p>
      {points.length === 0 ? (
        <p className="text-xs text-slate-500">暂无风险点</p>
      ) : (
        points.map((pt, i) => (
          <RiskPointCard
            key={pt._rid ?? i}
            point={pt}
            index={i + 1}
            isReadonly={isReadonly}
            onChange={(updated) => onChange(i, updated)}
            onDelete={() => onDelete(i)}
          />
        ))
      )}
    </div>
  );
}
