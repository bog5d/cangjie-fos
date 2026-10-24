"""Phase 6.2：上传向导会话（内存态，与 pitch_job_store 同寿命模型）。"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any

from cangjie_fos.schemas.pitch_upload_wizard import UploadWizardCreateRequest

_lock = threading.Lock()
_sessions: dict[str, dict[str, Any]] = {}
_TTL_SEC = 3600


def _purge_stale() -> None:
    now = time.time()
    dead: list[str] = []
    for sid, data in _sessions.items():
        if now - float(data.get("created", 0)) > _TTL_SEC:
            dead.append(sid)
    for sid in dead:
        _delete_session_files(sid)
        _sessions.pop(sid, None)


def _delete_session_files(session_id: str) -> None:
    data = _sessions.get(session_id) or {}
    for p in (data.get("audio") or {}).values():
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass
    for lst in (data.get("qa") or {}).values():
        for item in lst or []:
            if isinstance(item, dict) and "path" in item:
                try:
                    Path(item["path"]).unlink(missing_ok=True)
                except OSError:
                    pass


def session_create(payload: UploadWizardCreateRequest) -> str:
    with _lock:
        _purge_stale()
        sid = uuid.uuid4().hex
        _sessions[sid] = {
            "payload": payload.model_dump(),
            "audio": {},  # int index -> str path
            "qa": {},  # int index -> list[{"path": str, "name": str}]
            "created": time.time(),
        }
        return sid


def session_get(session_id: str) -> dict[str, Any] | None:
    with _lock:
        _purge_stale()
        return _sessions.get(session_id)


def session_set_audio(session_id: str, track_index: int, path: Path, original_name: str) -> bool:
    with _lock:
        s = _sessions.get(session_id)
        if not s:
            return False
        s["audio"][track_index] = str(path.resolve())
        s.setdefault("filenames", {})[track_index] = original_name
        return True


def session_append_qa(
    session_id: str, track_index: int, *, temp_path: Path, original_name: str
) -> bool:
    with _lock:
        s = _sessions.get(session_id)
        if not s:
            return False
        s.setdefault("qa", {}).setdefault(track_index, []).append(
            {"path": str(temp_path.resolve()), "name": original_name}
        )
        return True


def session_delete(session_id: str) -> dict[str, Any] | None:
    """校验通过后删除会话。"""
    with _lock:
        return _sessions.pop(session_id, None)
