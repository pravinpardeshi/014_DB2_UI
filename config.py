from __future__ import annotations

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    odbc_driver: str = field(default_factory=lambda: os.getenv("ODBC_DRIVER", "{IBM DB2 ODBC DRIVER}"))
    odbc_host: str = field(default_factory=lambda: os.getenv("ODBC_HOST", "localhost"))
    odbc_port: str = field(default_factory=lambda: os.getenv("ODBC_PORT", "50000"))
    odbc_database: str = field(default_factory=lambda: os.getenv("ODBC_DATABASE", "MFGDB"))
    odbc_uid: str = field(default_factory=lambda: os.getenv("ODBC_UID", ""))
    odbc_password: str = field(default_factory=lambda: os.getenv("ODBC_PWD", ""))

    app_host: str = field(default_factory=lambda: os.getenv("APP_HOST", "0.0.0.0"))
    app_port: int = field(default_factory=lambda: int(os.getenv("APP_PORT", "8000")))
    app_debug: bool = field(default_factory=lambda: os.getenv("APP_DEBUG", "false").lower() in ("true", "1", "yes"))
    app_mode: str = field(default_factory=lambda: os.getenv("APP_MODE", "demo"))

    @property
    def connection_string(self) -> str:
        parts = [
            f"DRIVER={self.odbc_driver}",
            f"HOST={self.odbc_host}",
            f"PORT={self.odbc_port}",
            f"DATABASE={self.odbc_database}",
            f"UID={self.odbc_uid}",
            f"PWD={self.odbc_password}",
        ]

        return ";".join(parts) + ";"


def load_settings() -> Settings:
    load_dotenv()
    return Settings()
