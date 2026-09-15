# Pendientes

Este documento contiene exclusivamente pendientes reales identificados en `ARQUITECTURA_PORTABILIDAD.md`, `INVENTARIO_V2.md` y el estado actual de `work_v2`.

Documentos relacionados:

- [ESTADO_PROYECTO.md](ESTADO_PROYECTO.md)
- [ROADMAP.md](ROADMAP.md)
- [CHANGELOG.md](CHANGELOG.md)
- [DECISIONES.md](DECISIONES.md)
- [ARQUITECTURA.md](ARQUITECTURA.md)
- [HELENA_CORE.md](HELENA_CORE.md)
- [MIGRACION_HELENA_CORE.md](MIGRACION_HELENA_CORE.md)

## Alta prioridad

- Validar en Windows el candidato de las tres automatizaciones contra la copia
  local Access y configuraciones privadas, primero por ejecucion manual y luego
  mediante las tareas registradas. No declararlo productivo antes de comprobar
  Access, SMTP y Telegram reales.

- Repetir una tarea real con el orquestador en `-NoPublicar` después del ajuste
  de responsabilidades y revisar costos/tiempos antes de habilitar publicación
  automática habitual.
- Inicializar un repositorio Git en una tarea separada si se desea complementar
  los manifiestos SHA-256 con historial y revisión nativa; actualmente `.git` no
  es utilizable.
- Aplicar los flags de escritura a scripts y flujos especificos, validar todos los scripts contra la configuracion central y separar secretos por entorno antes de habilitar ejecuciones reales en V2.
- Evitar cualquier modificacion de la carpeta productiva `work`.
- Mantener Telegram deshabilitado en `development` hasta completar separacion de secretos y validaciones.
- Validar `server_writes_enabled` antes de copia de base desde servidor, copia de PDFs desde servidor, backups, escrituras de estado compartido o salidas a recursos de servidor.
- Validar `scheduled_tasks_enabled` antes de instalar, registrar, iniciar o modificar tareas programadas y accesos de inicio automatico.
- Validar `automatic_alerts_enabled` antes de enviar alertas automaticas de cheques, IVA, Resumen Gerencial u otros mensajes no iniciados manualmente por un usuario.

## Media

- Migrar la siguiente capacidad funcional a Helena Core solo despues de revisar los resultados de la validacion real de `clientes.saldo`.
- Revisar scripts con rutas absolutas a `C:\USUARIO_EJEMPLO\...`.
- Revisar referencias a `\\SERVIDOR_EJEMPLO`.
- Revisar referencias internas a `work\...`.
- Definir configuracion portable para base local, outputs, logs, cache y backups.
- Validar dependencias Python externas detectadas antes de crear un `requirements.txt`.
- Validar todos los scripts contra `helena_core/settings.py` sin cambiar reglas comerciales.
- Diseñar manejo seguro de secretos fuera del repositorio o por entorno.

## Baja

- Definir estructura futura tipo `SistemaLaHelena` cuando la portabilidad este validada.
- Preparar requisitos del futuro instalador.
- Planificar asistente Windows despues de completar arquitectura V2 y portabilidad.
- Evaluar integraciones futuras como WhatsApp o API solo despues de estabilizar el nucleo portable.

## Regla de actualizacion futura

Desde ahora, cada etapa futura debera actualizar automaticamente:

- `docs/ESTADO_PROYECTO.md`
- `docs/CHANGELOG.md`
- `docs/PENDIENTES.md`

La infraestructura multiagente controla que la documentación requerida quede en
el diff de la tarea, pero no inventa ni actualiza contenido sin evidencia.
