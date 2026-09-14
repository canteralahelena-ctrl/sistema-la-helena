# Guia del bot Telegram - Cantera La Helena

Esta guia documenta las consultas reales aceptadas por `work\telegram_access_bot.py`.
No contiene tokens, claves, chat_id ni configuraciones privadas.

## Objetivo

El bot permite consultar informacion administrativa de Access desde Telegram,
por texto o por voz. Usa la copia local de la base, scripts PowerShell ya
existentes y, cuando corresponde, devuelve archivos PDF, CSV, ZIP o Excel.

Antes de responder consultas administrativas, el bot intenta actualizar la copia
local de Access o usar los scripts que lo hacen.

## Usuarios y permisos

### Propietarios

Deben estar configurados con rol `owner` en la configuracion privada del bot.
Pueden usar:

- consultas de clientes y saldos;
- deudores;
- materiales por cliente;
- estados de cuenta PDF;
- facturas PDF;
- IVA mensual;
- cobros por medio de pago;
- caja operativa incluida en cobros/auditoria;
- cheques y eCheq;
- combinacion de eCheq;
- auditoria del usuario 3 por mail, no por Telegram.

### Usuario administrativo

Debe estar configurado como usuario de consulta limitada. Puede usar consultas
generales permitidas por el bot:

- saldo/cliente;
- deudores;
- materiales;
- estados de cuenta PDF;
- facturas PDF.

No puede usar:

- cobros;
- cheques;
- eCheq;
- vencimientos;
- combinacion de eCheq;
- auditoria;
- IVA mensual;
- caja sensible;
- cartera.

Si intenta usar una consulta reservada, el bot responde que la accion esta
reservada para propietarios.

## Ayuda dentro del bot

Mensajes aceptados:

```text
/start
/ayuda
ayuda
help
```

Devuelve texto con ejemplos basicos. La ayuda interna del bot es mas corta que
esta guia.

## Consultas de cliente y saldo

Devuelve texto con datos del cliente, saldo actual y ultimo pago segun
`consultas_rapidas.ps1 cliente`.

Acepta:

```text
/saldo CLIENTE
saldo CLIENTE
saldo de CLIENTE
```

Requiere:

- cliente.

Devuelve:

- texto.

Notas:

- Si el nombre es ambiguo, el bot puede pedir elegir entre opciones numeradas.
- El bot usa busqueda flexible por nombre, pero conviene escribir una parte
  clara de la razon social.

## Deudores

Devuelve listado de clientes deudores. Si existe `outputs\deudores.csv`, lo
envia como documento.

Acepta:

```text
/deudores
deudores
/deudores top 20
deudores top 20
```

Requiere:

- opcional: `top N`.

Devuelve:

- CSV si se genero/encontro;
- texto resumen si no hay CSV.

## Materiales por cliente

Devuelve los materiales que mas compra un cliente.

Acepta:

```text
/material CLIENTE
material CLIENTE
material que mas compra CLIENTE
```

Requiere:

- cliente.

Devuelve:

- texto.

Restriccion:

- no recibe fechas desde el bot; por bot usa top 10.

## Cuenta corriente y estados PDF

### Estado desde una fecha

Genera un PDF de estado de cuenta desde una fecha. Si se indica segunda fecha,
usa periodo.

Acepta:

```text
/estado_pdf CLIENTE desde FECHA
estado pdf CLIENTE desde FECHA
estado de cuenta de CLIENTE desde FECHA
resumen de cuenta de CLIENTE desde MES hasta hoy
dame resumen de CLIENTE desde FECHA hasta FECHA
```

Requiere:

- cliente;
- fecha inicial.

Fechas admitidas:

- `dd/mm/aaaa`;
- `dd-mm-aaaa`;
- nombres de meses en espanol, por ejemplo `desde marzo hasta hoy`;
- `hasta hoy`.

Devuelve:

- PDF.

### Estado abierto

Si se pide estado/resumen sin fecha, el bot usa el flujo de estado abierto:
empieza desde el primer movimiento con saldo abierto.

Acepta:

```text
estado de cuenta CLIENTE
resumen de cuenta CLIENTE
dame estado CLIENTE
dame resumen CLIENTE
enviame estado CLIENTE
mandame estado CLIENTE
pasame estado CLIENTE
```

Requiere:

- cliente.

Devuelve:

- PDF.

### Estado desde ultimo pago

Genera PDF desde el ultimo pago del cliente.

Acepta:

