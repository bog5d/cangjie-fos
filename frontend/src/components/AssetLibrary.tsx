import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { AssetIndexResponse, AssetItem } from "../types/assets";
import { AssetHealthPanel } from "./AssetHealthPanel";
import { AssetScanConfigModal } from "./AssetScanConfigModal";
import { InstitutionArchivePanel } from "./InstitutionArchivePanel";
import { MatchMakerPanel } from "./MatchMakerPanel";

// ─── 常量 ─────────────────────────────────────────────────────────────────────

const PAGE_SIZE = 50;

// ─── 文件类型分组定义 ─────────────────────────────────────────────────────────
// 关键词顺序即权重：靠前的更特异（"营业执照" > "执照" > "证书"）

const CATEGORY_DEFS = [
  {
    key: "bp",
    label: "📋 BP / 商业计划",
    keywords: ["bp", "商业计划", "business plan", "pitch", "路演", "融资计划", "项目介绍", "一页纸"],
  },
  {
    key: "finance",
    label: "📊 财务报表",
    keywords: ["财务", "资产负债", "利润", "现金流", "审计", "financial", "财报", "资金",
               "收入", "报表", "核算", "月报", "季报", "年报", "损益"],
  },
  {
    key: "equity",
    label: "🏛 股权结构",
    keywords: ["股权", "股东", "cap table", "持股", "投资协议", "期权", "vesting",
               "shareholding", "equity", "股权激励", "架构"],
  },
  {
    key: "team",
    label: "👥 核心团队",
    keywords: ["简历", "团队", "创始人", "合伙人", "联创", "biography", "resume", "cv",
               "个人介绍", "background", "人员"],
  },
  {
    key: "product",
    label: "🚀 产品 / 技术",
    keywords: ["产品", "技术", "架构", "白皮书", "roadmap", "需求", "功能", "原型",
               "prototype", "product", "demo", "方案", "解决方案"],
  },
  {
    key: "market",
    label: "📈 市场分析",
    keywords: ["市场", "竞品", "竞争", "行业", "分析", "research", "survey", "调研",
               "用户研究", "市调", "赛道", "趋势"],
  },
  {
    key: "legal",
    label: "⚖️ 法律合规",
    keywords: ["协议", "合同", "保密", "nda", "章程", "公司章程", "资质", "认证",
               "专利", "证书", "备案", "合规", "legal"],
  },
  {
    key: "license",
    label: "📜 营业执照",
    keywords: ["营业执照", "business license", "执照"],
  },
  {
    key: "other",
    label: "📁 其他文件",
    keywords: [],
  },
] as const;

type CatKey = (typeof CATEGORY_DEFS)[number]["key"];

/**
 * 多信号优先级分类：tags > 目录路径 > 文件名 > 摘要
 * 每层独立判断，靠前层命中即返回，防止低质信号污染高质信号。
 */
function categorizeAsset(a: AssetItem): CatKey {
  const cats = CATEGORY_DEFS.slice(0, -1);

  const matchAny = (text: string) => {
    const t = text.toLowerCase();
    for (const cat of cats) {
      if (cat.keywords.some((k) => t.includes(k))) return cat.key;
    }
    return null;
  };

  // 1. Tags（扫描引擎语义标注，置信度最高）
  for (const tag of a.tags) {
    const hit = matchAny(tag);
    if (hit) return hit;
  }
  // 2. 目录路径各段（用户自己组织的文件夹结构）
  const pathParts = a.relative_path.split(/[/\\]/).filter(Boolean);
  for (const part of pathParts) {
    const hit = matchAny(part);
    if (hit) return hit;
  }
  // 3. 文件名
  const fnHit = matchAny(a.filename);
  if (fnHit) return fnHit;
  // 4. 摘要（最后兜底）
  const sumHit = matchAny(a.summary);
  if (sumHit) return sumHit;

  return "other";
}

// ─── 目录分组（按顶层文件夹名，0误判） ───────────────────────────────────────

function topDir(a: AssetItem): string {
  const parts = a.relative_path.split(/[/\\]/).filter(Boolean);
  return parts[0] || "（根目录）";
}

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

function daysSince(s: string): number {
  if (!s) return 9999;
  try { return (Date.now() - new Date(s.replace(" ", "T")).getTime()) / 86_400_000; }
  catch { return 9999; }
}

