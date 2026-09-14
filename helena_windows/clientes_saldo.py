from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Queue
from threading import Lock
from typing import Callable, Protocol

from helena_core.application.contracts import ErrorInfo, Request, Result, UserContext


@dataclass(frozen=True)
class SaldoPresentation:
    success: bool
    message: str
    error_code: str = ""


class SaldoService(Protocol):
    def __call__(self, request: Request) -> Result:
        ...


class FutureLike(Protocol):
    def add_done_callback(self, callback: Callable[[object], None]) -> None:
        ...

    def result(self) -> object:
        ...


class Submitter(Protocol):
    def __call__(self, function: Callable[[], SaldoPresentation]) -> FutureLike:
        ...


_CONTROLLED_ERRORS = {
    "cliente_requerido": "Ingresá un cliente, nombre o identificador.",
    "cliente_no_encontrado": "No se encontró el cliente indicado.",
    "cliente_ambiguo": "Se encontraron varios clientes. Ingresá un identificador o un nombre más preciso.",
    "cliente_saldo_timeout": "La consulta demoró demasiado. Intentá nuevamente.",
    "cliente_saldo_error": "No se pudo consultar el saldo. Intentá nuevamente.",
    "capacidad_invalida": "No se pudo iniciar la consulta de saldo.",
    "adaptador_requerido": "La consulta de saldo no está disponible.",
    "resultado_invalido": "La consulta devolvió un resultado no válido.",
    "error_inesperado": "No se pudo consultar el saldo. Intentá nuevamente.",
}


class ClientesSaldoController:
    """Traduce la interacción Windows al contrato estable de Helena Core."""

    def __init__(self, service: SaldoService) -> None:
        self._service = service

    @staticmethod
    def empty_presentation() -> SaldoPresentation:
        return SaldoPresentation(False, _CONTROLLED_ERRORS["cliente_requerido"], "cliente_requerido")

    @staticmethod
    def unexpected_error() -> SaldoPresentation:
        return SaldoPresentation(False, _CONTROLLED_ERRORS["error_inesperado"], "error_inesperado")

    def consultar(self, cliente: str) -> SaldoPresentation:
        cliente_normalizado = str(cliente or "").strip()
        if not cliente_normalizado:
            return self.empty_presentation()

        request = Request(
            capability="clientes.saldo",
            parameters={"cliente": cliente_normalizado},
            user_context=UserContext(channel="windows"),
            channel="windows",
        )
        try:
            result = self._service(request)
        except TimeoutError:
            return SaldoPresentation(
                False,
                _CONTROLLED_ERRORS["cliente_saldo_timeout"],
                "cliente_saldo_timeout",
            )
        except Exception:
            return self.unexpected_error()

        if not isinstance(result, Result):
            return SaldoPresentation(False, _CONTROLLED_ERRORS["resultado_invalido"], "resultado_invalido")
        if result.success:
            message = str(result.message or "").strip() or "Consulta completada."
            return SaldoPresentation(True, message)

        error = result.error or ErrorInfo(code="cliente_saldo_error", message="")
        code = str(error.code or "cliente_saldo_error")
        message = _CONTROLLED_ERRORS.get(code, _CONTROLLED_ERRORS["cliente_saldo_error"])
        return SaldoPresentation(False, message, code)


class AsyncSaldoCoordinator:
    """Ejecuta la consulta fuera del hilo gráfico y entrega resultados al hacer poll."""

    def __init__(self, controller: ClientesSaldoController, submitter: Submitter) -> None:
        self._controller = controller
        self._submitter = submitter
        self._lock = Lock()
        self._running = False
        self._results: Queue[SaldoPresentation] = Queue()
        self._on_busy: Callable[[bool], None] | None = None
        self._on_complete: Callable[[SaldoPresentation], None] | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    def start(
        self,
        cliente: str,
        *,
        on_busy: Callable[[bool], None],
        on_complete: Callable[[SaldoPresentation], None],
    ) -> bool:
        if not str(cliente or "").strip():
            on_complete(self._controller.empty_presentation())
            return False

        with self._lock:
            if self._running:
                return False
            self._running = True
            self._on_busy = on_busy
            self._on_complete = on_complete

        on_busy(True)
        try:
            future = self._submitter(lambda: self._controller.consultar(cliente))
            future.add_done_callback(self._capture_result)
        except Exception:
            self._results.put(self._controller.unexpected_error())
        return True

    def _capture_result(self, future: object) -> None:
        try:
            presentation = future.result()  # type: ignore[attr-defined]
            if not isinstance(presentation, SaldoPresentation):
                presentation = self._controller.unexpected_error()
        except Exception:
            presentation = self._controller.unexpected_error()
        self._results.put(presentation)

    def poll(self) -> bool:
        try:
            presentation = self._results.get_nowait()
        except Empty:
            return False

        with self._lock:
            on_busy = self._on_busy
            on_complete = self._on_complete
            self._on_busy = None
            self._on_complete = None
            self._running = False

        if on_busy is not None:
            on_busy(False)
        if on_complete is not None:
            on_complete(presentation)
        return True

