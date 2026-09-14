# Inventario work_v2

Fecha de inventario: 2026-07-14.

## Resumen de copia

- Origen productivo: `C:\USUARIO_EJEMPLO\Documents\Codex\2026-06-04\como-te-conecto-a-mi-programa\work`
- Destino V2: `C:\USUARIO_EJEMPLO\Documents\Codex\2026-06-04\como-te-conecto-a-mi-programa\work_v2`
- Archivos copiados inicialmente: 74.
- Directorios copiados inicialmente: 1 (`assets`).
- Bytes copiados inicialmente: 726540.
- Excluido por ser regenerable o pesado: `__pycache__`, `cache`, `backups_base`, `telegram_voice`, `*.log`, `*.pyc`, `*.tmp`, `*.pdf`, `*.xlsx`, `*.xls`.
- Bases Access dentro de `work_v2`: ninguna.
- Bases Access presentes en la raiz del proyecto: `CANTERA LA HELENA 1.0_be.accdb`, `CANTERA LA HELENA 2-4-26.accdb`.

## Archivos Python

- `helena_core\__init__.py`
- `helena_core\environment.py`
- `helena_core\paths.py`
- `helena_core\process_runner.py`
- `helena_core\settings.py`
- `telegram_access_bot.py`
- `combinar_echeq.py`
- `combinar_pagos.py`
- `comparar_arca_gastos.py`
- `generar_estado_pdf.py`
- `generar_excel_analisis_categorias.py`
- `generar_excel_auditoria.py`
- `grafico_gravas_mayo.py`
- `grafico_importes_materiales_mayo.py`
- `grafico_ventas_mayo.py`
- `leer_total_pdf.py`

## Scripts PowerShell

- `account_statement.ps1`
- `actualizar_copia_base.ps1`
- `analisis_categorias.ps1`
- `armar_pago_echeq.ps1`
- `armar_pago_optimo.ps1`
- `auditoria_semanal_maxi.ps1`
- `auditoria_usuario_3.ps1`
- `cache_access.ps1`
- `cliente_rapido.ps1`
- `cobros_medio.ps1`
- `consultas_rapidas.ps1`
- `consulta_cache.ps1`
- `deudores.ps1`
- `enviar_mail_auditoria.ps1`
- `estado_cliente.ps1`
- `estado_pdf_data.ps1`
- `exportar_gastos_mes.ps1`
- `facturas_pdf.ps1`
- `generar_estado_abierto.ps1`
- `generar_estado_cuenta_pdf.ps1`
- `generar_estado_desde_ultimo_pago.ps1`
- `gestion_cheques.ps1`
- `inspect_access.ps1`
- `intenciones_consultas.ps1`
- `iva_mensual.ps1`
- `materiales_m3_mensual_2026.ps1`
- `material_cliente.ps1`
- `query_access.ps1`
- `ranking_clientes.ps1`
- `schema_access.ps1`
- `ventas_gravas_mayo.ps1`
- `ventas_importes_materiales_mayo.ps1`
- `ventas_productos_mayo.ps1`

## Lanzadores renombrados en V2

- `iniciar_bot_telegram.ps1` -> `iniciar_bot_telegram_DESHABILITADO_V2.ps1`
- `reiniciar_bot_telegram.ps1` -> `reiniciar_bot_telegram_DESHABILITADO_V2.ps1`
- `watchdog_bot_telegram.ps1` -> `watchdog_bot_telegram_DESHABILITADO_V2.ps1`
- `watchdog_bot_telegram_hidden.vbs` -> `watchdog_bot_telegram_hidden_DESHABILITADO_V2.vbs`
- `instalar_bot_telegram_inicio.ps1` -> `instalar_bot_telegram_inicio_DESHABILITADO_V2.ps1`
- `instalar_bot_telegram_inicio_usuario.ps1` -> `instalar_bot_telegram_inicio_usuario_DESHABILITADO_V2.ps1`

## JSON

- `telegram_bot_config.json`: configuracion real copiada; contiene secretos y no debe usarse en V2 hasta integrar modo desarrollo.
- `telegram_bot_config.example.json`: plantilla de Telegram.
- `telegram_usuarios.json`: usuarios y roles.
- `telegram_pending_users.json`: usuarios pendientes.
- `diccionario_intenciones.json`: diccionario de intenciones.
- `diccionario_intenciones.json.bak`: backup del diccionario.
- `email_config.json`: configuracion real SMTP copiada; contiene secreto.
- `email_config.example.json`: plantilla de SMTP.
- `actualizacion_base_estado.json`: estado de copia de base con rutas absolutas.
- `auditoria_semanal_maxi_estado.json`: estado de auditorias enviadas.
- `pettarin_vaccarini_estado.json`
- `rodriguez_fabio_estado_2026-06-01.json`
- `vmr_estado.json`
- `config\environment.json`: nuevo modo desarrollo, todo desactivado.
- `config\environment.example.json`: ejemplo sin secretos con entorno, rutas, ejecutables, configuracion tecnica, bases opcionales y timeouts.

## Documentacion

