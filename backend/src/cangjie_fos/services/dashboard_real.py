"""由 asset_index + 资料室文件数计算真实健康度（Phase 4 SPEC A2）。"""
from __future__ import annotations

from cangjie_fos.services.fss_asset_scan import count_data_room_files, load_asset_index_assets

# 可配置「满血」参照：资产条目与资料室文件数分别对齐 DD 常见体量
TARGET_ASSET_SLOTS = 40
TARGET_DATA_ROOM_FILES = 30


def compute_health_percentages(*, tenant_id: str) -> tuple[int, int]:
    """返回 (docs_health_pct, data_room_completeness_pct)。"""
    assets = load_asset_index_assets()
    docs_pct = min(100, int(round(100 * min(len(assets), TARGET_ASSET_SLOTS) / max(1, TARGET_ASSET_SLOTS))))
    if not assets:
        docs_pct = min(docs_pct, 35)

    n_files = count_data_room_files(tenant_id)
    room_pct = min(100, int(round(100 * min(n_files, TARGET_DATA_ROOM_FILES) / max(1, TARGET_DATA_ROOM_FILES))))
    if n_files == 0:
        room_pct = min(room_pct, 25)

    return docs_pct, room_pct
