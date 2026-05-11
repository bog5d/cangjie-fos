"""API Key 设置端点（运行时读写，不需要重启）。

注意：此路由不要求认证 token，因为 API Key 配置在启动初期就可能需要。
Key 写入 os.environ（立即生效，因 os.getenv() 调用时读取），同时持久化到 backend/.env。
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cangjie_fos.core.paths import get_backend_root

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

# 允许在界面配置的 Key 白名单
_KEY_NAMES: set[str] = {"DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "KIMI_API_KEY"}


class KeysPayload(BaseModel):
    keys: dict[str, str]  # key_name -> value


@router.get("/api-keys")
def get_api_keys() -> dict[str, bool]:
    """返回各 Key 是否已填写（不返回实际 Key 值，避免泄漏）。"""
    return {k: bool((os.getenv(k) or "").strip()) for k in sorted(_KEY_NAMES)}


@router.post("/api-keys")
def set_api_keys(payload: KeysPayload) -> dict[str, bool]:
    """更新 os.environ 并持久化到 backend/.env（立即生效，无需重启）。"""
    unknown = set(payload.keys) - _KEY_NAMES
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知 Key 名称: {sorted(unknown)}")

    env_path = get_backend_root() / ".env"

    # 读取现有 .env（保留注释和其他行）
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    for key, value in payload.keys.items():
        value = value.strip()
        # 写入当前进程 env（调用时读取的 os.getenv() 会立即生效）
        os.environ[key] = value
        # 更新 .env 文件中对应行
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
                lines[i] = f"{key}={value}"
                found = True
                break
        if not found:
            lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True}


@router.post("/api-keys/test-deepseek")
def test_deepseek() -> dict[str, object]:
    """测试 DEEPSEEK_API_KEY 是否有效（发送最小请求验证连通性）。"""
    key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        return {"ok": False, "message": "DEEPSEEK_API_KEY 尚未填写"}
    try:
        resp = httpx.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            },
            timeout=15.0,
        )
        if resp.status_code == 200:
            return {"ok": True, "message": "DeepSeek 连接正常 ✅"}
        if resp.status_code == 401:
            return {"ok": False, "message": "DeepSeek Key 无效（401 Unauthorized），请重新获取"}
        if resp.status_code == 402:
            return {"ok": False, "message": "DeepSeek 账户余额不足（402），请充值后再试"}
        return {"ok": False, "message": f"HTTP {resp.status_code}：{resp.text[:200]}"}
    except httpx.TimeoutException:
        return {"ok": False, "message": "连接超时（15s），请检查网络或稍后重试"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"连接异常：{str(e)[:200]}"}


@router.post("/api-keys/test-dashscope")
def test_dashscope() -> dict[str, object]:
    """测试 DASHSCOPE_API_KEY 是否有效（访问 DashScope 转写列表接口验证鉴权）。"""
    key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
    if not key:
        return {"ok": False, "message": "DASHSCOPE_API_KEY 尚未填写"}
    try:
        # 查询任务列表（不传 task_id，会返回列表或 400；重要的是看是否 401）
        resp = httpx.get(
            "https://dashscope.aliyuncs.com/api/v1/tasks",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10.0,
        )
        if resp.status_code == 401:
            return {"ok": False, "message": "DashScope Key 无效（401 Unauthorized），请重新获取"}
        # 400/404/200 均说明 Key 本身有效，只是请求参数可能不对
        return {"ok": True, "message": f"阿里云百炼连接正常（HTTP {resp.status_code}）✅"}
    except httpx.TimeoutException:
        return {"ok": False, "message": "连接超时（10s），请检查网络或稍后重试"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"连接异常：{str(e)[:200]}"}
