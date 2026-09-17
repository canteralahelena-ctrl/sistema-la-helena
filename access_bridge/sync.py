from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .access import AccessReader
from .catalog import MAPPINGS
from .config import BridgeConfig
from .postgres import PostgresReplica


def refresh_local_copy(config: BridgeConfig) -> None:
    if not config.refresh_before_sync:
        return
    if config.refresh_script is None or not config.refresh_script.is_file():
        raise RuntimeError("No se configuró el script existente de actualización de copia local.")
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(config.refresh_script), "-Destino", str(config.access_path)]
    if config.source_access_path is not None:
        command.extend(["-Origen", str(config.source_access_path)])
    result = subprocess.run(
        command,
        check=False, capture_output=True, text=True, timeout=600,
    )
    if result.returncode:
        raise RuntimeError("Falló la actualización segura de la copia local.")


def fingerprint(path: Path) -> str:
    stat = path.stat()
    return hashlib.sha256(f"{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()


def run_sync(config: BridgeConfig, *, migrate: bool = True, reader_class: Any = AccessReader, replica_class: Any = PostgresReplica) -> dict[str, Any]:
    refresh_local_copy(config)
    started = datetime.now(timezone.utc)
    counts: dict[str, int] = {}
    root = Path(__file__).resolve().parents[1]
    try:
        with reader_class(config.access_path) as access, replica_class(config.postgres_dsn) as postgres:
            if migrate:
                postgres.migrate(root / "migrations")
            # One PostgreSQL transaction: a failed table leaves the previous snapshot intact.
            with postgres.sync_run() as cursor:
                for mapping in MAPPINGS:
                    batches = list(access.rows(mapping, config.batch_size))
                    counts[mapping.target_table] = postgres.replace_table(cursor, mapping, batches)
                cursor.execute(
                    "INSERT INTO replica.sync_runs(started_at, finished_at, status, source_fingerprint, row_counts) VALUES (%s,%s,'ok',%s,%s::jsonb)",
                    (started, datetime.now(timezone.utc), fingerprint(config.access_path), json.dumps(counts)),
                )
        result = {"status": "ok", "started_at": started.isoformat(), "tables": counts}
        _write_log(config.log_path, result)
        return result
    except Exception:
        _write_log(config.log_path, {"status": "error", "started_at": started.isoformat(), "message": "sync_failed"})
        raise


def _write_log(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
