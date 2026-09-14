# Estado del proyecto

Este documento resume el estado operativo de `work_v2` para que el desarrollo pueda continuar sin depender del historial de Codex.

Documentos relacionados:

- [ROADMAP.md](ROADMAP.md)
- [CHANGELOG.md](CHANGELOG.md)
- [DECISIONES.md](DECISIONES.md)
- [ARQUITECTURA.md](ARQUITECTURA.md)
- [PENDIENTES.md](PENDIENTES.md)
- [HELENA_CORE.md](HELENA_CORE.md)
- [MIGRACION_HELENA_CORE.md](MIGRACION_HELENA_CORE.md)

## Descripcion general

El proyecto es el sistema administrativo de La Helena conectado a un bot de Telegram. El bot (`telegram_access_bot.py`) atiende consultas, ejecuta scripts PowerShell y Python, genera reportes y trabaja con datos de Access, PDFs, configuraciones de usuarios y recursos externos como Telegram, SMTP y el servidor `\\SERVIDOR_EJEMPLO`.

`work_v2` es una copia paralela de desarrollo creada a partir de la carpeta productiva `work`. La carpeta productiva sigue intacta y no debe modificarse desde esta etapa.

## Objetivo

Hacer que el proyecto sea autosuficiente para continuar el desarrollo desde los archivos del propio proyecto, sin depender del historial de Codex.

La reorganizacion actual busca preparar portabilidad, separacion de configuracion, protecciones de entorno y una futura estructura instalable, sin cambiar reglas comerciales ni comportamiento funcional.

## Arquitectura actual

La arquitectura vigente mantiene el bot principal y los scripts existentes, con un nucleo nuevo `helena_core` para entorno, rutas, configuracion tecnica y ejecucion de procesos.

Helena Core ya fue disenado formalmente como nucleo reutilizable futuro. El diseno define capas, contratos conceptuales, reglas de dependencia, capacidades del sistema y un plan de migracion incremental. Ver [HELENA_CORE.md](HELENA_CORE.md) y [MIGRACION_HELENA_CORE.md](MIGRACION_HELENA_CORE.md).

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
    |-- data
    |-- integrations
    |-- security
    |-- ai
    |-- scheduler
    |-- cache
    |-- infrastructure actual
        |-- environment.py
        |-- paths.py
        |-- settings.py
        |-- process_runner.py
    |
    v
Adaptadores actuales
    |-- PowerShell / Python scripts existentes
    |-- Access
    |-- PDFs / outputs / SMTP
