from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Iterable, Iterator

from .catalog import MAPPINGS, TableMapping


TEXT_COLUMNS = {
    "razon_social", "cuit", "localidad", "producto", "unidad", "tipo", "numero",
    "id_cliente_texto", "estado", "banco", "observacion",
}
INTEGER_COLUMNS = {
    "id_cliente", "id_producto", "id_comprobante", "id_detalle", "id_pago", "id_entrega",
}
DECIMAL_COLUMNS = {
    "precio_unitario", "subtotal", "iva", "importe", "saldo", "cantidad", "monto",
}
DATE_COLUMNS = {"fecha", "fecha_cobro"}


def _access_decimal(value: Any, column: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value))

    text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace("$", "")
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    # Text fields in this Access database use es-AR: dot for thousands, comma for decimals.
    if "," in text:
        normalized = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3})+", text):
        normalized = text.replace(".", "")
    else:
        normalized = text
    try:
        number = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"{column}: número inválido en Access") from exc
    return -number if negative else number


def _access_datetime(value: Any, column: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for pattern in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    raise ValueError(f"{column}: fecha inválida en Access")


def normalize_value(column: str, value: Any) -> Any:
    if value is None:
        return None
    if column in TEXT_COLUMNS:
        return str(value)
    if column in INTEGER_COLUMNS:
        number = _access_decimal(value, column)
        if number is None:
            return None
        if number != number.to_integral_value():
            raise ValueError(f"{column}: entero inválido en Access")
        return int(number)
    if column in DECIMAL_COLUMNS:
        return _access_decimal(value, column)
    if column in DATE_COLUMNS:
        return _access_datetime(value, column)
    return value


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
        iterator = iter(batches)
        try:
            for rows in iterator:
                normalized = [
                    tuple(normalize_value(column, value) for column, value in zip(mapping.target_columns, row))
                    for row in rows
                ]
                cursor.executemany(statement, normalized)
                total += len(rows)
        finally:
            close = getattr(iterator, "close", None)
            if callable(close):
                close()
        return total

    def latest_snapshot(self, cursor: Any) -> tuple[str | None, dict[str, int]]:
        import json

        cursor.execute(
            "SELECT source_fingerprint, row_counts "
            "FROM replica.sync_runs "
            "WHERE status IN ('ok', 'skipped') AND source_fingerprint IS NOT NULL "
            "ORDER BY finished_at DESC NULLS LAST, id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if not row:
            return None, {}
        counts = row[1]
        if isinstance(counts, str):
            counts = json.loads(counts)
        if not isinstance(counts, dict):
            counts = {}
        return row[0], {str(key): int(value) for key, value in counts.items()}

    def table_count(self, cursor: Any, mapping: TableMapping) -> int:
        # target_table is not caller input: it comes exclusively from MAPPINGS.
        cursor.execute(f'SELECT count(*) FROM replica."{mapping.target_table}"')
        return int(cursor.fetchone()[0])

    def record_run(
        self,
        cursor: Any,
        *,
        started_at: datetime,
        finished_at: datetime,
        status: str,
        source_fingerprint: str,
        row_counts: dict[str, int],
    ) -> None:
        import json

        if status not in {"ok", "skipped"}:
            raise ValueError("Estado de sincronización inválido.")
        cursor.execute(
            "INSERT INTO replica.sync_runs"
            "(started_at, finished_at, status, source_fingerprint, row_counts) "
            "VALUES (%s,%s,%s,%s,%s::jsonb)",
            (started_at, finished_at, status, source_fingerprint, json.dumps(row_counts)),
        )

    def diagnose_schema(self) -> dict[str, bool]:
        """Perform SELECT-only checks; this method never commits or changes schema."""
        cursor = self.connection.cursor()
        try:
            result: dict[str, bool] = {}
            for mapping in MAPPINGS:
                relation = f"replica.{mapping.target_table}"
                cursor.execute("SELECT to_regclass(%s)", (relation,))
                result[mapping.target_table] = cursor.fetchone()[0] is not None
            cursor.execute("SELECT to_regclass('replica.sync_runs')")
            result["sync_runs"] = cursor.fetchone()[0] is not None
            self.connection.rollback()
            return result
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cursor.close()

    def latest_run_id(self) -> int | None:
        """Return the newest synchronization id using a SELECT-only query."""
        cursor = self.connection.cursor()
        try:
            cursor.execute("SELECT max(id) FROM replica.sync_runs")
            value = cursor.fetchone()[0]
            self.connection.rollback()
            return None if value is None else int(value)
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cursor.close()

    def __exit__(self, *_: object) -> None:
        if self.connection is not None:
            self.connection.close()
