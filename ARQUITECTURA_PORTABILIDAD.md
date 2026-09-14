# Arquitectura y portabilidad - work_v2

Fecha de relevamiento: 2026-07-14.

## Estado actual

`work_v2` es una copia paralela de desarrollo de:

`C:\USUARIO_EJEMPLO\Documents\Codex\2026-06-04\como-te-conecto-a-mi-programa\work`

La carpeta productiva `work` no fue renombrada ni movida. No se reorganizo codigo y no se integraron cambios funcionales.

## Rutas principales detectadas

- Proyecto actual: `C:\USUARIO_EJEMPLO\Documents\Codex\2026-06-04\como-te-conecto-a-mi-programa`
- Produccion: `C:\USUARIO_EJEMPLO\Documents\Codex\2026-06-04\como-te-conecto-a-mi-programa\work`
- Desarrollo paralelo: `C:\USUARIO_EJEMPLO\Documents\Codex\2026-06-04\como-te-conecto-a-mi-programa\work_v2`
- Base local esperada: `C:\USUARIO_EJEMPLO\Documents\Codex\2026-06-04\como-te-conecto-a-mi-programa\CANTERA LA HELENA 1.0_be.accdb`
- Base servidor: `\\SERVIDOR_EJEMPLO\D\LA HELENA\RUTA_ADMIN_EJEMPLO\BASE_DATOS_EJEMPLO\CANTERA LA HELENA 1.0_be.accdb`
- PDFs servidor: `\\SERVIDOR_EJEMPLO\D\LA HELENA\RUTA_ADMIN_EJEMPLO\FACTURAS_EJEMPLO\02_FACTURACION SOCIEDAD`
- Runtime Python usado por scripts: `C:\USUARIO_EJEMPLO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`
- Carpeta de outputs del proyecto: `C:\USUARIO_EJEMPLO\Documents\Codex\2026-06-04\como-te-conecto-a-mi-programa\outputs`
- Logs productivos habituales: `work\telegram_bot_debug.log`, `work\watchdog_bot.log`, `work\reiniciar_bot_telegram.log`, `work\actualizacion_base.log`, `work\telegram_bot_stdout.log`, `work\telegram_bot_stderr.log`
- Cache productivo habitual: `work\cache`
- Backups locales de base: `work\backups_base`

## Dependencias detectadas

- Python: requerido para `telegram_access_bot.py` y utilidades `.py`.
- Modulos estandar usados por el bot y utilidades: `argparse`, `calendar`, `csv`, `datetime`, `difflib`, `json`, `os`, `pathlib`, `re`, `shutil`, `socket`, `subprocess`, `time`, `traceback`, `unicodedata`, `urllib`, `zipfile`.
- Paquetes Python externos detectados en scripts: `openpyxl`, `PIL`/Pillow, `pypdf`, `reportlab`.
- PowerShell: requerido para scripts `.ps1`; el ejecutable queda parametrizado por configuracion tecnica.
- Microsoft Access Runtime / ACE OLE DB: requerido por scripts que abren `Microsoft.ACE.OLEDB.12.0`.
- Driver ODBC Access: detectado en relevamientos previos, aunque el codigo operativo principal usa OLE DB.
- Telegram Bot API: usado por `telegram_access_bot.py` mediante HTTPS para `sendMessage`, `sendDocument`, `getUpdates`, `getFile` y descarga de archivos.
- SMTP: usado por `enviar_mail_auditoria.ps1` mediante `System.Net.Mail.SmtpClient`.
- PDF: `pypdf` para lectura/extraccion y `reportlab` para generacion de documentos.
- Audio/voz: `ffmpeg` configurado desde la configuracion privada para convertir audios antes de transcribir.

No se instalo ninguna dependencia en esta etapa. Una propuesta futura de `requirements.txt` podria incluir `openpyxl`, `Pillow`, `pypdf` y `reportlab`, pero debe validarse antes contra todos los scripts reales.

## Configuracion especifica de esta PC

