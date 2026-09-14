import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from helena_core.application.contracts import ErrorInfo, Result
from helena_windows.clientes_saldo import (
    AsyncSaldoCoordinator,
    ClientesSaldoController,
    SaldoPresentation,
)


class RecordingService:
    def __init__(self, result=None, raises=None):
        self.result = result
        self.raises = raises
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        if self.raises is not None:
            raise self.raises
        return self.result


class DeferredFuture:
    def __init__(self, function):
        self.function = function
        self.callbacks = []
        self.value = None
        self.error = None

    def add_done_callback(self, callback):
        self.callbacks.append(callback)

    def run(self):
        try:
            self.value = self.function()
        except Exception as exc:
            self.error = exc
        for callback in self.callbacks:
            callback(self)

    def result(self):
        if self.error is not None:
            raise self.error
        return self.value


class DeferredSubmitter:
    def __init__(self, raises=None):
        self.raises = raises
        self.futures = []

    def __call__(self, function):
        if self.raises is not None:
            raise self.raises
        future = DeferredFuture(function)
        self.futures.append(future)
        return future


class ClientesSaldoControllerTests(unittest.TestCase):
    def test_empty_input_is_controlled_without_calling_service(self):
        service = RecordingService(Result(success=True, message="unused"))
        presentation = ClientesSaldoController(service).consultar("   ")
        self.assertFalse(presentation.success)
        self.assertEqual(presentation.error_code, "cliente_requerido")
        self.assertEqual(service.requests, [])

    def test_valid_input_builds_saldo_request(self):
        service = RecordingService(Result(success=True, message="Saldo actual: $ 10,00"))
        ClientesSaldoController(service).consultar("  CLIENTE  ")
        request = service.requests[0]
        self.assertEqual(request.capability, "clientes.saldo")
        self.assertEqual(request.parameters, {"cliente": "CLIENTE"})

    def test_request_identifies_windows_channel(self):
        service = RecordingService(Result(success=True, message="ok"))
        ClientesSaldoController(service).consultar("123")
        request = service.requests[0]
        self.assertEqual(request.channel, "windows")
        self.assertEqual(request.user_context.channel, "windows")
        self.assertEqual(request.user_context.channel_user_id, "")

    def test_success_preserves_core_visible_message(self):
        message = "Cliente: CLIENTE\nSaldo actual: $ 10,00"
        presentation = ClientesSaldoController(RecordingService(Result(success=True, message=message))).consultar(
            "CLIENTE"
        )
        self.assertTrue(presentation.success)
        self.assertEqual(presentation.message, message)

    def test_success_without_message_has_controlled_fallback(self):
        presentation = ClientesSaldoController(RecordingService(Result(success=True))).consultar("123")
        self.assertEqual(presentation.message, "Consulta completada.")

    def test_nonexistent_client_is_controlled(self):
        result = Result(
            success=False,
            message="raw",
            error=ErrorInfo(code="cliente_no_encontrado", message="raw"),
        )
        presentation = ClientesSaldoController(RecordingService(result)).consultar("NO EXISTE")
        self.assertEqual(presentation.error_code, "cliente_no_encontrado")
        self.assertIn("No se encontró", presentation.message)
        self.assertNotIn("raw", presentation.message)

    def test_ambiguous_client_is_controlled_without_telegram_choices(self):
        result = Result(
            success=False,
            error=ErrorInfo(code="cliente_ambiguo", message="detalle técnico"),
        )
        presentation = ClientesSaldoController(RecordingService(result)).consultar("CLIENTE")
        self.assertEqual(presentation.error_code, "cliente_ambiguo")
        self.assertIn("varios clientes", presentation.message)
        self.assertNotIn("detalle técnico", presentation.message)

    def test_service_error_hides_technical_detail(self):
        result = Result(
            success=False,
            message="C:\\secret\\script.ps1: line 10",
            error=ErrorInfo(
                code="cliente_saldo_error",
                message="fallo",
                technical_detail="stack trace secreto",
            ),
        )
        presentation = ClientesSaldoController(RecordingService(result)).consultar("CLIENTE")
        self.assertEqual(presentation.message, "No se pudo consultar el saldo. Intentá nuevamente.")
        self.assertNotIn("secret", presentation.message)

    def test_timeout_is_controlled(self):
        presentation = ClientesSaldoController(RecordingService(raises=TimeoutError())).consultar("CLIENTE")
        self.assertEqual(presentation.error_code, "cliente_saldo_timeout")
        self.assertIn("demoró demasiado", presentation.message)

    def test_unexpected_exception_is_controlled(self):
        presentation = ClientesSaldoController(RecordingService(raises=RuntimeError("trace"))).consultar("CLIENTE")
        self.assertEqual(presentation.error_code, "error_inesperado")
        self.assertNotIn("trace", presentation.message)

    def test_invalid_service_result_is_controlled(self):
        presentation = ClientesSaldoController(RecordingService({"success": True})).consultar("CLIENTE")
        self.assertEqual(presentation.error_code, "resultado_invalido")

    def test_controller_does_not_import_telegram(self):
        module = sys.modules[ClientesSaldoController.__module__]
        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("telegram_access_bot", source)
        self.assertNotIn("import telegram", source)

    def test_controller_does_not_invoke_powershell_directly(self):
        module = sys.modules[ClientesSaldoController.__module__]
        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("subprocess", source)
        self.assertNotIn("cliente_rapido.ps1", source)


