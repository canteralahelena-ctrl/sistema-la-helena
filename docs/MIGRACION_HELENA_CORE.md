# Migracion Helena Core

Plan incremental para extraer Helena Core sin cambiar funcionalidades, sin tocar produccion y sin modificar reglas comerciales.

Documentos relacionados:

- [HELENA_CORE.md](HELENA_CORE.md)
- [ESTADO_PROYECTO.md](ESTADO_PROYECTO.md)
- [ROADMAP.md](ROADMAP.md)
- [DECISIONES.md](DECISIONES.md)
- [ARQUITECTURA.md](ARQUITECTURA.md)
- [PENDIENTES.md](PENDIENTES.md)

## Principios

- Cada etapa modifica una sola responsabilidad.
- Mantener compatibilidad con Telegram.
- Incluir pruebas.
- Permitir volver atras.
- No tocar produccion.
- Comparar resultados con la version anterior.
- No modificar reglas comerciales durante la extraccion.
- No ejecutar acciones reales si el entorno las bloquea.

## ETAPA A - Contratos comunes

Estado: completada para `Request`, `Result`, `ErrorInfo` y `UserContext`.

Objetivo:

- Definir contratos programados para `Request`, `Result`, `Error`, `UserContext`, `PermissionDecision`, `QueryService`, `ReportService`, `NotificationService` y `DataProvider`.

Responsabilidad unica:

- Crear lenguaje comun interno del nucleo.

Compatibilidad:

- Telegram sigue usando el flujo actual.
- No se reemplaza `handle_command`.

Pruebas:

- Construccion de contratos.
- Serializacion o conversion simple a diccionarios si se define.
- Defaults seguros.

Vuelta atras:

- Los contratos nuevos pueden quedar sin uso y Telegram sigue funcionando igual.

Comparacion:

- No aplica resultado funcional todavia.

## ETAPA B - Primera capacidad funcional

Estado: completada para `clientes.saldo`.

Objetivo:

- Extraer `clientes.saldo` como primera capacidad funcional.

Responsabilidad unica:

- Resolver una solicitud estructurada de saldo de cliente dentro de Helena Core.

Compatibilidad:

- Telegram conserva parseo, menus y desambiguacion.
- El adaptador temporal puede seguir llamando el flujo actual equivalente a `consultas_rapidas.ps1`.
- No se modifica `consultas_rapidas.ps1`.

Pruebas:

- Request valido con cliente.
- Request sin cliente.
- Error controlado ante falla del proveedor.
- Comparacion de mensaje/datos contra salida anterior para un caso de prueba controlado.

Vuelta atras:

- Telegram puede seguir llamando `handle_command("saldo", params)` sin usar la nueva capacidad.

Comparacion:

- Ejecutar la version vieja y la nueva en entorno controlado cuando corresponda.
- Comparar que el cliente y saldo informado coincidan.

## ETAPA C - Adaptador Telegram para esa capacidad

Estado: completada solamente para `kind == "saldo"`.

Objetivo:

- Hacer que Telegram invoque `clientes.saldo` a traves de Helena Core.

Responsabilidad unica:

- Adaptar `kind == "saldo"` al contrato `Request`/`Result`.

Compatibilidad:

- Mantener comandos, textos y permisos actuales.
- Mantener `reply_result` o equivalente hasta que exista una capa comun de presentacion.

Pruebas:

- Parseo actual produce la misma intencion.
- Usuario autorizado recibe respuesta equivalente.
- Usuario no autorizado sigue bloqueado.

Vuelta atras:

- Revertir solo el adaptador Telegram y volver a `handle_command` actual.

Comparacion:

- Mismo texto de entrada, mismo usuario, mismo cliente, misma respuesta funcional.

## ETAPA D - Prueba desde interfaz simulada independiente de Telegram

Objetivo:

- Probar `clientes.saldo` sin Telegram.

Responsabilidad unica:

- Crear una interfaz simulada que envie un `Request` estructurado y lea un `Result`.

Compatibilidad:

- No cambia Telegram.
- No cambia scripts.

Pruebas:

- Request desde simulador.
- Result independiente de Telegram.
- Error sin referencias internas crudas.

Vuelta atras:

- Quitar o ignorar la interfaz simulada sin afectar Telegram.

Comparacion:

- Comparar salida simulada contra salida Telegram para el mismo cliente.

## ETAPA E - Migracion progresiva de las demas capacidades

Estado parcial: `clientes.estado_pdf` completada y `clientes.facturas_pdf` migrada en sus variantes compatibles.

Capacidad migrada:

- Un contrato unico con modos `RANGE`, `OPEN_BALANCE` y `SINCE_LAST_PAYMENT`.
- Servicio independiente de Telegram para validar entrada y resultado.
- Adaptador PowerShell que reutiliza las acciones `estado-pdf`, `estado-pdf-abierto` y `estado-pdf-ultimo-pago` de `consultas_rapidas.ps1`.
- Integracion minima en los tres bloques existentes de `handle_command`.
- Validacion de ruta autorizada, extension PDF y tamano mayor que cero.

