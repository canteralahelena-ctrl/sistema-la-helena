# Guia de consultas Access - Cantera La Helena

## Bases

- Front-end / mascara: `CANTERA LA HELENA 2-4-26.accdb`
- Back-end / tablas: `CANTERA LA HELENA 1.0_be.accdb`
- Password de apertura front-end: `espinillo`

## Comando central

```powershell
.\work\consultas_rapidas.ps1 ayuda
```

Regla actual:

```text
Cada consulta ejecutada desde consultas_rapidas.ps1 fuerza primero una actualizacion de la copia local del back-end.
La base real del servidor se lee solamente; nunca se escribe ni se reemplaza nada ahi.
Si el servidor no esta disponible, se avisa el error y se consulta con la ultima copia local disponible.
Optimizacion: antes de copiar se comparan fecha y tamano del archivo real. Si no cambio, no se copia y se usa la copia local.
Optimizacion rapida: cliente, deudores y material sin fecha usan `work\cache\access_fast_cache.json`. Ese cache se reconstruye solo cuando cambia la copia local.
```

Actualizador:

```powershell
.\work\actualizar_copia_base.ps1
```

Reconstruir cache manualmente:

```powershell
.\work\cache_access.ps1 -Force
```

Estado de ultima actualizacion correcta:

```text
work\actualizacion_base_estado.json
```

## Cliente rapido

Devuelve cliente, saldo actual y ultimo pago.

```powershell
.\work\consultas_rapidas.ps1 cliente "VMR TEAM"
.\work\consultas_rapidas.ps1 cliente "349"
```

## Estado de cuenta

Formula validada contra Access:

```text
Saldo = Sum(COMPROVANTES.SALDO) - Sum(PAGOS.SALDO)
```

Para estado desde una fecha:

```powershell
.\work\consultas_rapidas.ps1 estado "327" -Desde "2026-05-01"
```

Para PDF:

```powershell
.\work\consultas_rapidas.ps1 estado-pdf "CLIENTE_A" -Desde "2026-06-01"
```

El PDF usa:

- Logo: `work\assets\LOgoTIPO.jpg`
- Encabezado moderno
- Formato A4
- Detalle combinado: `RMT 0000-00030425`, `FTS A ...`, `PAGO ...`

## Deudores

```powershell
.\work\consultas_rapidas.ps1 deudores
```

Salida:

- `outputs\deudores.csv`
- `outputs\deudores_listado.txt`

Formula:

```text
Debe abierto: Sum(COMPROVANTES.SALDO)
Haber abierto: Sum(PAGOS.SALDO)
Deuda: Debe abierto - Haber abierto
```

## Material que mas compra un cliente

```powershell
.\work\consultas_rapidas.ps1 material "CLIENTE_TEST_1396" -Top 10
```

Usa:

- `COMPROVANTES`
- `DETALLE DE COMPROVANTES`
- Agrupa por `PRODUCTO` y `UNIDAD`
- Sin `-Desde` responde desde cache rapido.
- Con `-Desde` consulta Access directo para respetar el rango de fechas.

## Auditoria usuario 3

Reporte completo con comprobantes, pagos y medios de pago:

```powershell
.\work\auditoria_usuario_3.ps1 -Desde "2026-06-01" -Hasta "2026-06-06"
```

Salida principal:

- `outputs\auditoria_usuario_3_YYYY-MM-DD_YYYY-MM-DD.xlsx`
- Hoja `Comprobantes`
- Hoja `Pagos`
- Hoja `Medios de pago`

Optimizaciones:

- Los totales leidos de PDF se guardan en `work\cache\pdf_totales_cache.json`.
- Si el PDF mantiene la misma fecha y tamano, no se vuelve a leer.
- Los medios de pago salen de `DETALLE DE ENTREGAS.TIPO`.

## Graficos de mayo 2026

Materiales en m3:

```powershell
.\work\consultas_rapidas.ps1 ventas-m3
```

Gravas en m3:

```powershell
.\work\consultas_rapidas.ps1 gravas-m3
```

Importe de ventas:

```powershell
.\work\consultas_rapidas.ps1 ventas-importes
```

## Conversiones

Materiales y gravas:

```text
1 m3 = 1,5 TN
TN a m3 = TN / 1,5
```

Gravas:

```text
1 bolson = 0,8 m3
1 bolsa 25 kg = 0,01666 m3
```

## Productos normalizados

Materiales:

- Arena zarandeada
- Arena bruta
- Granza 5/8
- Granza 3/8
- Piedra 1-3
- Piedra bola
- Arena fina
- Arena fina Parana

Gravas:

- Grava 2-4 mm
- Grava 3-6 mm
- Grava N12
- Grava N15
- Grava N20
- Grava 6-9 mm

## Archivos principales

- `work\cliente_rapido.ps1`
- `work\estado_cliente.ps1`
- `work\generar_estado_cuenta_pdf.ps1`
- `work\deudores.ps1`
- `work\material_cliente.ps1`
- `work\ventas_productos_mayo.ps1`
- `work\ventas_gravas_mayo.ps1`
- `work\ventas_importes_materiales_mayo.ps1`
