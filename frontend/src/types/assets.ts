export interface AssetItem {
  filename: string;
  relative_path: string;
  full_path: string;
  last_modified: string;
  summary: string;
  tags: string[];
  asset_status?: "draft" | "approved" | "sent" | "archived";
}

export interface AssetIndexResponse {
  generated_at: string | null;
  total_files: number;
  assets: AssetItem[];
  source_dir: string;
  /** FOS 解析的桥接目录（.fos_data 所在或等价路径） */
  bridge_dir?: string;
}
