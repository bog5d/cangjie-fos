import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { AssetIndexResponse, AssetItem } from "../types/assets";
import { AssetHealthPanel } from "./AssetHealthPanel";
import { AssetScanConfigModal } from "./AssetScanConfigModal";
import { MatchMakerPanel } from "./MatchMakerPanel";

function TagBadge({ tag }: { tag: string }) {
  return (
    <span className="rounded-full border border-cyan/30 bg-cyan/10 px-2 py-0.5 text-[11px] text-cyan">
      {tag}
    </span>
  );
}

function AssetRow({ asset }: { asset: AssetItem }) {
  const dir = asset.relative_path || "根目录";
  return (
    <tr className="border-b border-white/5 transition hover:bg-white/5">
      <td className="py-2.5 pr-4 align-top">
        <p className="text-sm font-medium text-white">{asset.filename}</p>
        <p className="mt-0.5 text-xs text-slate-500">{dir}</p>
      </td>
      <td className="py-2.5 pr-4 align-top text-xs text-slate-400">
        {asset.summary || <span className="text-slate-600">—</span>}
      </td>
      <td className="py-2.5 pr-4 align-top">
        <div className="flex flex-wrap gap-1">
          {asset.tags.length > 0
            ? asset.tags.map((t) => <TagBadge key={t} tag={t} />)
            : <span className="text-xs text-slate-600">—</span>}
        </div>
      </td>
      <td className="py-2.5 align-top text-xs text-slate-500 tabular-nums">
        {asset.last_modified}
      </td>
    </tr>
  );
}

export function AssetLibrary() {
  const [data, setData] = useState<AssetIndexResponse | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [scanModalOpen, setScanModalOpen] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [scanStatus, setScanStatus] = useState<string | null>(null);

  const fetchAssets = useCallback(async (q: string) => {
    setLoading(true);
    setError(null);
    try {
      const url = q.trim()
        ? `/api/v1/assets/search?q=${encodeURIComponent(q.trim())}`
        : "/api/v1/assets";
      const res = await api.get<AssetIndexResponse>(url);
      setData(res.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchAssets("");
  }, [fetchAssets]);

  // debounce search
  useEffect(() => {
    const t = setTimeout(() => void fetchAssets(query), 300);
    return () => clearTimeout(t);
  }, [query, fetchAssets]);

  const notSynced = !data?.generated_at;
  const bridge = (data?.bridge_dir || "").trim();

  const copyBridge = useCallback(() => {
    if (!bridge) return;
    void navigator.clipboard.writeText(bridge).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [bridge]);

  const triggerScan = useCallback(async (scanDir?: string) => {
    setScanning(true);
    setScanStatus(null);
    try {
      const url = scanDir
        ? `/api/v1/assets/scan?scan_dir=${encodeURIComponent(scanDir)}`
        : "/api/v1/assets/scan";
      const res = await api.post<{ indexed: number; scanned_at: string }>(url);
      setScanStatus(`扫描完成，已索引 ${res.data.indexed} 个文件`);
      void fetchAssets(query);
    } catch {
      setScanStatus("扫描失败，请检查目录配置");
    } finally {
      setScanning(false);
    }
  }, [fetchAssets, query]);

  return (
    <section className="mt-8 rounded-2xl border border-white/10 bg-white/3 p-6">
      <div className="mb-4 flex flex-col gap-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="font-display text-lg font-bold text-white">资产台账</h2>
            <p className="text-xs text-slate-500">
              {data?.generated_at
                ? `FSS 同步于 ${data.generated_at.replace("T", " ")}　共 ${data.total_files} 个文件`
                : "暂无数据 — 请先在仓颉资产台账（FSS）中运行「向上扫描」"}
            </p>
          </div>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索文件名 / 摘要 / 标签…"
            className="w-full rounded-xl border border-white/15 bg-black/40 px-3 py-2 text-sm text-white placeholder:text-slate-600 sm:max-w-xs"
          />
        </div>
        <div className="flex flex-wrap gap-2 items-center text-xs">
          <button
            type="button"
            onClick={() => void fetchAssets(query)}
            className="rounded-lg border border-white/20 bg-white/5 px-3 py-1.5 text-cyan-200 hover:border-cyan-500/40"
          >
            刷新列表
          </button>
          <button
            type="button"
            onClick={() => setScanModalOpen(true)}
            disabled={scanning}
            className="rounded-lg border border-cyan-500/40 bg-cyan-950/40 px-3 py-1.5 text-cyan-300 hover:border-cyan-400/60 disabled:opacity-50"
          >
            {scanning ? "扫描中…" : "配置并扫描"}
          </button>
          {bridge ? (
            <button
              type="button"
              onClick={copyBridge}
              className="rounded-lg border border-white/15 px-3 py-1.5 text-slate-300 hover:border-white/30"
            >
              {copied ? "已复制路径" : "复制桥目录路径"}
            </button>
          ) : null}
          {bridge ? (
            <span className="text-[10px] text-slate-600 break-all max-w-full sm:max-w-xl">
              桥：{bridge}
            </span>
          ) : null}
        </div>
        {scanStatus && (
          <p className="text-xs text-cyan-400/80">{scanStatus}</p>
        )}
      </div>

      {loading && (
        <p className="py-10 text-center text-sm text-slate-500">加载中…</p>
      )}

      {error && (
        <p className="py-6 text-center text-sm text-red-400">{error}</p>
      )}

      {!loading && !error && notSynced && (
        <div className="rounded-xl border border-yellow-500/20 bg-yellow-500/5 px-5 py-6 text-center">
          <p className="text-sm text-yellow-300">尚未找到资产数据</p>
          <p className="mt-1 text-xs text-slate-500">
            点击「配置并扫描」设置素材目录，FOS 将自动索引所有文件。
          </p>
        </div>
      )}

      {!loading && !error && !notSynced && (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-white/10 text-xs font-semibold uppercase tracking-wider text-slate-500">
                <th className="pb-2 pr-4">文件名称</th>
                <th className="pb-2 pr-4">摘要</th>
                <th className="pb-2 pr-4">场景标签</th>
                <th className="pb-2">更新日期</th>
              </tr>
            </thead>
            <tbody>
              {data!.assets.length === 0 ? (
                <tr>
                  <td colSpan={4} className="py-8 text-center text-sm text-slate-500">
                    没有匹配的文件
                  </td>
                </tr>
              ) : (
                data!.assets.map((a) => (
                  <AssetRow key={`${a.relative_path}/${a.filename}`} asset={a} />
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      <AssetHealthPanel />
      <MatchMakerPanel />

      <AssetScanConfigModal
        open={scanModalOpen}
        onClose={() => setScanModalOpen(false)}
        onScan={(dir) => {
          setScanModalOpen(false);
          void triggerScan(dir);
        }}
      />
    </section>
  );
}
