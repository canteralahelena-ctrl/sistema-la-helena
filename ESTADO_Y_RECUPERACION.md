# Estado y recuperacion - Cantera La Helena

Fecha de guardado: 05/06/2026

## Ubicacion principal

```text
C:\USUARIO_EJEMPLO\Documents\Codex\2026-06-04\como-te-conecto-a-mi-programa
```

## Bot Telegram

Bot:

```text
@la_helena_consultas_bot
```

Archivos:

```text
work\telegram_access_bot.py
work\telegram_bot_config.json
work\iniciar_bot_telegram.ps1
work\instalar_bot_telegram_inicio_usuario.ps1
```

Arranque automatico instalado en:

```text
C:\USUARIO_EJEMPLO\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\LaHelenaTelegramAccessBot.vbs
```

Si se corta la energia:

- Si Windows inicia sesion con este usuario, el bot arranca solo.
- Si la PC queda prendida pero nadie inicia sesion, este metodo no arranca hasta que se inicie sesion.
- Para iniciar manualmente:

```powershell
.\work\iniciar_bot_telegram.ps1
```

## Voz

Estado:

- El bot ya sabe recibir audio.
- FFmpeg quedo configurado en `telegram_bot_config.json`.
- Falta cargar `openai_api_key` para transcribir audios.

Config:

```text
work\telegram_bot_config.json
```

No compartir ese archivo fuera de la PC porque contiene claves.

## Consultas principales

Comando central:

```powershell
.\work\consultas_rapidas.ps1 ayuda
```

Comandos disponibles:

```powershell
.\work\consultas_rapidas.ps1 cliente "VMR TEAM"
.\work\consultas_rapidas.ps1 deudores
.\work\consultas_rapidas.ps1 cobros efectivo -Desde "2026-06-04" -Hasta "2026-06-05"
.\work\consultas_rapidas.ps1 material "CLIENTE_TEST_1396" -Top 10
.\work\consultas_rapidas.ps1 estado-pdf "CLIENTE_A" -Desde "2026-06-01"
.\work\consultas_rapidas.ps1 estado-pdf-ultimo-pago "CLIENTE_A"
```

## Correcciones importantes ya aplicadas

- La copia local de Access solo se actualiza si cambia fecha/tamano del archivo original.
- Las consultas rapidas usan cache local para cliente, deudores y material.
- El bot evita instancias duplicadas con un bloqueo local.
- El estado de cuenta desde ultimo pago usa fecha y hora exacta del pago, no solo el dia.
- Los medios de pago se toman desde `DETALLE DE ENTREGAS.TIPO`.
- El reporte usuario 3 incluye comprobantes, pagos y medios de pago.
- Los totales de PDF auditados se cachean para no releer PDFs sin cambios.

## Archivos de cache y logs

```text
work\cache\access_fast_cache.json
work\cache\pdf_totales_cache.json
work\actualizacion_base_estado.json
work\actualizacion_base.log
work\telegram_bot.log
work\telegram_bot.err.log
```

## Reportes y salidas

```text
outputs\
```

Ejemplos recientes:

```text
outputs\estado_chovet_desde_ultimo_pago_corregido.pdf
outputs\auditoria_usuario_3_2026-06-01_2026-06-05.xlsx
```

## Auditoria semanal Maxi por email

Estado confirmado: funcionando.

- Automatizacion Codex: `auditoria-semanal-maxi-usuario-3`
- Frecuencia: todos los lunes a las 08:00.
- Periodo auditado: semana anterior completa, de lunes a domingo.
- Script principal: `work\auditoria_semanal_maxi.ps1 -EnviarMail`
- Genera: Excel de auditoria usuario 3 / Maxi.
- Envia a: `usuario@example.com`
- Config privada de correo: `work\email_config.json`
- Plantilla sin clave: `work\email_config.example.json`

Prueba confirmada el 08/06/2026:

- La clave de aplicacion de Gmail quedo cargada con formato correcto.
- El envio SMTP a Gmail respondio `ENVIADO`.
- El flujo completo genero el Excel y envio el correo correctamente.

No mostrar ni copiar la clave de `work\email_config.json` en chats o reportes.

## Si el bot no responde

1. Ver si hay proceso Python:

```powershell
Get-Process python -ErrorAction SilentlyContinue
```

2. Iniciar manualmente:

```powershell
.\work\iniciar_bot_telegram.ps1
```

3. Revisar errores:

```powershell
Get-Content .\work\telegram_bot.err.log -Tail 50
```

## Si Access o servidor no responde

El sistema intenta usar la ultima copia local disponible.

Estado de ultima copia:

```powershell
Get-Content .\work\actualizacion_base_estado.json
```

Actualizar manualmente:

```powershell
.\work\actualizar_copia_base.ps1
```
