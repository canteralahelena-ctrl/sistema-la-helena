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
    roles = Path("admin/neon_roles_v2.sql").read_text(encoding="utf-8")
    for name in ("v_saldos_clientes", "v_mayores_deudores", "v_ventas_producto", "v_cliente_metricas", "v_cheques_vencimiento", "v_resumen_gerencial"):
        assert name in sql
    assert "CREATE ROLE" not in sql
    assert "default_transaction_read_only = on" in roles
    assert "GRANT SELECT" in roles
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS" in roles
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
        def sync_run(self): return Transaction()
        def latest_snapshot(self, cursor): return None, {}
        def replace_table(self, cursor, mapping, batches):
            list(batches)
            return 0
        def __exit__(self, *args): pass

    before = access_file.read_bytes()
    with pytest.raises(RuntimeError):
        run_sync(load_config(config_file), reader_class=Reader, replica_class=Replica)
    assert access_file.read_bytes() == before
    assert "rollback" in events and "access_closed" in events


def _sync_config(tmp_path):
    from access_bridge.config import BridgeConfig

    access_file = tmp_path / "copy.accdb"
    access_file.write_bytes(b"snapshot")
    return BridgeConfig(
        access_path=access_file,
        postgres_dsn="postgresql://user:top-secret@private-host/database",
        refresh_script=None,
        source_access_path=None,
        log_path=tmp_path / "bridge.log",
        refresh_before_sync=False,
    )


def test_unchanged_fingerprint_records_skipped_without_opening_access_or_deleting(tmp_path):
    from access_bridge.sync import fingerprint, run_sync

    config = _sync_config(tmp_path)
    events = []

    class Reader:
        def __init__(self, path):
            raise AssertionError("Access must not be opened for an unchanged source")

    class Cursor:
        def execute(self, *args): events.append(("sql", args[0]))
        def close(self): events.append(("cursor", "closed"))

    class Transaction:
        def __enter__(self): return Cursor()
        def __exit__(self, exc_type, *_): events.append(("tx", "rollback" if exc_type else "commit"))

    class Replica:
        def __init__(self, dsn): pass
        def __enter__(self): return self
        def sync_run(self): return Transaction()
        def latest_snapshot(self, cursor):
            return fingerprint(config.access_path), {"clientes": 1552}
        def record_run(self, cursor, **values): events.append(("record", values))
        def replace_table(self, *_): raise AssertionError("No table may be reloaded")
        def __exit__(self, *args): pass

    result = run_sync(config, reader_class=Reader, replica_class=Replica)

    assert result["status"] == "skipped"
    assert result["tables"] == {"clientes": 1552}
    assert next(value for kind, value in events if kind == "record")["status"] == "skipped"
    assert not any("DELETE" in str(value).upper() for _, value in events)
    assert ("tx", "commit") in events


def test_force_reloads_even_when_fingerprint_is_unchanged(tmp_path):
    from access_bridge.sync import fingerprint, run_sync

    config = _sync_config(tmp_path)
    events = []

    class Reader:
        def __init__(self, path): pass
        def __enter__(self): return self
        def rows(self, mapping, batch_size): yield [(mapping.target_table,)]
        def __exit__(self, *args): pass

    class Transaction:
        def __enter__(self): return object()
        def __exit__(self, *_): pass

    class Replica:
        def __init__(self, dsn): pass
        def __enter__(self): return self
        def sync_run(self): return Transaction()
        def latest_snapshot(self, cursor): return fingerprint(config.access_path), {"clientes": 1552}
        def replace_table(self, cursor, mapping, batches):
            list(batches)
            events.append(mapping.target_table)
            return 1
        def table_count(self, cursor, mapping): return 1
        def record_run(self, cursor, **values): events.append(values["status"])
        def __exit__(self, *args): pass

    result = run_sync(config, force=True, reader_class=Reader, replica_class=Replica)
    assert result["status"] == "ok"
    assert events[-1] == "ok"
    assert set(events[:-1]) == {mapping.target_table for mapping in MAPPINGS}