- `telegram_bot_config.json`: contiene token real de Telegram, usuarios, chat ids, OpenAI key, powershell y ffmpeg. No mostrar secretos.
- `telegram_usuarios.json`: contiene usuarios y roles autorizados.
- `telegram_pending_users.json`: contiene usuarios pendientes.
- `email_config.json`: contiene configuracion SMTP y clave de aplicacion. No mostrar secretos.
- `actualizacion_base_estado.json`: contiene rutas absolutas de origen y destino de la base.
- `auditoria_semanal_maxi_estado.json`: contiene historial de envios y rutas absolutas de outputs.
- Scripts con rutas absolutas al runtime Python: `iniciar_bot_telegram`, `analisis_categorias`, `armar_pago_*`, `auditoria_*`, `consultas_rapidas`, `generar_estado_cuenta_pdf`, `comparar_arca_gastos`.
- `watchdog_bot_telegram_hidden.vbs`: contiene ruta absoluta a la carpeta productiva `work`.

## Recursos externos

- Servidor `\\SERVIDOR_EJEMPLO` para base Access y PDFs de facturacion.
- Base local `.accdb` en la carpeta raiz del proyecto.
- Carpeta `outputs` para Excel, PDF, ZIP, HTML y CSV generados.
- Tarea programada instalable: `LaHelenaTelegramAccessBot`, declarada en `instalar_bot_telegram_inicio.ps1`.
- Inicio automatico por usuario instalable mediante VBS en Startup.
- Servicio externo Telegram Bot API.
- Servicio SMTP configurado para auditorias por mail.

## Archivos que pueden escribir o enviar datos reales

- `telegram_access_bot.py`: envia mensajes/documentos por Telegram y ejecuta scripts.
- `iniciar_bot_telegram_DESHABILITADO_V2.ps1`, `reiniciar_bot_telegram_DESHABILITADO_V2.ps1`, `watchdog_bot_telegram_DESHABILITADO_V2.ps1`: podrian iniciar el bot si se vuelven a habilitar.
- `instalar_bot_telegram_inicio_DESHABILITADO_V2.ps1`: registra e inicia tarea programada si se vuelve a habilitar.
- `instalar_bot_telegram_inicio_usuario_DESHABILITADO_V2.ps1`: escribe un VBS en Startup si se vuelve a habilitar.
- `actualizar_copia_base.ps1`: copia la base desde servidor hacia destino local, crea backups y escribe estado/log.
- `facturas_pdf.ps1`: copia PDFs desde servidor hacia outputs y puede crear ZIPs.
- `auditoria_semanal_maxi.ps1` y `enviar_mail_auditoria.ps1`: generan auditorias y pueden enviar mails reales si se ejecutan con `-EnviarMail`.
- Scripts de consultas y reportes: escriben cache, JSON, CSV, HTML, PDF o Excel en carpetas locales/outputs.

## Elementos que impiden mover hoy el sistema a otra PC

- Rutas absolutas a `C:\USUARIO_EJEMPLO\...`.
- Dependencia del share `\\SERVIDOR_EJEMPLO`.
- Token de Telegram, OpenAI key y clave SMTP dentro de archivos reales de configuracion.
- Dependencia de Access/ACE OLE DB y drivers locales.
- Referencias internas a `work\...` en scripts, documentacion y estado.
- Tareas de inicio configurables con rutas absolutas.
- Base local ubicada fuera de `work_v2` y no parametrizada por ambiente.
- Outputs, logs, cache y backups mezclados con scripts en la carpeta productiva.

## Elementos para futuro instalador

- Instalacion/verificacion de Python y paquetes Python.
- Instalacion/verificacion de Access Runtime o ACE OLE DB.
- Configuracion de rutas de servidor, base local, outputs, logs y cache.
- Configuracion segura de secretos fuera del repositorio.
- Registro opcional de tarea programada.
- Pruebas de conectividad con servidor, Access, Telegram y SMTP.
- Modo desarrollo/produccion integrado antes de iniciar servicios.
- Migracion controlada de `work` a estructura de aplicacion.

## Estructura futura propuesta

No mover archivos todavia. La estructura deseada para una etapa posterior seria:

```text
SistemaLaHelena
app
core
telegram
desktop
scripts
config
data
logs
outputs
installer
tests
```