```text
/estado_ultimo_pago CLIENTE
estado de cuenta de CLIENTE desde ultimo pago
resumen de cuenta de CLIENTE desde el ultimo pago
dame estado de CLIENTE desde ultimo pago en pdf
```

Requiere:

- cliente.

Devuelve:

- PDF.

## Facturas PDF

### Una factura por numero

Busca una factura o comprobante por tipo y numero.

Acepta:

```text
/factura_pdf FACTURA NUMERO
dame factura NUMERO
enviame factura A NUMERO
mandame FACTURA NUMERO
nota de credito A NUMERO
ND B NUMERO
FP A NUMERO
```

Tipos reconocidos por el bot:

- `FTS A`, `FTS B`;
- `factura A`, `factura B`;
- `FP A`, `FP B`;
- `NCS A`, `NCS B`;
- `nota de credito A/B`;
- `ND A`, `ND B`;
- `nota de debito A/B`.

Requiere:

- numero de comprobante;
- tipo recomendado, aunque si no se indica el bot prueba variantes.

Devuelve:

- PDF directo si encuentra una sola factura;
- texto si no encuentra PDF o si hay duda.

### Facturas de un cliente por periodo

Busca todas las facturas/comprobantes PDF de un cliente en un periodo.

Acepta:

```text
facturas de CLIENTE desde FECHA hasta FECHA en pdf
comprobantes de CLIENTE desde MES hasta hoy en pdf
enviame todas las facturas de CLIENTE desde FECHA hasta FECHA en pdf
```

Requiere:

- cliente;
- fecha inicial o periodo.

Devuelve:

- ZIP si encuentra varios PDFs;
- PDF directo si el resultado final es un unico archivo;
- texto si existen comprobantes en Access pero no se encontraron PDFs.

### Ultimas facturas de un cliente

Busca la ultima o las ultimas facturas de un cliente.

Acepta:

```text
ultima factura de CLIENTE
dame ultima factura de CLIENTE
enviame ultimas 2 facturas de CLIENTE
ultimos comprobantes de CLIENTE
```

Tambien existe una variante muy flexible:

```text
enviame de CLIENTE
dame de CLIENTE
mandame de CLIENTE
pasame de CLIENTE
```

Esa variante interpreta que se pide la ultima factura del cliente.

Requiere:

- cliente;
- cantidad opcional entre 1 y 20.

Devuelve:

- PDF directo si es una sola factura encontrada;
- ZIP si son varias;
- texto si no encuentra PDF.

## Pagos, cobros y caja

Consulta cobros por medio de pago y periodo.

Acepta:

```text
/cobros efectivo ayer
cuanto se cobro en efectivo ayer
cuanto se cobró por transferencia hoy
cobrado en cheque FECHA
cobrado en echeq hoy
cobrado por flete ayer
cobrado por retencion ayer
cobrado por materiales ayer
```

Medios reconocidos:

- efectivo;
- transferencia / transf;
- cheque;
- eCheq / e-cheq;
- flete;
- retencion;
- materiales;
- todos, si no detecta un medio.

Fechas reconocidas:

- `hoy`;
- `ayer`;
- una fecha `dd/mm/aaaa` o `dd-mm-aaaa`.

Requiere:

- medio opcional;
- periodo opcional.

Devuelve:

- texto.

Restriccion:

- consulta reservada para propietarios.

## Cheques y eCheq

Consultas reservadas para propietarios.

### Resumen de cartera

Acepta:

```text
/cheques
cheques
echeq
cartera de cheques
cuanto tengo en cheques
cuanto tengo en echeq
cuanto tengo de cada
```

Variantes:

- si menciona solo `echeq`, filtra eCheq;
- si menciona `fisico`, filtra cheque fisico;
- si no, muestra ambos.

Devuelve:

- texto.

### Cheques depositables

Acepta:

```text
depositables
cobrar
depositar
cheques depositables
cheques para depositar
cheques para cobrar
que puedo depositar hoy
que puedo depositar ya
que importe puedo cobrar o depositar ya
/depositables
```

Devuelve:

- texto con importes disponibles para depositar/cobrar hoy.

### Vencimientos

Acepta:

```text
/vencimientos
/vencimientos echeq 7 dias
vencimientos cheques
proximos a vencer
echeq proximos a vencer en 15 dias
cheques que vencen en 30 dias
```

Requiere:

- dias opcional; por defecto 7.

Devuelve:

- texto.

### Armar pago con eCheq

Propone combinacion de eCheq, pero no endosa ni modifica Access.

Acepta:

