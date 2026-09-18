import json
from decimal import Decimal
from pathlib import Path

import pytest

from access_bridge.access import AccessReader, assert_read_only_sql
from access_bridge.catalog import MAPPINGS, select_sql
from access_bridge.config import load_config, redacted_dsn
from access_bridge.postgres import PostgresReplica, normalize_value, upsert_sql


def test_every_access_statement_is_select_only():
    for mapping in MAPPINGS:
        sql = select_sql(mapping)
        assert_read_only_sql(sql)
        assert sql.startswith("SELECT ")
    for sql in ("UPDATE CLIENTES SET x=1", "SELECT * INTO backup FROM CLIENTES", "DELETE FROM PAGOS"):
        with pytest.raises(ValueError):
            assert_read_only_sql(sql)


def test_access_connection_is_explicitly_read_only_and_rolls_back(tmp_path):
    database = tmp_path / "copy.accdb"
    database.touch()
    captured = {}

    class Connection:
        def rollback(self): captured["rollback"] = True
        def close(self): captured["closed"] = True

    def connect(connection_string, autocommit):
        captured.update(connection_string=connection_string, autocommit=autocommit)
        return Connection()

    with AccessReader(database, connector=connect):
        pass
    assert "READONLY=TRUE" in captured["connection_string"]
    assert "Mode=Read" in captured["connection_string"]
    assert captured == {**captured, "autocommit": False, "rollback": True, "closed": True}


def test_upsert_targets_only_postgres_replica():
    for mapping in MAPPINGS:
        sql = upsert_sql(mapping)
        assert sql.startswith('INSERT INTO replica."')
        assert "ON CONFLICT" in sql and "DO UPDATE" in sql


def test_postgres_mapping_normalizes_access_numbers_for_text_columns():
    mapping = next(item for item in MAPPINGS if item.target_table == "comprobantes")
    events = []
    class Cursor:
        def execute(self, statement): events.append(statement)
        def executemany(self, statement, rows): events.append(rows)
    replica = PostgresReplica("unused")
    count = replica.replace_table(Cursor(), mapping, [[(1, 2, None, "FC", 123, 10, 2.1, 12.1, 0)]])
    assert count == 1
    assert events[-1][0][4] == "123"



def test_access_locale_numbers_are_normalized_before_postgres():
    assert normalize_value("precio_unitario", "885,24") == Decimal("885.24")
    assert normalize_value("importe", "1.234,56") == Decimal("1234.56")
    assert normalize_value("saldo", "$ 1.234,56") == Decimal("1234.56")
    assert normalize_value("cantidad", "1234.56") == Decimal("1234.56")
    assert normalize_value("id_cliente", "775") == 775
    assert normalize_value("numero", 123) == "123"
    assert normalize_value("monto", "") is None


def test_access_batch_generator_is_closed_when_postgres_rejects_a_row():
    mapping = next(item for item in MAPPINGS if item.target_table == "productos")
    events = []

    def batches():
        try:
            yield [(1, "producto", "tn", "885,24")]
        finally:
            events.append("closed")

    class Cursor:
        def execute(self, statement): pass
        def executemany(self, statement, rows): raise RuntimeError("simulated")

    with pytest.raises(RuntimeError, match="simulated"):
        PostgresReplica("unused").replace_table(Cursor(), mapping, batches())
    assert events == ["closed"]



def test_config_supports_windows_path_and_environment_dsn(tmp_path):
    config = tmp_path / "bridge.json"
    config.write_text(json.dumps({"access_path": r"C:\LaHelena\copy.accdb", "postgres_dsn": ""}), encoding="utf-8")
    loaded = load_config(config, {"HELENA_BRIDGE_POSTGRES_DSN": "postgresql://secret@host/db"})
    assert str(loaded.access_path).endswith("copy.accdb")
    assert redacted_dsn(loaded.postgres_dsn) == "postgresql://***:***@***/***"


@pytest.mark.parametrize("value", ["false", 0, 1, None])
def test_config_rejects_non_boolean_refresh_flag(tmp_path, value):
    config = tmp_path / "bridge.json"
    config.write_text(json.dumps({"access_path": "copy.accdb", "postgres_dsn": "postgresql://test", "refresh_before_sync": value}), encoding="utf-8")
    with pytest.raises(ValueError, match="booleano"):
        load_config(config)


def test_config_rejects_invalid_batch_size(tmp_path):
    config = tmp_path / "bridge.json"
    config.write_text(json.dumps({"access_path": "copy.accdb", "postgres_dsn": "postgresql://test", "batch_size": 0}), encoding="utf-8")
    with pytest.raises(ValueError, match="entero positivo"):
        load_config(config)


def test_migrations_define_expected_read_views_and_reader_guard():
    sql = "\n".join(path.read_text(encoding="utf-8") for path in sorted(Path("migrations").glob("*.sql")))
    for name in ("v_saldos_clientes", "v_mayores_deudores", "v_ventas_producto", "v_cliente_metricas", "v_cheques_vencimiento", "v_resumen_gerencial"):
        assert name in sql
    assert "default_transaction_read_only = on" in sql
    assert "GRANT SELECT" in sql
    assert not any(word in sql.upper() for word in (" ACCESS UPDATE ", " ACCESS DELETE "))


def test_examples_contain_no_secret():
    example = json.loads(Path("config/bridge.example.json").read_text(encoding="utf-8"))
    assert example["postgres_dsn"] == ""
    assert "SERVIDOR" not in json.dumps(example)


def test_sync_failure_rolls_back_postgres_and_never_writes_access(tmp_path, monkeypatch):
    from access_bridge.sync import run_sync
    config_file = tmp_path / "bridge.json"
    access_file = tmp_path / "copy.accdb"
    access_file.write_bytes(b"unchanged")
    config_file.write_text(json.dumps({"access_path": str(access_file), "postgres_dsn": "postgresql://test", "refresh_before_sync": False}), encoding="utf-8")
    events = []

    class Reader:
        def __init__(self, path): self.path = path
        def __enter__(self): return self
        def rows(self, mapping, batch_size):
            raise RuntimeError("simulated")
        def __exit__(self, *args): events.append("access_closed")

    class Cursor:
        def execute(self, *args): events.append("sql")
        def close(self): pass

    class Transaction:
        def __enter__(self): return Cursor()
        def __exit__(self, exc_type, *_): events.append("rollback" if exc_type else "commit")

    class Replica:
        def __init__(self, dsn): pass
        def __enter__(self): return self
        def migrate(self, path): pass
        def sync_run(self): return Transaction()
        def __exit__(self, *args): pass

    before = access_file.read_bytes()
    with pytest.raises(RuntimeError):
        run_sync(load_config(config_file), reader_class=Reader, replica_class=Replica)
    assert access_file.read_bytes() == before
    assert "rollback" in events and "access_closed" in events