type FreshLevel = "active" | "sleeping" | "zombie";
function freshLevel(a: AssetItem): FreshLevel {
  const d = daysSince(a.last_modified);
  if (d <= 30) return "active";
  if (d <= 90) return "sleeping";
  return "zombie";
}
function needsAttention(a: AssetItem) {
  return daysSince(a.last_modified) > 90 || !a.summary.trim();
}
const FRESH_DOT: Record<FreshLevel, string> = {
  active: "bg-emerald-400", sleeping: "bg-amber-400", zombie: "bg-red-400/70",
};
const FRESH_LABEL: Record<FreshLevel, string> = {
  active: "近期活跃", sleeping: "待更新", zombie: "已超期",
};
const FRESH_COLOR: Record<FreshLevel, string> = {
  active: "text-emerald-400", sleeping: "text-amber-400", zombie: "text-red-400",
};

// ─── 文件状态 ─────────────────────────────────────────────────────────────────

const STATUS_LABEL: Record<string, string> = {
  draft:    "草稿",
  approved: "定稿",
  sent:     "已发出",
  archived: "已归档",
};

const STATUS_COLOR: Record<string, string> = {
  draft:    "border-slate-600 bg-slate-800/50 text-slate-400",
  approved: "border-emerald-500/40 bg-emerald-950/40 text-emerald-400",
  sent:     "border-cyan-500/40 bg-cyan-950/40 text-cyan-400",
  archived: "border-white/10 bg-white/5 text-slate-600",
};

function StatusBadge({
  status,
  onClick,
}: {
  status: string | undefined;
  onClick?: (e: React.MouseEvent) => void;
}) {
  const s = status ?? "approved";
  return (
    <span
      onClick={onClick}
      title={onClick ? "点击修改状态" : undefined}
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium transition
        ${STATUS_COLOR[s] ?? STATUS_COLOR.approved}
        ${onClick ? "cursor-pointer hover:opacity-80" : ""}`}
    >
      {STATUS_LABEL[s] ?? s}
    </span>
  );
}

// ─── TagBadge ─────────────────────────────────────────────────────────────────

function TagBadge({ tag }: { tag: string }) {
  return (
    <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-0.5 text-[11px] text-cyan-400">
      {tag}
    </span>
  );
}

// ─── 侧滑详情面板 ─────────────────────────────────────────────────────────────

function AssetDetailPanel({ asset, onClose }: { asset: AssetItem; onClose: () => void }) {
  const level = freshLevel(asset);
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="fixed inset-y-0 right-0 z-50 flex w-[26rem] max-w-[92vw] flex-col border-l border-white/10 bg-gray-950 shadow-2xl">
        <div className="flex items-start justify-between border-b border-white/10 px-5 py-4">
          <div className="min-w-0 flex-1 pr-3">
            <p className="break-words text-base font-semibold leading-snug text-white">{asset.filename}</p>
            <p className={`mt-1 text-xs ${FRESH_COLOR[level]}`}>
              {FRESH_LABEL[level]}&ensp;·&ensp;{asset.last_modified?.slice(0, 10) || "—"}
            </p>
          </div>
          <button onClick={onClose} className="shrink-0 rounded-lg p-1.5 text-slate-500 hover:bg-white/10 hover:text-white">
            <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
              <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
            </svg>
          </button>
        </div>
        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5">
          <PanelSection label="路径">
            <p className="break-all text-xs leading-relaxed text-slate-300">{asset.full_path || asset.relative_path || "—"}</p>
          </PanelSection>
          <PanelSection label="摘要">
            {asset.summary
              ? <p className="text-sm leading-relaxed text-slate-200">{asset.summary}</p>
              : <p className="text-xs italic text-slate-600">暂无摘要</p>}
          </PanelSection>
          {asset.tags.length > 0 && (
            <PanelSection label="场景标签">
              <div className="flex flex-wrap gap-1.5">{asset.tags.map(t => <TagBadge key={t} tag={t} />)}</div>
            </PanelSection>
          )}
        </div>
        <div className="border-t border-white/10 px-5 py-4">
          <p className="text-[11px] text-slate-600">点击背景关闭</p>
        </div>
      </div>
    </>
  );
}

function PanelSection({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      {children}
    </div>
  );
}

// ─── Tab 按钮 ─────────────────────────────────────────────────────────────────

type TabKey = "active" | "attention" | "all";

function TabBtn({ label, count, active, dot, onClick }: {
  label: string; count: number; active: boolean; dot?: string; onClick: () => void;
}) {
  return (
    <button type="button" onClick={onClick}
      className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition ${
        active ? "border border-cyan-500/40 bg-cyan-500/15 text-cyan-300"
               : "border border-transparent text-slate-400 hover:text-white"
      }`}
    >
      {dot && <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />}
      {label}
      <span className={`rounded-full px-1.5 py-px text-[10px] font-mono ${
        active ? "bg-cyan-500/25 text-cyan-200" : "bg-white/8 text-slate-600"
      }`}>{count}</span>
    </button>
  );
}

// ─── 资产 Wiki 浮层 ──────────────────────────────────────────────────────────

