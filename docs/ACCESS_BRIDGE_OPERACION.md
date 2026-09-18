# Instalación y operación del puente

## Instalación única en Windows

Desde PowerShell, en el checkout de esta rama:

```powershell
.\instalar_access_bridge.ps1
```

El instalador verifica Python 3.11+, crea un entorno aislado, solicita de forma segura el DSN cloud y la ruta de la **copia local**, aplica migraciones, ejecuta el snapshot inicial, crea un usuario PostgreSQL autenticado con permisos `SELECT` y transacciones read-only, registra la tarea cada 15 minutos y ejecuta la validación. No edita Access ni sobrescribe una configuración existente. Microsoft Access Database Engine (driver ODBC) debe estar instalado con la misma arquitectura de Python.

Entregar al conector PostgreSQL de ChatGPT únicamente el usuario creado por `provision-reader`, nunca el DSN escritor guardado localmente. Restringir además por IP/TLS en el proveedor cloud cuando esté disponible.

## Diagnóstico y validación end-to-end

```powershell
.\validar_access_bridge.ps1
```

Actualiza la copia mediante el script existente, repite una sincronización atómica, prueba ambas conexiones, informa el último sync y confirma la tarea programada. Los logs JSON no contienen DSN, claves, filas reales ni rutas.

## Rollback local

```powershell
.\desinstalar_access_bridge.ps1
```

Quita tarea y entorno. Conserva la configuración privada por defecto; `-EliminarConfiguracionPrivada` la elimina. La réplica cloud se conserva para evitar pérdida accidental y puede borrarla después un administrador. El rollback nunca toca Access.

## Limitaciones físicas verificables sólo en la PC

Cloud no puede abrir el `.accdb`, comprobar el driver ACE/ODBC, alcanzar el recurso Windows ni autenticar contra PostgreSQL real. Ésas son las únicas verificaciones pendientes y están automatizadas por el instalador/validador. Si la cuenta cloud no tiene `CREATEROLE`, un administrador del proveedor deberá concederlo o crear el usuario lector una vez.
