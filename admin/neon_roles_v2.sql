\set ON_ERROR_STOP on

-- Ejecutar únicamente con psql y una conexión DIRECTA (sin "-pooler") del
-- propietario de la base, primero en una rama de prueba de Neon.
-- Los nombres de login son parametrizables:
--   psql "$OWNER_DIRECT_DSN" -v sync_login=mi_sync -v reader_login=mi_reader \
--     -f admin/neon_roles_v2.sql
-- Este archivo no recibe ni imprime contraseñas. Asignarlas después con
-- \password <login>, que solicita el secreto sin dejarlo en el historial.

\if :{?sync_login}
\else
\set sync_login helena_bridge_sync_v2
\endif

\if :{?reader_login}
\else
\set reader_login helena_chatgpt_reader_v2
\endif

BEGIN;

SELECT format(
  'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT',
  'helena_bridge_sync_privs_v2'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'helena_bridge_sync_privs_v2')
\gexec

SELECT format(
  'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT',
  'helena_bridge_reader_privs_v2'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'helena_bridge_reader_privs_v2')
\gexec

SELECT format(
  'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT',
  :'sync_login'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'sync_login')
\gexec

SELECT format(
  'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT',
  :'reader_login'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'reader_login')
\gexec

SELECT format(
  'ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT',
  :'sync_login'
) \gexec
SELECT format(
  'ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT',
  :'reader_login'
) \gexec

ALTER ROLE helena_bridge_sync_privs_v2
  NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT;
ALTER ROLE helena_bridge_reader_privs_v2
  NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT;

-- Elimina cualquier membresía previa. Luego se concederá exactamente un grupo
-- a cada login y ninguno a los grupos de privilegios.
SELECT format('REVOKE %I FROM %I', parent.rolname, member_role.rolname)
FROM pg_auth_members membership
JOIN pg_roles parent ON parent.oid = membership.roleid
JOIN pg_roles member_role ON member_role.oid = membership.member
WHERE member_role.rolname IN (
  'helena_bridge_sync_privs_v2',
  'helena_bridge_reader_privs_v2',
  :'sync_login',
  :'reader_login'
)
\gexec

-- Una ejecución repetida limpia privilegios directos de los logins. Los
-- permisos efectivos deben provenir exclusivamente de los grupos *_privs_v2.
SELECT format('REVOKE ALL PRIVILEGES ON DATABASE %I FROM %I', :'DBNAME', :'sync_login') \gexec
SELECT format('REVOKE ALL PRIVILEGES ON DATABASE %I FROM %I', :'DBNAME', :'reader_login') \gexec
SELECT format('REVOKE ALL PRIVILEGES ON SCHEMA replica FROM %I', :'sync_login') \gexec
SELECT format('REVOKE ALL PRIVILEGES ON SCHEMA replica FROM %I', :'reader_login') \gexec
SELECT format('REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA replica FROM %I', :'sync_login') \gexec
SELECT format('REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA replica FROM %I', :'reader_login') \gexec
SELECT format('REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA replica FROM %I', :'sync_login') \gexec
SELECT format('REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA replica FROM %I', :'reader_login') \gexec

REVOKE ALL PRIVILEGES ON DATABASE :"DBNAME"
  FROM helena_bridge_sync_privs_v2, helena_bridge_reader_privs_v2;
REVOKE ALL PRIVILEGES ON SCHEMA replica
  FROM helena_bridge_sync_privs_v2, helena_bridge_reader_privs_v2;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA replica
  FROM helena_bridge_sync_privs_v2, helena_bridge_reader_privs_v2;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA replica
  FROM helena_bridge_sync_privs_v2, helena_bridge_reader_privs_v2;

-- Si una API del proveedor creó alguno de estos roles como miembro de
-- neon_superuser, esa herencia se elimina de forma explícita.
SELECT format('REVOKE neon_superuser FROM %I', role_name)
FROM (VALUES
  ('helena_bridge_sync_privs_v2'),
  ('helena_bridge_reader_privs_v2'),
  (:'sync_login'),
  (:'reader_login')
) AS roles(role_name)
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'neon_superuser')
  AND EXISTS (
    SELECT 1
    FROM pg_roles member_role
    JOIN pg_roles admin_role ON admin_role.rolname = 'neon_superuser'
    WHERE member_role.rolname = role_name
      AND pg_has_role(member_role.oid, admin_role.oid, 'MEMBER')
  )
