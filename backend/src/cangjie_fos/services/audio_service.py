"""ASR 前置音频处理：薄封装 engine.audio_preprocess（Phase 1 迁移后）。"""
from __future__ import annotations

from typing import Any

from cangjie_fos.engine.audio_preprocess import smart_compress_media as _smart_compress_media


class AudioService:
    """不复制算法，仅适配 import 路径。"""

    @staticmethod
    def smart_compress_media(data: bytes, *, filename_hint: str = "audio.bin") -> Any:
        return _smart_compress_media(data, filename_hint=filename_hint)
