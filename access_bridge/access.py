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
        cursor.execute(sql)
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            yield [tuple(row) for row in rows]
        cursor.close()

    def __exit__(self, *_: object) -> None:
        if self.connection is not None:
            self.connection.rollback()
            self.connection.close()
