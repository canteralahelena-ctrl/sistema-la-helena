# Helena Core

Este documento define formalmente el nucleo reutilizable del Sistema La Helena. Es una definicion de arquitectura y planificacion: no crea carpetas, no mueve codigo y no cambia funcionalidades.

Documentos relacionados:

- [ESTADO_PROYECTO.md](ESTADO_PROYECTO.md)
- [ROADMAP.md](ROADMAP.md)
- [DECISIONES.md](DECISIONES.md)
- [ARQUITECTURA.md](ARQUITECTURA.md)
- [PENDIENTES.md](PENDIENTES.md)
- [MIGRACION_HELENA_CORE.md](MIGRACION_HELENA_CORE.md)

## 1. Objetivo del nucleo

Helena Core debe concentrar las capacidades reutilizables del Sistema La Helena para que puedan ser usadas por:

- Telegram.
- Aplicacion Windows.
- API futura.
- WhatsApp futuro.
- Tareas automaticas.

Telegram no debe ser el nucleo. Telegram debe ser una interfaz de usuario y transporte. El nucleo debe recibir solicitudes estructuradas, aplicar reglas y devolver resultados independientes del canal.

## 2. Capas

### Interfaces

Responsabilidad:

- Recibir mensajes, clicks, comandos o requests externos.
- Traducir interacciones del canal a `Request`.
- Mostrar `Result` al usuario segun las capacidades visuales del canal.
- Manejar elementos propios del canal, como menus, botones, adjuntos, typing, audio o archivos.

No pertenece:

- Reglas comerciales.
- SQL.
- Detalles internos de Access.
- Ejecucion directa de scripts arbitrarios.
- Decisiones de permisos fuera del contrato del nucleo.

### Aplicacion / orquestacion

Responsabilidad:

- Recibir `Request`.
- Resolver la capacidad solicitada.
- Coordinar permisos, validaciones, servicios de negocio, proveedores de datos e integraciones.
- Convertir excepciones tecnicas en `Error` controlados.
- Devolver `Result`.

No pertenece:

- Detalles visuales de Telegram, Windows o WhatsApp.
- SQL embebido.
- Rutas fijas de una PC.
- Reglas de infraestructura.

### Negocio

Responsabilidad:

- Reglas comerciales del sistema.
- Conceptos como clientes, ventas, caja, IVA, cheques, pagos y reportes.
- Validaciones de dominio.
- Calculos, criterios y formatos de datos independientes del canal.

No pertenece:

- Telegram.
- Access.
- PowerShell.
- Archivos fisicos.
- Rutas locales.
- Secretos.

### Acceso a datos

Responsabilidad:

- Definir contratos para consultar datos.
- Entregar datos normalizados al negocio.
- Ocultar si la fuente real es Access, un script actual, una base futura o una API.

No pertenece:

- Mensajes de Telegram.
- Reglas de negocio nuevas dentro de scripts.
- Decisiones de permisos.

### Integraciones

Responsabilidad:

- Implementar contratos tecnicos definidos por Helena Core.
- Adaptar PowerShell, Access, mail, Telegram API, filesystem, PDFs u otros servicios.
- Encapsular dependencias externas.

No pertenece:

- Reglas comerciales nuevas.
- Interpretacion libre de solicitudes.
- Dependencias invertidas hacia interfaces.

### Infraestructura

Responsabilidad:

- Entorno.
- Paths.
- Settings.
- Logs.
- Cache tecnico.
- Ejecucion controlada de procesos.
- Timeouts.
- Protecciones de development/production.

No pertenece:

- Reglas comerciales.
- Menus.
- Presentacion.

### Inteligencia artificial

Responsabilidad:

- Interpretar lenguaje natural.
- Sugerir intenciones.
- Transcribir audio.
- Clasificar solicitudes hacia capacidades conocidas.

No pertenece:

- Ejecutar SQL.
- Ejecutar scripts arbitrarios.
- Saltar permisos.
- Decidir acciones irreversibles sin contrato explicito.

## 3. Modulos futuros

Estructura conceptual futura. No crear estas carpetas todavia.

```text
helena_core\
  application\
  business\
    clientes\
    ventas\
    caja\
    iva\
    cheques\
    pagos\
    reportes\
  data\
  integrations\
    access\
    powershell\
    mail\
  security\
  ai\
  scheduler\
  cache\
  infrastructure\
```

