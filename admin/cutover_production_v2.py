from __future__ import annotations

import argparse
import json
import os
import secrets
import tempfile
import sys
from pathlib import Path
from typing import Callable, Iterable

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


SYNC_ROLE = "helena_bridge_sync_v2"
READER_ROLE = "helena_chatgpt_reader_v2"
EXPECTED_GROUPS = {
    SYNC_ROLE: "helena_bridge_sync_privs_v2",
    READER_ROLE: "helena_bridge_reader_privs_v2",
}
ALLOWED_ADMINISTRATORS = {"helena_bridge_sync", "neondb_owner"}


def redacted_error(
    exc: BaseException,
    sensitive_values: Iterable[str] = (),
    **kwargs: object,
) -> str:
    # ``secrets=`` is kept as a compatibility alias for callers/tests.
    if "secrets" in kwargs:
        sensitive_values = kwargs["secrets"]  # type: ignore[assignment]
    text = redact_text(str(exc), sensitive_values)
    # A libpq error can echo a conninfo. Never send it to the operator console.
    if "postgresql://" in text or "postgres://" in text or "password=" in text:
        return "Falló una operación PostgreSQL; revise el diagnóstico local."
    return text or "Falló el corte de roles V2."


def role_dsn(source_dsn: str, role: str, password: str) -> str:
    config = conninfo_to_dict(source_dsn)
    config["user"] = role
    config["password"] = password
    return make_conninfo(**config)


def direct_dsn(source_dsn: str) -> str:
    """Return the direct Neon endpoint for a pooled or direct conninfo."""
    config = conninfo_to_dict(source_dsn)
    host = config.get("host", "")
    if "-pooler" in host:
        config["host"] = host.replace("-pooler", "", 1)
    return make_conninfo(**config)


def redact_text(text: str, sensitive_values: Iterable[str]) -> str:
    """Remove generated credentials from errors before they reach the console."""
    result = text
    for value in sensitive_values:
        if value:
            result = result.replace(value, "***")
    return result