```

Detalle ampliado: [ARQUITECTURA.md](ARQUITECTURA.md).

## Modulos existentes

- `telegram_access_bot.py`: punto de entrada del bot de Telegram. En V2 ya integra proteccion de entorno para finalizar en `development` si Telegram esta deshabilitado.
- `helena_core/environment.py`: lee `config/environment.json` y neutraliza valores peligrosos en modo desarrollo.
- `helena_core/paths.py`: calcula rutas desde la ubicacion real de `work_v2` y permite overrides por configuracion o variables de entorno.
- `helena_core/settings.py`: centraliza ejecutables tecnicos, rutas, archivos de configuracion, timeouts y base local opcional.
- `helena_core/process_runner.py`: concentra utilidades comunes para ejecutar subprocess y PowerShell con UTF-8.
- `helena_core/application/contracts.py`: contratos comunes `Request`, `Result`, `ErrorInfo` y `UserContext`, independientes de Telegram.
- `helena_core/business/clientes/saldo.py`: primera capacidad funcional `clientes.saldo`, con validacion de cliente y resultado normalizado.
- `helena_core/integrations/powershell/cliente_saldo_adapter.py`: adaptador tecnico para `cliente_rapido.ps1` con `process_runner` y `SETTINGS`.
- `data/test_database/CANTERA_LA_HELENA_TEST.accdb`: copia local de prueba para validar `clientes.saldo` sin usar servidor ni produccion.
- Diseno Helena Core: documentado en `docs/HELENA_CORE.md`; aun no se crearon las carpetas futuras ni los contratos programados.
- Plan de migracion Helena Core: documentado en `docs/MIGRACION_HELENA_CORE.md`.
- `config/environment.json`: entorno real de desarrollo, con Telegram, alertas, escrituras a servidor y tareas programadas desactivadas.
- `config/environment.example.json`: ejemplo documentado sin secretos reales.
- Scripts PowerShell existentes: consultas, reportes, auditorias, facturas, gestion de cheques, IVA, cache y copia de base.
- Scripts Python existentes: combinadores, reportes, graficos, PDFs y utilidades.
- `tests/`: pruebas unitarias de entorno, paths, settings, process runner y guardia de arranque del bot.

## Estado de cada modulo

- Bot Telegram: protegido en desarrollo. Integra solamente la capacidad `clientes.saldo` sin mover menus, permisos ni conversacion.
- `helena_core/environment.py`: implementado y probado.
- `helena_core/paths.py`: implementado y probado.
- `helena_core/settings.py`: implementado y probado.
- `helena_core/process_runner.py`: implementado y probado.
- Helena Core reutilizable: ya contiene contratos comunes y la primera capacidad funcional `clientes.saldo`.
- `clientes.saldo`: validado en forma real contra copia local Access en modo lectura, comparando ejecucion directa de PowerShell contra Helena Core.
- Scripts PowerShell existentes: conservados. Aun no validan todos los flags de escritura de entorno.
- Scripts Python existentes fuera de `helena_core`: conservados. No fueron reorganizados en esta etapa.
- Configuracion real copiada: existe en V2 pero contiene secretos y no debe exponerse.
- Lanzadores de inicio: renombrados con sufijo `_DESHABILITADO_V2`.
- Produccion `work`: protegida, no movida, no renombrada y no modificada por la reorganizacion documentada.

## Ultimas etapas completadas

Segun `ARQUITECTURA_PORTABILIDAD.md` e `INVENTARIO_V2.md`:

- Creacion de `work_v2` como copia paralela de desarrollo.
- Separacion de configuracion de entorno con `config/environment.json`.
- Separacion de paths con `helena_core/paths.py`.
- Separacion de configuracion tecnica con `helena_core/settings.py`.
- Separacion de ejecucion de procesos con `helena_core/process_runner.py`.
- Bloqueo de arranque activo del bot V2 en `development`.
- Renombrado de lanzadores de inicio con `_DESHABILITADO_V2`.
- Creacion de pruebas para entorno, paths, settings, process runner y guardia de arranque.
- Documentacion de estado, roadmap, changelog, decisiones, arquitectura y pendientes en `docs/`.
- Diseno formal de Helena Core como nucleo reutilizable independiente de Telegram.
- Plan incremental de migracion de Helena Core.

## Pruebas existentes

Archivos de prueba existentes:

- `tests/test_environment.py`
- `tests/test_paths.py`
- `tests/test_process_runner.py`
- `tests/test_bot_environment_guard.py`
- `tests/test_settings.py`
- `tests/test_contracts.py`
- `tests/test_cliente_saldo_service.py`
- `tests/test_cliente_saldo_adapter.py`

Cantidad de archivos de tests: 8.

Las pruebas existentes validan valores seguros de entorno, rutas portables, comportamiento de settings, utilidades de procesos y bloqueo del bot en desarrollo.

## Entorno development

`config/environment.json` define:

- `environment`: `development`
- `telegram_enabled`: `false`
- `automatic_alerts_enabled`: `false`
- `server_writes_enabled`: `false`
- `scheduled_tasks_enabled`: `false`
- `use_local_database_only`: `true`
- `local_database_path`: `data/test_database/CANTERA_LA_HELENA_TEST.accdb`
- `allow_database_writes`: `false`

`MODO_DESARROLLO.txt` indica que esta carpeta no debe usar token productivo de Telegram, no debe iniciar alertas automaticas, no debe escribir en el servidor, no debe registrar tareas programadas y no debe reemplazar la carpeta productiva `work` hasta completar validaciones.

## Produccion protegida

Produccion es:

```text
C:\USUARIO_EJEMPLO\Documents\Codex\2026-06-04\como-te-conecto-a-mi-programa\work
```

Desarrollo paralelo es:

```text
C:\USUARIO_EJEMPLO\Documents\Codex\2026-06-04\como-te-conecto-a-mi-programa\work_v2
```

La carpeta productiva `work` no debe modificarse. Toda etapa nueva debe trabajar exclusivamente sobre `work_v2` hasta que exista un procedimiento de migracion validado.

## Punto exacto de retoma

Retomar en:

```text
Validar la siguiente capacidad candidata de Helena Core sin migrar otras funciones hasta que `clientes.saldo` quede probado en entorno controlado.
```

Este mismo punto figura como primer pendiente en [PENDIENTES.md](PENDIENTES.md).

## Orquestacion multiagente de desarrollo

Existe una capa separada en `orchestration/` para coordinar diagnóstico,
implementación única, regresión, health, limpieza y release. Usa staging saneado,
manifiestos SHA-256 y rollback; no forma parte de la lógica de Helena Core ni
inicia servicios operativos. Ver [ORQUESTACION_MULTIAGENTE.md](ORQUESTACION_MULTIAGENTE.md)
y [CERTIFIED_BASELINE.md](CERTIFIED_BASELINE.md).

Desde el 2026-09-11 los inspectores pueden informar evidencia confirmada con una
limitación secundaria sin bloquear la fase diagnóstica, siempre que acrediten
evidencia mínima, cero escrituras y cero archivos modificados. Health, regresión
y Release Gate continúan fallando cerrado. El Health controlado vigente es 9/9.

Cada rol evalúa sólo su fase. Legacy y Root Cause no exigen Git, suite ni Health;
Regression y Health pueden usar temporales controlados; Diff/Cleanup trabaja con
manifests y hashes. Si no se requiere cambio, se omite implementación sin omitir
los gates posteriores. El grafo no solicita intervención humana entre agentes.

La evidencia de inspectores se evalúa mediante señales objetivas. Un exit code
posterior no invalida resultados positivos completos, pero sólo permite continuar
si la comprobación principal y la evidencia adicional son válidas, no existen
contradicciones ni errores incompatibles y no hubo escrituras. Todo `NO_LISTO`
expone rol, clasificación y causa en el resultado final.

## Regla de actualizacion futura

Desde ahora, cada etapa futura debera actualizar automaticamente:

- `docs/ESTADO_PROYECTO.md`
- `docs/CHANGELOG.md`
- `docs/PENDIENTES.md`

El orquestador exige que los cambios documentales del alcance formen parte del
diff revisado; no altera documentos automáticamente fuera de la tarea.
