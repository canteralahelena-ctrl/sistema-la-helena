\set ON_ERROR_STOP on

-- Ejecutar con la conexión DIRECTA del propietario sólo después de validar los
-- dos logins nuevos en una rama Neon y luego en producción.
\if :{?old_sync_login}
\else
\set old_sync_login helena_bridge_sync
\endif
\if :{?old_reader_login}
\else
\set old_reader_login helena_bridge_reader
\endif
\if :{?new_sync_login}
\else
\set new_sync_login helena_bridge_sync_v2
\endif
\if :{?new_reader_login}
\else
\set new_reader_login helena_chatgpt_reader_v2
\endif
\if :{?confirm}
\else
\set confirm NO_CONFIRMADO
\endif

SELECT :'confirm' = 'DESACTIVAR_ROLES_ANTIGUOS' AS confirmed \gset
\if :confirmed
\else
\echo Corte cancelado: use -v confirm=DESACTIVAR_ROLES_ANTIGUOS únicamente tras validar y cambiar ambos DSN.
\quit 3
\endif

SELECT (:'old_sync_login' <> :'new_sync_login'
        AND :'old_sync_login' <> :'new_reader_login'
        AND :'old_reader_login' <> :'new_sync_login'
        AND :'old_reader_login' <> :'new_reader_login') AS distinct_roles \gset
\if :distinct_roles
\else
\echo Corte cancelado: un rol anterior coincide con un rol V2.
\quit 4
\endif

BEGIN;

-- Retira toda membresía heredada de los logins anteriores, no sólo una
-- pertenencia directa a neon_superuser. Los objetos que posean no se borran.
SELECT format('REVOKE %I FROM %I', parent.rolname, member_role.rolname)
FROM pg_auth_members membership
JOIN pg_roles parent ON parent.oid = membership.roleid
JOIN pg_roles member_role ON member_role.oid = membership.member
WHERE member_role.rolname IN (:'old_sync_login', :'old_reader_login')
\gexec

SELECT format('ALTER ROLE %I NOLOGIN', role_name)
FROM (VALUES (:'old_sync_login'), (:'old_reader_login')) AS old_roles(role_name)
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name)
\gexec

COMMIT;

\echo Corte aplicado: roles anteriores en NOLOGIN y sin membresía neon_superuser.
\echo No se eliminaron roles ni objetos; el rollback de conexión sigue siendo posible tras revisión del propietario.
