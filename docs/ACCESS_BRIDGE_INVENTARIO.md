# Inventario y mapeo del puente Access

El inventario se dedujo de las consultas productivas existentes, sin copiar datos. La réplica usa una **allowlist**: cualquier tabla o columna no enumerada queda excluida.

| Access | Clave observada | PostgreSQL | Uso |
|---|---|---|---|
| `CLIENTES` | `IdCLIENTE` | `replica.clientes` | identidad comercial, CUIT y localidad |
| `PRODUCTOS` | `IdPRODUCTO` | `replica.productos` | catálogo y unidad |
| `COMPROVANTES` | `IdCOMPROVANTE` | `replica.comprobantes` | ventas, saldo e IVA |
| `DETALLE DE COMPROVANTES` | `IdDET` | `replica.comprobante_detalles` | productos vendidos; relación por `IdCOMPROVANTE` |
| `PAGOS` | `IdPAGO` | `replica.pagos` | cobranzas; `IdCLIENTE` histórico se conserva como texto |
| `DETALLE DE ENTREGAS` | `IdENTREGA` | `replica.entregas` | cheque/eCheq; relaciones por `IdPAGO` e `IdCLIENTE` |

Las relaciones provienen de `cliente_rapido.ps1`, `auditoria_usuario_3.ps1`, `gestion_cheques.ps1`, `material_cliente.ps1` e `iva_mensual.ps1`. No se replican usuarios, credenciales, tablas del sistema, contactos, configuración de correo, rutas, adjuntos, cajas ni gastos/proveedores. Gastos quedan fuera de V1 para reducir exposición y porque sus variantes de nombre necesitan validación local antes de fijar contrato.

La fuente no ofrece una marca de modificación confiable en todas las tablas. Por eso V1 hace un *snapshot* completo dentro de una única transacción PostgreSQL: es incremental en lotes durante la transferencia, pero no finge un incremental por ID que perdería ediciones históricas. El `source_fingerprint` permite auditar cada copia. Access siempre se abre con `READONLY=TRUE;Mode=Read`, sólo se emiten `SELECT` allowlisted y al cerrar se ejecuta `rollback`.

## Capa semántica

Las migraciones ofrecen saldos (debe de comprobantes menos haber de pagos, igual que `cliente_rapido.ps1`), deudores, ventas, productos, última compra, frecuencia, ticket, RFM básico, caída respecto del promedio, series semanales/mensuales, cobranzas, cheques por vencimiento y resumen gerencial. Las notas de crédito se identifican por prefijo `NC`; no se crea una estimación de IVA distinta del valor almacenado.