### application

Orquestadores de capacidades. Deben depender de contratos, no de Telegram ni de scripts concretos.

### business

Reglas del dominio. Deben operar sobre datos estructurados y servicios abstractos.

### data

Contratos de lectura/escritura de datos. No debe saber de Telegram.

### integrations

Adaptadores tecnicos. Puede contener implementaciones para Access, PowerShell y mail, pero siempre atras de contratos.

### security

Usuarios, roles, permisos y decisiones de acceso independientes del canal.

### ai

Clasificacion de intenciones, transcripcion y normalizacion de solicitudes naturales.

### scheduler

Tareas automaticas y alertas. Debe obedecer flags de entorno.

### cache

Cache reutilizable del nucleo. No debe depender de rutas productivas fijas.

### infrastructure

Entorno, paths, settings, runner, logs y utilidades tecnicas.

## 4. Responsabilidades por componente

### Telegram

- Recibe mensajes.
- Recibe audios.
- Muestra respuestas.
- Envia documentos.
- Maneja menus y navegacion propios del canal.
- Mantiene estados conversacionales del canal mientras no exista un estado comun.

Telegram no debe aplicar reglas comerciales nuevas ni decidir como consultar Access.

### Helena Core

- Interpreta solicitudes estructuradas.
- Ejecuta capacidades.
- Aplica reglas comerciales.
- Aplica permisos por contrato.
- Devuelve resultados independientes del canal.
- Expone contratos reutilizables por Telegram, Windows, API, WhatsApp y tareas automaticas.

### PowerShell

- Acceso tecnico a datos existentes.
- Ejecucion de procesos existentes.
- Compatibilidad con consultas y reportes actuales.

PowerShell no debe recibir nuevas reglas comerciales durante la migracion. Si una regla se extrae, debe vivir en `business` y PowerShell debe quedar como adaptador o fuente temporal.

### Access

- Fuente actual de datos administrativos.
- Debe quedar detras de contratos de datos.

Access no debe ser dependencia directa de negocio.

### Aplicacion Windows futura

- Interfaz local.
- Debe consumir Helena Core mediante `Request` y `Result`.
- No debe duplicar reglas de Telegram ni reglas comerciales.

## 5. Reglas de dependencia

- Telegram puede depender de Helena Core.
- Helena Core no puede depender de Telegram.
- Negocio no puede depender de PowerShell.
- Negocio no puede depender de Access.
- Integraciones pueden implementar contratos definidos por el nucleo.
- IA no puede ejecutar SQL ni scripts arbitrarios.
- Ninguna capacidad debe depender de una ruta fija de una PC.
- Interfaces no deben escribir en produccion por fuera de los servicios autorizados.
- Tareas automaticas deben respetar `automatic_alerts_enabled`, `server_writes_enabled` y `scheduled_tasks_enabled`.
- Los adaptadores pueden llamar scripts existentes, pero el nucleo debe conocerlos como contratos, no como rutas hardcodeadas.

## 6. Contratos conceptuales

No programar todavia. Estos contratos describen el lenguaje comun futuro.

### Request

- `capability`
- `parameters`
- `user_context`
- `channel`
- `request_id`
- `metadata`

### Result

- `success`
- `data`
- `message`
- `files`
- `warnings`
- `metadata`

### Error

- `code`
- `message`
- `technical_detail`
- `recoverable`
- `metadata`

### UserContext

- `user_id`
- `display_name`
- `roles`
- `permissions`
- `channel`
- `channel_user_id`

### PermissionDecision

- `allowed`
- `reason`
- `permission`
- `role`
- `metadata`

### QueryService

- Ejecuta consultas de lectura.
- Recibe parametros estructurados.
- Devuelve datos o texto normalizado segun contrato.

### ReportService

- Genera reportes.
- Devuelve archivos y metadatos.
- No decide como enviarlos por Telegram.

### NotificationService

- Prepara notificaciones.
- Respeta entorno y destinatarios autorizados.
- No envia alertas si el entorno lo bloquea.

### DataProvider

- Abstrae fuente de datos.
- Puede tener implementacion temporal PowerShell/Access.
- Debe devolver datos sin depender de canales.

