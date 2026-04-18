"""ASR 前置音频处理：薄封装 Pitch_Coach `audio_preprocess`（SPEC A4）。"""
from __future__ import annotations

from typing import Any

from cangjie_fos.core.paths import ensure_pitch_coach_import_path


class AudioService:
    """不复制算法，仅适配 import 路径。"""

    @staticmethod
    def smart_compress_media(data: bytes, *, filename_hint: str = "audio.bin") -> Any:
        ensure_pitch_coach_import_path()
        from audio_preprocess import smart_compress_media

        return smart_compress_media(data, filename_hint=filename_hint)
