"""Phase 5：监听 data_room/incoming，落 Job + 推送到 NPC WebSocket。"""
from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from cangjie_fos.core import paths as fos_paths
from cangjie_fos.events.npc_ws_house import schedule_broadcast_to_tenant
from cangjie_fos.schemas.pitch_upload import PitchJobStatus
from cangjie_fos.services.pitch_failure_present import job_failure_update_kwargs
from cangjie_fos.services.pitch_job_store import job_create, job_update
from cangjie_fos.services.pitch_upload_pipeline import run_pitch_upload_job

logger = logging.getLogger(__name__)

_observer: Observer | None = None
_observer_lock = threading.Lock()
_main_incoming: Path | None = None

_AUDIO_EXT = frozenset({".mp3", ".wav", ".m4a", ".webm", ".flac", ".ogg"})


def incoming_root() -> Path:
    return fos_paths.get_data_room_root() / "incoming"


def is_file_watchdog_running() -> bool:
    with _observer_lock:
        return _observer is not None and _observer.is_alive()


def _default_watchdog_tenant() -> str:
    return os.getenv("CANGJIE_WATCHDOG_DEFAULT_TENANT", "demo-tenant").strip() or "demo-tenant"


def _resolve_tenant_and_name(rel: Path) -> tuple[str, str]:
    """rel 相对于 incoming/；首段为 tenant 子目录，否则走默认租户。"""
    parts = rel.parts
    if len(parts) >= 2:
        return parts[0], str(Path(*parts[1:]))
    return _default_watchdog_tenant(), rel.name


def process_incoming_file_path(src: Path) -> str | None:
    """
    处理已落盘的 incoming 文件：复制到资料室、建 Job、推送 NPC、异步完成 Job。
    返回 job_id；忽略非 incoming 路径或目录。
    """
    src = src.resolve()
    inc = incoming_root().resolve()
    try:
        rel = src.relative_to(inc)
    except ValueError:
        return None
    if src.is_dir():
        return None
    name = src.name
    if name.startswith(".") or name.endswith("~"):
        return None

    tenant_id, logical_name = _resolve_tenant_and_name(rel)
    job_id = uuid.uuid4().hex
    job_create(job_id, tenant_id)

    dest_dir = fos_paths.get_data_room_root() / tenant_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(logical_name).name
    if dest.exists():
        dest = dest_dir / f"{int(time.time())}_{Path(logical_name).name}"
    try:
        shutil.copy2(src, dest)
    except OSError as e:
        logger.warning("incoming_copy_failed src=%s err=%s", src, e)
        job_update(job_id, status=PitchJobStatus.FAILED, **job_failure_update_kwargs(e, job_id=job_id))
        return job_id

    job_update(job_id, report={"source": "incoming_watchdog", "path": str(dest), "filename": logical_name})

    schedule_broadcast_to_tenant(
        tenant_id,
        {
            "type": "npc_prompt",
            "role": "系统",
            "proactive": True,
            "text": "检测到新资产，已自动同步至大盘，是否查看？",
            "job_id": job_id,
            "asset_filename": logical_name,
        },
    )

    ext = src.suffix.lower()
    if ext in _AUDIO_EXT:
        job_update(job_id, status=PitchJobStatus.TRANSCRIBING)

        def _audio_thread() -> None:
            try:
                raw = dest.read_bytes()
                run_pitch_upload_job(job_id=job_id, raw_bytes=raw, filename=dest.name, tenant_id=tenant_id)
            except Exception as e:  # noqa: BLE001
                logger.exception("watchdog_audio_pipeline_failed job_id=%s", job_id)
                job_update(job_id, status=PitchJobStatus.FAILED, **job_failure_update_kwargs(e, job_id=job_id))
            schedule_broadcast_to_tenant(
                tenant_id,
                {
                    "type": "npc_prompt",
                    "role": "系统",
                    "proactive": False,
                    "text": f"录音资产「{logical_name}」解析链路已结束，可在任务面板查看 job {job_id[:8]}…",
                    "job_id": job_id,
                },
            )

        threading.Thread(target=_audio_thread, daemon=True).start()
        return job_id

    def _doc_done() -> None:
        job_update(job_id, status=PitchJobStatus.EVALUATING)
        job_update(
            job_id,
            status=PitchJobStatus.COMPLETED,
            report={
                "watchdog": True,
                "tenant_id": tenant_id,
                "stored_path": str(dest),
                "filename": logical_name,
            },
            exp_delta=15,
            exp_reason="新资产入库并完成解析占位",
        )
        schedule_broadcast_to_tenant(
            tenant_id,
            {
                "type": "score_delta",
                "delta": 15,
                "reason": "新资产同步",
            },
        )

    threading.Timer(0.25, _doc_done).start()
    return job_id


class _IncomingHandler(FileSystemEventHandler):
    def on_created(self, event):  # type: ignore[no-untyped-def]
        if event.is_directory:
            return
        path = Path(event.src_path)
        # 等写入落盘（Windows 拖拽大文件）
        threading.Timer(0.4, lambda p=path: self._safe_handle(p)).start()

    def on_moved(self, event):  # type: ignore[no-untyped-def]
        if event.is_directory:
            return
        dest = getattr(event, "dest_path", None)
        if dest:
            path = Path(dest)
            threading.Timer(0.4, lambda p=path: self._safe_handle(p)).start()

    @staticmethod
    def _safe_handle(path: Path) -> None:
        try:
            if not path.is_file():
                return
            if path.stat().st_size <= 0:
                return
        except OSError:
            return
        jid = process_incoming_file_path(path)
        if jid:
            logger.info("incoming_asset_processed job_id=%s path=%s", jid, path)


def start_file_watchdog() -> None:
    global _observer, _main_incoming
    inc = incoming_root()
    inc.mkdir(parents=True, exist_ok=True)
    with _observer_lock:
        if _observer is not None:
            return
        obs = Observer()
        h = _IncomingHandler()
        obs.schedule(h, str(inc.resolve()), recursive=True)
        obs.start()
        _observer = obs
        _main_incoming = inc.resolve()
        logger.info("file_watchdog_started path=%s", _main_incoming)


def stop_file_watchdog() -> None:
    global _observer, _main_incoming
    with _observer_lock:
        if _observer is None:
            return
        _observer.stop()
        _observer.join(timeout=8)
        _observer = None
        _main_incoming = None
        logger.info("file_watchdog_stopped")