## 7. Capacidades del sistema

| Capacidad | Implementacion actual | Ubicacion actual | Depende de Telegram | Depende de PowerShell | Riesgo de migracion | Destino futuro |
| --- | --- | --- | --- | --- | --- | --- |
| Consultar cliente | `run_ps(["cliente", cliente])`, cache y resolucion de clientes | `telegram_access_bot.py`, `consultas_rapidas.ps1` | Media: parseo, menus y desambiguacion estan en el bot | Alta | Medio | `business/clientes` + `data/QueryService` |
| Consultar saldo | `kind == "saldo"` usa `consultas_rapidas.ps1` | `telegram_access_bot.py`, `consultas_rapidas.ps1` | Baja si se recibe cliente estructurado; media con lenguaje natural | Alta | Bajo/medio | `business/clientes` |
| Generar estado de cuenta | `estado_pdf`, `estado_pdf_abierto`, `estado_pdf_ultimo_pago` | `telegram_access_bot.py`, `consultas_rapidas.ps1`, scripts PDF | Media: devuelve documento para Telegram | Alta | Alto | `business/reportes` + `ReportService` |
| Obtener facturas | `facturas_pdf.ps1` con busqueda por numero, cliente o periodo | `telegram_access_bot.py`, `facturas_pdf.ps1` | Media: envio de PDF/ZIP por canal | Alta | Alto | `business/reportes` + `integrations/access` |
| Consultar ventas | `analisis_categorias.ps1` y formateo rapido | `telegram_access_bot.py`, `analisis_categorias.ps1` | Baja/media | Alta | Medio | `business/ventas` |
| Consultar caja | `run_ps(["cobros", medio, ...])` | `telegram_access_bot.py`, `consultas_rapidas.ps1` | Baja/media | Alta | Medio | `business/caja` |
| Calcular IVA | `run_ps(["iva-mensual", "-Desde", desde])`, alertas IVA | `telegram_access_bot.py`, `iva_mensual.ps1` | Baja para consulta; media para alerta | Alta | Medio | `business/iva` |
| Consultar cheques | `gestion_cheques.ps1`, JSON temporal, formateo especifico | `telegram_access_bot.py`, `gestion_cheques.ps1` | Media: menus y filtros | Alta | Alto | `business/cheques` |
| Armar pagos | `armar_pago_echeq.ps1`, `armar_pago_optimo.ps1` | `telegram_access_bot.py`, scripts de pago | Media/alta: flujo conversacional | Alta | Alto | `business/pagos` |
| Generar rankings | `ranking_clientes.ps1`, deudores y analisis | `telegram_access_bot.py`, `ranking_clientes.ps1`, `consultas_rapidas.ps1` | Baja/media | Alta | Medio | `business/reportes` |
| Generar resumen gerencial | funciones dashboard, consultas Access, cache y alertas | `telegram_access_bot.py` | Media: envio y alertas | Alta | Alto | `business/reportes` + `scheduler` |
| Administrar usuarios | JSON de usuarios, roles y pendientes | `telegram_access_bot.py`, `telegram_usuarios.json` | Alta: chat_id y flujo Telegram | Baja | Alto | `security` |
| Interpretar lenguaje natural | diccionario, normalizacion, IA, audio | `telegram_access_bot.py`, `diccionario_intenciones.json` | Alta en audio y menus; baja en clasificacion abstracta | Baja | Medio | `ai` + `application` |
| Gestionar alertas | cheques, IVA y resumen gerencial automaticos | `telegram_access_bot.py`, cache de alertas | Alta: destinatarios Telegram | Alta | Alto | `scheduler` + `NotificationService` |

## 8. Estado actual

Ya existen:

- `helena_core/environment.py`.
- `helena_core/paths.py`.
- `helena_core/settings.py`.
- `helena_core/process_runner.py`.
- `helena_core/application/contracts.py`.
- `helena_core/business/clientes/saldo.py`.
- `helena_core/integrations/powershell/cliente_saldo_adapter.py`.
- Entorno `development`.
- Bloqueo de Telegram en desarrollo.
- Pruebas automatizadas.
- Documentacion permanente en `docs/`.

