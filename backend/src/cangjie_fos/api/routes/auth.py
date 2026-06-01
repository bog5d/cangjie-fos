"""简单账号认证 — 登录门控。

设计原则：
- 账号列表配置在 .env FOS_ACCOUNTS（格式：账号:密码:tenant_id，逗号分隔）
- 登录成功 → 生成 UUID token，存内存，有效期 72 小时
- 登录成功 → 后台触发 GitHub pull（拉取该 tenant 的最新数据）
- 前端 localStorage 存 token，每次请求 header 带 X-FOS-Token
- /api/auth/me 验证 token 有效性，返回 tenant_id 供前端使用
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

# ─── 内存 session 存储 ────────────────────────────────────────────────────────
# {token: {username, tenant_id, login_at}}
_sessions: dict[str, dict[str, Any]] = {}
_TOKEN_TTL = 72 * 3600  # 72小时

# 内置默认账号：两个租户数据完全隔离（tenant=zt / tenant=gk）
# .env 里的 FOS_ACCOUNTS 会覆盖此默认值；未配置时自动生效
_BUILTIN_ACCOUNTS = "zt001:123456:zt,gk001:123456:gk"


def _load_accounts() -> dict[str, dict[str, str]]:
    """从环境变量读取账号表。格式：账号:密码:tenant_id，逗号分隔。
    未配置 FOS_ACCOUNTS 时使用内置默认账号（zt001/gk001）。
    """
    raw = os.getenv("FOS_ACCOUNTS", _BUILTIN_ACCOUNTS).strip()
    accounts: dict[str, dict[str, str]] = {}
    if not raw:
        return accounts
    for entry in raw.split(","):
        parts = entry.strip().split(":")
        if len(parts) == 3:
            username, password, tenant_id = parts
            accounts[username.strip()] = {
                "password": password.strip(),
                "tenant_id": tenant_id.strip(),
            }
    return accounts


def get_session(token: str) -> dict[str, Any] | None:
    """验证 token 并返回 session。过期或不存在返回 None。"""
    sess = _sessions.get(token)
    if not sess:
        return None
    if time.time() - sess["login_at"] > _TOKEN_TTL:
        del _sessions[token]
        return None
    return sess


def require_session(token: str | None) -> dict[str, Any]:
    """验证 token，失败抛 401。供其他路由调用。"""
    if not token:
        raise HTTPException(status_code=401, detail="未登录，请先登录")
    sess = get_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="会话已过期，请重新登录")
    return sess


# ─── 请求/响应 schema ─────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    tenant_id: str
    message: str = "登录成功"


class MeResponse(BaseModel):
    username: str
    tenant_id: str
    login_at: float


# ─── 路由 ─────────────────────────────────────────────────────────────────────

@router.post("/api/auth/login", response_model=LoginResponse, tags=["auth"])
def login_route(body: LoginRequest, background_tasks: BackgroundTasks) -> LoginResponse:
    """登录。成功后后台拉取 GitHub 最新数据。"""
    accounts = _load_accounts()
    account = accounts.get(body.username)
    if not account or account["password"] != body.password:
        raise HTTPException(status_code=401, detail="账号或密码错误")

    token = str(uuid.uuid4())
    tenant_id = account["tenant_id"]
    _sessions[token] = {
        "username": body.username,
        "tenant_id": tenant_id,
        "login_at": time.time(),
    }
    logger.info("用户 %s (tenant=%s) 登录成功", body.username, tenant_id)

    # 登录后台触发 GitHub pull（拉取该 tenant 最新数据）
    background_tasks.add_task(_pull_for_tenant, tenant_id)

    return LoginResponse(token=token, username=body.username, tenant_id=tenant_id)


@router.get("/api/auth/me", response_model=MeResponse, tags=["auth"])
def me_route(request: Request) -> MeResponse:
    """验证 token 有效性，前端用于判断是否需要重新登录。"""
    token = request.headers.get("X-FOS-Token") or request.query_params.get("token", "")
    sess = require_session(token or None)
    return MeResponse(
        username=sess["username"],
        tenant_id=sess["tenant_id"],
        login_at=sess["login_at"],
    )


@router.post("/api/auth/logout", tags=["auth"])
def logout_route(request: Request) -> dict[str, str]:
    """注销 token。"""
    token = request.headers.get("X-FOS-Token") or request.query_params.get("token", "")
    if token and token in _sessions:
        del _sessions[token]
    return {"message": "已退出登录"}


@router.get("/api/auth/accounts-configured", tags=["auth"])
def accounts_configured_route() -> dict[str, bool]:
    """前端用于判断是否需要显示登录页。"""
    return {"configured": bool(_load_accounts())}


@router.get("/api/sync/status", tags=["auth"])
def sync_status_route() -> dict[str, Any]:
    """返回最近一次 GitHub 同步的状态（无需认证，供 UI 状态栏使用）。"""
    from cangjie_fos.services.github_sync import get_sync_status  # noqa: PLC0415
    return get_sync_status()


@router.post("/api/sync/pull", tags=["auth"])
async def sync_pull_route(request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """手动触发 GitHub 数据同步（异步后台执行，立即返回，避免超时）。"""
    token = request.headers.get("X-FOS-Token") or request.query_params.get("token", "")
    sess = require_session(token or None)
    tenant_id = sess["tenant_id"]

    from cangjie_fos.services.github_sync import is_configured  # noqa: PLC0415
    if not is_configured():
        return {"ok": False, "message": "GitHub 同步未配置（COACH_DATA_GITHUB_TOKEN 未设置）", "pitch_imported": 0, "match_imported": 0}

    background_tasks.add_task(_pull_for_tenant, tenant_id)
    return {"ok": True, "message": "同步已在后台启动，30秒后刷新页面查看新数据", "pitch_imported": 0, "match_imported": 0}


# ─── 内部辅助 ─────────────────────────────────────────────────────────────────

def _pull_for_tenant(tenant_id: str) -> None:
    """登录后拉取 GitHub 数据，临时设置 tenant_id 环境变量。"""
    import os as _os  # noqa: PLC0415
    original = _os.environ.get("COACH_DATA_TENANT_ID", "")
    _os.environ["COACH_DATA_TENANT_ID"] = tenant_id
    try:
        from cangjie_fos.services.github_sync import pull_latest  # noqa: PLC0415
        result = pull_latest()
        logger.info("GitHub pull for tenant=%s: %s", tenant_id, result)
    except Exception as e:  # noqa: BLE001
        logger.warning("GitHub pull 失败 tenant=%s: %s", tenant_id, e)
    finally:
        _os.environ["COACH_DATA_TENANT_ID"] = original
