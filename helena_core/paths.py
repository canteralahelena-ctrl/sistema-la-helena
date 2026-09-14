from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


PATH_CONFIG_KEYS = {
    "config": ("HELENA_CONFIG_DIR", "config"),
    "scripts": ("HELENA_SCRIPTS_DIR", "."),
    "outputs": ("HELENA_OUTPUTS_DIR", "outputs"),
    "logs": ("HELENA_LOGS_DIR", "logs"),
    "data": ("HELENA_DATA_DIR", "data"),
    "tests": ("HELENA_TESTS_DIR", "tests"),
    "private_config": ("HELENA_PRIVATE_CONFIG", "telegram_bot_config.json"),
    "private_config_example": ("HELENA_PRIVATE_CONFIG_EXAMPLE", "telegram_bot_config.example.json"),
    "local_database": ("HELENA_LOCAL_DATABASE", None),
    "external": ("HELENA_EXTERNAL_DIR", None),
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_config_paths(config_path: Path) -> Mapping[str, str]:
    if not config_path.exists():
        return {}
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, Mapping):
        return {}
    paths = data.get("paths", {})
    return paths if isinstance(paths, Mapping) else {}


def _to_path(root: Path, value: str | os.PathLike[str] | None) -> Path | None:
    if value in (None, ""):
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


def _configured_path(
    key: str,
    root: Path,
    config_values: Mapping[str, str],
    environ: Mapping[str, str],
) -> Path | None:
    env_name, default_value = PATH_CONFIG_KEYS[key]
    raw_value = environ.get(env_name)
    if raw_value in (None, ""):
        raw_value = config_values.get(key, default_value)
    return _to_path(root, raw_value)


@dataclass(frozen=True)
class HelenaPaths:
    root: Path
    config: Path
    scripts: Path
    outputs: Path
    logs: Path
    data: Path
    tests: Path
    private_config: Path
    private_config_example: Path
    local_database: Path | None = None
    external: Path | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "root": str(self.root),
            "config": str(self.config),
            "scripts": str(self.scripts),
            "outputs": str(self.outputs),
            "logs": str(self.logs),
            "data": str(self.data),
            "tests": str(self.tests),
            "private_config": str(self.private_config),
            "private_config_example": str(self.private_config_example),
            "local_database": str(self.local_database) if self.local_database is not None else None,
            "external": str(self.external) if self.external is not None else None,
        }


def load_paths(
    *,
    root: Path | str | None = None,
    config_path: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> HelenaPaths:
    base = Path(root) if root is not None else project_root()
    env = os.environ if environ is None else environ
    path_config = Path(config_path) if config_path is not None else base / "config" / "environment.json"
    config_values = _read_config_paths(path_config)

    config_dir = _configured_path("config", base, config_values, env)
    scripts_dir = _configured_path("scripts", base, config_values, env)
    outputs_dir = _configured_path("outputs", base, config_values, env)
    logs_dir = _configured_path("logs", base, config_values, env)
    data_dir = _configured_path("data", base, config_values, env)
    tests_dir = _configured_path("tests", base, config_values, env)
    private_config_path = _configured_path("private_config", base, config_values, env)
    private_config_example_path = _configured_path("private_config_example", base, config_values, env)

    return HelenaPaths(
        root=base,
        config=config_dir if config_dir is not None else base / "config",
        scripts=scripts_dir if scripts_dir is not None else base,
        outputs=outputs_dir if outputs_dir is not None else base / "outputs",
        logs=logs_dir if logs_dir is not None else base / "logs",
        data=data_dir if data_dir is not None else base / "data",
        tests=tests_dir if tests_dir is not None else base / "tests",
        private_config=private_config_path if private_config_path is not None else base / "telegram_bot_config.json",
        private_config_example=(
            private_config_example_path
            if private_config_example_path is not None
            else base / "telegram_bot_config.example.json"
        ),
        local_database=_configured_path("local_database", base, config_values, env),
        external=_configured_path("external", base, config_values, env),
    )
