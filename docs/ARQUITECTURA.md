# Arquitectura

Documentos relacionados:

- [ESTADO_PROYECTO.md](ESTADO_PROYECTO.md)
- [ROADMAP.md](ROADMAP.md)
- [CHANGELOG.md](CHANGELOG.md)
- [DECISIONES.md](DECISIONES.md)
- [PENDIENTES.md](PENDIENTES.md)
- [HELENA_CORE.md](HELENA_CORE.md)
- [MIGRACION_HELENA_CORE.md](MIGRACION_HELENA_CORE.md)

## Diagrama textual actual

```text
Interfaces
    |-- Telegram actual
    |-- Aplicacion Windows futura
    |-- API futura
    |-- WhatsApp futuro
    |-- Tareas automaticas
    |
    v
Helena Core
    |-- application / orquestacion
    |-- business
    |   |-- clientes
    |   |-- ventas
    |   |-- caja
    |   |-- iva
    |   |-- cheques
    |   |-- pagos
    |   |-- reportes
    |-- data
    |-- integrations
    |   |-- access
    |   |-- powershell
    |   |-- mail
    |-- security
    |-- ai
    |-- scheduler
    |-- cache
    |-- infrastructure
        |-- environment.py
        |-- paths.py
        |-- settings.py
        |-- process_runner.py
    |
    v
Adaptadores actuales
    |-- PowerShell / Python scripts existentes
    |-- Access
    |-- servidor
    |-- PDFs / outputs
    |-- SMTP
```

## Responsabilidades

### Telegram

Canal de entrada y salida del usuario. El bot usa la API de Telegram para recibir mensajes, enviar respuestas y enviar documentos.

En V2 development, Telegram queda deshabilitado por `config/environment.json`.

En la arquitectura objetivo, Telegram es una interfaz. Puede depender de Helena Core, pero Helena Core no puede depender de Telegram.

### telegram_access_bot.py

Punto de entrada principal del bot.

Responsabilidades actuales:

- Leer configuracion privada cuando el entorno permite operar.
- Mantener usuarios, permisos, intenciones y reglas existentes.
- Ejecutar scripts para consultas y reportes.
- Enviar mensajes y documentos por Telegram.
- Bloquear el arranque activo en `development` cuando `telegram_enabled` esta en `false`.
- Usar `SETTINGS` para constantes tecnicas centralizadas.

No debe modificarse en esta etapa documental.

### helena_core/environment.py

Responsable de leer `config/environment.json` y aplicar valores seguros para desarrollo.

Controles principales:

- `telegram_enabled`
- `automatic_alerts_enabled`
- `server_writes_enabled`
- `scheduled_tasks_enabled`
- `use_local_database_only`

### Helena Core objetivo

Responsable de concentrar capacidades reutilizables por Telegram, aplicacion Windows, API futura, WhatsApp futuro y tareas automaticas.

Capas objetivo:

- Interfaces.
- Aplicacion / orquestacion.
- Negocio.
- Acceso a datos.
- Integraciones.
- Infraestructura.
- Inteligencia artificial.

El diseno completo esta en [HELENA_CORE.md](HELENA_CORE.md).

### Contratos y primera capacidad implementada

Helena Core ya incluye contratos programados en `helena_core/application/contracts.py`:

- `Request`.
- `Result`.
- `ErrorInfo`.
- `UserContext`.

La primera capacidad funcional implementada es `clientes.saldo` en `helena_core/business/clientes/saldo.py`.

El acceso tecnico temporal se realiza mediante `helena_core/integrations/powershell/cliente_saldo_adapter.py`, que encapsula `cliente_rapido.ps1` usando `SETTINGS` y `process_runner`.

Telegram consume esta capacidad solo en el flujo `kind == "saldo"` y conserva la responsabilidad de permisos, estados, menus y presentacion.

### helena_core/paths.py

Responsable de resolver rutas desde la ubicacion real de `work_v2`.

Permite que la arquitectura avance hacia portabilidad porque evita depender de rutas rigidas cuando los modulos nuevos calculan paths.

### helena_core/settings.py

Responsable de centralizar configuracion tecnica:

- Ejecutables: PowerShell, ffmpeg.
- Puerto de bloqueo.
- Rutas de scripts, outputs, logs y datos.
- Archivos de configuracion privada, usuarios e intenciones.
- Base local opcional y referencia de base servidor opcional.
- Timeouts tecnicos.

No lee secretos reales durante importacion, no abre Access, no ejecuta PowerShell y no crea carpetas.

### helena_core/process_runner.py

Responsable de utilidades comunes de procesos:

- Setup UTF-8 para PowerShell.
- Entorno UTF-8 para subprocess.
- Ejecucion de subprocess de texto.
- Quote de argumentos PowerShell.
- Construccion de comandos PowerShell por archivo o inline.

No depende de Telegram ni de configuracion privada.

### Scripts PowerShell existentes

Responsables de consultas, reportes, auditorias, facturas, gestion de cheques, IVA, cache, copia de base y otras operaciones administrativas.

Estado actual:

- Conservados.
- No reescritos.
- Aun deben validar flags de escritura antes de acciones reales.

### Scripts Python existentes

Responsables de combinadores, reportes, generacion de PDFs, Excel, graficos y utilidades.

Estado actual:

- Conservados.
- No reorganizados fuera de la integracion tecnica ya documentada.

### Access

Fuente de datos administrativa.

Dependencias registradas:

- Base local esperada fuera de `work_v2`.
- Servidor `\\SERVIDOR_EJEMPLO`.
- Proveedor `Microsoft.ACE.OLEDB.12.0`.

No se modifica Access en esta etapa.

### PowerShell

Capa de ejecucion de consultas y procesos existentes.

La reorganizacion V2 agrego `process_runner`, pero no cambio los scripts PowerShell ni sus reglas comerciales.

### Produccion y desarrollo

```text
Produccion:
C:\USUARIO_EJEMPLO\Documents\Codex\2026-06-04\como-te-conecto-a-mi-programa\work

Desarrollo:
C:\USUARIO_EJEMPLO\Documents\Codex\2026-06-04\como-te-conecto-a-mi-programa\work_v2
```

Produccion esta protegida. Desarrollo continua solo en `work_v2`.

## Orquestación de desarrollo

La automatización de cambios vive en `orchestration/`, separada de Helena Core.
Opera sobre copias saneadas, reserva la escritura de código al Implementador y
publica sólo después de Regression, Health, Diff y Release Gate. Su diseño y
comandos están en [ORQUESTACION_MULTIAGENTE.md](ORQUESTACION_MULTIAGENTE.md).
