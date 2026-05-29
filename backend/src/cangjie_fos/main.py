"""ASGI 入口：仅组装应用。"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from cangjie_fos.api.router import api_router
from cangjie_fos.core.checkpointing import get_sqlite_checkpointer, shutdown_checkpointer
from cangjie_fos.core.config import settings
from cangjie_fos.core.http_errors import http_exception_handler, unhandled_exception_handler
from cangjie_fos.core.paths import get_backend_root, get_frontend_dist_dir, get_audio_dir
from cangjie_fos.events.file_watchdog import start_file_watchdog, stop_file_watchdog
from cangjie_fos.events.npc_ws_house import set_main_event_loop
from cangjie_fos.events.watchdog_runner import stop_watchdog_stub
from cangjie_fos.middleware.request_context import RequestContextMiddleware

_SPA_EXCLUDE_PREFIXES = ("/api/", "/health", "/reports/", "/docs", "/openapi")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    # 1. 先加载 .env（用户自己填的 Key/Token 优先，不覆盖已有环境变量）
    try:
        from dotenv import load_dotenv  # noqa: PLC0415
        load_dotenv(dotenv_path=get_backend_root() / ".env", override=False)
    except Exception:  # noqa: BLE001
        pass
    # 2. 再注入内置默认配置（仅填补 .env 和系统环境变量都没有的项）
    try:
        from cangjie_fos.core._embedded import inject_defaults  # noqa: PLC0415
        inject_defaults()
    except Exception:  # noqa: BLE001
        pass
    from cangjie_fos.core.preflight import run_preflight  # noqa: PLC0415

    if (os.getenv("CANGJIE_STRICT_STARTUP", "").strip().lower() in {"1", "true", "yes"}):
        from cangjie_fos.core.readiness import compute_readiness  # noqa: PLC0415

        r = compute_readiness()
        if not r.ok:
            err_codes = [i.code for i in r.issues if i.severity == "error"]
            raise RuntimeError(f"strict startup: readiness failed codes={err_codes!r}")
    run_preflight(strict=True)
    # 预加载 Coach .env 使 NPC 从启动即可访问 LLM，无需等到 pipeline 首次运行
    try:
        from cangjie_fos.core.paths import hydrate_pitch_coach_env  # noqa: PLC0415
        hydrate_pitch_coach_env()
    except Exception:  # noqa: BLE001
        pass
    set_main_event_loop(asyncio.get_running_loop())
    get_sqlite_checkpointer()
    if settings.enable_watchdog:
        start_file_watchdog()
    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # noqa: PLC0415
    from cangjie_fos.services.nightly_settle import nightly_settle_all_tenants  # noqa: PLC0415

    from cangjie_fos.services.proactive_interviewer import run_proactive_interview_all_tenants  # noqa: PLC0415

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(nightly_settle_all_tenants, "cron", hour=2, minute=0)
    _scheduler.add_job(run_proactive_interview_all_tenants, "cron", hour=18, minute=0)
    try:
        import logging as _logging  # noqa: PLC0415
        from cangjie_fos.services.wiki_consolidator import consolidate_wiki  # noqa: PLC0415
        _scheduler.add_job(consolidate_wiki, "cron", hour=2, minute=30)
        _logging.getLogger(__name__).info("wiki_consolidator 已注册，每晚 02:30 执行")
    except Exception as _e:  # noqa: BLE001
        _logging.getLogger(__name__).warning("wiki_consolidator 注册失败（非致命）: %s", _e)
    _scheduler.start()
    # GitHub 同步：启动时拉取最新数据（后台线程，不阻塞启动）
    try:
        import threading as _threading  # noqa: PLC0415
        from cangjie_fos.services.github_sync import pull_latest  # noqa: PLC0415
        _threading.Thread(target=pull_latest, daemon=True, name="github-pull").start()
    except Exception as _e:  # noqa: BLE001
        import logging as _log  # noqa: PLC0415
        _log.getLogger(__name__).warning("GitHub pull 启动失败（非致命）: %s", _e)
    # 启动时补全 institutions 表（从 pitch_jobs 回溯）
    # 修复：路演录音写入的机构数据因静默失败未能进 institutions.sqlite，
    # 导致重启后 War Room 漏斗显示为空。此处幂等补全，不依赖 LLM。
    try:
        import threading as _threading  # noqa: PLC0415
        from cangjie_fos.services.institution_store import sync_institutions_from_pitch_jobs  # noqa: PLC0415
        _threading.Thread(
            target=sync_institutions_from_pitch_jobs,
            daemon=True,
            name="institution-sync",
        ).start()
    except Exception as _e:  # noqa: BLE001
        import logging as _log  # noqa: PLC0415
        _log.getLogger(__name__).warning("institution startup sync 失败（非致命）: %s", _e)
    yield
    _scheduler.shutdown(wait=False)
    from cangjie_fos.services.npc_chat_graph import reset_compiled_npc_graph_for_tests

    reset_compiled_npc_graph_for_tests()
    shutdown_checkpointer()
    stop_watchdog_stub()
    set_main_event_loop(None)


def create_app() -> FastAPI:
    app = FastAPI(title="CangJie FOS", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> object:
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(StarletteHTTPException)
    async def _spa_fallback(request: Request, exc: StarletteHTTPException) -> object:
        if exc.status_code == 404:
            path = request.url.path
            if not any(path.startswith(p) for p in _SPA_EXCLUDE_PREFIXES):
                index = get_frontend_dist_dir() / "index.html"
                if index.is_file():
                    return FileResponse(str(index))
        return await http_exception_handler(request, exc)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> object:
        if isinstance(exc, StarletteHTTPException):
            return await _spa_fallback(request, exc)
        return await unhandled_exception_handler(request, exc)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    from cangjie_fos.core.paths import get_backend_root  # noqa: PLC0415

    html_reports_dir = get_backend_root() / "data" / "html_reports"
    html_reports_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = get_audio_dir()
    audio_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/reports", StaticFiles(directory=str(html_reports_dir)), name="html_reports")
    dist = get_frontend_dist_dir()
    if (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="spa")
    return app


app = create_app()
