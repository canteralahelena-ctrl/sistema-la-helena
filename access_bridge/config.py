from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class BridgeConfig:
    access_path: Path
    postgres_dsn: str
    refresh_script: Path | None
    source_access_path: Path | None
    log_path: Path
    batch_size: int = 1000
    refresh_before_sync: bool = True


def load_config(path: str | Path, environ: Mapping[str, str] | None = None) -> BridgeConfig:
    env = os.environ if environ is None else environ
    config_path = Path(path).expanduser().resolve()
    try:
        raw: Any = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("No se pudo leer la configuración privada del puente.") from exc
    if not isinstance(raw, dict):
        raise ValueError("La configuración debe ser un objeto JSON.")
    root = config_path.parent

    def resolve(value: object) -> Path | None:
        if not value:
            return None
        candidate = Path(os.path.expandvars(str(value))).expanduser()
        return candidate if candidate.is_absolute() else (root / candidate).resolve()

    access_path = resolve(env.get("HELENA_BRIDGE_ACCESS_PATH") or raw.get("access_path"))
    dsn = env.get("HELENA_BRIDGE_POSTGRES_DSN") or str(raw.get("postgres_dsn") or "")
    if access_path is None or access_path.suffix.lower() not in {".accdb", ".mdb"}:
        raise ValueError("access_path debe indicar una copia local .accdb o .mdb.")
    if not dsn:
        raise ValueError("Falta HELENA_BRIDGE_POSTGRES_DSN o postgres_dsn.")
    refresh_value = raw.get("refresh_before_sync", True)
    if not isinstance(refresh_value, bool):
        raise ValueError("refresh_before_sync debe ser booleano.")
    try:
        batch_size = int(raw.get("batch_size", 1000))
    except (TypeError, ValueError) as exc:
        raise ValueError("batch_size debe ser un entero positivo.") from exc
    if batch_size < 1:
        raise ValueError("batch_size debe ser un entero positivo.")
    return BridgeConfig(
        access_path=access_path,
        postgres_dsn=dsn,
        refresh_script=resolve(raw.get("refresh_script")),
        source_access_path=resolve(raw.get("source_access_path")),
        log_path=resolve(raw.get("log_path")) or root / "bridge.log",
        batch_size=batch_size,
        refresh_before_sync=refresh_value,
    )


def redacted_dsn(dsn: str) -> str:
    """Never return credentials; only identify the PostgreSQL endpoint generically."""
    return "postgresql://***:***@***/***" if dsn else ""
