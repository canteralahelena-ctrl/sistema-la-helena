# Roadmap

Documentos relacionados:

- [ESTADO_PROYECTO.md](ESTADO_PROYECTO.md)
- [CHANGELOG.md](CHANGELOG.md)
- [DECISIONES.md](DECISIONES.md)
- [ARQUITECTURA.md](ARQUITECTURA.md)
- [PENDIENTES.md](PENDIENTES.md)
- [HELENA_CORE.md](HELENA_CORE.md)
- [MIGRACION_HELENA_CORE.md](MIGRACION_HELENA_CORE.md)

## FASE 1 - Bot Telegram

Estado: parcialmente completo y protegido en desarrollo.

Alcance existente:

- `telegram_access_bot.py` opera como punto de entrada principal.
- Mantiene compatibilidad con configuracion privada, usuarios, intenciones y scripts existentes.
- En V2, el arranque queda bloqueado en `development` cuando `telegram_enabled` esta deshabilitado.
- La importacion del bot como modulo no inicia polling.

Pendiente de esta fase:

- No habilitar Telegram en V2 hasta separar secretos por entorno y validar ejecuciones reales.
- No modificar reglas comerciales ni flujos de Telegram durante la reorganizacion.

## FASE 2 - Arquitectura V2

Estado: en progreso.

Completado:

- Creacion de `helena_core`.
- Separacion de entorno en `helena_core/environment.py`.
- Separacion de rutas en `helena_core/paths.py`.
- Separacion de configuracion tecnica en `helena_core/settings.py`.
- Separacion de ejecucion de procesos en `helena_core/process_runner.py`.
- Pruebas unitarias para los modulos nuevos y para el bloqueo del bot.
- Diseno formal de Helena Core como nucleo reutilizable independiente de Telegram.
- Plan incremental de migracion de Helena Core.

Pendiente:

- Implementar contratos comunes de Helena Core.
- Extraer `clientes.saldo` como primera capacidad funcional.
- Aplicar flags de escritura a scripts y flujos especificos.
- Validar todos los scripts contra la configuracion central.
- Separar secretos por entorno.

### Diseno y migracion de Helena Core

Estado: disenado, pendiente de implementacion.

Completado:

- Capas definidas: interfaces, aplicacion/orquestacion, negocio, acceso a datos, integraciones, infraestructura e inteligencia artificial.
- Modulos futuros definidos conceptualmente.
- Reglas de dependencia documentadas.
- Contratos conceptuales definidos.
- Capacidades existentes inventariadas.
- Primera extraccion recomendada: `clientes.saldo`.

Pendiente:

- Programar contratos comunes.
- Migrar la primera capacidad manteniendo compatibilidad con Telegram.
- Probar la capacidad desde una interfaz simulada independiente de Telegram.

## FASE 3 - Portabilidad

Estado: pendiente con base relevada.

Completado:

- Relevamiento de rutas absolutas y dependencias en `ARQUITECTURA_PORTABILIDAD.md`.
- Inventario de archivos, scripts, JSON, documentacion, riesgos y referencias a rutas absolutas en `INVENTARIO_V2.md`.
- Identificacion de dependencias: Python, PowerShell, Access/ACE OLE DB, Telegram Bot API, SMTP, PDF y ffmpeg.

Pendiente:

- Eliminar dependencias rigidas de rutas de esta PC.
- Definir configuracion portable para servidor, base local, outputs, logs, cache y secretos.
- Validar ejecucion en otra PC.

## FASE 4 - Instalador

Estado: pendiente.

Base disponible:

- `ARQUITECTURA_PORTABILIDAD.md` enumera elementos requeridos para futuro instalador.

Pendiente:

- Verificar o instalar Python y paquetes requeridos.
- Verificar Access Runtime o ACE OLE DB.
- Configurar rutas, secretos y entorno.
- Registrar tarea programada solo cuando `scheduled_tasks_enabled` y el modo productivo lo permitan.
- Ejecutar pruebas de conectividad y arranque seguro.

## FASE 5 - Asistente Windows

Estado: pendiente.

Objetivo futuro:

- Crear una capa de asistencia local para instalacion, configuracion, diagnostico y operacion controlada en Windows.

Condicion previa:

- Completar arquitectura V2, portabilidad y separacion de secretos.

## FASE 6 - Integracion futura

Estado: pendiente.

Integraciones posibles:

- WhatsApp.
- API.
- Otros canales o servicios futuros.

Condicion previa:

- Mantener el nucleo portable y las reglas comerciales aisladas para no acoplar integraciones nuevas al bot de Telegram ni a rutas locales.
