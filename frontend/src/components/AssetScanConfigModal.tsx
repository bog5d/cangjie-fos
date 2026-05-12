import { useEffect, useState } from "react";
import { api } from "../api/client";

interface Props {
  open: boolean;
  onClose: () => void;
  onScan: (scanDir: string) => void;
}

interface ScanConfig {
  scan_dir: string;
  auto_scan: boolean;
  configured: boolean;
}

export function AssetScanConfigModal({ open, onClose, onScan }: Props) {
  const [scanDir, setScanDir] = useState("");
  const [autoScan, setAutoScan] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    void api.get<ScanConfig>("/api/v1/assets/scan/config").then((res) => {
      setScanDir(res.data.scan_dir || "");
      setAutoScan(res.data.auto_scan || false);
    });
  }, [open]);

  if (!open) return null;

  const handleSave = async () => {
    const dir = scanDir.trim();
    if (!dir) {
      setError("请填写扫描目录路径");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.put("/api/v1/assets/scan/config", { scan_dir: dir, auto_scan: autoScan });
      onScan(dir);
    } catch {
      setError("保存失败，请稍后重试");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center pointer-events-none">
      <button
        type="button"
        className="absolute inset-0 bg-black/75 backdrop-blur-sm pointer-events-auto"
        onClick={onClose}
      />
      <div className="relative w-full max-w-md rounded-2xl border border-cyan/30 bg-gradient-to-b from-[#0a0a14] to-black p-6 shadow-2xl pointer-events-auto">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <p className="text-[10px] uppercase tracking-[0.35em] text-slate-500">资产扫描</p>
            <h2 className="font-display text-base font-bold text-white">配置扫描目录</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-500 hover:text-white"
          >
            ✕
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs text-slate-400">
              资料室根目录路径
            </label>
            <input
              value={scanDir}
              onChange={(e) => setScanDir(e.target.value)}
              placeholder="例：D:\团队资产pbb"
              className="w-full rounded-xl border border-white/15 bg-black/40 px-3 py-2 text-sm text-white placeholder:text-slate-600 focus:border-cyan/40 focus:outline-none"
            />
            <p className="mt-1 text-[11px] text-slate-600">
              将递归扫描此目录下所有文件（跳过 .git / node_modules 等）
            </p>
          </div>

          <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={autoScan}
              onChange={(e) => setAutoScan(e.target.checked)}
              className="accent-cyan-400"
            />
            启动时自动扫描
          </label>

          {error && <p className="text-xs text-red-400">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl border border-white/15 px-4 py-2 text-sm text-slate-400 hover:text-white"
            >
              取消
            </button>
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saving}
              className="rounded-xl bg-cyan-600 px-5 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
            >
              {saving ? "保存中…" : "保存并扫描"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