class AsyncSaldoCoordinatorTests(unittest.TestCase):
    def make_coordinator(self, submitter=None):
        service = RecordingService(Result(success=True, message="Saldo actual: $ 10,00"))
        selected_submitter = submitter or DeferredSubmitter()
        return AsyncSaldoCoordinator(ClientesSaldoController(service), selected_submitter), selected_submitter

    def test_start_disables_query_while_work_is_pending(self):
        coordinator, submitter = self.make_coordinator()
        busy = []
        accepted = coordinator.start("CLIENTE", on_busy=busy.append, on_complete=Mock())
        self.assertTrue(accepted)
        self.assertEqual(busy, [True])
        self.assertTrue(coordinator.running)
        self.assertEqual(len(submitter.futures), 1)

    def test_duplicate_query_is_rejected(self):
        coordinator, submitter = self.make_coordinator()
        coordinator.start("CLIENTE", on_busy=Mock(), on_complete=Mock())
        accepted = coordinator.start("OTRO", on_busy=Mock(), on_complete=Mock())
        self.assertFalse(accepted)
        self.assertEqual(len(submitter.futures), 1)

    def test_worker_completion_does_not_touch_ui_until_main_thread_poll(self):
        coordinator, submitter = self.make_coordinator()
        busy = []
        completed = []
        coordinator.start("CLIENTE", on_busy=busy.append, on_complete=completed.append)
        submitter.futures[0].run()
        self.assertEqual(busy, [True])
        self.assertEqual(completed, [])
        self.assertTrue(coordinator.running)

    def test_poll_reenables_button_and_presents_result(self):
        coordinator, submitter = self.make_coordinator()
        busy = []
        completed = []
        coordinator.start("CLIENTE", on_busy=busy.append, on_complete=completed.append)
        submitter.futures[0].run()
        self.assertTrue(coordinator.poll())
        self.assertEqual(busy, [True, False])
        self.assertEqual(completed[0].message, "Saldo actual: $ 10,00")
        self.assertFalse(coordinator.running)

    def test_poll_without_result_does_nothing(self):
        coordinator, _submitter = self.make_coordinator()
        self.assertFalse(coordinator.poll())

    def test_empty_input_does_not_start_background_work(self):
        coordinator, submitter = self.make_coordinator()
        completed = []
        accepted = coordinator.start("", on_busy=Mock(), on_complete=completed.append)
        self.assertFalse(accepted)
        self.assertEqual(submitter.futures, [])
        self.assertEqual(completed[0].error_code, "cliente_requerido")

    def test_submit_failure_is_presented_after_poll(self):
        coordinator, _submitter = self.make_coordinator(DeferredSubmitter(raises=RuntimeError("pool")))
        busy = []
        completed = []
        coordinator.start("CLIENTE", on_busy=busy.append, on_complete=completed.append)
        coordinator.poll()
        self.assertEqual(busy, [True, False])
        self.assertEqual(completed[0].error_code, "error_inesperado")

    def test_worker_failure_is_presented_after_poll(self):
        controller = ClientesSaldoController(RecordingService(raises=RuntimeError("worker")))
        submitter = DeferredSubmitter()
        coordinator = AsyncSaldoCoordinator(controller, submitter)
        completed = []
        coordinator.start("CLIENTE", on_busy=Mock(), on_complete=completed.append)
        submitter.futures[0].run()
        coordinator.poll()
        self.assertEqual(completed[0].error_code, "error_inesperado")


