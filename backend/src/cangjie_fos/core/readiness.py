"""运行时就绪探针：Coach、环境、前端、桥接数据、磁盘、SQLite（供 /api/v1/ready）。"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from shutil import disk_usage

from cangjie_fos.core.paths import (
    get_backend_root,
    get_fos_bridge_data_dir,
    get_frontend_dist_dir,
    get_langgraph_sqlite_path,
    get_pitch_coach_root,
    hydrate_pitch_coach_env,
)

# 稳定错误码，与文档、前端横幅对应
E_PITCH_COACH_SRC_MISSING = "E_PITCH_COACH_SRC_MISSING"
E_API_KEYS_INCOMPLETE = "E_API_KEYS_INCOMPLETE"
E_FRONTEND_DIST_MISSING = "E_FRONTEND_DIST_MISSING"
W_ASSET_INDEX_MISSING = "W_ASSET_INDEX_MISSING"
W_ASSET_INDEX_TOO_LARGE = "W_ASSET_INDEX_TOO_LARGE"
E_ASSET_INDEX_IO = "E_ASSET_INDEX_IO"
E_DISK_CRITICALLY_LOW = "E_DISK_CRITICALLY_LOW"
E_SQLITE_INTEGRITY = "E_SQLITE_INTEGRITY"


@dataclass
class ReadinessIssue:
    code: str
    message: str
    fix_hint: str
    severity: str = "error"  # error | warn


@dataclass
class ReadinessResult:
    ok: bool
    issues: list[ReadinessIssue] = field(default_factory=list)
    pitch_coach_ok: bool = False
    api_keys_ok: bool = False
    frontend_dist_ok: bool = False
    asset_index_ok: bool = True
    asset_index_warn: bool = False
    disk_free_bytes: int = 0
    disk_sufficient: bool = True
    bridge_dir: str = ""
    pitch_coach_root: str = ""
    sqlite_ok: bool = True
    sqlite_details: dict[str, str] = field(default_factory=dict)
    job_queue_in_use: int = 0
    job_queue_capacity: int = 0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "issues": [
                {"code": i.code, "message": i.message, "fix_hint": i.fix_hint, "severity": i.severity}
                for i in self.issues
            ],
            "pitch_coach_ok": self.pitch_coach_ok,
            "api_keys_ok": self.api_keys_ok,
            "frontend_dist_ok": self.frontend_dist_ok,
            "asset_index_ok": self.asset_index_ok,
            "asset_index_warn": self.asset_index_warn,
            "disk_free_bytes": self.disk_free_bytes,
            "disk_sufficient": self.disk_sufficient,
            "bridge_dir": self.bridge_dir,
            "pitch_coach_root": self.pitch_coach_root,
            "sqlite_ok": self.sqlite_ok,
            "sqlite_details": self.sqlite_details,
            "job_queue_in_use": self.job_queue_in_use,
            "job_queue_capacity": self.job_queue_capacity,
        }


def _min_disk_bytes() -> int:
    v = (os.getenv("CANGJIE_MIN_DISK_FREE_MB") or "256").strip()
    try:
        return max(64, int(v)) * 1024 * 1024
    except ValueError:
        return 256 * 1024 * 1024


def _max_asset_index_bytes() -> int:
    v = (os.getenv("CANGJIE_MAX_ASSET_INDEX_MB") or "32").strip()
    try:
        return max(1, int(v)) * 1024 * 1024
    except ValueError:
        return 32 * 1024 * 1024


def _check_sqlite_file(path: Path) -> str | None:
    """若文件存在则 PRAGMA integrity_check；返回 None=ok 或错误信息。"""
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2.0)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
        if row and str(row[0]).lower() == "ok":
            return None
        return row[0] if row else "unknown"
    except OSError as e:
        return str(e)
    except sqlite3.Error as e:
        return str(e)


def compute_readiness() -> ReadinessResult:
    """合并 .env 后再检查（与主进程 lifespan 行为一致）。"""
    try:
        hydrate_pitch_coach_env()
    except Exception:  # noqa: BLE001
        pass

    issues: list[ReadinessIssue] = []
    r = ReadinessResult(ok=True, issues=issues)

    # ---- Pitch_Coach ----
    root = get_pitch_coach_root()
    r.pitch_coach_root = str(root)
    src = root / "src"
    r.pitch_coach_ok = src.is_dir()
    if not r.pitch_coach_ok:
        issues.append(
            ReadinessIssue(
                code=E_PITCH_COACH_SRC_MISSING,
                message="未找到 AI_Pitch_Coach 的 src 目录",
                fix_hint="将 AI_Pitch_Coach 与 CangJie_FOS 并列放在同一父目录，或在 backend/.env 设置 CANGJIE_PITCH_COACH_ROOT=绝对路径",
            )
        )

    # ---- API keys（主力 + 转写二选一策略：Silicon 必填，DeepSeek 按产品；这里报缺省） ----
    sili = (os.getenv("SILICONFLOW_API_KEY") or "").strip()
    deep = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    r.api_keys_ok = bool(sili) and bool(deep)
    if not sili or not deep:
        issues.append(
            ReadinessIssue(
                code=E_API_KEYS_INCOMPLETE,
                message="SILICONFLOW_API_KEY 或 DEEPSEEK_API_KEY 未配置",
                fix_hint="运行「填写API密钥_双击我.bat」或编辑 backend/.env，在 = 后粘贴密钥并保存",
                severity="error",
            )
        )
    if not (os.getenv("DASHSCOPE_API_KEY") or "").strip():
        # 不阻断 ok，仅警告
        issues.append(
            ReadinessIssue(
                code="W_DASHSCOPE_OPTIONAL",
                message="未配置 DASHSCOPE_API_KEY，语音转写将不可用",
                fix_hint="若需上传录音，请在 .env 中填写 DASHSCOPE_API_KEY",
                severity="warn",
            )
        )

    # ---- frontend dist ----
    dist = get_frontend_dist_dir() / "index.html"
    r.frontend_dist_ok = dist.is_file()
    if not r.frontend_dist_ok:
        issues.append(
            ReadinessIssue(
                code=E_FRONTEND_DIST_MISSING,
                message="未找到前端构建产物 frontend/dist/index.html",
                fix_hint="在 CangJie_FOS 目录执行 build_frontend.ps1 或 cd frontend && npm run build",
            )
        )

    # ---- 桥与 asset_index ----
    bridge = get_fos_bridge_data_dir()
    r.bridge_dir = str(bridge)
    idx = bridge / "asset_index.json"
    max_b = _max_asset_index_bytes()
    if not idx.is_file():
        r.asset_index_ok = True
        r.asset_index_warn = True
        issues.append(
            ReadinessIssue(
                code=W_ASSET_INDEX_MISSING,
                message="未找到 .fos_data/asset_index.json（资产台账可能为空）",
                fix_hint="若使用仓颉资产台账 FSS：在 FSS 中执行「向上扫描」；并确保 FSS 与 FOS 的 .fos_data 路径一致",
                severity="warn",
            )
        )
    else:
        try:
            st = idx.stat()
            if st.st_size > max_b:
                r.asset_index_ok = True
                r.asset_index_warn = True
                issues.append(
                    ReadinessIssue(
                        code=W_ASSET_INDEX_TOO_LARGE,
                        message=f"asset_index.json 超过建议大小（>{max_b // (1024 * 1024)}MB）",
                        fix_hint="提高阈值 CANGJIE_MAX_ASSET_INDEX_MB 或清理索引；列表页可能变慢",
                        severity="warn",
                    )
                )
        except OSError as e:
            r.asset_index_ok = False
            issues.append(
                ReadinessIssue(
                    code=E_ASSET_INDEX_IO,
                    message=f"无法读取 asset_index：{e}",
                    fix_hint="检查 .fos_data 目录权限与磁盘",
                )
            )

    # ---- 磁盘 ----
    try:
        be = get_backend_root()
        du = disk_usage(be)
        r.disk_free_bytes = int(du.free)
        r.disk_sufficient = du.free >= _min_disk_bytes()
        if not r.disk_sufficient:
            issues.append(
                ReadinessIssue(
                    code=E_DISK_CRITICALLY_LOW,
                    message="磁盘剩余空间可能不足",
                    fix_hint="清理磁盘或提高 CANGJIE_MIN_DISK_FREE_MB 以下仍警告",
                    severity="warn",
                )
            )
    except OSError:
        r.disk_free_bytes = 0
        r.disk_sufficient = False

    # ---- SQLite（仅当文件已存在时做 integrity_check）----
    to_check = [
        ("langgraph", get_langgraph_sqlite_path()),
        ("pitch_jobs", get_backend_root() / "data" / "pitch_jobs.sqlite"),
        ("npc_threads", get_backend_root() / "data" / "npc_threads.sqlite"),
        ("institutions", get_backend_root() / "data" / "institutions.sqlite"),
    ]
    for name, p in to_check:
        if not p.is_file():
            r.sqlite_details[name] = "absent"
            continue
        err = _check_sqlite_file(p)
        if err is not None:
            r.sqlite_ok = False
            r.sqlite_details[name] = err
            issues.append(
                ReadinessIssue(
                    code=E_SQLITE_INTEGRITY,
                    message=f"SQLite 损坏或不可读: {name} ({err})",
                    fix_hint="关闭服务后使用 tools/backup_sqlite.ps1 备份，再删库文件以重建或从备份恢复",
                )
            )
        else:
            r.sqlite_details[name] = "ok"

    # 队列（job_semaphore 背压模块）
    try:
        from cangjie_fos.core.job_semaphore import queue_snapshot

        snap = queue_snapshot()
        r.job_queue_in_use = snap.get("in_use", 0)
        r.job_queue_capacity = snap.get("capacity", 0)
    except Exception:  # noqa: BLE001
        pass

    # 汇总 ok：硬条件 + 无 error 级 issue + sqlite
    hard = r.pitch_coach_ok and r.api_keys_ok and r.frontend_dist_ok and r.asset_index_ok and r.sqlite_ok
    err_issues = [i for i in issues if i.severity == "error"]
    r.ok = hard and len(err_issues) == 0
    r.issues = issues
    return r
