"""管理员端点（调试用）。"""
from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
doctor_router = APIRouter(prefix="/api/v1", tags=["admin"])


@router.post("/nightly-settle")
async def trigger_nightly_settle(tenant_id: str) -> dict:
    """立即执行单租户夜间结算（偏好提取），返回提取到的偏好条数。"""
    from cangjie_fos.services.nightly_settle import nightly_settle_for_tenant  # noqa: PLC0415

    count = await nightly_settle_for_tenant(tenant_id)
    return {"tenant_id": tenant_id, "extracted": count}


# ── Doctor 诊断端点 ──────────────────────────────────────────────────────────

def _check_data_dir() -> bool:
    from cangjie_fos.core.paths import get_backend_root  # noqa: PLC0415
    root = get_backend_root()
    return (root / "data" / "audio").is_dir() and (root / "data" / "html_reports").is_dir()


def _check_db_writable() -> bool:
    try:
        fd, tmp = tempfile.mkstemp(suffix=".sqlite")
        import os
        os.close(fd)
        conn = sqlite3.connect(tmp)
        conn.execute("CREATE TABLE _t (id INTEGER PRIMARY KEY)")
        conn.close()
        Path(tmp).unlink(missing_ok=True)
        return True
    except Exception:  # noqa: BLE001
        return False


@doctor_router.get("/doctor")
def run_doctor_probe() -> dict:
    """返回详细诊断报告，供前端「系统诊断」面板使用。"""
    issues: list[str] = []
    fix_suggestions: list[str] = []

    ffmpeg_ok = bool(shutil.which("ffmpeg"))
    if not ffmpeg_ok:
        issues.append("FFmpeg 未安装，语音转写功能不可用")
        fix_suggestions.append("安装 FFmpeg：winget install ffmpeg（Windows）或 brew install ffmpeg（Mac）")

    data_dir_ok = _check_data_dir()
    if not data_dir_ok:
        issues.append("data/ 目录不存在，运行时无法保存音频和报告")
        fix_suggestions.append("运行 python tools/doctor.py --fix 自动创建 data/ 目录")

    db_ok = _check_db_writable()
    if not db_ok:
        issues.append("SQLite 不可写，数据无法持久化")
        fix_suggestions.append("检查磁盘空间和目录权限，运行 python tools/doctor.py 查看详情")

    from cangjie_fos.core.paths import get_backend_root  # noqa: PLC0415
    env_ok = (get_backend_root() / ".env").is_file()
    if not env_ok:
        issues.append("backend/.env 不存在，API 密钥未配置")
        fix_suggestions.append("运行「填写API密钥_双击我.bat」或手动创建 backend/.env")

    return {
        "python_version": sys.version,
        "ffmpeg_available": ffmpeg_ok,
        "data_dir_writable": data_dir_ok,
        "port_8000_self": True,
        "db_writable": db_ok,
        "env_exists": env_ok,
        "issues": issues,
        "fix_suggestions": fix_suggestions,
    }