interface AssetWikiData {
  total_selected: number;
  total_shown: number;
  selection_rate: number;
  institutions: { institution: string; times: number }[];
  last_selected: number | null;
}

function AssetWikiPanel({ path, onClose }: { path: string; onClose: () => void }) {
  const [data, setData] = useState<AssetWikiData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void api.get<AssetWikiData>(`/api/v1/assets/wiki/${encodeURIComponent(path)}`)
      .then(r => setData(r.data))
      .finally(() => setLoading(false));
  }, [path]);

  function fmtDate(ts: number | null) {
    if (!ts) return "—";
    try { return new Date(ts * 1000).toISOString().slice(0, 10); } catch { return "—"; }
  }

  return (
    <tr className="bg-slate-900/60">
      <td colSpan={7} className="px-4 pb-3 pt-0">
        <div className="rounded-xl border border-white/8 bg-black/30 p-3 text-xs">
          {loading ? (
            <p className="text-slate-500">加载历史…</p>
          ) : data && data.total_shown > 0 ? (
            <div className="space-y-1.5">
              <div className="flex gap-4 text-slate-400">
                <span>📤 被选中 <strong className="text-white">{data.total_selected}</strong> 次</span>
                <span>出现 <strong className="text-white">{data.total_shown}</strong> 次</span>
                <span>选中率 <strong className="text-white">{Math.round(data.selection_rate * 100)}%</strong></span>
                <span>最近选中 <strong className="text-white">{fmtDate(data.last_selected)}</strong></span>
              </div>
              {data.institutions.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {data.institutions.map(i => (
                    <span key={i.institution} className="rounded border border-cyan-500/20 bg-cyan-950/20 px-1.5 py-0.5 text-[10px] text-cyan-400">
                      {i.institution} ×{i.times}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="text-slate-600">暂无匹配历史</p>
          )}
          <button
            type="button"
            onClick={onClose}
            className="mt-2 text-slate-600 hover:text-slate-400"
          >
            收起 ↑
          </button>
        </div>
      </td>
    </tr>
  );
}

// ─── 资产行（共用） ───────────────────────────────────────────────────────────

function AssetRow({ asset, selected, onSelect, onClick, onStatusChange }: {
  asset: AssetItem; selected: boolean;
  onSelect: (c: boolean) => void; onClick: () => void;
  onStatusChange?: (status: string) => void;
}) {
  const level = freshLevel(asset);
  const [wikiOpen, setWikiOpen] = useState(false);

  const cycleStatus = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!onStatusChange) return;
    const cycle: Record<string, string> = {
      draft: "approved", approved: "sent", sent: "archived", archived: "draft",
    };
    onStatusChange(cycle[asset.asset_status ?? "approved"] ?? "approved");
  };

  return (
    <>
      <tr className={`group cursor-pointer border-b border-white/5 transition-colors ${selected ? "bg-cyan-950/30" : "hover:bg-white/5"}`} onClick={onClick}>
        <td className="w-8 py-2.5 pl-3 align-middle" onClick={e => { e.stopPropagation(); onSelect(!selected); }}>
          <input type="checkbox" checked={selected} onChange={e => onSelect(e.target.checked)}
            className={`h-3.5 w-3.5 cursor-pointer rounded transition-opacity ${selected ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
          />
        </td>
        <td className="w-4 py-2.5 pr-2 align-middle">
          <span className={`inline-block h-1.5 w-1.5 rounded-full ${FRESH_DOT[level]}`} title={FRESH_LABEL[level]} />
        </td>
        <td className="py-2.5 pr-4 align-top">
          <p className="text-sm font-medium text-white">{asset.filename}</p>
          <p className="mt-0.5 max-w-[220px] truncate text-xs text-slate-500">{asset.relative_path || "根目录"}</p>
        </td>
        <td className="max-w-sm py-2.5 pr-4 align-top text-xs text-slate-400">
          {asset.summary
            ? <span style={{ display:"-webkit-box", WebkitLineClamp:2, WebkitBoxOrient:"vertical", overflow:"hidden" }}>{asset.summary}</span>
            : <span className="text-slate-600">—</span>}
        </td>
        <td className="py-2.5 pr-4 align-top">
          <div className="flex flex-wrap gap-1">
            {asset.tags.slice(0, 3).map(t => <TagBadge key={t} tag={t} />)}
            {asset.tags.length > 3 && <span className="text-[11px] text-slate-600">+{asset.tags.length - 3}</span>}
          </div>
        </td>
        <td className="py-2.5 pr-3 align-top text-xs tabular-nums text-slate-500 whitespace-nowrap">
          {asset.last_modified?.slice(0, 10) || "—"}
        </td>
        <td className="py-2.5 pr-3 align-top" onClick={e => e.stopPropagation()}>
          <div className="flex items-center gap-1.5">
            <StatusBadge status={asset.asset_status} onClick={onStatusChange ? cycleStatus : undefined} />
            <button
              type="button"
              title="查看匹配历史"
              onClick={e => { e.stopPropagation(); setWikiOpen(v => !v); }}
              className={`rounded px-1 py-0.5 text-[10px] transition ${
                wikiOpen ? "bg-cyan-950/40 text-cyan-400" : "text-slate-600 hover:text-slate-400"
              }`}
            >
              📊
            </button>
          </div>
        </td>
      </tr>
      {wikiOpen && (
        <AssetWikiPanel
          path={asset.relative_path}
          onClose={() => setWikiOpen(false)}
        />
      )}
    </>
  );
}

function TableHeader() {
  return (
    <thead>
      <tr className="border-b border-white/10 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
        <th className="w-8 pb-2 pl-3" />
        <th className="w-4 pb-2 pr-2" />
        <th className="pb-2 pr-4">文件名称</th>
        <th className="pb-2 pr-4">摘要</th>
        <th className="pb-2 pr-4">标签</th>
        <th className="pb-2 pr-3">更新日期</th>
        <th className="pb-2 pr-3">状态</th>
      </tr>
    </thead>
  );
}

// ─── 折叠分组通用组件 ─────────────────────────────────────────────────────────

interface GroupDef {
  key: string;
  label: string;
  items: AssetItem[];
}

function CollapsibleGroups({ groups, selectedKeys, onSelect, onClickRow, onStatusChange, defaultCollapseThreshold = 15 }: {
  groups: GroupDef[];
  selectedKeys: Set<string>;
  onSelect: (key: string, checked: boolean) => void;
  onClickRow: (a: AssetItem) => void;
  onStatusChange?: (path: string, status: string) => void;
  defaultCollapseThreshold?: number;
}) {
  const assetKey = (a: AssetItem) => `${a.relative_path}||${a.filename}`;

  const [collapsed, setCollapsed] = useState<Set<string>>(
    () => new Set(groups.filter(g => g.items.length > defaultCollapseThreshold).map(g => g.key))
  );
  const [showAll, setShowAll] = useState<Set<string>>(new Set());

  const toggle = (key: string) => setCollapsed(prev => {
    const next = new Set(prev); next.has(key) ? next.delete(key) : next.add(key); return next;
  });

  return (
    <div className="space-y-2">
      {groups.map(group => {
        const isCollapsed = collapsed.has(group.key);
        const expanded = showAll.has(group.key);
        const visible = expanded ? group.items.length : Math.min(defaultCollapseThreshold, group.items.length);
        return (
          <div key={group.key} className="overflow-hidden rounded-xl border border-white/8">
            <button type="button" onClick={() => toggle(group.key)}
              className="flex w-full items-center justify-between px-4 py-3 transition hover:bg-white/5">
              <span className="text-sm font-medium text-white">{group.label}</span>
              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-500">{group.items.length} 个</span>
                <svg className={`h-4 w-4 text-slate-500 transition-transform ${isCollapsed ? "" : "rotate-180"}`}
                  viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M5.22 8.22a.75.75 0 011.06 0L10 11.94l3.72-3.72a.75.75 0 111.06 1.06l-4.25 4.25a.75.75 0 01-1.06 0L5.22 9.28a.75.75 0 010-1.06z" clipRule="evenodd"/>
                </svg>
              </div>
            </button>
            {!isCollapsed && (
              <div className="border-t border-white/8">
                <table className="w-full text-left">
                  <TableHeader />
                  <tbody>
                    {group.items.slice(0, visible).map(a => {
                      const key = assetKey(a);
                      return (
                        <AssetRow key={key} asset={a}
                          selected={selectedKeys.has(key)}
                          onSelect={checked => onSelect(key, checked)}
                          onClick={() => onClickRow(a)}
                          onStatusChange={onStatusChange ? (s) => onStatusChange(a.relative_path, s) : undefined}
                        />
                      );
                    })}
                  </tbody>
                </table>
                {!expanded && group.items.length > defaultCollapseThreshold && (
                  <button type="button"
                    onClick={() => setShowAll(prev => new Set(prev).add(group.key))}
                    className="w-full py-2.5 text-center text-xs text-slate-500 hover:text-cyan-400 transition">
                    查看剩余 {group.items.length - defaultCollapseThreshold} 个 ▼
                  </button>
                )}
                {expanded && group.items.length > defaultCollapseThreshold && (
                  <button type="button"
                    onClick={() => setShowAll(prev => { const s = new Set(prev); s.delete(group.key); return s; })}
                    className="w-full py-2.5 text-center text-xs text-slate-600 hover:text-slate-400 transition">
                    收起 ▲
                  </button>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── 语义分组视图（按文件类型） ────────────────────────────────────────────────

function SemanticGroupedView({ assets, selectedKeys, onSelect, onClickRow, onStatusChange }: {
  assets: AssetItem[]; selectedKeys: Set<string>;
  onSelect: (key: string, checked: boolean) => void; onClickRow: (a: AssetItem) => void;
  onStatusChange?: (path: string, status: string) => void;
}) {
  const groups = useMemo<GroupDef[]>(() => {
    const map = new Map<CatKey, AssetItem[]>(CATEGORY_DEFS.map(c => [c.key, []]));
    for (const a of assets) map.get(categorizeAsset(a))!.push(a);
    return CATEGORY_DEFS
      .map(def => ({ key: def.key, label: def.label, items: map.get(def.key)! }))
      .filter(g => g.items.length > 0);
  }, [assets]);

  return <CollapsibleGroups groups={groups} selectedKeys={selectedKeys} onSelect={onSelect} onClickRow={onClickRow} onStatusChange={onStatusChange} />;
}

// ─── 目录分组视图（按顶层文件夹，0误判） ─────────────────────────────────────

function DirGroupedView({ assets, selectedKeys, onSelect, onClickRow, onStatusChange }: {
  assets: AssetItem[]; selectedKeys: Set<string>;
  onSelect: (key: string, checked: boolean) => void; onClickRow: (a: AssetItem) => void;
  onStatusChange?: (path: string, status: string) => void;
}) {
  const groups = useMemo<GroupDef[]>(() => {
    const map = new Map<string, AssetItem[]>();
    for (const a of assets) {
      const dir = topDir(a);
      if (!map.has(dir)) map.set(dir, []);
      map.get(dir)!.push(a);
    }
    // 按文件数量降序排列
    return [...map.entries()]
      .sort((a, b) => b[1].length - a[1].length)
      .map(([dir, items]) => ({ key: dir, label: `📂 ${dir}`, items }));
  }, [assets]);

  return (
    <>
      <p className="mb-3 text-[11px] text-slate-600">
        按顶层文件夹分组 · 共 {groups.length} 个目录
      </p>
      <CollapsibleGroups groups={groups} selectedKeys={selectedKeys} onSelect={onSelect} onClickRow={onClickRow} onStatusChange={onStatusChange} />
    </>
  );
}

// ─── 分页控件 ─────────────────────────────────────────────────────────────────

function Pagination({ page, totalPages, totalItems, onChange }: {
  page: number; totalPages: number; totalItems: number; onChange: (p: number) => void;
}) {
  if (totalPages <= 1) return null;
  const start = page * PAGE_SIZE + 1;
  const end = Math.min((page + 1) * PAGE_SIZE, totalItems);
  return (
    <div className="flex items-center justify-between border-t border-white/10 px-1 pt-3 text-xs text-slate-500">
      <button type="button" disabled={page === 0} onClick={() => onChange(page - 1)}
        className="rounded-lg border border-white/15 px-3 py-1.5 hover:text-white disabled:opacity-30">
        ← 上一页
      </button>
      <span>{start}–{end} / 共 {totalItems} 个&ensp;·&ensp;第 {page + 1}/{totalPages} 页</span>
      <button type="button" disabled={page >= totalPages - 1} onClick={() => onChange(page + 1)}
        className="rounded-lg border border-white/15 px-3 py-1.5 hover:text-white disabled:opacity-30">
        下一页 →
      </button>
    </div>
  );
}

// ─── 加入尽调包内联表单 ───────────────────────────────────────────────────────

function BundleForm({ files, onDone, onCancel }: {
  files: AssetItem[];
  onDone: (msg: string) => void;
  onCancel: () => void;
}) {
  const [institution, setInstitution] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const submit = async () => {
    setLoading(true);
    setErr(null);
    try {
      const payload = {
        institution: institution.trim(),
        files: files.map(f => ({
          filename: f.filename,
          full_path: f.full_path,
          relative_path: f.relative_path,
        })),
      };
      await api.post("/api/v1/assets/bundle", payload);
      onDone(`已打包 ${files.length} 个文件${institution.trim() ? `（${institution.trim()}）` : ""}`);
    } catch {
      setErr("提交失败，请重试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-xl border border-cyan-500/30 bg-cyan-950/20 px-4 py-4 space-y-3">
      <p className="text-sm font-medium text-cyan-300">
        加入尽调包 — 已选 {files.length} 个文件
      </p>
      <div className="flex flex-wrap gap-2 items-center">
        <input
          ref={inputRef}
          value={institution}
          onChange={e => setInstitution(e.target.value)}
          onKeyDown={e => e.key === "Enter" && void submit()}
          placeholder="机构名称（可选，如：红杉资本）"
          className="flex-1 min-w-[200px] rounded-lg border border-white/15 bg-black/40 px-3 py-1.5 text-sm text-white placeholder:text-slate-600"
        />
        <button type="button" onClick={() => void submit()} disabled={loading}
          className="rounded-lg bg-cyan-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50">
          {loading ? "提交中…" : "确认打包"}
        </button>
        <button type="button" onClick={onCancel}
          className="rounded-lg border border-white/20 px-3 py-1.5 text-sm text-slate-400 hover:text-white">
          取消
        </button>
      </div>
      {err && <p className="text-xs text-red-400">{err}</p>}
      <div className="flex flex-wrap gap-1 max-h-20 overflow-y-auto">
        {files.map(f => (
          <span key={`${f.relative_path}||${f.filename}`}
            className="rounded border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] text-slate-300">
            {f.filename}
          </span>
        ))}
      </div>
    </div>
  );
}

// ─── 主组件 ───────────────────────────────────────────────────────────────────

type ViewMode = "list" | "semantic" | "dir";

export function AssetLibrary() {
  const [data, setData] = useState<AssetIndexResponse | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scanModalOpen, setScanModalOpen] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [scanStatus, setScanStatus] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("all");
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [page, setPage] = useState(0);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [detailAsset, setDetailAsset] = useState<AssetItem | null>(null);
  const [bundleOpen, setBundleOpen] = useState(false);
  const [bundleMsg, setBundleMsg] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("active"); // "active" = approved+sent

  const assetKey = (a: AssetItem) => `${a.relative_path}||${a.filename}`;

  // ── 数据加载 ─────────────────────────────────────────────────────────────

  const fetchAssets = useCallback(async (q: string) => {
    setLoading(true);
    setError(null);
    try {
      const url = q.trim()
        ? `/api/v1/assets/search?q=${encodeURIComponent(q.trim())}`
        : "/api/v1/assets";
      const res = await api.get<AssetIndexResponse>(url);
      setData(res.data);
      setPage(0);
      setSelectedKeys(new Set());
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void fetchAssets(""); }, [fetchAssets]);
  useEffect(() => {
    const t = setTimeout(() => void fetchAssets(query), 300);
    return () => clearTimeout(t);
  }, [query, fetchAssets]);

  // ── 派生数据 ─────────────────────────────────────────────────────────────

  const allAssets = data?.assets ?? [];
  const activeAssets = useMemo(() => allAssets.filter(a => freshLevel(a) === "active"), [allAssets]);
  const attentionAssets = useMemo(() => allAssets.filter(needsAttention), [allAssets]);

  const tabAssets = useMemo(() => {
    if (activeTab === "active") return activeAssets;
    if (activeTab === "attention") return attentionAssets;
    return allAssets;
  }, [activeTab, allAssets, activeAssets, attentionAssets]);

  const displayAssets = useMemo(() => {
    if (statusFilter === "active") {
      return tabAssets.filter(a => !a.asset_status || a.asset_status === "approved" || a.asset_status === "sent");
    }
    if (statusFilter === "all") return tabAssets;
    return tabAssets.filter(a => (a.asset_status ?? "approved") === statusFilter);
  }, [tabAssets, statusFilter]);

  const totalPages = Math.ceil(displayAssets.length / PAGE_SIZE);
  const pageAssets = useMemo(
    () => displayAssets.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
    [displayAssets, page],
  );

  useEffect(() => { setPage(0); setSelectedKeys(new Set()); }, [activeTab, query, statusFilter]);

  // ── 操作 ─────────────────────────────────────────────────────────────────

  const handleTabChange = (tab: TabKey) => { setActiveTab(tab); setDetailAsset(null); };

  const triggerScan = useCallback(async (scanDir?: string) => {
    setScanning(true); setScanStatus(null);
    try {
      const url = scanDir
        ? `/api/v1/assets/scan?scan_dir=${encodeURIComponent(scanDir)}`
        : "/api/v1/assets/scan";
      const res = await api.post<{ indexed: number }>(url);
      setScanStatus(`扫描完成，已索引 ${res.data.indexed} 个文件`);
      void fetchAssets(query);
    } catch { setScanStatus("扫描失败，请检查目录配置"); }
    finally { setScanning(false); }
  }, [fetchAssets, query]);

  const updateFileStatus = useCallback(async (relativePath: string, status: string) => {
    try {
      await api.put("/api/v1/assets/status", { relative_paths: [relativePath], status });
      setData(prev => {
        if (!prev) return prev;
        return {
          ...prev,
          assets: prev.assets.map(a =>
            a.relative_path === relativePath ? { ...a, asset_status: status as AssetItem["asset_status"] } : a
          ),
        };
      });
    } catch {
      // 静默失败，不打断用户操作
    }
  }, []);

  const toggleSelect = (key: string, checked: boolean) =>
    setSelectedKeys(prev => { const n = new Set(prev); checked ? n.add(key) : n.delete(key); return n; });

  const selectAllPage = () => setSelectedKeys(new Set(pageAssets.map(assetKey)));
  const selectAllTab  = () => setSelectedKeys(new Set(displayAssets.map(assetKey)));
  const clearSelect   = () => setSelectedKeys(new Set());

  // 从 selectedKeys 还原 AssetItem 列表
  const selectedAssets = useMemo(
    () => allAssets.filter(a => selectedKeys.has(assetKey(a))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [allAssets, selectedKeys],
  );

  const notSynced = !data?.generated_at;

  // ── 渲染 ─────────────────────────────────────────────────────────────────

  return (
    <section className="mt-8 rounded-2xl border border-white/10 bg-white/[0.03] p-6">
      {/* 头部 */}
      <div className="mb-5 space-y-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="font-display text-lg font-bold text-white">资产台账</h2>
            <p className="text-xs text-slate-500">
              {data?.generated_at
                ? `共 ${data.total_files} 个文件 · 上次扫描 ${data.generated_at.slice(0, 10)}`
                : "暂无数据 — 请先配置并扫描素材目录"}
            </p>
          </div>
          {/* 搜索框 */}
          <div className="relative">
            <svg className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500"
              viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clipRule="evenodd"/>
            </svg>
            <input value={query} onChange={e => setQuery(e.target.value)}
              placeholder="搜索文件名 / 摘要 / 标签…"
              className="w-full rounded-xl border border-white/15 bg-black/40 py-2 pl-9 pr-8 text-sm text-white placeholder:text-slate-600 sm:w-72"
            />
            {query && (
              <button type="button" onClick={() => setQuery("")}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white">
                ✕
              </button>
            )}
          </div>
        </div>

        {/* 操作按钮行 */}
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <button type="button" onClick={() => void fetchAssets(query)}
            className="rounded-lg border border-white/20 bg-white/5 px-3 py-1.5 text-cyan-200 hover:border-cyan-500/40">
            刷新
          </button>
          <button type="button" onClick={() => setScanModalOpen(true)} disabled={scanning}
            className="rounded-lg border border-cyan-500/40 bg-cyan-950/40 px-3 py-1.5 text-cyan-300 hover:border-cyan-400/60 disabled:opacity-50">
            {scanning ? "扫描中…" : "配置并扫描"}
          </button>
          {scanStatus && <span className="text-cyan-400/80">{scanStatus}</span>}
        </div>
      </div>

      {/* 状态 */}
      {loading && <p className="py-10 text-center text-sm text-slate-500">加载中…</p>}
      {error && <p className="py-6 text-center text-sm text-red-400">{error}</p>}

      {!loading && !error && notSynced && (
        <div className="rounded-xl border border-yellow-500/20 bg-yellow-500/5 px-5 py-6 text-center">
          <p className="text-sm text-yellow-300">尚未找到资产数据</p>
          <p className="mt-1 text-xs text-slate-500">点击「配置并扫描」设置素材目录，FOS 将自动索引所有文件。</p>
        </div>
      )}

      {!loading && !error && !notSynced && (
        <>
          {/* Tabs + 视图切换 */}
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-1.5">
              <TabBtn label="近期活跃" count={activeAssets.length} active={activeTab === "active"}
                dot="bg-emerald-400" onClick={() => handleTabChange("active")} />
              <TabBtn label="需关注" count={attentionAssets.length} active={activeTab === "attention"}
                dot={attentionAssets.length > 0 ? "bg-amber-400" : undefined} onClick={() => handleTabChange("attention")} />
              <TabBtn label="全部文件" count={allAssets.length} active={activeTab === "all"}
                onClick={() => handleTabChange("all")} />
            </div>
            {/* 视图模式切换 */}
            <div className="flex rounded-lg border border-white/15 overflow-hidden text-xs">
              {([ ["list", "≡ 列表"], ["semantic", "⊞ 按类型"], ["dir", "📂 按目录"] ] as [ViewMode, string][]).map(([mode, label], i) => (
                <button key={mode} type="button" onClick={() => setViewMode(mode)}
                  className={`px-3 py-1.5 transition ${i > 0 ? "border-l border-white/15" : ""} ${viewMode === mode ? "bg-white/10 text-white" : "text-slate-500 hover:text-white"}`}>
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* 状态筛选器 */}
          <div className="mb-3 flex flex-wrap gap-1.5 text-xs">
            {([
              ["active",   "定稿 + 已发出"],
              ["all",      "全部"],
              ["draft",    "草稿"],
              ["archived", "已归档"],
            ] as [string, string][]).map(([val, label]) => (
              <button key={val} type="button" onClick={() => setStatusFilter(val)}
                className={`rounded-lg border px-2.5 py-1 transition ${
                  statusFilter === val
                    ? "border-cyan-500/40 bg-cyan-950/30 text-cyan-300"
                    : "border-white/10 text-slate-500 hover:text-slate-300"
                }`}>
                {label}
                <span className="ml-1.5 text-[10px] text-slate-600">
                  {val === "active"
                    ? tabAssets.filter(a => !a.asset_status || a.asset_status === "approved" || a.asset_status === "sent").length
                    : val === "all"
                    ? tabAssets.length
                    : tabAssets.filter(a => (a.asset_status ?? "approved") === val).length}
                </span>
              </button>
            ))}
          </div>

          {/* 批量操作栏 */}
          {selectedKeys.size > 0 && (
            <div className="mb-3 flex flex-wrap items-center gap-3 rounded-xl border border-cyan-500/30 bg-cyan-950/25 px-4 py-2.5 text-sm">
              <span className="font-medium text-cyan-300">已选 {selectedKeys.size} 个</span>
              <button type="button" onClick={selectAllPage} className="text-slate-400 hover:text-white">
                全选本页（{pageAssets.length}）
              </button>
              <button type="button" onClick={selectAllTab} className="text-slate-400 hover:text-white">
                全选当前视图（{displayAssets.length}）
              </button>
              <span className="text-slate-700">|</span>
              <button type="button" onClick={() => { setBundleOpen(true); setBundleMsg(null); }}
                className="rounded-lg bg-cyan-600/80 px-3 py-1 text-white hover:bg-cyan-500 text-xs font-medium">
                📦 加入尽调包
              </button>
              <button type="button" onClick={clearSelect} className="text-slate-500 hover:text-white">
                取消选择
              </button>
            </div>
          )}

          {/* 打包成功提示 */}
          {bundleMsg && !bundleOpen && (
            <div className="mb-3 rounded-xl border border-emerald-500/30 bg-emerald-950/20 px-4 py-2.5 text-sm text-emerald-300">
              ✅ {bundleMsg}
            </div>
          )}

          {/* 加入尽调包表单 */}
          {bundleOpen && selectedAssets.length > 0 && (
            <div className="mb-4">
              <BundleForm
                files={selectedAssets}
                onDone={msg => { setBundleMsg(msg); setBundleOpen(false); clearSelect(); }}
                onCancel={() => setBundleOpen(false)}
              />
            </div>
          )}

          {/* 列表视图 */}
          {viewMode === "list" && (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <TableHeader />
                  <tbody>
                    {pageAssets.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="py-8 text-center text-sm text-slate-500">
                          {activeTab === "active" ? "暂无近 30 天内更新的文件"
                            : activeTab === "attention" ? "没有需要关注的文件 🎉"
                            : "没有匹配的文件"}
                        </td>
                      </tr>
                    ) : (
                      pageAssets.map(a => {
                        const key = assetKey(a);
                        return (
                          <AssetRow key={key} asset={a}
                            selected={selectedKeys.has(key)}
                            onSelect={checked => toggleSelect(key, checked)}
                            onClick={() => setDetailAsset(a)}
                            onStatusChange={(s) => void updateFileStatus(a.relative_path, s)}
                          />
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
              <Pagination page={page} totalPages={totalPages} totalItems={displayAssets.length} onChange={setPage} />
            </>
          )}

          {/* 语义分组（按文件类型关键词） */}
          {viewMode === "semantic" && (
            <SemanticGroupedView
              assets={displayAssets}
              selectedKeys={selectedKeys}
              onSelect={toggleSelect}
              onClickRow={setDetailAsset}
              onStatusChange={(path, s) => void updateFileStatus(path, s)}
            />
          )}

          {/* 目录分组（按顶层文件夹，0误判） */}
          {viewMode === "dir" && (
            <DirGroupedView
              assets={displayAssets}
              selectedKeys={selectedKeys}
              onSelect={toggleSelect}
              onClickRow={setDetailAsset}
              onStatusChange={(path, s) => void updateFileStatus(path, s)}
            />
          )}
        </>
      )}

      {/* 子面板 */}
      <AssetHealthPanel />
      <MatchMakerPanel />
      <InstitutionArchivePanel />

      <AssetScanConfigModal
        open={scanModalOpen}
        onClose={() => setScanModalOpen(false)}
        onScan={dir => { setScanModalOpen(false); void triggerScan(dir); }}
      />

      {/* 详情侧滑面板 */}
      {detailAsset && (
        <AssetDetailPanel asset={detailAsset} onClose={() => setDetailAsset(null)} />
      )}
    </section>
  );
}
