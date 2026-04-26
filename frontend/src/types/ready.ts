export type ReadyIssue = {
  code: string;
  message: string;
  fix_hint: string;
  severity: string;
};

export type ReadyPayload = {
  ok: boolean;
  issues: ReadyIssue[];
  pitch_coach_ok: boolean;
  api_keys_ok: boolean;
  frontend_dist_ok: boolean;
  asset_index_ok: boolean;
  asset_index_warn: boolean;
  disk_free_bytes: number;
  disk_sufficient: boolean;
  bridge_dir: string;
  pitch_coach_root: string;
  sqlite_ok: boolean;
  job_queue_in_use: number;
  job_queue_capacity: number;
};