\gexec

SELECT format('GRANT %I TO %I', 'helena_bridge_sync_privs_v2', :'sync_login') \gexec
SELECT format('GRANT %I TO %I', 'helena_bridge_reader_privs_v2', :'reader_login') \gexec

GRANT CONNECT ON DATABASE :"DBNAME"
  TO helena_bridge_sync_privs_v2, helena_bridge_reader_privs_v2;
GRANT USAGE ON SCHEMA replica
  TO helena_bridge_sync_privs_v2, helena_bridge_reader_privs_v2;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA replica
  TO helena_bridge_sync_privs_v2;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA replica
  TO helena_bridge_sync_privs_v2;
GRANT SELECT ON ALL TABLES IN SCHEMA replica
  TO helena_bridge_reader_privs_v2;

-- Evita que un permiso heredado del pseudo-rol PUBLIC permita DDL. En una rama
-- Neon nueva esto normalmente ya está revocado, pero se fija explícitamente.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM helena_bridge_sync_privs_v2, helena_bridge_reader_privs_v2;
REVOKE CREATE ON SCHEMA replica FROM helena_bridge_sync_privs_v2, helena_bridge_reader_privs_v2;

ALTER DEFAULT PRIVILEGES IN SCHEMA replica
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO helena_bridge_sync_privs_v2;
ALTER DEFAULT PRIVILEGES IN SCHEMA replica
  GRANT USAGE, SELECT ON SEQUENCES TO helena_bridge_sync_privs_v2;
ALTER DEFAULT PRIVILEGES IN SCHEMA replica
  GRANT SELECT ON TABLES TO helena_bridge_reader_privs_v2;

SELECT format('ALTER ROLE %I SET search_path = replica, pg_catalog', :'sync_login') \gexec
SELECT format('ALTER ROLE %I SET search_path = replica, pg_catalog', :'reader_login') \gexec
SELECT format('ALTER ROLE %I RESET default_transaction_read_only', :'sync_login') \gexec
SELECT format('ALTER ROLE %I SET default_transaction_read_only = on', :'reader_login') \gexec
SELECT format('ALTER ROLE %I SET statement_timeout = %L', :'reader_login', '60s') \gexec

-- Fallar la transacción si un rol nuevo conserva atributos o membresías
-- administrativas, o si recibe grupos distintos del único grupo esperado.
SELECT set_config('bridge.sync_login', :'sync_login', true);
SELECT set_config('bridge.reader_login', :'reader_login', true);
DO $guard$
DECLARE
  role_name text;
  expected_group text;
  role_row record;
BEGIN
  FOR role_name, expected_group IN
    SELECT current_setting('bridge.sync_login'), 'helena_bridge_sync_privs_v2'
    UNION ALL
    SELECT current_setting('bridge.reader_login'), 'helena_bridge_reader_privs_v2'
  LOOP
    SELECT * INTO role_row FROM pg_roles WHERE rolname = role_name;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'No existe el login esperado: %', role_name;
    END IF;
    IF role_row.rolsuper OR role_row.rolcreatedb OR role_row.rolcreaterole
       OR role_row.rolreplication OR role_row.rolbypassrls THEN
      RAISE EXCEPTION 'El login % conserva atributos administrativos', role_name;
    END IF;
    IF EXISTS (
      SELECT 1
      FROM pg_auth_members membership
      JOIN pg_roles parent ON parent.oid = membership.roleid
      JOIN pg_roles member_role ON member_role.oid = membership.member
      WHERE member_role.rolname = role_name AND parent.rolname <> expected_group
    ) THEN
      RAISE EXCEPTION 'El login % conserva una membresía no permitida', role_name;
    END IF;
    IF NOT pg_has_role(role_name, expected_group, 'MEMBER') THEN
      RAISE EXCEPTION 'El login % no hereda %', role_name, expected_group;
    END IF;
  END LOOP;
END
$guard$;

COMMIT;

\echo Roles mínimos creados. Asigne claves con comandos interactivos, por ejemplo:
\echo   \password :sync_login
\echo   \password :reader_login
\echo Después pruebe conexiones REALES con validate_sync_v2.sql y validate_reader_v2.sql.
