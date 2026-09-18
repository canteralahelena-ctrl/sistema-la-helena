from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableMapping:
    access_table: str
    target_table: str
    key: str
    columns: tuple[tuple[str, str], ...]

    @property
    def access_columns(self) -> tuple[str, ...]:
        return tuple(item[0] for item in self.columns)

    @property
    def target_columns(self) -> tuple[str, ...]:
        return tuple(item[1] for item in self.columns)


# Allowlist only. Passwords/users/system tables and free-form contacts are deliberately absent.
MAPPINGS = (
    TableMapping("CLIENTES", "clientes", "id_cliente", (("IdCLIENTE", "id_cliente"), ("RAZ SOCIAL", "razon_social"), ("CUIT", "cuit"), ("LOCALIDAD", "localidad"))),
    TableMapping("PRODUCTOS", "productos", "id_producto", (("IdPRODUCTO", "id_producto"), ("PRODUCTO", "producto"), ("UNIDAD", "unidad"), ("PUNITARIO", "precio_unitario"))),
    TableMapping("COMPROVANTES", "comprobantes", "id_comprobante", (("IdCOMPROVANTE", "id_comprobante"), ("IdCLIENTE", "id_cliente"), ("FECHA", "fecha"), ("TIPO", "tipo"), ("Nº", "numero"), ("SUBTOTAL", "subtotal"), ("IVA", "iva"), ("IMPORTE", "importe"), ("SALDO", "saldo"))),
    TableMapping("DETALLE DE COMPROVANTES", "comprobante_detalles", "id_detalle", (("IdDET", "id_detalle"), ("IdCOMPROVANTE", "id_comprobante"), ("PRODUCTO", "producto"), ("UNIDAD", "unidad"), ("CANTIDAD", "cantidad"), ("PUNITARIO", "precio_unitario"), ("Subtot", "subtotal"))),
    TableMapping("PAGOS", "pagos", "id_pago", (("IdPAGO", "id_pago"), ("IdCLIENTE", "id_cliente_texto"), ("FECHA", "fecha"), ("MONTO", "monto"), ("TIPO", "tipo"), ("SALDO", "saldo"))),
    TableMapping("DETALLE DE ENTREGAS", "entregas", "id_entrega", (("IdENTREGA", "id_entrega"), ("IdPAGO", "id_pago"), ("IdCLIENTE", "id_cliente"), ("TIPO", "tipo"), ("ESTADO", "estado"), ("BANCO", "banco"), ("NUMERO", "numero"), ("FECHA A COBRAR", "fecha_cobro"), ("IMPORTE", "importe"), ("OBSERVACION", "observacion"))),
)


def quote_access(identifier: str) -> str:
    if "]" in identifier or not identifier.strip():
        raise ValueError("Identificador Access inválido")
    return f"[{identifier}]"


def select_sql(mapping: TableMapping) -> str:
    fields = ", ".join(quote_access(name) for name in mapping.access_columns)
    return f"SELECT {fields} FROM {quote_access(mapping.access_table)}"
