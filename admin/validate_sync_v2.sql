\set ON_ERROR_STOP on

-- Ejecutar conectado directamente como el NUEVO login sincronizador.
SELECT current_user AS sync_login,
       current_database() AS database_name,
       current_setting('transaction_read_only') AS transaction_read_only;

DO $validate_attrs$
DECLARE
  r record;
BEGIN
  SELECT * INTO r FROM pg_roles WHERE rolname = current_user;
  IF r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls THEN
    RAISE EXCEPTION 'FAIL: el sincronizador tiene atributos administrativos';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_roles admin_role
    WHERE admin_role.rolname = 'neon_superuser'
      AND pg_has_role(current_user, admin_role.oid, 'MEMBER')
  ) THEN
    RAISE EXCEPTION 'FAIL: el sincronizador hereda neon_superuser';
  END IF;
  IF NOT has_schema_privilege(current_user, 'replica', 'USAGE')
     OR NOT has_table_privilege(current_user, 'replica.sync_runs', 'SELECT')
     OR NOT has_table_privilege(current_user, 'replica.sync_runs', 'INSERT')
     OR NOT has_table_privilege(current_user, 'replica.sync_runs', 'UPDATE')
     OR NOT has_table_privilege(current_user, 'replica.sync_runs', 'DELETE') THEN
    RAISE EXCEPTION 'FAIL: faltan permisos DML mínimos en replica';
  END IF;
  IF has_schema_privilege(current_user, 'replica', 'CREATE')
     OR has_schema_privilege(current_user, 'public', 'CREATE') THEN
    RAISE EXCEPTION 'FAIL: el sincronizador puede crear estructuras';
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'replica' AND table_type = 'BASE TABLE'
      AND NOT (
        has_table_privilege(current_user, format('%I.%I', table_schema, table_name), 'SELECT')
        AND has_table_privilege(current_user, format('%I.%I', table_schema, table_name), 'INSERT')
        AND has_table_privilege(current_user, format('%I.%I', table_schema, table_name), 'UPDATE')
        AND has_table_privilege(current_user, format('%I.%I', table_schema, table_name), 'DELETE')
      )
  ) THEN
    RAISE EXCEPTION 'FAIL: faltan permisos DML en alguna tabla de replica';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_namespace
    WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
      AND nspname !~ '^pg_temp_' AND nspname !~ '^pg_toast_temp_'
      AND has_schema_privilege(current_user, oid, 'CREATE')
  ) THEN
    RAISE EXCEPTION 'FAIL: el sincronizador puede crear objetos en algún esquema';
  END IF;
END
$validate_attrs$;

-- Prueba positiva reversible de los cuatro permisos usados por el runtime.
BEGIN;
SELECT count(*) >= 0 AS select_ok FROM replica.sync_runs;
INSERT INTO replica.sync_runs(started_at, finished_at, status, source_fingerprint, row_counts)
VALUES (clock_timestamp(), clock_timestamp(), 'permission_test', 'rollback', '{}'::jsonb);
UPDATE replica.sync_runs SET status = status WHERE source_fingerprint = 'rollback';
DELETE FROM replica.sync_runs WHERE source_fingerprint = 'rollback';
ROLLBACK;

-- Pruebas negativas efectivas. Cada sentencia debe ser rechazada; el bloque
-- aborta si cualquiera llega a ejecutarse.
DO $negative_tests$
DECLARE
  statement text;
  blocked boolean;
BEGIN
  FOREACH statement IN ARRAY ARRAY[
    'CREATE TABLE public.helena_permission_probe(id integer)',
    'CREATE TABLE replica.helena_permission_probe(id integer)',
    'CREATE SCHEMA helena_permission_probe',
    'CREATE ROLE helena_permission_probe',
    'SET ROLE neon_superuser'
  ]
  LOOP
    blocked := false;
    BEGIN
      EXECUTE statement;
    EXCEPTION
      WHEN insufficient_privilege OR read_only_sql_transaction THEN
        blocked := true;
    END;
    IF NOT blocked THEN
      RAISE EXCEPTION 'FAIL: el sincronizador ejecutó: %', statement;
    END IF;
  END LOOP;
END
$negative_tests$;

SELECT 'PASS: sincronizador limitado; DML reversible OK; DDL/administración bloqueados' AS result;
