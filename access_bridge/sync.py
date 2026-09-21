from __future__ import annotations

import hashlib
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
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_sync(
    config: BridgeConfig,
    *,
    force: bool = False,
    reader_class: Any = AccessReader,
    replica_class: Any = PostgresReplica,
) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    counts: dict[str, int] = {}
    result: dict[str, Any]
    stage = "refresh"
    table: str | None = None
    try:
        refresh_local_copy(config)
        stage = "fingerprint"
        source_fingerprint = fingerprint(config.access_path)
        stage = "postgres_connect"
        with replica_class(config.postgres_dsn) as postgres:
            # One PostgreSQL transaction and one advisory lock protect the whole snapshot.
            stage = "lock"
            with postgres.sync_run() as cursor:
                stage = "fingerprint_check"
                previous_fingerprint, previous_counts = postgres.latest_snapshot(cursor)
                if previous_fingerprint == source_fingerprint and not force:
                    stage = "record_run"
                    postgres.record_run(
                        cursor,
                        started_at=started,
                        finished_at=datetime.now(timezone.utc),
                        status="skipped",
                        source_fingerprint=source_fingerprint,
                        row_counts=previous_counts,
                    )
                    result = {
                        "status": "skipped",
                        "started_at": started.isoformat(),
                        "tables": previous_counts,
                    }
                else:
                    stage = "access_connect"
                    with reader_class(config.access_path) as access:
                        for mapping in MAPPINGS:
                            table = mapping.target_table
                            stage = "table_sync"
                            batches = access.rows(mapping, config.batch_size)
                            inserted = postgres.replace_table(cursor, mapping, batches)
                            stage = "table_verify"
                            persisted = postgres.table_count(cursor, mapping)
                            if persisted != inserted:
                                raise RuntimeError("El conteo persistido no coincide con la fuente.")
                            counts[mapping.target_table] = persisted
                    table = None
                    stage = "record_run"
                    postgres.record_run(
                        cursor,
                        started_at=started,
                        finished_at=datetime.now(timezone.utc),
                        status="ok",
                        source_fingerprint=source_fingerprint,
                        row_counts=counts,
                    )
                    result = {"status": "ok", "started_at": started.isoformat(), "tables": counts}
        _write_log(config.log_path, result)
        return result
    except Exception as exc:
        event: dict[str, Any] = {
            "status": "error",
            "started_at": started.isoformat(),
            "stage": stage,
            "error_type": type(exc).__name__,
        }
        if table is not None:
            event["table"] = table
        sqlstate = getattr(exc, "sqlstate", None)
        if isinstance(sqlstate, str) and len(sqlstate) == 5 and sqlstate.isalnum():
            event["sqlstate"] = sqlstate
        _write_log(config.log_path, event)
        raise


def _write_log(path: Path, event: dict[str, Any]) -> None:
    import json

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        # Logging must never replace the actual synchronization result/error.
        pass