El `helena_core` actual contiene infraestructura minima, contratos comunes y las capacidades funcionales `clientes.saldo`, `clientes.estado_pdf` y las variantes seguras de `clientes.facturas_pdf` documentadas mas abajo.

## 9. Primera extraccion recomendada

Primera capacidad recomendada: consultar saldo de cliente mediante una solicitud estructurada.

Alcance exacto recomendado:

- Entrada: `Request` con `capability = "clientes.saldo"` y parametro `cliente` ya resuelto o ingresado.
- Salida: `Result` con mensaje y datos/metadatos disponibles.
- Adaptador temporal: seguir usando el mecanismo actual equivalente a `consultas_rapidas.ps1` mediante contrato, sin cambiar el script.
- Telegram: conservar parseo, menus, desambiguacion y envio de mensajes como adaptador.

### Comparacion de alternativas

| Alternativa | Dependencias | Variables globales | Telegram | Estados conversacionales | Prueba | Reutilizacion Windows | Evaluacion |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Clientes | Usa cache, resolucion y consultas | Media | Media | Media | Media | Alta | Conviene separar por partes. |
| Ventas | Usa refresh de Access, script y formateo | Media | Baja/media | Baja | Media | Alta | Buena candidata posterior. |
| IVA | Usa parser de periodo, script y formato | Baja/media | Baja | Baja | Alta | Alta | Buena candidata posterior, pero menos representativa de cliente. |
| Cheques | Usa Access, JSON temporal, filtros y formatos | Alta | Media | Media | Media | Alta | Riesgo alto para primera extraccion. |
| Permisos | Usa usuarios Telegram, roles, legacy y chat_id | Alta | Alta | Media | Media | Alta | Importante, pero muy acoplado al canal actual. |
| Ejecucion de consultas | Es infraestructura transversal | Media | Baja | Baja | Alta | Alta | Ya empezo con `process_runner`; no es capacidad de usuario. |
| Formateo de respuestas | Baja dependencia tecnica | Baja | Media por textos actuales | Baja | Alta | Alta | Debe extraerse como apoyo, pero no es una capacidad funcional completa. |
| Consultar saldo | Usa cliente, `run_ps` y formato simple | Baja/media si se recibe `cliente` estructurado | Baja | Baja | Alta | Alta | Mejor primera capacidad funcional. |

### Justificacion

Consultar saldo de cliente es la primera extraccion mas segura porque:

- Es una capacidad real de usuario.
- Tiene alto valor para Telegram y aplicacion Windows.
- Puede acotarse a parametros estructurados sin mover el parser natural.
- No requiere tocar Access directamente.
- No requiere modificar PowerShell.
- No depende de archivos PDF, ZIP ni adjuntos.
- No depende de alertas ni tareas automaticas.
- Permite comparar la respuesta nueva contra la version actual con el mismo cliente.

No se recomienda empezar por permisos, cheques, pagos, facturas o resumen gerencial porque arrastran mas estados, archivos, destinatarios, cache, JSON temporal o alertas.

## 10. Estado de `clientes.saldo`

La capacidad `clientes.saldo` queda implementada como primera extraccion funcional.

Alcance implementado:

- Contrato de entrada mediante `Request`.
- Resultado independiente de canal mediante `Result`.
- Validacion de cliente requerido en negocio.
- Adaptador tecnico inyectable para pruebas.
- Adaptador PowerShell real para `cliente_rapido.ps1`.
- Integracion minima en Telegram sin migrar otras capacidades.

Limites conservados:

- No se modificaron scripts PowerShell.
- No se modifico Access.
- No se agregaron reglas comerciales.
- No se migraron menus, permisos ni estados conversacionales.

## 11. Estado de `clientes.estado_pdf`

La capacidad `clientes.estado_pdf` queda migrada a Helena Core usando los contratos comunes `Request`, `Result`, `ErrorInfo` y `UserContext`.

Variantes incluidas:

- `RANGE`: estado PDF desde una fecha y, opcionalmente, hasta otra fecha.
- `OPEN_BALANCE`: estado PDF desde el primer movimiento abierto.
- `SINCE_LAST_PAYMENT`: estado PDF desde el ultimo pago.

Implementacion:

