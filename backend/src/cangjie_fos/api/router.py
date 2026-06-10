"""顶层 API 聚合（禁止在此写业务实现）。"""
from __future__ import annotations

from fastapi import APIRouter

from cangjie_fos.api.routes import (
    admin,
    assets,
    auth,
    coaching,
    dashboard,
    dd_response,
    feedback,
    follow_ups,
    health,
    materials,
    npc,
    participants,
    pipeline,
    pitch,
    pitch_wizard,
    ready,
    reflection_settle,
    roadshow,
    settings,
    war_room,
    watch,
    webhooks,
    wiki,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(health.router, tags=["health"])
api_router.include_router(ready.router)
api_router.include_router(feedback.router, prefix="/api/v1", tags=["evolution"])
api_router.include_router(reflection_settle.router)
api_router.include_router(webhooks.router, prefix="/api/v1", tags=["webhooks"])
api_router.include_router(watch.router, prefix="/api/v1", tags=["watch"])
api_router.include_router(pipeline.router)
api_router.include_router(dashboard.router)
api_router.include_router(war_room.router)
api_router.include_router(pitch.router)
api_router.include_router(pitch_wizard.router)
api_router.include_router(participants.router)
api_router.include_router(npc.router)
api_router.include_router(assets.router)
api_router.include_router(materials.router)
api_router.include_router(admin.router)
api_router.include_router(admin.doctor_router)
api_router.include_router(wiki.router)
api_router.include_router(follow_ups.router)
api_router.include_router(settings.router)
api_router.include_router(roadshow.router)
api_router.include_router(dd_response.router)
api_router.include_router(coaching.router)