```text
/armar_pago_echeq 5000000 30 dias
armame un pago con echeq de 5 millones a no mas de 30 dias
combiname echeq por 2500000 en 20 dias
```

Requiere:

- importe;
- dias opcional, maximo 30.

Devuelve:

- texto con propuesta de combinacion.

## Auditoria usuario 3

No esta habilitada por Telegram por decision operativa actual. La auditoria del
usuario 3 debe generarse por el proceso semanal y enviarse por mail.

Acepta:

```text
/auditoria usuario 3
auditoria usuario 3
reporte usuario 3
```

Devuelve:

- texto informando que la auditoria no esta habilitada por Telegram.

Proceso correcto:

- usar `work\auditoria_semanal_maxi.ps1 -EnviarMail`;
- mantener la automatizacion semanal por mail.

## IVA mensual

Consulta reservada para propietarios.

Acepta:

```text
/iva
/iva mayo
iva mensual mayo
iva MES/ANIO
reporte iva MES de ANIO
```

Requiere:

- mes opcional; si no se indica, usa el mes actual.

Devuelve:

- texto con resumen operativo `IVA ventas - IVA gastos`;
- genera archivos de detalle/resumen en `outputs/` mediante `iva_mensual.ps1`.

Nota:

- es un control operativo; debe validarse con contador antes de usarlo como
  liquidacion fiscal definitiva.

## Consultas por voz

El bot acepta audios de Telegram si estan configurados:

- OpenAI API para transcribir;
- `ffmpeg` para convertir el audio.

Flujo real:

1. Recibe audio.
2. Descarga archivo a `work\telegram_voice`.
3. Convierte a MP3.
4. Transcribe.
5. Ejecuta el texto transcripto como si fuera mensaje escrito.

Consejos:

- hablar claro y decir primero la accion;
- usar nombres de clientes simples;
- si falla el audio, escribir el mismo pedido por texto;
- si el bot pide elegir cliente, responder solo el numero.

Ejemplos por voz:

```text
saldo de CLIENTE
estado de cuenta CLIENTE
enviame ultima factura de CLIENTE_A
cuanto se cobro en efectivo ayer
cheques para depositar hoy
```

## Cuando el bot pide elegir entre opciones

Si encuentra varios clientes parecidos, responde con opciones numeradas.

Ejemplo:

```text
Encontre varios clientes parecidos:
1. CLIENTE OPCION A
2. CLIENTE OPCION B

Responde solamente con el numero de la opcion.
```

Que hacer:

```text
1
```

No escribir otro comando junto al numero. El bot conserva la consulta original y
continua con el cliente elegido.

## Consultas que NO estan habilitadas por bot actualmente

Aunque existen scripts, el bot no tiene comando directo para:

- graficos de materiales;
- graficos de gravas;
- ventas por importe de materiales;
- auditoria con periodo elegido por mensaje;
- reporte semanal de usuario administrativo con envio de mail;
- consulta libre SQL.

Para esas tareas usar scripts, automatizacion por mail o agregar intenciones al
bot en una mejora futura.

## Resumen rapido por salida

| Consulta | Ejemplo | Rol | Devuelve |
|---|---|---|---|
| Saldo cliente | `/saldo CLIENTE` | permitido | texto |
| Deudores | `/deudores` | permitido para usuario autorizado | CSV o texto |
| Materiales | `/material CLIENTE` | permitido | texto |
| Estado PDF fecha | `/estado_pdf CLIENTE desde FECHA` | permitido | PDF |
| Estado abierto | `estado de cuenta CLIENTE` | permitido | PDF |
| Estado ultimo pago | `/estado_ultimo_pago CLIENTE` | permitido | PDF |
| Factura por numero | `/factura_pdf FACTURA NUMERO` | permitido | PDF o texto |
| Facturas periodo | `facturas de CLIENTE desde FECHA hasta FECHA en pdf` | permitido | ZIP/PDF/texto |
| Ultima factura | `ultima factura de CLIENTE` | permitido | PDF/ZIP/texto |
| Cobros | `/cobros efectivo ayer` | propietarios | texto |
| IVA mensual | `/iva mayo` | propietarios | texto |
| Cheques | `/cheques` | propietarios | texto |
| Depositables | `cheques para depositar` | propietarios | texto |
| Vencimientos | `/vencimientos echeq 7 dias` | propietarios | texto |
| Armar eCheq | `/armar_pago_echeq 5000000 30 dias` | propietarios | texto |
| Auditoria | `/auditoria usuario 3` | no habilitado por bot | texto informativo |