- `AGENTS.md`
- `ESTADO_Y_RECUPERACION.md`
- `GUIA_BOT_TELEGRAM.md`
- `GUIA_CONSULTAS.md`
- `USUARIOS_Y_PERMISOS.md`
- `MODO_DESARROLLO.txt`
- `ARQUITECTURA_PORTABILIDAD.md`
- `INVENTARIO_V2.md`

## Pruebas agregadas en Etapa 2

- `tests\test_environment.py`
- `tests\test_paths.py`

## Pruebas agregadas en Etapa 3

- `tests\test_process_runner.py`
- `tests\test_bot_environment_guard.py`

## Pruebas agregadas en Etapa 4

- `tests\test_settings.py`

## CSV y datos livianos copiados

- `ventas_gravas_mayo_2026.csv`
- `ventas_gravas_mayo_2026.detalle.csv`
- `ventas_importes_materiales_mayo_2026.csv`
- `ventas_importes_materiales_mayo_2026.detalle.csv`
- `ventas_productos_mayo_2026.csv`

## Assets

- `assets\LOgoTIPO.jpg`

## Referencias a rutas absolutas

Escaneo en `work_v2`:

- `C:\`: 19 coincidencias.
- `\\Server`: 4 coincidencias.
- `Documents\Codex`: 2 coincidencias.
- `work\`: 80 coincidencias.
- `.accdb`: 38 coincidencias.

Archivos representativos:

- `actualizacion_base_estado.json`
- `actualizar_copia_base.ps1`
- `auditoria_usuario_3.ps1`
- `facturas_pdf.ps1`
- `watchdog_bot_telegram_hidden_DESHABILITADO_V2.vbs`
- scripts con ruta absoluta al Python de Codex.

## Referencias a Telegram

- `telegram_access_bot.py`
- `telegram_bot_config.json`
- `telegram_bot_config.example.json`
- `telegram_usuarios.json`
- `telegram_pending_users.json`
- `GUIA_BOT_TELEGRAM.md`
- `ESTADO_Y_RECUPERACION.md`
- lanzadores deshabilitados.

No se listan tokens ni chat ids completos.

## Referencias a base del servidor

- `actualizar_copia_base.ps1`
- `actualizacion_base_estado.json`
- `auditoria_usuario_3.ps1`
- `facturas_pdf.ps1`

## Referencias a Access local

- La mayoria de scripts PowerShell usan `Join-Path $root "CANTERA LA HELENA 1.0_be.accdb"`.
- `telegram_access_bot.py` tambien ejecuta consultas Access agrupadas mediante PowerShell inline.
- Proveedor esperado: `Microsoft.ACE.OLEDB.12.0`.

## Configuracion tecnica centralizada

- `helena_core\settings.py`: centraliza rutas tecnicas, ejecutables, timeouts y ubicaciones de configuracion sin leer secretos ni abrir recursos externos.
- `telegram_access_bot.py`: conserva `CONFIG` para valores privados y reglas existentes, pero toma `ROOT`, `WORK`, `OUTPUTS`, caches, logs, diccionarios, usuarios, puerto, PowerShell por defecto y timeouts centrales desde `SETTINGS`.
- `helena_core\paths.py`: resuelve rutas relativas desde `work_v2`, con overrides por `environment.json` o variables de entorno.
- Base local de pruebas: opcional; si no se configura, queda vacia y no se reemplaza por base de servidor.

## Acciones de escritura detectadas

- `Set-Content`: estados, cache, CSV, HTML, JSON, resumenes.
- `Copy-Item`: copia de base local, copia de PDFs, backups de diccionario.
- `Move-Item`: reemplazo de base temporal y manejo de PDF unico.
- `Remove-Item`: temporales, locks, ZIP/PDF temporales, archivos auxiliares.
- `Register-ScheduledTask` y `Start-ScheduledTask`: instalacion de inicio automatico en script deshabilitado.
- `SmtpClient`: envio de mail en auditoria.
- `sendMessage` y `sendDocument`: envio Telegram en bot.

## Riesgos actuales de V2

- La configuracion real fue copiada por seguridad de integridad de la copia, pero contiene secretos.
- El bot V2 integra `config\environment.json` en el punto de entrada principal y finaliza sin polling en desarrollo.
- Los lanzadores fueron renombrados; `python telegram_access_bot.py` finaliza sin polling en desarrollo y solo usaria la configuracion real si Telegram se habilita por entorno.
- Scripts no deshabilitados pueden generar outputs, copiar base local o enviar mails si se ejecutan manualmente con parametros correspondientes.
- El nucleo `helena_core` ya provee deteccion de entorno, rutas, configuracion tecnica y utilidades comunes de procesos para el bot, pero los scripts existentes aun no validan flags de escritura propios.

## Estado Git

- Existe carpeta `.git` en `C:\USUARIO_EJEMPLO\Documents\Codex\2026-06-04\como-te-conecto-a-mi-programa`.
- No se pudo ejecutar `git status` porque `git.exe` no esta disponible en PATH ni en ubicaciones tipicas revisadas.
- No se hizo commit, cambio de rama ni descarte de cambios.
