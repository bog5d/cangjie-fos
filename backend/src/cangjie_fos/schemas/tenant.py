"""多租户基类（SPEC A8）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class TenantScoped(BaseModel):
    tenant_id: str = Field(..., min_length=1, description="租户隔离主键")
