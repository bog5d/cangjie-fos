from __future__ import annotations

from fastapi import APIRouter

from cangjie_fos.core.readiness import compute_readiness

router = APIRouter()


@router.get("/api/v1/ready", tags=["health"])
def get_ready() -> dict:
    """分时就绪探针：Coach、Key、前端、桥接、磁盘、SQLite、任务队列。供启动脚本与 UI 防呆。"""
    r = compute_readiness()
    return r.to_dict()
