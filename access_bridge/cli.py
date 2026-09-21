from __future__ import annotations

import argparse
import json
import sys

from .access import AccessReader
from .catalog import MAPPINGS
from .config import load_config
from .postgres import PostgresReplica
from .sync import run_sync


def diagnostic(config_path: str) -> dict[str, object]:
    config = load_config(config_path)
    with AccessReader(config.access_path) as access:
        sources = access.diagnose(MAPPINGS)
    with PostgresReplica(config.postgres_dsn) as postgres:
        schema = postgres.diagnose_schema()
        last_sync = postgres.latest_run_id() if schema.get("sync_runs") else None
    return {
        "status": "ok" if all(sources.values()) and all(schema.values()) else "error",
        "access_mode": "read-only",
        "sources": sources,
        "schema": schema,
        "last_sync": last_sync,
        "mutations": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Puente de lectura Access -> PostgreSQL")
    parser.add_argument("command", choices=("sync", "diagnose"))
    parser.add_argument("--config", default="config/bridge.json")
    parser.add_argument("--force", action="store_true", help="Recarga el snapshot aunque la huella no haya cambiado.")
    args = parser.parse_args(argv)
    if args.command != "sync" and args.force:
        parser.error("--force sólo se admite con sync")
    try:
        if args.command == "sync":
            output = run_sync(load_config(args.config), force=args.force)
        else:
            output = diagnostic(args.config)
        print(json.dumps(output, ensure_ascii=False, default=str))
        return 0
    except Exception:
        # Clean operator-facing error: no paths, DSNs, stack traces or driver details.
        print(json.dumps({"status": "error", "message": "Operación fallida; revise el diagnóstico local."}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
