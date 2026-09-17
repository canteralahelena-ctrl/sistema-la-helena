from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .access import AccessReader
from .config import load_config
from .postgres import PostgresReplica
from .sync import run_sync


def diagnostic(config_path: str) -> dict[str, object]:
    config = load_config(config_path)
    access_ok = False
    postgres_ok = False
    with AccessReader(config.access_path):
        access_ok = True
    with PostgresReplica(config.postgres_dsn) as postgres:
        cursor = postgres.connection.cursor()
        cursor.execute("SELECT rolconfig FROM pg_roles WHERE rolname='helena_bridge_reader'")
        role_row = cursor.fetchone()
        cursor.execute("SELECT max(finished_at) FROM replica.sync_runs")
        last_sync = cursor.fetchone()[0]
        postgres.connection.rollback()
        postgres_ok = True
    role_config = role_row[0] if role_row else []
    return {"access_copy": access_ok, "access_mode": "read-only", "postgres": postgres_ok, "connector_role_read_only": "default_transaction_read_only=on" in (role_config or []), "last_sync": last_sync.isoformat() if last_sync else None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Puente de lectura Access -> PostgreSQL")
    parser.add_argument("command", choices=("sync", "diagnose", "provision-reader"))
    parser.add_argument("--config", default="config/bridge.json")
    args = parser.parse_args(argv)
    try:
        if args.command == "sync":
            output = run_sync(load_config(args.config))
        elif args.command == "diagnose":
            output = diagnostic(args.config)
        else:
            import getpass
            config = load_config(args.config)
            username = input("Usuario read-only para ChatGPT: ").strip()
            password = getpass.getpass("Clave (mínimo 16 caracteres): ")
            with PostgresReplica(config.postgres_dsn) as postgres:
                postgres.provision_reader(username, password)
            output = {"status": "ok", "reader": username, "privileges": "SELECT only"}
        print(json.dumps(output, ensure_ascii=False, default=str))
        return 0
    except Exception:
        # Clean operator-facing error: no paths, DSNs, stack traces or driver details.
        print(json.dumps({"status": "error", "message": "Operación fallida; revise el diagnóstico local."}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
