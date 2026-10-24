from __future__ import annotations

from cangjie_fos.services.audio_service import AudioService


def test_audio_service_compress_small_file_skips() -> None:
    data = b"\x00" * (1024 * 1024)
    r = AudioService.smart_compress_media(data, filename_hint="x.mp3")
    assert r.data == data
    assert r.did_compress is False
