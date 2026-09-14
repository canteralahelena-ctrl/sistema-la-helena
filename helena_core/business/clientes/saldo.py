from __future__ import annotations

from typing import Any, Protocol

from helena_core.application.contracts import ErrorInfo, Request, Result


class ClienteSaldoAdapter(Protocol):
    def consultar_saldo(self, cliente: str) -> Any:
        ...


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _cliente_desde_request(request: Request | None, cliente: str | None) -> str:
    if cliente is not None:
        return str(cliente).strip()
    if request is None:
        return ""
    parameters = request.parameters or {}
    value = parameters.get("cliente") or parameters.get("id_cliente") or parameters.get("identificador")
    return str(value or "").strip()


def consultar_saldo_cliente(
    request: Request | None = None,
    *,
    cliente: str | None = None,
    adapter: ClienteSaldoAdapter | None = None,
) -> Result:
    if request is not None and request.capability != "clientes.saldo":
        return Result(
            success=False,
            error=ErrorInfo(
                code="capacidad_invalida",
                message="La capacidad solicitada no corresponde a clientes.saldo.",
                recoverable=False,
            ),
            metadata={"capability": request.capability},
        )

    cliente_normalizado = _cliente_desde_request(request, cliente)
    if not cliente_normalizado:
        return Result(
            success=False,
            error=ErrorInfo(
                code="cliente_requerido",
                message="Debe indicar un cliente o identificador de cliente.",
                recoverable=True,
            ),
            metadata={"capability": "clientes.saldo"},
        )

    if adapter is None:
        return Result(
            success=False,
            error=ErrorInfo(
                code="adaptador_requerido",
                message="Debe indicar un adaptador para consultar el saldo del cliente.",
                recoverable=False,
            ),
            metadata={"capability": "clientes.saldo"},
        )

    technical_adapter = adapter
    technical_result = technical_adapter.consultar_saldo(cliente_normalizado)
    stdout = str(_value(technical_result, "stdout", "") or "").strip()
    stderr = str(_value(technical_result, "stderr", "") or "").strip()
    returncode = _value(technical_result, "returncode", None)
    command = _value(technical_result, "command", None)
    cwd = _value(technical_result, "cwd", None)
    timeout = _value(technical_result, "timeout", None)
    message = stdout or "Consulta ejecutada."

    metadata = {
        "capability": "clientes.saldo",
        "returncode": returncode,
        "timeout": timeout,
    }
    if command is not None:
        metadata["command"] = command
    if cwd is not None:
        metadata["cwd"] = cwd

    data = {
        "cliente": cliente_normalizado,
        "stdout": stdout,
        "stderr": stderr,
        "returncode": returncode,
    }

    if not bool(_value(technical_result, "success", False)):
        return Result(
            success=False,
            data=data,
            message=message if stdout else stderr,
            metadata=metadata,
            error=ErrorInfo(
                code="cliente_saldo_error",
                message=stderr or stdout or "No se pudo consultar el saldo del cliente.",
                technical_detail=stderr,
                recoverable=True,
                metadata={"returncode": returncode},
            ),
        )

    if stdout.lower().startswith("no encontre cliente"):
        return Result(
            success=False,
            data=data,
            message=message,
            metadata=metadata,
            error=ErrorInfo(
                code="cliente_no_encontrado",
                message=message,
                recoverable=True,
            ),
        )

    return Result(
        success=True,
        data=data,
        message=message,
        metadata=metadata,
    )
