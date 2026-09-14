from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


CONTROL_KEYS = (
    "environment",
    "telegram_enabled",
    "automatic_alerts_enabled",
    "server_writes_enabled",
    "scheduled_tasks_enabled",
    "use_local_database_only",
)

DANGEROUS_FLAGS = (
    "telegram_enabled",
    "automatic_alerts_enabled",
    "server_writes_enabled",
    "scheduled_tasks_enabled",
)


def _default_config_path(project_root: Path | None = None) -> Path:
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]
    return root / "config" / "environment.json"


def _strict_bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


@dataclass(frozen=True)
class EnvironmentSettings:
    environment: str = "development"
    pilot_mode: bool = False
    telegram_enabled: bool = False
    automatic_alerts_enabled: bool = False
    server_writes_enabled: bool = False
    scheduled_tasks_enabled: bool = False
    use_local_database_only: bool = True
    source_path: Path | None = None
    source_found: bool = False
    invalid_environment: str | None = None
    read_error: str | None = None
    neutralized_keys: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    def as_dict(self) -> dict[str, bool | str]:
        return {
            "environment": self.environment,
            "pilot_mode": self.pilot_mode,
            "telegram_enabled": self.telegram_enabled,
            "automatic_alerts_enabled": self.automatic_alerts_enabled,
            "server_writes_enabled": self.server_writes_enabled,
            "scheduled_tasks_enabled": self.scheduled_tasks_enabled,
            "use_local_database_only": self.use_local_database_only,
        }


def _load_raw_config(config_path: Path) -> tuple[Mapping[str, Any], str | None, bool]:
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


def load_environment(
    config_path: Path | str | None = None,
    *,
    project_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> EnvironmentSettings:
    path = Path(config_path) if config_path is not None else _default_config_path(
        Path(project_root) if project_root is not None else None
    )
    data, read_error, source_found = _load_raw_config(path)
    env = os.environ if environ is None else environ
    pilot_mode = str(env.get("HELENA_PILOT_MODE", "")).strip() == "1"
    pilot_telegram = str(env.get("HELENA_PILOT_TELEGRAM", "")).strip() == "1"
    neutralized: list[str] = []

    requested_environment = str(data.get("environment", "development")).strip().lower()
    invalid_environment = None
    if requested_environment != "development":
        invalid_environment = requested_environment or "<empty>"
        neutralized.append("environment")

    values: dict[str, bool | str] = {
        "environment": "development",
        "telegram_enabled": False,
        "automatic_alerts_enabled": False,
        "server_writes_enabled": False,
        "scheduled_tasks_enabled": False,
        "use_local_database_only": True,
    }

    for key in DANGEROUS_FLAGS:
        if _strict_bool(data.get(key), False):
            neutralized.append(key)
        values[key] = False

    if pilot_mode and pilot_telegram:
        values["telegram_enabled"] = True

    if not _strict_bool(data.get("use_local_database_only"), True):
        neutralized.append("use_local_database_only")
    values["use_local_database_only"] = True

    return EnvironmentSettings(
        environment=str(values["environment"]),
        pilot_mode=pilot_mode,
        telegram_enabled=bool(values["telegram_enabled"]),
        automatic_alerts_enabled=bool(values["automatic_alerts_enabled"]),
        server_writes_enabled=bool(values["server_writes_enabled"]),
        scheduled_tasks_enabled=bool(values["scheduled_tasks_enabled"]),
        use_local_database_only=bool(values["use_local_database_only"]),
        source_path=path,
        source_found=source_found,
        invalid_environment=invalid_environment,
        read_error=read_error,
        neutralized_keys=tuple(dict.fromkeys(neutralized)),
    )
