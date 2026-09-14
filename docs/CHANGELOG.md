# Changelog

Historial cronologico construido solo con informacion existente en los documentos del proyecto.

Documentos relacionados:

- [ESTADO_PROYECTO.md](ESTADO_PROYECTO.md)
- [ROADMAP.md](ROADMAP.md)
- [DECISIONES.md](DECISIONES.md)
- [ARQUITECTURA.md](ARQUITECTURA.md)
- [PENDIENTES.md](PENDIENTES.md)
- [HELENA_CORE.md](HELENA_CORE.md)
- [MIGRACION_HELENA_CORE.md](MIGRACION_HELENA_CORE.md)

## 2026-09-11

- Resolución de alias conocidos en el Health Check con validación completa de
  los campos del nombre real encontrado.
- Incorporación de `CONFIRMED_WITH_LIMITATION` para inspectores diagnósticos con
  evidencia mínima concluyente, sin relajar Regression, Health ni Release Gate.
- Resultados JSON del orquestador escritos como UTF-8 con BOM para lectura
  estable en Windows PowerShell 5.1.
- Separación estricta de responsabilidades: diagnóstico ya no exige gates
  posteriores, validación puede usar temporales controlados y Cleanup usa
  manifests/hashes sin requerir Git.
- Soporte del camino sin implementación cuando Root Cause confirma que la
  corrección ya está presente, conservando todos los gates finales.
- Criterio objetivo y reusable de evidencia para inspectores: un fallo tardío
  sólo se normaliza a `CONFIRMED_WITH_LIMITATION` con todas las señales positivas,
  sin contradicciones ni escrituras; el exit code queda registrado.
- Mensajes finales `NO_LISTO` enriquecidos con rol, clasificación y causa para
  evitar la inspección manual de JSON internos.
- Health controlado 9/9 y suite completa 408/408.

## 2026-09-10

- Creación de la infraestructura multiagente de desarrollo para `work_v2`.
- Incorporación de 12 perfiles, grafo, estado persistente, schema de resultados
  y baseline verificable.
- Aislamiento del Implementador en staging sin `work`, Access, PDFs, secretos ni
  runtime; publicación mecánica con hashes y rollback.
- Gates de regresión, Health, limpieza e integridad; estado máximo
  `LISTO_PARA_PILOTO`, sin aprobación automática.
- Pruebas aisladas con agentes simulados; sin invocar Telegram, Access, PDFs,
  correo ni tareas programadas.
- Revalidación de Health: bloqueo previo documentado por alias conocido de la
  tabla de gastos; no se modificó la lógica fuera de alcance.

## 2026-07-14

- Relevamiento de arquitectura y portabilidad en `ARQUITECTURA_PORTABILIDAD.md`.
- Inventario de `work_v2` en `INVENTARIO_V2.md`.
- Creacion de `work_v2` como copia paralela de desarrollo desde `work`.
- Identificacion de produccion en `work` y desarrollo paralelo en `work_v2`.
- Registro de archivos copiados inicialmente, exclusiones, assets, documentacion, scripts, JSON y riesgos.
- Creacion de `config/environment.json` con modo `development`.
- Creacion de `config/environment.example.json` sin secretos reales.
- Creacion de `MODO_DESARROLLO.txt`.
- Renombrado de lanzadores de inicio y programacion con sufijo `_DESHABILITADO_V2`.
- Creacion de `helena_core/environment.py`.
- Creacion de `helena_core/paths.py`.
- Agregado de pruebas `tests/test_environment.py` y `tests/test_paths.py`.
- Integracion de deteccion de entorno en `telegram_access_bot.py` para bloquear arranque activo en desarrollo si Telegram esta deshabilitado.
- Separacion de utilidades de ejecucion en `helena_core/process_runner.py`.
- Agregado de pruebas `tests/test_process_runner.py` y `tests/test_bot_environment_guard.py`.
- Creacion de `helena_core/settings.py` para configuracion tecnica centralizada.
- Integracion de `SETTINGS` en `telegram_access_bot.py` para constantes tecnicas, conservando `CONFIG` para configuracion privada y reglas existentes.
- Agregado de prueba `tests/test_settings.py`.

## Etapa actual de documentacion

- Creacion de `docs/`.
- Creacion de `docs/ESTADO_PROYECTO.md`.
- Creacion de `docs/ROADMAP.md`.
- Creacion de `docs/CHANGELOG.md`.
- Creacion de `docs/DECISIONES.md`.
- Creacion de `docs/ARQUITECTURA.md`.
- Creacion de `docs/PENDIENTES.md`.
- Documentacion de la regla futura: cada etapa debera actualizar `ESTADO_PROYECTO.md`, `CHANGELOG.md` y `PENDIENTES.md`.

No se consigna fecha para esta etapa porque la instruccion indica no inventar fechas y los documentos existentes no registran fecha para esta nueva documentacion.

## Etapa actual de diseno Helena Core

- Creacion de `docs/HELENA_CORE.md`.
- Creacion de `docs/MIGRACION_HELENA_CORE.md`.
- Definicion de Helena Core como nucleo reutilizable para Telegram, aplicacion Windows, API futura, WhatsApp futuro y tareas automaticas.
- Documentacion de capas, modulos futuros, responsabilidades y reglas de dependencia.
- Definicion conceptual de contratos: `Request`, `Result`, `Error`, `UserContext`, `PermissionDecision`, `QueryService`, `ReportService`, `NotificationService` y `DataProvider`.
- Inventario de capacidades existentes por implementacion actual, ubicacion, dependencias, riesgo y destino futuro.
- Seleccion de `clientes.saldo` como primera extraccion funcional recomendada.
- Actualizacion de `ESTADO_PROYECTO.md`, `ROADMAP.md`, `DECISIONES.md`, `ARQUITECTURA.md` y `PENDIENTES.md`.

No se consigna fecha para esta etapa porque la instruccion indica no inventar fechas y los documentos existentes no registran fecha para este diseno.

## 2026-07-18

- Creacion de contratos programados de Helena Core en `helena_core/application/contracts.py`: `Request`, `Result`, `ErrorInfo` y `UserContext`.
- Creacion de la primera capacidad funcional `clientes.saldo` en `helena_core/business/clientes/saldo.py`.
- Creacion del adaptador PowerShell `ClienteSaldoPowerShellAdapter` para encapsular `cliente_rapido.ps1` usando `helena_core.process_runner` y `SETTINGS`.
- Integracion minima de Telegram para que `kind == "saldo"` consuma `clientes.saldo` conservando textos, permisos, navegacion y formateo visible existentes.
- Agregado de pruebas unitarias para contratos, servicio, adaptador y compatibilidad del flujo Telegram con salida simulada.
- No se modificaron scripts PowerShell, SQL, Access, produccion ni configuracion productiva.
- Validacion real de `clientes.saldo` en `development` con copia local de base Access en `data/test_database/CANTERA_LA_HELENA_TEST.accdb`.
- Agregado de parametro opcional `DatabasePath` a `cliente_rapido.ps1`, conservando el comportamiento anterior cuando no se informa.
- Configuracion de `local_database_path` y `allow_database_writes=false` para pruebas locales sin fallback al servidor.
- Verificacion de igualdad entre ejecucion directa de `cliente_rapido.ps1` y Helena Core para la misma consulta real.
- Verificacion de hash SHA-256 estable antes y despues de las consultas reales.
