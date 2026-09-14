import unittest
from unittest.mock import patch

from helena_core.application.contracts import Request, Result
from helena_core.business.clientes.saldo import consultar_saldo_cliente


class FakeAdapter:
    def __init__(self, *, success=True, stdout="", stderr="", returncode=0):
        self.success = success
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.calls = []

    def consultar_saldo(self, cliente):
        self.calls.append(cliente)
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "command": ["fake"],
            "cwd": "test",
            "timeout": 180,
        }


class ClienteSaldoServiceTests(unittest.TestCase):
    def test_valid_client_delegates_to_adapter(self):
        adapter = FakeAdapter(stdout="Cliente: CLIENTE\nSaldo actual: $ 10,00")
        request = Request(capability="clientes.saldo", parameters={"cliente": " CLIENTE "})

        result = consultar_saldo_cliente(request, adapter=adapter)

        self.assertTrue(result.success)
        self.assertEqual(adapter.calls, ["CLIENTE"])
        self.assertIn("Saldo actual", result.message)
        self.assertEqual(result.data["cliente"], "CLIENTE")

    def test_empty_client_returns_controlled_error(self):
        result = consultar_saldo_cliente(
            Request(capability="clientes.saldo", parameters={"cliente": ""}),
            adapter=FakeAdapter(),
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "cliente_requerido")
        self.assertEqual(result.files, [])

    def test_adapter_success_is_normalized(self):
        result = consultar_saldo_cliente(
            Request(capability="clientes.saldo", parameters={"id_cliente": "123"}),
            adapter=FakeAdapter(stdout="Cliente: CLIENTE"),
        )

        self.assertTrue(result.success)
        self.assertEqual(result.message, "Cliente: CLIENTE")
        self.assertEqual(result.metadata["returncode"], 0)

    def test_adapter_not_found_is_preserved_as_message(self):
        result = consultar_saldo_cliente(
            Request(capability="clientes.saldo", parameters={"cliente": "NO EXISTE"}),
            adapter=FakeAdapter(stdout="No encontre cliente: NO EXISTE"),
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "cliente_no_encontrado")
        self.assertEqual(result.message, "No encontre cliente: NO EXISTE")

    def test_adapter_error_is_normalized(self):
        result = consultar_saldo_cliente(
            Request(capability="clientes.saldo", parameters={"cliente": "CLIENTE"}),
            adapter=FakeAdapter(success=False, stderr="fallo tecnico", returncode=1),
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "cliente_saldo_error")
        self.assertEqual(result.data["stderr"], "fallo tecnico")
        self.assertEqual(result.metadata["returncode"], 1)

    def test_result_is_channel_independent(self):
        result = consultar_saldo_cliente(
            Request(capability="clientes.saldo", parameters={"cliente": "CLIENTE"}, channel="telegram"),
            adapter=FakeAdapter(stdout="Cliente: CLIENTE"),
        )

        self.assertNotIn("telegram", result.data)
        self.assertNotIn("bot", result.metadata)
        self.assertNotIn("markdown", result.metadata)

    def test_telegram_flow_keeps_same_visible_text_with_simulated_output(self):
        import telegram_access_bot

        simulated = "prelude\nCliente: CLIENTE\nSaldo actual: $ 10,00"
        expected = ("text", telegram_access_bot.useful_output(simulated, "Cliente:"))

        with patch.object(telegram_access_bot, "ClienteSaldoPowerShellAdapter", lambda settings: object()):
            with patch.object(
                telegram_access_bot,
                "consultar_saldo_cliente",
                return_value=Result(success=True, message=simulated),
            ):
                actual = telegram_access_bot.handle_command("saldo", {"cliente": "CLIENTE", "chat_id": "1"})

        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