def test_sync_verifies_each_persisted_count_and_records_verified_counts(tmp_path, monkeypatch):
    from access_bridge.sync import run_sync

    config = _sync_config(tmp_path)
    events = []

    class Reader:
        def __init__(self, path): pass
        def __enter__(self): return self
        def rows(self, mapping, batch_size):
            yield [(mapping.target_table,)]
        def __exit__(self, *args): events.append(("access", "closed"))

    class Transaction:
        def __enter__(self): return object()
        def __exit__(self, exc_type, *_): events.append(("tx", "rollback" if exc_type else "commit"))

    class Replica:
        def __init__(self, dsn): pass
        def __enter__(self): return self
        def sync_run(self): return Transaction()
        def latest_snapshot(self, cursor): return None, {}
        def replace_table(self, cursor, mapping, batches):
            assert len(list(batches)) == 1
            events.append(("replace", mapping.target_table))
            return 1
        def table_count(self, cursor, mapping):
            events.append(("count", mapping.target_table))
            return 1
        def record_run(self, cursor, **values): events.append(("record", values))
        def __exit__(self, *args): pass

    result = run_sync(config, reader_class=Reader, replica_class=Replica)

    assert result["status"] == "ok"
    assert result["tables"] == {mapping.target_table: 1 for mapping in MAPPINGS}
    for mapping in MAPPINGS:
        assert ("replace", mapping.target_table) in events
        assert ("count", mapping.target_table) in events
    recorded = next(value for kind, value in events if kind == "record")
    assert recorded["row_counts"] == result["tables"]
    assert ("tx", "commit") in events


def test_sync_error_log_contains_only_sanitized_metadata(tmp_path):
    from access_bridge.sync import run_sync

    config = _sync_config(tmp_path)
    secret = "postgresql://user:top-secret@private-host/database C:\\private\\copy.accdb value=885,24"

    class SqlFailure(RuntimeError):
        sqlstate = "22P02"

    class Reader:
        def __init__(self, path): pass
        def __enter__(self): return self
        def rows(self, mapping, batch_size):
            raise SqlFailure(secret)
        def __exit__(self, *args): pass

    class Transaction:
        def __enter__(self): return object()
        def __exit__(self, *_): pass

    class Replica:
        def __init__(self, dsn): pass
        def __enter__(self): return self
        def sync_run(self): return Transaction()
        def latest_snapshot(self, cursor): return None, {}
        def replace_table(self, cursor, mapping, batches): list(batches)
        def __exit__(self, *args): pass

    with pytest.raises(SqlFailure):
        run_sync(config, reader_class=Reader, replica_class=Replica)

    event = json.loads(config.log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event == {
        "status": "error",
        "started_at": event["started_at"],
        "stage": "table_sync",
        "error_type": "SqlFailure",
        "table": "clientes",
        "sqlstate": "22P02",
    }
    serialized = json.dumps(event)
    for forbidden in ("top-secret", "private-host", "copy.accdb", "885,24"):
        assert forbidden not in serialized


def test_operational_cli_exposes_only_sync_and_non_mutating_diagnose():
    source = Path("access_bridge/cli.py").read_text(encoding="utf-8")
    assert 'choices=("sync", "diagnose")' in source
    assert "provision-reader" not in source
    assert "--migrate" not in source
    assert '"mutations": False' in source


def test_schema_diagnostic_executes_selects_only_and_rolls_back():
    statements = []

    class Cursor:
        def execute(self, statement, params=None):
            statements.append(statement)
        def fetchone(self): return ("replica.relation",)
        def close(self): statements.append("CURSOR_CLOSED")

    class Connection:
        def cursor(self): return Cursor()
        def rollback(self): statements.append("ROLLBACK")

    replica = PostgresReplica("unused")
    replica.connection = Connection()
    result = replica.diagnose_schema()

    sql_statements = [item for item in statements if item not in {"ROLLBACK", "CURSOR_CLOSED"}]
    assert all(item.lstrip().upper().startswith("SELECT") for item in sql_statements)
    assert "ROLLBACK" in statements
    assert all(result.values())


def test_latest_run_id_is_select_only_and_rolls_back():
    statements = []

    class Cursor:
        def execute(self, statement): statements.append(statement)
        def fetchone(self): return (42,)
        def close(self): statements.append("CURSOR_CLOSED")

    class Connection:
        def cursor(self): return Cursor()
        def rollback(self): statements.append("ROLLBACK")

    replica = PostgresReplica("unused")
    replica.connection = Connection()
    assert replica.latest_run_id() == 42
    assert statements[0].lstrip().upper().startswith("SELECT")
    assert "ROLLBACK" in statements