## Medidas de seguridad aplicadas en work_v2

- `config\environment.json` creado con Telegram, alertas, escrituras a servidor y tareas programadas desactivadas.
- `config\environment.example.json` creado sin secretos reales.
- `MODO_DESARROLLO.txt` creado como marcador visible.
- Lanzadores de inicio y programacion renombrados con `_DESHABILITADO_V2`.
- Los scripts PowerShell existentes no se modificaron en las etapas de nucleo.

## Etapa 2 - nucleo independiente

Se agrego un nucleo minimo en `helena_core` sin integracion con el bot:

- `helena_core\environment.py`: lee `config\environment.json` y neutraliza cualquier valor peligroso en modo desarrollo.
- `helena_core\paths.py`: calcula rutas desde la ubicacion real de `work_v2` y permite overrides por configuracion o variables de entorno.
- `tests\test_environment.py` y `tests\test_paths.py`: validan valores seguros, rutas portables y ausencia de rutas rigidas en los modulos nuevos.

Este nucleo no importa `telegram_access_bot.py`, no abre Access, no ejecuta PowerShell, no crea carpetas de salida y no accede al servidor.

## Etapa 3 - proteccion de arranque y procesos

Se integro la deteccion de entorno en el punto de entrada real de `telegram_access_bot.py`.

- En `development`, si `telegram_enabled` esta deshabilitado, el bot finaliza de forma controlada antes de leer la configuracion privada, crear la instancia de Telegram, iniciar polling o ejecutar alertas.
- La importacion de `telegram_access_bot.py` como modulo no inicia el bot.
- El flujo productivo se conserva cuando Telegram este habilitado por entorno.

Se extrajeron utilidades comunes de ejecucion a `helena_core\process_runner.py`:

- `PS_UTF8_SETUP`
- `subprocess_utf8_env`
- `run_text_subprocess`
- `ps_quote`
- `powershell_file_command`
- `powershell_inline_command`

El modulo `process_runner` es independiente de Telegram, no lee configuraciones privadas y recibe explicitamente el ejecutable PowerShell.

## Etapa 4 - configuracion tecnica centralizada

Se agrego `helena_core\settings.py` como modulo central de configuracion tecnica.

- Centraliza ejecutables tecnicos (`powershell`, `ffmpeg`), puerto de bloqueo, rutas de scripts, outputs, logs, datos, configuracion privada, configuracion de usuarios, diccionario de intenciones, base local opcional, referencia de base servidor opcional y timeouts tecnicos.
- No importa `telegram_access_bot.py`, no abre Access, no ejecuta PowerShell, no crea carpetas durante importacion y no lee valores privados del archivo real.
- La base local de pruebas queda como ruta opcional. Si no esta configurada, queda en `None`; no se reemplaza automaticamente por una base del servidor.
- `telegram_access_bot.py` usa `SETTINGS` para constantes tecnicas, pero conserva `CONFIG` para la configuracion privada y las claves existentes que usan las funciones comerciales.
- `config\environment.example.json` documenta las claves tecnicas nuevas sin secretos ni rutas de esta PC.

## Validaciones pendientes para escrituras

No se modifico todavia la logica de escrituras o envios existentes. En etapas futuras deberan validar los flags de entorno antes de ejecutar acciones reales:

- `server_writes_enabled`: copia de base desde servidor, copia de PDFs desde servidor, backups, escrituras de estado compartido o cualquier salida que apunte a recursos de servidor.
- `scheduled_tasks_enabled`: instalacion, registro, inicio o modificacion de tareas programadas y accesos de inicio automatico.
- `automatic_alerts_enabled`: envio automatico de alertas de cheques, IVA, Resumen Gerencial u otros mensajes no iniciados manualmente por un usuario.

La proteccion directa aplicada ahora solo bloquea el arranque activo del bot V2 en desarrollo. No altera consultas iniciadas manualmente ni reglas comerciales.

## Integracion pendiente

Queda pendiente aplicar los flags de escritura a scripts y flujos especificos, validar todos los scripts contra la configuracion central y separar secretos por entorno antes de habilitar ejecuciones reales en V2.
