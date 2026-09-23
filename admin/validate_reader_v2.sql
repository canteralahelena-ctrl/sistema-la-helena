\set ON_ERROR_STOP on

-- Ejecutar conectado directamente como el NUEVO login lector de ChatGPT.
SELECT current_user AS reader_login,
       current_database() AS database_name,
       current_setting('transaction_read_only') AS transaction_read_only;

DO $validate_attrs$
DECLARE
  r record;
BEGIN
  SELECT * INTO r FROM pg_roles WHERE rolname = current_user;
  IF current_setting('transaction_read_only') <> 'on' THEN
    RAISE EXCEPTION 'FAIL: la conexión lectora no inició read-only';
  END IF;
  IF r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls THEN
    RAISE EXCEPTION 'FAIL: el lector tiene atributos administrativos';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_roles admin_role
    WHERE admin_role.rolname = 'neon_superuser'
      AND pg_has_role(current_user, admin_role.oid, 'MEMBER')
  ) THEN
    RAISE EXCEPTION 'FAIL: el lector hereda neon_superuser';
  END IF;
  IF NOT has_schema_privilege(current_user, 'replica', 'USAGE')
     OR NOT has_table_privilege(current_user, 'replica.sync_runs', 'SELECT') THEN
    RAISE EXCEPTION 'FAIL: faltan USAGE/SELECT en replica';
  END IF;
  IF has_table_privilege(current_user, 'replica.sync_runs', 'INSERT')
     OR has_table_privilege(current_user, 'replica.sync_runs', 'UPDATE')
     OR has_table_privilege(current_user, 'replica.sync_runs', 'DELETE')
     OR has_table_privilege(current_user, 'replica.sync_runs', 'TRUNCATE')
     OR has_schema_privilege(current_user, 'replica', 'CREATE')
     OR has_schema_privilege(current_user, 'public', 'CREATE') THEN
    RAISE EXCEPTION 'FAIL: el lector tiene permisos de escritura o DDL';
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'replica'
      AND NOT has_table_privilege(current_user, format('%I.%I', table_schema, table_name), 'SELECT')
  ) THEN
    RAISE EXCEPTION 'FAIL: falta SELECT en alguna tabla o vista de replica';
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'replica' AND table_type = 'BASE TABLE'
      AND (
        has_table_privilege(current_user, format('%I.%I', table_schema, table_name), 'INSERT')
        OR has_table_privilege(current_user, format('%I.%I', table_schema, table_name), 'UPDATE')
        OR has_table_privilege(current_user, format('%I.%I', table_schema, table_name), 'DELETE')
        OR has_table_privilege(current_user, format('%I.%I', table_schema, table_name), 'TRUNCATE')
      )
  ) THEN
    RAISE EXCEPTION 'FAIL: el lector escribe en alguna tabla de replica';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_namespace
    WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
      AND nspname !~ '^pg_temp_' AND nspname !~ '^pg_toast_temp_'
      AND has_schema_privilege(current_user, oid, 'CREATE')
  ) THEN
    RAISE EXCEPTION 'FAIL: el lector puede crear objetos en algún esquema';
  END IF;
END
$validate_attrs$;

-- Prueba positiva real.
SELECT count(*) >= 0 AS select_ok FROM replica.sync_runs;

-- Pruebas negativas efectivas. El bloque aborta si alguna escritura o acción
-- administrativa no es rechazada por PostgreSQL.
DO $negative_tests$
DECLARE
  statement text;
  blocked boolean;
BEGIN
  FOREACH statement IN ARRAY ARRAY[
    $$INSERT INTO replica.sync_runs(started_at, status) VALUES (clock_timestamp(), 'permission_test')$$,
    $$UPDATE replica.sync_runs SET status = status WHERE false$$,
    $$DELETE FROM replica.sync_runs WHERE false$$,
    $$TRUNCATE replica.sync_runs$$,
    $$CREATE TABLE public.helena_permission_probe(id integer)$$,
    $$CREATE TABLE replica.helena_permission_probe(id integer)$$,
    $$CREATE SCHEMA helena_permission_probe$$,
    $$CREATE ROLE helena_permission_probe$$,
    $$SET ROLE neon_superuser$$
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
      RAISE EXCEPTION 'FAIL: el lector ejecutó: %', statement;
    END IF;
  END LOOP;
END
$negative_tests$;

SELECT 'PASS: lector SELECT-only; DML/DDL/administración bloqueados' AS result;
