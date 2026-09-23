\set ON_ERROR_STOP on

-- Ejecutar únicamente con psql y el DSN directo del propietario, primero en
-- una rama Neon aislada. Las migraciones no crean roles ni credenciales.
BEGIN;
\ir ../migrations/001_replica_schema.sql
\ir ../migrations/002_semantic_views.sql
\ir ../migrations/003_reader_guard.sql
COMMIT;

\echo Esquema y vistas aplicados sin aprovisionar roles.
