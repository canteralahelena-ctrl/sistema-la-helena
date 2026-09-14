from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from helena_core.business.clientes.saldo import consultar_saldo_cliente
from helena_core.integrations.powershell.cliente_saldo_adapter import ClienteSaldoPowerShellAdapter
from helena_core.settings import AppSettings, load_settings

from .clientes_saldo import AsyncSaldoCoordinator, ClientesSaldoController


@dataclass
class WindowsRuntime:
    coordinator: AsyncSaldoCoordinator
    executor: ThreadPoolExecutor

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)


def build_windows_runtime(settings: AppSettings | None = None) -> WindowsRuntime:
    active_settings = settings or load_settings()
    local_database = active_settings.databases.local_database
    if not active_settings.environment.use_local_database_only:
        raise RuntimeError("La aplicación Windows requiere modo de base local.")
    if local_database is None or not local_database.exists() or not local_database.is_file():
        raise RuntimeError("La copia local de la base no está disponible.")

    adapter = ClienteSaldoPowerShellAdapter(settings=active_settings)

    def service(request):
        return consultar_saldo_cliente(request, adapter=adapter)

    controller = ClientesSaldoController(service)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="helena-saldo")
    coordinator = AsyncSaldoCoordinator(controller, executor.submit)
    return WindowsRuntime(coordinator=coordinator, executor=executor)

