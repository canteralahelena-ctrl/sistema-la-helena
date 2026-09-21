# Instalación y operación del puente

## Estado y separación de responsabilidades

El puente tiene tres operaciones distintas y no deben ejecutarse con la misma
credencial:

1. **Administración:** esquema, vistas y roles. Usa temporalmente una conexión
   **directa** del propietario de la base.
2. **Sincronización:** reemplaza el snapshot de `replica` y registra
   `sync_runs`. Usa el login sincronizador mínimo.
3. **Consultas de ChatGPT:** sólo ejecuta `SELECT`. Usa un login lector distinto.

Las migraciones de `migrations/` ya no crean roles ni usuarios. El instalador y
la tarea periódica no deben recibir la credencial del propietario ni ejecutar
`provision-reader`. Los roles se aprovisionan una sola vez con los archivos de
`admin/`.

## Regla Neon: rama primero y conexión directa

Todo cambio administrativo se prueba primero en una **rama aislada de Neon**
creada desde producción. Para scripts administrativos y migraciones se usa el
DSN directo del propietario: el hostname **no** debe contener `-pooler`.

No aplicar estos scripts primero en `production`. Tampoco pegar contraseñas en
el comando, en el repositorio, en capturas ni en el chat.

## 1. Crear roles mínimos V2 en la rama de prueba

Desde la raíz del checkout, con `psql` disponible:

```powershell
psql "$env:HELENA_OWNER_DIRECT_DSN" `
  -v sync_login=helena_bridge_sync_v2 `
  -v reader_login=helena_chatgpt_reader_v2 `
  -f .\admin\neon_roles_v2.sql
```

El script crea dos grupos `NOLOGIN`:

- `helena_bridge_sync_privs_v2`: `CONNECT`, `USAGE`, `SELECT`, `INSERT`,
  `UPDATE`, `DELETE` y acceso a las secuencias de `replica`.
- `helena_bridge_reader_privs_v2`: únicamente `CONNECT`, `USAGE` y `SELECT`.

También crea los dos logins parametrizados sin atributos administrativos. Los
logins no pueden ser `SUPERUSER`, crear bases, crear roles, replicar, ignorar RLS
ni heredar `neon_superuser`. El lector inicia cada conexión con
`default_transaction_read_only=on`.

El script revoca `CREATE` sobre `public` a `PUBLIC`. Es una protección global de
la base que debe probarse en la rama Neon antes de producción por si otra
aplicación dependiera de crear objetos en ese esquema.

Asigne las claves en la misma sesión de `psql` mediante el prompt oculto:

```text
\password helena_bridge_sync_v2
\password helena_chatgpt_reader_v2
```

No use las claves de los roles anteriores.

## 2. Validar conexiones reales en la rama

Las validaciones deben conectarse como cada login; ejecutar `SET ROLE` desde el
propietario no prueba la configuración de inicio de sesión.

```powershell
psql "$env:HELENA_SYNC_V2_DIRECT_DSN" -f .\admin\validate_sync_v2.sql
psql "$env:HELENA_READER_V2_DIRECT_DSN" -f .\admin\validate_reader_v2.sql
```

El sincronizador debe superar una transacción DML reversible y debe fallar al
intentar DDL, crear roles o asumir `neon_superuser`. El lector debe poder hacer
`SELECT`, pero PostgreSQL debe rechazar efectivamente `INSERT`, `UPDATE`,
`DELETE`, `TRUNCATE`, `CREATE TABLE`, `CREATE SCHEMA`, `CREATE ROLE` y
`SET ROLE neon_superuser`.

El resultado aceptable de ambos archivos termina en `PASS`. Una salida
interrumpida, un privilegio inesperado o una sola operación negativa permitida
es **NO-GO**.

Después ejecute en esa rama una sincronización completa con el DSN V2 y compare
los seis conteos con el último snapshot válido. No avance sólo porque la conexión
abre.

## 3. Aplicar en producción sin cortar los roles anteriores

Sólo después del `PASS` en la rama:

1. Ejecute `admin/neon_roles_v2.sql` con el DSN **directo** del propietario de
   producción.
2. Asigne contraseñas nuevas mediante `\password`.
3. Ejecute las dos validaciones conectándose realmente con los logins V2.
4. Cambie el DSN privado del puente al sincronizador V2 sin imprimirlo.
5. Ejecute una sincronización manual y confirme `status: ok`, los conteos y un
   nuevo registro en `replica.sync_runs`.
6. Configure ChatGPT exclusivamente con el lector V2 y compruebe una consulta
   real y una escritura rechazada.
7. Registre o habilite la tarea de Windows y confirme al menos dos ejecuciones
   con `LastTaskResult = 0`.

Durante todos esos pasos, los roles anteriores permanecen activos. No se
deshabilitan antes de confirmar ambos caminos V2.

## 4. Cutover de seguridad

Primero identifique los nombres exactos de los logins anteriores. Después, y
únicamente cuando sincronización, tarea y ChatGPT funcionen con V2:

```powershell
psql "$env:HELENA_OWNER_DIRECT_DSN" `
  -v old_sync_login=helena_bridge_sync `
  -v old_reader_login=helena_bridge_reader `
  -v confirm=DESACTIVAR_ROLES_ANTIGUOS `
  -f .\admin\neon_roles_v2_cutover.sql