- Servicio de aplicacion en `helena_core/business/clientes/estado_pdf.py`.
- Adaptador tecnico en `helena_core/integrations/powershell/estado_pdf_adapter.py`.
- Reutilizacion de `consultas_rapidas.ps1` y sus acciones existentes sin modificar PowerShell ni SQL.
- Validacion de que el resultado sea un archivo `.pdf`, no vacio y ubicado dentro de `outputs`.
- Telegram conserva frases, menus, permisos, desambiguacion, captions y envio del documento.

Limites conservados:

- El estado de cuenta textual no fue migrado y permanece fuera del bot actual.
- Helena Core genera y valida el documento; el envio del PDF sigue siendo responsabilidad del adaptador Telegram.
- `clientes.saldo` continua migrado y sin cambios funcionales.

## 12. Estado de `clientes.facturas_pdf`

La capacidad `clientes.facturas_pdf` reutiliza `Request`, `Result`, `ErrorInfo` y `UserContext` sin incorporar objetos de Telegram.

Variantes migradas:

- `BY_NUMBER`: comprobante individual por tipo y numero; el PDF encontrado se prepara en `outputs` conservando su nombre antes de validarlo.
- `BY_PERIOD`: comprobantes de un cliente entre las fechas ya interpretadas por Telegram; puede devolver un PDF unico o un ZIP.
- `LATEST`: ultimos comprobantes de un cliente; puede devolver un PDF unico o un ZIP.
- `SINCE_LAST_PAYMENT`: comprobantes desde la fecha del ultimo pago, resuelto por `FECHA DESC, IdPAGO DESC`; puede devolver un PDF unico o un ZIP.

Componentes:

- Servicio en `helena_core/business/clientes/facturas_pdf.py`.
- Adaptador en `helena_core/integrations/powershell/facturas_pdf_adapter.py`.
- Script existente `facturas_pdf.ps1`, sin cambios de parametros, SQL ni reglas comerciales.
- Validacion de correspondencia de solicitud, carpeta autorizada, existencia, archivo regular, extension esperada y tamano mayor que cero.

Variante no migrada:

- `SINCE_LAST_PAYMENT` se ejecuta mediante Core; Telegram conserva la interaccion visible y el adaptador encapsula la resolucion del ultimo pago y la infraestructura legacy.

Responsabilidades:

- Helena Core valida y devuelve el documento local mediante `Result`.
- Telegram conserva menus, permisos, estados, desambiguacion, captions, mensajes visibles y `send_document`.
- Telegram sigue siendo responsable del envio; Helena Core no envia ni elimina documentos.

## 13. Primera aplicacion Windows

La primera interfaz Windows se encuentra en `helena_windows` y expone solamente la consulta de saldo de clientes.

Arquitectura:

- La vista Tkinter captura un nombre o identificador y presenta el resultado.
- `ClientesSaldoController` crea un `Request` de `clientes.saldo` con canal `windows` y consume el `Result` existente.
- La composicion inyecta `consultar_saldo_cliente` y `ClienteSaldoPowerShellAdapter`; la vista y el controlador no importan Telegram ni ejecutan PowerShell directamente.
- `AsyncSaldoCoordinator` limita la ejecucion a una consulta simultanea. El trabajo se ejecuta en un hilo y la vista solo se actualiza desde el hilo principal mediante polling.
- La composicion exige modo local y una copia local existente; no permite continuar con un fallback al servidor.

Alcance y limites:

- La interfaz no interpreta `stdout`, `stderr`, SQL ni datos de Access: presenta el mensaje normalizado por Helena Core.
- Los errores tecnicos se reemplazan por mensajes controlados sin trazas, comandos ni rutas.
- Helena Core no expone alternativas estructuradas para `clientes.saldo`. Ante una futura respuesta `cliente_ambiguo`, Windows solicita un identificador o nombre mas preciso; no replica la resolucion de Telegram.
- No se agrego autenticacion ni permisos por usuario en esta primera interfaz local.
- Telegram y las capacidades `clientes.estado_pdf` y `clientes.facturas_pdf` no fueron modificados.

Inicio manual exacto en la PC de desarrollo (no fue ejecutado durante esta etapa):

```powershell
Set-Location 'C:\USUARIO_EJEMPLO\Documents\Codex\2026-06-04\como-te-conecto-a-mi-programa\work_v2'
& 'C:\USUARIO_EJEMPLO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m helena_windows.app
```
