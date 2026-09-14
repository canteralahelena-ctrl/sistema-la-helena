from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .environment import EnvironmentSettings, load_environment
from .paths import HelenaPaths, load_paths, project_root


def _default_config_path(root: Path) -> Path:
    return root / "config" / "environment.json"


def _read_config(config_path: Path) -> tuple[Mapping[str, Any], str | None, bool]:
    if not config_path.exists():
        return {}, None, False
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return {}, exc.__class__.__name__, True
    if not isinstance(data, Mapping):
        return {}, "InvalidRootType", True
    return data, None, True


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any, default: str) -> str:
    if value in (None, ""):
        return default
    return str(value)


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _int_value(value: Any, default: int, *, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def _optional_path(root: Path, value: Any) -> Path | None:
    if value in (None, ""):
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


@dataclass(frozen=True)
class TechnicalSettings:
    powershell_executable: str = "powershell"
    ffmpeg_executable: str = "ffmpeg"
    lock_port: int = 47825


@dataclass(frozen=True)
class PrivateConfigSettings:
    telegram_bot_config: Path
    telegram_bot_config_example: Path
    email_config: Path
    email_config_example: Path


@dataclass(frozen=True)
class UserConfigSettings:
    telegram_users: Path
    telegram_pending_users: Path


@dataclass(frozen=True)
class BusinessConfigSettings:
    intent_dictionary: Path


@dataclass(frozen=True)
class DatabaseSettings:
    local_database: Path | None = None
    server_database_ref: str | None = None
    allow_database_writes: bool = False


@dataclass(frozen=True)
class TimeoutSettings:
    default_script_seconds: int = 180
    long_script_seconds: int = 240
    export_script_seconds: int = 300
    audio_conversion_seconds: int = 120
    telegram_call_seconds: int = 120
    telegram_update_seconds: int = 30
    payment_seconds: int = 60
    dashboard_cache_ttl_seconds: int = 600


@dataclass(frozen=True)
class AppSettings:
    paths: HelenaPaths
    environment: EnvironmentSettings
    technical: TechnicalSettings
    private_config: PrivateConfigSettings
    user_config: UserConfigSettings
    business_config: BusinessConfigSettings
    databases: DatabaseSettings
    timeouts: TimeoutSettings
    source_path: Path
    source_found: bool = False
    read_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "paths": self.paths.as_dict(),
            "environment": self.environment.as_dict(),
            "technical": {
                "powershell_executable": self.technical.powershell_executable,
                "ffmpeg_executable": self.technical.ffmpeg_executable,
                "lock_port": self.technical.lock_port,
            },
            "private_config": {
                "telegram_bot_config": str(self.private_config.telegram_bot_config),
                "telegram_bot_config_example": str(self.private_config.telegram_bot_config_example),
                "email_config": str(self.private_config.email_config),
                "email_config_example": str(self.private_config.email_config_example),
            },
            "user_config": {
                "telegram_users": str(self.user_config.telegram_users),
                "telegram_pending_users": str(self.user_config.telegram_pending_users),
            },
            "business_config": {
                "intent_dictionary": str(self.business_config.intent_dictionary),
            },
            "databases": {
                "local_database": (
                    str(self.databases.local_database) if self.databases.local_database is not None else None
                ),
                "server_database_ref": self.databases.server_database_ref,
                "allow_database_writes": self.databases.allow_database_writes,
            },
            "timeouts": {
                "default_script_seconds": self.timeouts.default_script_seconds,
                "long_script_seconds": self.timeouts.long_script_seconds,
                "export_script_seconds": self.timeouts.export_script_seconds,
                "audio_conversion_seconds": self.timeouts.audio_conversion_seconds,
                "telegram_call_seconds": self.timeouts.telegram_call_seconds,
                "telegram_update_seconds": self.timeouts.telegram_update_seconds,
                "payment_seconds": self.timeouts.payment_seconds,
                "dashboard_cache_ttl_seconds": self.timeouts.dashboard_cache_ttl_seconds,
            },
            "source_found": self.source_found,
            "read_error": self.read_error,
        }


