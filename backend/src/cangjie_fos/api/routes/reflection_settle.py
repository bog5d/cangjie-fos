"""夜间结算 / 反思飞轮触发（Phase 4 SPEC A4）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends

from cangjie_fos.reflection.reflection_service import ReflectionService

router = APIRouter(prefix="/api/v1/reflection", tags=["reflection"])


class NightlySettleBody(BaseModel):
    tenant_id: str | None = Field(None, description="仅处理该租户；空则全量扫描")


def get_reflection_service() -> ReflectionService:
    return ReflectionService()


@router.post("/nightly-settle")
def nightly_settle(
    body: NightlySettleBody,
    svc: ReflectionService = Depends(get_reflection_service),
) -> dict:
    return dict(svc.run_nightly_settle(tenant_id=body.tenant_id))
