"""运行时配置（环境变量优先）。"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    """SPEC A2：集中读取环境变量，避免散落 os.getenv。"""

    pitch_coach_root: str | None = None
    evolution_data_dir: str | None = None
    enable_watchdog: bool = False
    log_full_feedback_body: bool = False
    sync_institution_to_coach: bool = True

    @classmethod
    def load(cls) -> Settings:
        return cls(
            pitch_coach_root=os.getenv("CANGJIE_PITCH_COACH_ROOT"),
            evolution_data_dir=os.getenv("CANGJIE_EVOLUTION_DATA_DIR"),
            enable_watchdog=_env_bool("CANGJIE_ENABLE_WATCHDOG", False),
            log_full_feedback_body=_env_bool("CANGJIE_LOG_FULL_FEEDBACK", False),
            sync_institution_to_coach=_env_bool("CANGJIE_SYNC_INSTITUTION_TO_COACH", True),
        )


settings = Settings.load()