Responsabilidades conservadas:

- Telegram mantiene menus, permisos, estados de conversacion, resolucion de clientes, cancelacion y envio del documento.
- Helena Core no envia archivos ni conoce `chat_id` fuera de `UserContext`.
- El estado de cuenta textual no fue migrado y queda fuera del bot actual.
- `clientes.saldo` permanece migrado y operativo.

Capacidad `clientes.facturas_pdf`:

- Modos migrados: `BY_NUMBER`, `BY_PERIOD`, `LATEST` y `SINCE_LAST_PAYMENT`.
- Servicio independiente que valida parametros, resultado estructurado y archivo exacto.
- Adaptador PowerShell que reutiliza `facturas_pdf.ps1` con las acciones y parametros existentes.
- PDF individual por numero preparado en `outputs`; consultas por cliente conservan la salida PDF o ZIP decidida por el script.
- Sin fallback a archivos anteriores y sin aceptar rutas de salida arbitrarias.
- Telegram conserva resolucion de cliente, estados, permisos, textos, captions, cancelacion y envio del documento.

Pendiente documentado:

- `SINCE_LAST_PAYMENT` resuelve en el adaptador el ultimo pago con el orden legacy `FECHA DESC, IdPAGO DESC` y genera el periodo desde esa fecha en una salida aislada por ejecucion.
- El flujo pendiente conserva su implementacion anterior y no llama a la nueva capacidad.

Objetivo:

- Migrar capacidades una por una despues de `clientes.saldo`.

Orden sugerido:

- IVA.
- Ventas.
- Caja.
- Rankings.
- Facturas.
- Estados de cuenta.
- Cheques.
- Pagos.
- Resumen gerencial.
- Alertas.
- Usuarios y permisos.
- IA e interpretacion natural.

Responsabilidad unica:

- Una capacidad por etapa.

Compatibilidad:

- Cada capacidad debe conservar su salida anterior hasta tener validacion.

Pruebas:

- Pruebas unitarias del nucleo.
- Pruebas del adaptador Telegram.
- Comparacion con salida anterior.

Vuelta atras:

- Feature switch o ruta anterior por capacidad.

Comparacion:

- Misma entrada, mismo entorno, mismo resultado esperado.

## ETAPA F - Aplicacion Windows

Objetivo:

- Crear una interfaz Windows que use Helena Core sin duplicar reglas.

Responsabilidad unica:

- Presentacion local y operacion de usuario.

Compatibilidad:

- Telegram sigue funcionando como interfaz paralela.

Pruebas:

- Interfaz Windows llama capacidades ya migradas.
- No depende de chat_id salvo cuando se use un `UserContext` equivalente.

Vuelta atras:

- La aplicacion Windows puede deshabilitarse sin afectar Telegram.

Comparacion:

- Mismo `Request` desde Telegram y Windows produce `Result` equivalente.

Implementacion inicial completada:

- Interfaz nativa Tkinter sin dependencias externas.
- Unica capacidad visible: `clientes.saldo`.
- Flujo `Windows -> controller -> Helena Core -> servicio saldo -> adaptador PowerShell -> cliente_rapido.ps1`.
- Consulta asincronica con una sola operacion activa, indicador de procesamiento y actualizacion de widgets exclusivamente desde el hilo principal.
- Validacion obligatoria de copia local antes de construir el adaptador; no existe fallback de la aplicacion al servidor.
- Errores de entrada, cliente inexistente, ambiguedad, timeout y fallos tecnicos se presentan sin trazas ni detalles internos.
- La desambiguacion estructurada sigue pendiente en Helena Core; no se copio la implementacion acoplada a Telegram.
- Telegram, PowerShell, Access, SQL y las demas capacidades no fueron alterados.

Inicio manual exacto en la PC de desarrollo (no fue ejecutado durante esta etapa):

```powershell
Set-Location 'C:\USUARIO_EJEMPLO\Documents\Codex\2026-06-04\como-te-conecto-a-mi-programa\work_v2'
& 'C:\USUARIO_EJEMPLO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m helena_windows.app
```

## ETAPA G - Instalador y migracion a otra PC

Objetivo:

- Preparar instalacion portable y migracion controlada.

Responsabilidad unica:

- Configuracion de entorno, dependencias, rutas, secretos y validaciones de conectividad.

Compatibilidad:

- Produccion no se reemplaza hasta que haya validacion.

Pruebas:

- Verificacion de Python.
- Verificacion de Access Runtime o ACE OLE DB.
- Verificacion de rutas configuradas.
- Verificacion de secretos externos.
- Smoke test en development sin Telegram activo.

Vuelta atras:

- Mantener `work` productivo intacto y `work_v2` como desarrollo.

Comparacion:

- Misma capacidad ejecutada en PC original y PC destino con datos equivalentes.
