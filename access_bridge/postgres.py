from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from .catalog import TableMapping


TEXT_COLUMNS = {
    "razon_social", "cuit", "localidad", "producto", "unidad", "tipo", "numero",
    "id_cliente_texto", "estado", "banco", "observacion",
}


def upsert_sql(mapping: TableMapping) -> str:
    columns = mapping.target_columns
    quoted = ", ".join(f'"{item}"' for item in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    updates = ", ".join(f'"{item}"=EXCLUDED."{item}"' for item in columns if item != mapping.key)
    return f'INSERT INTO replica."{mapping.target_table}" ({quoted}) VALUES ({placeholders}) ON CONFLICT ("{mapping.key}") DO UPDATE SET {updates}'


class PostgresReplica:
    def __init__(self, dsn: str, connector: Any = None) -> None:
        self.dsn = dsn
        self._connector = connector
        self.connection: Any = None

    def __enter__(self) -> "PostgresReplica":
        if self._connector is None:
            try:
                import psycopg
            except ImportError as exc:
                raise RuntimeError("Falta psycopg; ejecute el instalador del puente.") from exc
            self._connector = psycopg.connect
        self.connection = self._connector(self.dsn)
        return self

    def migrate(self, migration_dir: Path) -> None:
        cursor = self.connection.cursor()
        for path in sorted(migration_dir.glob("*.sql")):
            cursor.execute(path.read_text(encoding="utf-8"))
        self.connection.commit()

    def provision_reader(self, username: str, password: str) -> None:
        if not username.replace("_", "").isalnum() or not username:
            raise ValueError("Nombre de usuario PostgreSQL inválido.")
        if len(password) < 16:
            raise ValueError("La clave del conector debe tener al menos 16 caracteres.")
        try:
            from psycopg import sql
        except ImportError as exc:
            raise RuntimeError("Falta psycopg; ejecute el instalador del puente.") from exc
        cursor = self.connection.cursor()
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (username,))
        identifier = sql.Identifier(username)
        if cursor.fetchone():
            cursor.execute(sql.SQL("ALTER ROLE {} LOGIN PASSWORD %s").format(identifier), (password,))
        else:
            cursor.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s").format(identifier), (password,))
        cursor.execute(sql.SQL("GRANT helena_bridge_reader TO {}").format(identifier))
        cursor.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(identifier))
        self.connection.commit()

    @contextmanager
    def sync_run(self) -> Iterator[Any]:
        cursor = self.connection.cursor()
        try:
            cursor.execute("SELECT pg_advisory_xact_lock(4815162342)")
            yield cursor
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cursor.close()

    def replace_table(self, cursor: Any, mapping: TableMapping, batches: Iterable[list[tuple[Any, ...]]]) -> int:
        cursor.execute(f'DELETE FROM replica."{mapping.target_table}"')
        total = 0
        statement = upsert_sql(mapping)
        for rows in batches:
            normalized = [
                tuple(str(value) if value is not None and column in TEXT_COLUMNS else value for column, value in zip(mapping.target_columns, row))
                for row in rows
            ]
            cursor.executemany(statement, normalized)
            total += len(rows)
        return total

    def __exit__(self, *_: object) -> None:
        if self.connection is not None:
            self.connection.close()
