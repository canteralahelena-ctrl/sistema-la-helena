# Decisiones

Documentos relacionados:

- [ESTADO_PROYECTO.md](ESTADO_PROYECTO.md)
- [ROADMAP.md](ROADMAP.md)
- [CHANGELOG.md](CHANGELOG.md)
- [ARQUITECTURA.md](ARQUITECTURA.md)
- [PENDIENTES.md](PENDIENTES.md)
- [HELENA_CORE.md](HELENA_CORE.md)
- [MIGRACION_HELENA_CORE.md](MIGRACION_HELENA_CORE.md)

## Mantener produccion intacta

Decision: la carpeta productiva `work` no se renombra, no se mueve y no se modifica durante la reorganizacion.

Justificacion tecnica: reduce el riesgo de cortar el sistema operativo actual mientras V2 todavia esta en validacion.

## Trabajar siempre sobre work_v2

Decision: toda modificacion de desarrollo debe realizarse exclusivamente en `work_v2`.

Justificacion tecnica: permite probar cambios de arquitectura, configuracion y portabilidad sin afectar scripts, credenciales, tareas o archivos productivos.

## Desarrollo incremental

Decision: reorganizar por etapas pequenas y comprobables.

Justificacion tecnica: el sistema combina Telegram, PowerShell, Access, archivos locales, servidor, SMTP y PDFs. Cambios grandes aumentarian el riesgo de romper reglas comerciales o flujos ya validados.

## No modificar reglas comerciales durante la reorganizacion

Decision: no cambiar consultas, calculos, conversiones, armado de reportes ni comportamiento funcional mientras se separa arquitectura.

Justificacion tecnica: la prioridad de esta fase es aislar entorno, rutas, settings y procesos. Mantener reglas intactas facilita comparar V2 contra produccion.

## Reutilizar scripts PowerShell existentes

Decision: conservar los scripts PowerShell actuales como fuente operativa.

Justificacion tecnica: esos scripts encapsulan consultas y procesos administrativos ya usados. Reescribirlos ahora mezclaria portabilidad con cambios funcionales.

## Mantener compatibilidad con Telegram

Decision: `telegram_access_bot.py` conserva su configuracion privada y reglas existentes, aunque tome constantes tecnicas desde `SETTINGS`.

Justificacion tecnica: evita romper el contrato del bot con usuarios, roles, intenciones y respuestas mientras se introduce el nucleo V2.

## Bloquear desarrollo por entorno

Decision: en `development`, Telegram, alertas automaticas, escrituras a servidor y tareas programadas quedan desactivadas por configuracion.

Justificacion tecnica: impide arranques accidentales, envios reales o modificaciones externas desde la copia V2.

## Separar configuracion tecnica de secretos

Decision: `helena_core/settings.py` centraliza rutas, ejecutables y timeouts, pero no debe leer secretos ni reemplazar la configuracion privada real.

Justificacion tecnica: permite avanzar en portabilidad sin exponer tokens, claves SMTP, chat ids o credenciales.

## No depender del historial de Codex

Decision: el estado del proyecto debe quedar documentado dentro de `work_v2/docs`.

Justificacion tecnica: cualquier continuacion futura debe poder identificar estado, decisiones, arquitectura, roadmap, pruebas y pendientes leyendo el proyecto.

## No automatizar todavia la actualizacion documental

Decision: se documenta la regla de actualizacion futura, pero no se implementa automatizacion en esta etapa.

Justificacion tecnica: la instruccion actual prohibe crear codigo nuevo o modificar scripts. La regla queda como control operativo para etapas siguientes.

## Telegram pasa a ser una interfaz

Decision: Telegram no debe ser el nucleo del sistema; debe quedar como interfaz que consume Helena Core.

Justificacion tecnica: permite reutilizar capacidades desde aplicacion Windows, API futura, WhatsApp futuro y tareas automaticas sin duplicar reglas ni acoplarlas al chat.

## Helena Core no depende de Telegram

Decision: Helena Core debe recibir solicitudes estructuradas y devolver resultados independientes del canal.

Justificacion tecnica: evita que menus, chat_id, audio, archivos o formato de Telegram contaminen reglas comerciales y servicios reutilizables.

## Negocio no depende de PowerShell ni Access

Decision: la capa de negocio no debe depender directamente de PowerShell ni Access.

Justificacion tecnica: PowerShell y Access son implementaciones tecnicas actuales. Deben quedar atras de contratos para poder migrar, probar y reutilizar capacidades.

## Integraciones implementan contratos del nucleo

Decision: las integraciones pueden llamar scripts, Access, mail o servicios externos solo como adaptadores de contratos definidos por Helena Core.

Justificacion tecnica: conserva compatibilidad con los scripts existentes mientras se impide que nuevas reglas comerciales queden atrapadas en infraestructura.

## IA con alcance limitado

Decision: la inteligencia artificial puede interpretar lenguaje natural, sugerir intenciones o transcribir audio, pero no puede ejecutar SQL ni scripts arbitrarios.

Justificacion tecnica: reduce riesgo operativo y obliga a pasar por capacidades conocidas, permisos y validaciones.

## Primera extraccion funcional: clientes.saldo

Decision: la primera capacidad funcional recomendada para extraer es `clientes.saldo`.

Justificacion tecnica: es una capacidad real, reusable en Windows, de riesgo bajo/medio si recibe el cliente estructurado, y permite comparar contra el flujo actual sin modificar PowerShell ni reglas comerciales.