def write_json_atomic(
    path: Path, value: object, replace: Callable[[str, str], None] = os.replace
) -> None:
    """Write JSON beside its destination and publish it with one replacement."""
    if not isinstance(value, dict):
        raise TypeError("El documento privado debe ser un objeto JSON.")
    path = Path(path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        replace(str(temporary), str(path))
    finally:
        temporary.unlink(missing_ok=True)


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


def write_private_candidate(path: Path, value: object) -> None:
    if not isinstance(value, dict):
        raise TypeError("El documento privado debe ser un objeto JSON.")
    if not path.exists():
        raise RuntimeError("El contenedor privado no fue preparado por PowerShell.")
    flags = os.O_WRONLY | os.O_TRUNC
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def activate(
    config_path: Path,
    reader_path: Path,
    connector: Callable[..., object] = psycopg.connect,
    password_factory: Callable[[], str] = lambda: secrets.token_urlsafe(36),
    replace: Callable[[str, str], None] = os.replace,
) -> dict[str, str]:
    """Activate V2 credentials, validate real sessions, then publish private JSON.

    This library entry point is useful for automated tests. The Windows wrapper
    remains the operational entry point because it additionally applies the ACL.
    """
    config_path = Path(config_path)
    reader_path = Path(reader_path)
    raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict) or not raw.get("postgres_dsn"):
        raise RuntimeError("bridge.json no contiene postgres_dsn.")
    source_dsn = direct_dsn(str(raw["postgres_dsn"]))
    passwords = {SYNC_ROLE: password_factory(), READER_ROLE: password_factory()}

    try:
        with connector(source_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                    "rolreplication, rolbypassrls FROM pg_roles "
                    "WHERE rolname = ANY(%s) ORDER BY rolname",
                    (list(EXPECTED_GROUPS),),
                )
                found = {row[0]: row[1:] for row in cursor.fetchall()}
                if set(found) != set(EXPECTED_GROUPS):
                    raise RuntimeError("Faltan los dos logins V2 en la base de producción.")
                for role, attributes in found.items():
                    if not attributes[0] or any(attributes[1:]):
                        raise RuntimeError(f"El login {role} conserva atributos inseguros.")
                    cursor.execute(
                        "SELECT parent.rolname FROM pg_auth_members membership "
                        "JOIN pg_roles parent ON parent.oid=membership.roleid "
                        "JOIN pg_roles member_role ON member_role.oid=membership.member "
                        "WHERE member_role.rolname=%s ORDER BY parent.rolname",
                        (role,),
                    )
                    if [row[0] for row in cursor.fetchall()] != [EXPECTED_GROUPS[role]]:
                        raise RuntimeError(f"El login {role} tiene membresías inesperadas.")
                for role, password in passwords.items():
                    cursor.execute(
                        sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                            sql.Identifier(role), sql.Literal(password)
                        )
                    )

        sync_dsn = role_dsn(source_dsn, SYNC_ROLE, passwords[SYNC_ROLE])
        reader_dsn = role_dsn(source_dsn, READER_ROLE, passwords[READER_ROLE])
        with connector(sync_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_user")
                if cursor.fetchone()[0] != SYNC_ROLE:
                    raise RuntimeError("El login real no corresponde al sincronizador V2.")
                cursor.execute(
                    "INSERT INTO replica.sync_runs"
                    "(started_at,finished_at,status,source_fingerprint,row_counts) "
                    "VALUES(clock_timestamp(),clock_timestamp(),%s,%s,'{}'::jsonb)",
                    ("permission_test", "production_cutover_validation"),
                )
                cursor.execute("DELETE FROM replica.sync_runs WHERE source_fingerprint=%s", ("production_cutover_validation",))
        expect_blocked(sync_dsn, "CREATE TABLE public.helena_sync_must_fail(id integer)", {"42501"})
        with connector(reader_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_user, current_setting('transaction_read_only')")
                if cursor.fetchone() != (READER_ROLE, "on"):
                    raise RuntimeError("El lector V2 no inició en modo read-only.")
                cursor.execute("SELECT count(*) FROM replica.sync_runs")
                cursor.fetchone()
        expect_blocked(reader_dsn, "INSERT INTO replica.sync_runs(started_at,status) VALUES(clock_timestamp(),'must_fail')", {"25006", "42501"})

        backup_path = config_path.with_name("bridge.pre-v2.json")
        if not backup_path.exists():
            write_json_atomic(backup_path, raw, replace)
        updated = dict(raw)
        updated["postgres_dsn"] = sync_dsn
        write_json_atomic(reader_path, {"postgres_dsn": reader_dsn, "role": READER_ROLE}, replace)
        write_json_atomic(config_path, updated, replace)
        return {"sync_role": SYNC_ROLE, "reader_role": READER_ROLE}
    except Exception as exc:
        raise RuntimeError(redact_text(str(exc), passwords.values())) from None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-candidate", type=Path, required=True)
    parser.add_argument("--reader-candidate", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict) or not raw.get("postgres_dsn"):
        raise RuntimeError("bridge.json no contiene postgres_dsn.")
    source_dsn = direct_dsn(str(raw["postgres_dsn"]))
    source_config = conninfo_to_dict(source_dsn)
    if source_config.get("dbname") != "neondb":
        raise RuntimeError("La conexión no corresponde a la base neondb.")
    if source_config.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
        raise RuntimeError("La conexión debe exigir TLS mediante sslmode.")

    passwords = {
        SYNC_ROLE: secrets.token_urlsafe(36),
        READER_ROLE: secrets.token_urlsafe(36),
    }
    with psycopg.connect(source_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user")
            database, administrator = cursor.fetchone()
            if database != "neondb" or administrator not in ALLOWED_ADMINISTRATORS:
                raise RuntimeError("La conexión administrativa no es la esperada.")
            cursor.execute(
                "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                "rolreplication, rolbypassrls FROM pg_roles WHERE rolname = ANY(%s)",
                (list(EXPECTED_GROUPS.values()),),
            )
            groups = cursor.fetchall()
            if len(groups) != len(EXPECTED_GROUPS) or any(row[1] or any(row[2:]) for row in groups):
                raise RuntimeError("Los grupos de privilegios V2 no son mínimos.")
            cursor.execute(
                "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                "rolreplication, rolbypassrls FROM pg_roles "
                "WHERE rolname = ANY(%s) ORDER BY rolname",
                (list(EXPECTED_GROUPS),),
            )
            found = {row[0]: row[1:] for row in cursor.fetchall()}
            if set(found) != set(EXPECTED_GROUPS):
                raise RuntimeError("Faltan los dos logins V2 en la base de producción.")
            for role, attributes in found.items():
                if not attributes[0] or any(attributes[1:]):
                    raise RuntimeError(f"El login {role} conserva atributos inseguros.")
                cursor.execute(
                    "SELECT parent.rolname FROM pg_auth_members membership "
                    "JOIN pg_roles parent ON parent.oid=membership.roleid "
                    "JOIN pg_roles member_role ON member_role.oid=membership.member "
                    "WHERE member_role.rolname=%s ORDER BY parent.rolname",
                    (role,),
                )
                groups = [row[0] for row in cursor.fetchall()]
                if groups != [EXPECTED_GROUPS[role]]:
                    raise RuntimeError(f"El login {role} tiene membresías inesperadas.")
            for role, password in passwords.items():
                cursor.execute(
                    sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(password)
                    )
                )
    print("OWNER_PRODUCCION_OK")

    sync_dsn = role_dsn(source_dsn, SYNC_ROLE, passwords[SYNC_ROLE])
    reader_dsn = role_dsn(source_dsn, READER_ROLE, passwords[READER_ROLE])

    with psycopg.connect(sync_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user")
            if cursor.fetchone()[0] != SYNC_ROLE:
                raise RuntimeError("El login real no corresponde al sincronizador V2.")
            cursor.execute(
                "INSERT INTO replica.sync_runs"
                "(started_at,finished_at,status,source_fingerprint,row_counts) "
                "VALUES(clock_timestamp(),clock_timestamp(),%s,%s,'{}'::jsonb)",
                ("permission_test", "production_cutover_validation"),
            )
            cursor.execute(
                "UPDATE replica.sync_runs SET status=status "
                "WHERE source_fingerprint='production_cutover_validation'"
            )
            cursor.execute(
                "DELETE FROM replica.sync_runs "
                "WHERE source_fingerprint='production_cutover_validation'"
            )
    expect_blocked(
        sync_dsn,
        "CREATE TABLE public.helena_sync_must_fail(id integer)",
        {"42501"},
    )
    print("SYNC_V2_PRODUCCION_OK")

    with psycopg.connect(reader_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user, current_setting('transaction_read_only')")
            user, read_only = cursor.fetchone()
            if user != READER_ROLE or read_only != "on":
                raise RuntimeError("El lector V2 no inició en modo read-only.")
            cursor.execute("SELECT count(*) FROM replica.sync_runs")
            cursor.fetchone()
    expect_blocked(
        reader_dsn,
        "INSERT INTO replica.sync_runs(started_at,status) "
        "VALUES(clock_timestamp(),'must_fail')",
        {"25006", "42501"},
    )
    print("READER_V2_PRODUCCION_OK")

    updated = dict(raw)
    updated["postgres_dsn"] = sync_dsn
    write_private_candidate(args.config_candidate, updated)
    write_private_candidate(
        args.reader_candidate,
        {"postgres_dsn": reader_dsn, "role": READER_ROLE},
    )
    print("CANDIDATOS_PRIVADOS_OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"CORTE_ROLES_V2_ERROR: {redacted_error(exc)}", file=sys.stderr)
        raise SystemExit(1)
