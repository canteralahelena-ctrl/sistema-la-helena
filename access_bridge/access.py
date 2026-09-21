from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from .catalog import TableMapping, select_sql


FORBIDDEN_ACCESS_SQL = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "EXEC", "INTO")


def assert_read_only_sql(sql: str) -> None:
    tokens = sql.upper().replace("[", " ").replace("]", " ").split()
    if not tokens or tokens[0] != "SELECT" or any(word in tokens for word in FORBIDDEN_ACCESS_SQL):
        raise ValueError("Access admite únicamente SELECT.")


class AccessReader:
    def __init__(self, database: Path, connector: Any = None) -> None:
        self.database = database
        self._connector = connector
        self.connection: Any = None

    def __enter__(self) -> "AccessReader":
        if not self.database.is_file():
            raise FileNotFoundError("No se encontró la copia local Access.")
        if self._connector is None:
            try:
                import pyodbc
            except ImportError as exc:
                raise RuntimeError("Falta pyodbc; ejecute el instalador del puente.") from exc
            self._connector = pyodbc.connect
        connection_string = (
            r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
            f"DBQ={self.database};READONLY=TRUE;Mode=Read;"
        )
        self.connection = self._connector(connection_string, autocommit=False)
        return self

    def rows(self, mapping: TableMapping, batch_size: int) -> Iterator[list[tuple[Any, ...]]]:
        sql = select_sql(mapping)
        assert_read_only_sql(sql)
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql)
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                yield [tuple(row) for row in rows]
        finally:
            cursor.close()

    def diagnose(self, mappings: tuple[TableMapping, ...]) -> dict[str, bool]:
        """Check that every allowlisted source can be selected without reading rows."""
        result: dict[str, bool] = {}
        for mapping in mappings:
            sql = f"{select_sql(mapping)} WHERE 1 = 0"
            assert_read_only_sql(sql)
            cursor = self.connection.cursor()
            try:
                cursor.execute(sql)
                result[mapping.access_table] = True
            finally:
                cursor.close()
        return result

    def __exit__(self, *_: object) -> None:
        if self.connection is not None:
            try:
                self.connection.rollback()
            finally:
                self.connection.close()
