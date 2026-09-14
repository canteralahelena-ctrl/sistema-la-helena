# Baseline certificado de work_v2

Fuente verificable para el Release Gate del orquestador. Este archivo registra
evidencia; no aprueba despliegues ni reemplaza la validación humana del piloto.

## Estado inicial

| Capacidad | Estado | Evidencia |
|---|---|---|
| Health Check | OK CONTROLADO | 9/9 controles OK; el alias conocido de gastos se valida campo por campo |
| Ventas | OK | Suite y pruebas del módulo |
| Caja / cobros | OK | Suite y pruebas del módulo |
| Cheques / eCheq | OK | Suite y pruebas del módulo |
| IVA | OK | Suite y pruebas del módulo |
| Pago rápido | OK | Casos 845901/90 y 845790/90 |
| Pago fraccionado / óptimo | OK | Suite y regresiones específicas |
| Auditorías | TESTS_OK | Validación real depende de raíces accesibles |
| Facturas PDF / ZIP | TESTS_OK | PDF individual y ZIP probados; validación real en curso |
| Audio | ENTRADA_VALIDADA | Servicios externos sujetos a configuración |

## Suite certificada

- Baseline anterior aceptado: **377/377 OK** el 2026-09-09.
- Fecha de evidencia actual: 2026-09-11.
- Baseline anterior: **404/404 OK** tras corregir alias y robustez diagnóstica.
- Resultado actual tras separar responsabilidades del grafo: **408/408 OK**.
- Inventario estático al crear esta infraestructura: 42 archivos Python y 377
  métodos `test_*`.
- Regla: una suite futura puede tener más pruebas, pero nunca menos de 408 y
  debe finalizar con cero fallos y cero errores.

El Health controlado del 2026-09-11 terminó `HEALTH_OK`. La tabla real/fixture
expone el alias conocido `COMPROBANTES DE GASTOS`; ahora el validador lo resuelve
y comprueba todos los campos obligatorios antes de aceptar el esquema. La
validación final sobre las raíces reales permanece a cargo del entorno compatible.

Los inspectores sólo pueden continuar tras un fallo tardío cuando el resultado
incluye señales estructuradas de comprobación ejecutada, requisitos confirmados,
evidencia adicional válida, ausencia de contradicción y cero escrituras. El exit
code y la limitación de herramienta permanecen registrados.

El manifiesto legible por máquina está en `orchestration/baseline.json`.

## Regresiones prioritarias

- RMT 30767 y RMT 30831.
- FTS A 200004508, 200004526 y 200004460.
- IVA y SALDO con `DBNull`.
- `Access Denied` distinto de PDF faltante.
- GRANZA y ARENA M3/TN.
- Cheques sin cliente y variantes Cuenta Hugo/Gastón.
- Pago Rápido 845901/90 MIXTO/BLANCO.
- Selección pendiente de cliente para factura PDF.
- PDF individual y ZIP múltiple.

## Límite de certificación

El máximo estado automático es `LISTO_PARA_PILOTO`. La aprobación y la prueba
real final corresponden al usuario.