def load_settings(
    *,
    root: Path | str | None = None,
    config_path: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> AppSettings:
    base = Path(root) if root is not None else project_root()
    env = os.environ if environ is None else environ
    path = Path(config_path) if config_path is not None else _default_config_path(base)
    data, read_error, source_found = _read_config(path)

    paths = load_paths(root=base, config_path=path, environ=env)
    environment = load_environment(path, environ=env)

    executables = _mapping(data.get("executables"))
    private = _mapping(data.get("private_config"))
    users = _mapping(data.get("user_config"))
    business = _mapping(data.get("business_config"))
    databases = _mapping(data.get("databases"))
    timeouts = _mapping(data.get("timeouts"))

    technical = TechnicalSettings(
        powershell_executable=_text(
            env.get("HELENA_POWERSHELL_EXE"),
            _text(executables.get("powershell"), "powershell"),
        ),
        ffmpeg_executable=_text(
            env.get("HELENA_FFMPEG_EXE"),
            _text(executables.get("ffmpeg"), "ffmpeg"),
        ),
        lock_port=_int_value(env.get("HELENA_LOCK_PORT") or executables.get("lock_port"), 47825),
    )

    private_config = PrivateConfigSettings(
        telegram_bot_config=paths.private_config,
        telegram_bot_config_example=paths.private_config_example,
        email_config=_optional_path(base, private.get("email_config")) or base / "email_config.json",
        email_config_example=(
            _optional_path(base, private.get("email_config_example")) or base / "email_config.example.json"
        ),
    )
    user_config = UserConfigSettings(
        telegram_users=(
            _optional_path(base, env.get("HELENA_TELEGRAM_USERS"))
            or _optional_path(base, users.get("telegram_users"))
            or base / "telegram_usuarios.json"
        ),
        telegram_pending_users=(
            _optional_path(base, env.get("HELENA_TELEGRAM_PENDING_USERS"))
            or _optional_path(base, users.get("telegram_pending_users"))
            or base / "telegram_pending_users.json"
        ),
    )
    business_config = BusinessConfigSettings(
        intent_dictionary=_optional_path(base, business.get("intent_dictionary")) or base / "diccionario_intenciones.json",
    )

    database_settings = DatabaseSettings(
        local_database=(
            paths.local_database
            or _optional_path(base, data.get("local_database_path"))
            or _optional_path(base, databases.get("local"))
        ),
        server_database_ref=_optional_text(env.get("HELENA_SERVER_DATABASE_REF"))
        or _optional_text(databases.get("server_ref")),
        allow_database_writes=False,
    )
    timeout_settings = TimeoutSettings(
        default_script_seconds=_int_value(timeouts.get("default_script_seconds"), 180),
        long_script_seconds=_int_value(timeouts.get("long_script_seconds"), 240),
        export_script_seconds=_int_value(timeouts.get("export_script_seconds"), 300),
        audio_conversion_seconds=_int_value(timeouts.get("audio_conversion_seconds"), 120),
        telegram_call_seconds=_int_value(timeouts.get("telegram_call_seconds"), 120),
        telegram_update_seconds=_int_value(timeouts.get("telegram_update_seconds"), 30),
        payment_seconds=_int_value(timeouts.get("payment_seconds"), 60),
        dashboard_cache_ttl_seconds=_int_value(timeouts.get("dashboard_cache_ttl_seconds"), 600),
    )

    return AppSettings(
        paths=paths,
        environment=environment,
        technical=technical,
        private_config=private_config,
        user_config=user_config,
        business_config=business_config,
        databases=database_settings,
        timeouts=timeout_settings,
        source_path=path,
        source_found=source_found,
        read_error=read_error,
    )
