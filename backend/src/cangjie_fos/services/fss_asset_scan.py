"""读取 FSS 桥接 asset_index.json（Phase 4 SPEC A2/A3）。"""
from __future__ import annotations

import logging
from pathlib import Path

from cangjie_fos.core.paths import get_fos_bridge_data_dir
from cangjie_fos.services.asset_index_io import load_asset_index_dict

logger = logging.getLogger(__name__)


def load_asset_index_assets(fos_data_dir: Path | None = None) -> list[dict]:
    """等价于 FSS `load_asset_index_local`：返回 assets 列表；校验失败时降级为空。"""
    base = fos_data_dir or get_fos_bridge_data_dir()
    try:
        data = load_asset_index_dict(base)
        return list(data.get("assets") or [])
    except (ValueError, OSError) as e:
        logger.debug("asset_index_unavailable path=%s err=%s", base, e)
        return []


def count_data_room_files(tenant_id: str, root: Path | None = None) -> int:
    """扫描资料室目录下文件数量（递归）。"""
    import os

    base = Path(root) if root is not None else None
    if base is None:
        from cangjie_fos.core.paths import get_data_room_root

        base = get_data_room_root()
    safe = tenant_id.replace("/", "_").replace("..", "_")[:128]
    d = base / safe
    if not d.is_dir():
        return 0
    n = 0
    for _root, _dirs, files in os.walk(d):
        n += len(files)
    return n
