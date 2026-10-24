"""安全读取与校验 FSS 桥接 asset_index.json（大小、条数、结构）。"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

import cangjie_fos.core.paths as _fos_paths

logger = logging.getLogger(__name__)

_ASSET_INDEX = "asset_index.json"


def _max_file_bytes() -> int:
    raw = (os.getenv("CANGJIE_MAX_ASSET_INDEX_MB") or "32").strip()
    try:
        return max(1, int(raw)) * 1024 * 1024
    except ValueError:
        return 32 * 1024 * 1024


def _max_assets() -> int:
    raw = (os.getenv("CANGJIE_MAX_ASSET_COUNT") or "50000").strip()
    try:
        return max(10, min(500_000, int(raw)))
    except ValueError:
        return 50_000


class _AssetItemIn(BaseModel):
    filename: str = ""
    relative_path: str = ""
    full_path: str = ""
    last_modified: str = ""
    summary: str = ""
    tags: list[str] = Field(default_factory=list)

    @field_validator("filename", "relative_path", "full_path", "last_modified", "summary", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        if v is None:
            return ""
        if isinstance(v, str):
            return v[:16_000]
        return str(v)[:16_000]


def redact_path_for_api(path_str: str) -> str:
    """不信任 FSS 路径：仅作展示，去掉可疑片段与过长内容。"""
    s = (path_str or "").strip()
    if not s:
        return ""
    if ".." in s or s.startswith("\\\\") and ".." in s:
        return "[path_redacted]"
    # 只保留末段与有限前缀，避免把整盘路径暴露给前端
    p = s.replace("\\", "/")
    parts = [x for x in p.split("/") if x]
    if not parts:
        return ""
    if len(parts) > 4:
        return "/…/" + "/".join(parts[-3:])
    return "/".join(parts)[:500]


def load_asset_index_dict(fos_data_dir: Path | None = None) -> dict[str, Any]:
    """
    读取并校验，返回可 JSON 序列化 dict（与旧 API 兼容）。
    失败时抛 ValueError 或 OSError；过大文件不整读入（先 stat）。
    """
    base = fos_data_dir or _fos_paths.get_fos_bridge_data_dir()
    path = base / _ASSET_INDEX
    if not path.is_file():
        return {
            "generated_at": None,
            "total_files": 0,
            "assets": [],
            "source_dir": "",
        }
    mx = _max_file_bytes()
    st = path.stat()
    if st.st_size > mx:
        raise ValueError(f"asset_index.json 超过 {mx // (1024 * 1024)}MB 限制")
    raw = path.read_text(encoding="utf-8", errors="replace")
    if len(raw) > mx:
        raise ValueError("asset_index.json 读取后仍超限")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("asset_index 根须为 JSON 对象")
    raw_assets = data.get("assets", [])
    if not isinstance(raw_assets, list):
        raise ValueError("assets 须为数组")
    nmax = _max_assets()
    if len(raw_assets) > nmax:
        logger.warning("asset_index trimmed count=%s max=%s", len(raw_assets), nmax)
    redact = (os.getenv("CANGJIE_REDACT_ASSET_PATHS", "1").strip().lower() not in {"0", "false", "no"})
    out_assets: list[dict[str, Any]] = []
    for item in raw_assets[:nmax]:
        if not isinstance(item, dict):
            continue
        try:
            a = _AssetItemIn.model_validate(item)
        except Exception:  # noqa: BLE001
            continue
        fp = a.full_path
        if redact:
            fp = redact_path_for_api(fp)
        out_assets.append(
            {
                "filename": a.filename,
                "relative_path": a.relative_path,
                "full_path": fp,
                "last_modified": a.last_modified,
                "summary": a.summary[:2000] if a.summary else "",
                "tags": a.tags[:64],
            }
        )
    tf = data.get("total_files", 0)
    try:
        total_files = int(tf) if tf else len(out_assets)
    except (TypeError, ValueError):
        total_files = len(out_assets)
    return {
        "generated_at": data.get("generated_at") if isinstance(data.get("generated_at"), (str, type(None))) else None,
        "total_files": total_files,
        "source_dir": str(data.get("source_dir", ""))[:2000],
        "assets": out_assets,
    }
