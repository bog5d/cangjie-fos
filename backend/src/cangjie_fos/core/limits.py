"""上传体、JSON 等硬上限（环境变量可配）。"""
from __future__ import annotations

import os


def max_upload_bytes() -> int:
    raw = (os.getenv("CANGJIE_MAX_UPLOAD_MB") or "500").strip()
    try:
        return max(1, int(raw)) * 1024 * 1024
    except ValueError:
        return 200 * 1024 * 1024


def max_json_body_bytes() -> int:
    raw = (os.getenv("CANGJIE_MAX_JSON_BODY_MB") or "8").strip()
    try:
        return max(1, int(raw)) * 1024 * 1024
    except ValueError:
        return 8 * 1024 * 1024