```

El corte aplica `NOLOGIN` y revoca la pertenencia a `neon_superuser`. No elimina
roles ni objetos porque un rol anterior podría ser propietario de objetos. Si
los nombres reales difieren, no use los valores de ejemplo.

Después del corte repita una sincronización y una consulta de ChatGPT. Revise
además que no quede ningún otro login anterior miembro directo o indirecto de
`neon_superuser`.

## Rollback

### Antes del cutover

Vuelva los dos consumidores a sus DSN anteriores. Como los roles anteriores aún
están activos, no hace falta modificar PostgreSQL. Conserve los roles V2 para
diagnóstico; no los borre durante una incidencia.

### Después del cutover

Detenga primero la tarea automática. Un administrador debe revisar propiedad y
privilegios del rol anterior antes de devolverle `LOGIN`. **No** se restaura su
pertenencia a `neon_superuser`. Si necesita habilitarlo temporalmente, concédale
sólo el grupo V2 correspondiente, active `LOGIN`, restaure el DSN anterior y
repita las pruebas de permisos. Documente el intervalo y vuelva a `NOLOGIN` al
resolver el problema.

El rollback nunca toca Access ni elimina la réplica Neon.

## Instalación local en Windows

Desde PowerShell, en el checkout correcto:

```powershell
.\instalar_access_bridge.ps1
```

Antes de usarlo en una instalación limpia, confirme que la versión del
instalador no ejecuta migraciones administrativas ni crea lectores. Debe usar el
DSN del sincronizador V2 ya preparado. Microsoft Access Database Engine debe
estar instalado con la misma arquitectura que Python.

La fuente del servidor sólo se copia. El `.accdb` local se abre con
`READONLY=TRUE;Mode=Read`; el puente no escribe Access.

## Diagnóstico y validación end-to-end

```powershell
.\validar_access_bridge.ps1
```

La validación final debe confirmar simultáneamente:

- actualización de la copia local;
- sincronización atómica terminada en `status: ok`;
- conteos esperados en las seis tablas;
- nuevo `sync_run` exitoso;
- tarea programada bajo el usuario Windows que accede a la ruta UNC;
- lector V2 con `SELECT` permitido y DML/DDL rechazados;
- ningún login operativo miembro de `neon_superuser`.

Un chequeo que sólo lea `default_transaction_read_only` no es suficiente: deben
ejecutarse las pruebas negativas de `admin/validate_reader_v2.sql`.

## Rollback local

```powershell
.\desinstalar_access_bridge.ps1
```

Quita tarea y entorno local. Conserva la configuración privada por defecto; la
réplica Neon se conserva para evitar pérdida accidental. Nunca modifica Access.