class FakeWidget:
    def __init__(self, value=""):
        self.value = value
        self.options = {}
        self.focused = False

    def configure(self, **kwargs):
        self.options.update(kwargs)

    def delete(self, *_args):
        self.value = ""

    def insert(self, _index, value):
        self.value = value

    def focus_set(self):
        self.focused = True


class HelenaWindowsViewLogicTests(unittest.TestCase):
    def make_app_without_window(self):
        from helena_windows.app import HelenaWindowsApp

        app = HelenaWindowsApp.__new__(HelenaWindowsApp)
        app.query_button = FakeWidget()
        app.status_label = FakeWidget()
        app.result_text = FakeWidget()
        app.client_entry = FakeWidget("CLIENTE")
        app.coordinator = Mock(running=False)
        return app

    def test_busy_state_disables_and_reenables_query_button(self):
        app = self.make_app_without_window()
        app._set_busy(True)
        self.assertEqual(app.query_button.options["state"], "disabled")
        self.assertEqual(app.status_label.options["text"], "Consultando…")
        app._set_busy(False)
        self.assertEqual(app.query_button.options["state"], "normal")
        self.assertEqual(app.status_label.options["text"], "")

    def test_success_presentation_is_shown_without_prefix(self):
        app = self.make_app_without_window()
        app._show_presentation(SaldoPresentation(True, "Saldo actual: $ 10,00"))
        self.assertEqual(app.result_text.value, "Saldo actual: $ 10,00")
        self.assertEqual(app.result_text.options["state"], "disabled")

    def test_error_presentation_has_friendly_prefix(self):
        app = self.make_app_without_window()
        app._show_presentation(SaldoPresentation(False, "No se encontró el cliente."))
        self.assertTrue(app.result_text.value.startswith("No se pudo completar la consulta."))

    def test_clear_resets_input_result_and_focus(self):
        app = self.make_app_without_window()
        app.result_text.value = "resultado"
        app._clear()
        self.assertEqual(app.client_entry.value, "")
        self.assertEqual(app.result_text.value, "")
        self.assertTrue(app.client_entry.focused)

    def test_importing_app_does_not_create_tk_window(self):
        import helena_windows.app as app_module

        self.assertTrue(callable(app_module.main))
        self.assertFalse(hasattr(app_module, "root"))


class WindowsCompositionTests(unittest.TestCase):
    def test_composition_uses_existing_core_service_and_adapter(self):
        from helena_windows import composition

        database = Mock()
        database.exists.return_value = True
        database.is_file.return_value = True
        settings = Mock()
        settings.environment.use_local_database_only = True
        settings.databases.local_database = database
        adapter = Mock()
        core_result = Result(success=True, message="ok")
        with patch.object(composition, "ClienteSaldoPowerShellAdapter", return_value=adapter) as adapter_type:
            with patch.object(composition, "consultar_saldo_cliente", return_value=core_result) as service:
                runtime = composition.build_windows_runtime(settings)
                try:
                    presentation = runtime.coordinator._controller.consultar("123")
                finally:
                    runtime.close()
        adapter_type.assert_called_once_with(settings=settings)
        service.assert_called_once()
        self.assertTrue(presentation.success)

    def test_composition_rejects_missing_local_database(self):
        from helena_windows.composition import build_windows_runtime

        settings = Mock()
        settings.environment.use_local_database_only = True
        settings.databases.local_database = None
        with self.assertRaisesRegex(RuntimeError, "copia local"):
            build_windows_runtime(settings)

    def test_composition_rejects_non_local_mode(self):
        from helena_windows.composition import build_windows_runtime

        settings = Mock()
        settings.environment.use_local_database_only = False
        settings.databases.local_database = Mock()
        with self.assertRaisesRegex(RuntimeError, "base local"):
            build_windows_runtime(settings)


if __name__ == "__main__":
    unittest.main()

