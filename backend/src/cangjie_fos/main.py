"""ASGI 入口：仅组装应用。"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from cangjie_fos.api.router import api_router
from cangjie_fos.core.checkpointing import get_sqlite_checkpointer, shutdown_checkpointer
from cangjie_fos.core.config import settings
from cangjie_fos.core.paths import get_frontend_dist_dir
from cangjie_fos.events.file_watchdog import start_file_watchdog, stop_file_watchdog
from cangjie_fos.events.npc_ws_house import set_main_event_loop
from cangjie_fos.events.watchdog_runner import stop_watchdog_stub


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    set_main_event_loop(asyncio.get_running_loop())
    get_sqlite_checkpointer()
    if settings.enable_watchdog:
        start_file_watchdog()
    yield
    from cangjie_fos.services.npc_chat_graph import reset_compiled_npc_graph_for_tests

    reset_compiled_npc_graph_for_tests()
    shutdown_checkpointer()
    stop_watchdog_stub()
    set_main_event_loop(None)


def create_app() -> FastAPI:
    app = FastAPI(title="CangJie FOS", version="0.1.0", lifespan=lifespan)
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
    dist = get_frontend_dist_dir()
    if (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="spa")
    return app


app = create_app()
