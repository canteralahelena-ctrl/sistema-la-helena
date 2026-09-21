from __future__ import annotations

import os
import secrets

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


SYNC_ROLE = "helena_bridge_sync_v2"
READER_ROLE = "helena_chatgpt_reader_v2"
EXPECTED_ROLES = (SYNC_ROLE, READER_ROLE)


def role_dsn(owner_config: dict[str, str], role: str, password: str) -> str:
    config = dict(owner_config)
    config["user"] = role
    config["password"] = password
    return make_conninfo(**config)


def expect_blocked(dsn: str, statement: str, accepted_states: set[str]) -> None:
    with psycopg.connect(dsn) as connection:
        try:
            connection.execute(statement)
        except psycopg.Error as exc:
            connection.rollback()
            if exc.sqlstate not in accepted_states:
                raise
        else:
            connection.rollback()
            raise RuntimeError("Una operación prohibida fue permitida.")


def main() -> int:
    owner_dsn = os.environ.get("HELENA_TEST_OWNER_DSN", "")
    if not owner_dsn:
        raise RuntimeError("Falta HELENA_TEST_OWNER_DSN.")
    owner_config = conninfo_to_dict(owner_dsn)
    if "-pooler" in owner_config.get("host", ""):
        raise RuntimeError("La conexión debe ser directa, no pooled.")

    passwords = {role: secrets.token_urlsafe(32) for role in EXPECTED_ROLES}
    with psycopg.connect(owner_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user")
            if cursor.fetchone()[0] != "neondb_owner":
                raise RuntimeError("El DSN no corresponde a neondb_owner.")
            cursor.execute(
                "SELECT rolname, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
                "FROM pg_roles WHERE rolname = ANY(%s) ORDER BY rolname",
                (list(EXPECTED_ROLES),),
            )
            found = cursor.fetchall()
            if len(found) != len(EXPECTED_ROLES):
                raise RuntimeError("Los roles V2 no existen: verifique la rama de prueba.")
            for row in found:
                if any(row[1:]):
                    raise RuntimeError(f"El rol {row[0]} conserva atributos administrativos.")
            for role, password in passwords.items():
                cursor.execute(
                    sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(password)
                    )
                )
    print("OWNER_RAMA_PRUEBA_OK")

    sync_dsn = role_dsn(owner_config, SYNC_ROLE, passwords[SYNC_ROLE])
    reader_dsn = role_dsn(owner_config, READER_ROLE, passwords[READER_ROLE])

    with psycopg.connect(sync_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user")
            if cursor.fetchone()[0] != SYNC_ROLE:
                raise RuntimeError("La conexión no utiliza el sincronizador V2.")
            cursor.execute(
                "INSERT INTO replica.sync_runs"
                "(started_at,finished_at,status,source_fingerprint,row_counts) "
                "VALUES(clock_timestamp(),clock_timestamp(),%s,%s,'{}'::jsonb)",
                ("permission_test", "login_validation"),
            )
            cursor.execute(
                "UPDATE replica.sync_runs SET status=status "
                "WHERE source_fingerprint='login_validation'"
            )
            cursor.execute(
                "DELETE FROM replica.sync_runs "
                "WHERE source_fingerprint='login_validation'"
            )
    print("SYNC_LOGIN_REAL_OK")
    print("SYNC_DML_REVERSIBLE_OK")
    expect_blocked(
        sync_dsn,
        "CREATE TABLE public.helena_sync_must_fail(id integer)",
        {"42501"},
    )
    print("SYNC_DDL_BLOQUEADO_OK")

    with psycopg.connect(reader_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user, current_setting('transaction_read_only')")
            user, read_only = cursor.fetchone()
            if user != READER_ROLE or read_only != "on":
                raise RuntimeError("El lector V2 no inició en modo read-only.")
            cursor.execute("SELECT count(*) FROM replica.sync_runs")
            cursor.fetchone()
    print("READER_LOGIN_REAL_OK")
    print("READER_READONLY_OK")
    print("READER_SELECT_OK")
    expect_blocked(
        reader_dsn,
        "INSERT INTO replica.sync_runs(started_at,status) "
        "VALUES(clock_timestamp(),'must_fail')",
        {"25006", "42501"},
    )
    print("READER_WRITE_BLOQUEADO_OK")
    print("VALIDACION_RAMA_NEON: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
