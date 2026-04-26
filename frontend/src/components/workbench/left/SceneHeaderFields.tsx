
interface SceneHeaderFieldsProps {
  sceneType: string;
  speakerRoles: string;
  totalScore: number;
  totalScoreDeductionReason: string;
  isReadonly: boolean;
  onSceneChange: (field: "scene_type" | "speaker_roles", value: string) => void;
  onScoreChange: (score: number, reason: string) => void;
}

const inputCls =
  "bg-transparent border-b border-white/20 text-sm text-white focus:border-cyan-400/60 outline-none w-full";

export default function SceneHeaderFields({
  sceneType,
  speakerRoles,
  totalScore,
  totalScoreDeductionReason,
  isReadonly,
  onSceneChange,
  onScoreChange,
}: SceneHeaderFieldsProps) {
  return (
    <div className="bg-white/5 rounded-xl p-4 mb-4 space-y-3">
      {/* 小标题 */}
      <p className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">
        总览
      </p>

      {/* 行 1：场景类型 */}
      <div>
        <label className="text-xs text-slate-400 block mb-1">场景类型</label>
        {isReadonly ? (
          <span className="text-sm text-white">{sceneType || "—"}</span>
        ) : (
          <input
            className={inputCls}
            value={sceneType}
            onChange={(e) => onSceneChange("scene_type", e.target.value)}
          />
        )}
      </div>

      {/* 行 2：角色分工 */}
      <div>
        <label className="text-xs text-slate-400 block mb-1">角色分工</label>
        {isReadonly ? (
          <span className="text-sm text-white">{speakerRoles || "—"}</span>
        ) : (
          <input
            className={inputCls}
            value={speakerRoles}
            onChange={(e) => onSceneChange("speaker_roles", e.target.value)}
          />
        )}
      </div>

      {/* 行 3：总分 */}
      <div>
        <label className="text-xs text-slate-400 block mb-1">总分</label>
        {isReadonly ? (
          <span className="text-cyan-400 font-bold text-lg">{totalScore}</span>
        ) : (
          <input
            type="number"
            min={0}
            max={100}
            className={`${inputCls} text-cyan-400 font-bold text-lg w-24`}
            value={totalScore}
            onChange={(e) =>
              onScoreChange(Number(e.target.value), totalScoreDeductionReason)
            }
          />
        )}
      </div>

      {/* 行 4：扣分说明 */}
      <div>
        <label className="text-xs text-slate-400 block mb-1">扣分说明</label>
        {isReadonly ? (
          <p className="text-xs text-slate-300 whitespace-pre-wrap">
            {totalScoreDeductionReason || "—"}
          </p>
        ) : (
          <textarea
            rows={2}
            className={`${inputCls} resize-none`}
            value={totalScoreDeductionReason}
            onChange={(e) => onScoreChange(totalScore, e.target.value)}
          />
        )}
      </div>
    </div>
  );
}
