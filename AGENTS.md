# Reglas operativas - work

Esta carpeta contiene scripts, configuraciones privadas, cache y utilidades del sistema administrativo.

## Uso de scripts

Usar scripts existentes antes de crear consultas nuevas.

Scripts principales:

- `consultas_rapidas.ps1`: entrada central.
- `actualizar_copia_base.ps1`: actualizacion de copia local.
- `cache_access.ps1`: cache rapido.
- `cliente_rapido.ps1`: saldo y datos de cliente.
- `deudores.ps1`: deudores.
- `estado_cliente.ps1`: estado de cuenta.
- `generar_estado_cuenta_pdf.ps1`: PDF de cuenta.
- `generar_estado_desde_ultimo_pago.ps1`: PDF desde ultimo pago.
- `facturas_pdf.ps1`: facturas PDF por numero, cliente o periodo.
- `auditoria_usuario_3.ps1`: auditoria Maxi.
- `auditoria_semanal_maxi.ps1`: auditoria semanal.
- `gestion_cheques.ps1`: cheques y eCheq.
- `armar_pago_echeq.ps1`: combinador eCheq.
- `iva_mensual.ps1`: IVA ventas/gastos.
- `ventas_productos_mayo.ps1`: aridos en m3.
- `ventas_gravas_mayo.ps1`: gravas en m3.
- `ventas_importes_materiales_mayo.ps1`: ventas por importe.

## Validacion obligatoria

Antes de responder sobre:

- saldos;
- pagos;
- caja;
- cheques;
- eCheq;
- auditoria;
- IVA;
- deudores;
- facturas PDF;

actualizar o validar copia local y consultar datos reales.

No responder desde memoria si existe script o dato consultable.

## Bot

Script principal:

- `telegram_access_bot.py`

Config privada:

- `telegram_bot_config.json`

No mostrar ni copiar tokens, API keys, claves de correo o configuracion privada.

El bot debe responder limpio: sin stack traces, rutas internas ni errores tecnicos crudos.

## PDFs de facturas

- Si se pide una sola factura y se encuentra un solo PDF, enviar PDF directo.
- Si se piden varias facturas, enviar ZIP.
- Si hay faltantes o dudas, informar faltantes claramente.
- Buscar por carpetas anuales segun fecha del comprobante o periodo pedido.

## Graficos y materiales

Conversiones confirmadas:

```text
1 m3 = 1,5 TN
TN a m3 = TN / 1,5
1 bolson = 0,8 m3
1 bolsa 25 kg = 0,01666 m3
```

Productos de aridos y gravas deben mantenerse normalizados segun reglas ya validadas.

## ARCA y gastos

Para comparar ARCA contra Access:

- usar CUIT de `PROVEEDORES2` cuando exista;
- usar tipo, punto de venta, numero, fecha, IVA e importe;
- si ARCA tiene `Tipo Cambio` distinto de 1, convertir IVA e importe a pesos;
- no asumir que `UserID` identifica a Maxi en gastos si los datos reales muestran `UserID=0`.

No estandarizar ni modificar carga de gastos hasta que el usuario lo pida expresamente.
