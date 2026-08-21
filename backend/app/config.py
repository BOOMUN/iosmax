from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    project_root: Path = PROJECT_ROOT
    data_dir: Path = Path(os.getenv("IOSMAX_DATA_DIR", PROJECT_ROOT / "data"))
    admin_username: str = os.getenv("IOSMAX_ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("IOSMAX_ADMIN_PASSWORD", "ChangeMe123!")
    session_hours: int = int(os.getenv("IOSMAX_SESSION_HOURS", "12"))
    host: str = os.getenv("IOSMAX_HOST", "127.0.0.1")
    port: int = int(os.getenv("IOSMAX_PORT", "8000"))
    injection_demo: bool = env_flag("IOSMAX_INJECTION_DEMO")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'iosmax.db').as_posix()}"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
