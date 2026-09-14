import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from helena_core.application.contracts import ErrorInfo, Result

import telegram_access_bot


class FakeBot:
    def __init__(self):
        self.messages = []

    def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))


class EstadoPdfTelegramCompatibilityTests(unittest.TestCase):
    def success(self, path):
        return Result(success=True, data={"file_path": str(path)}, files=[str(path)], message="generado")

    def test_account_client_short_and_full_prefixes_are_cleaned(self):
        phrases = [
            "Resumen Basadella desde \u00faltimo pago",
            "Resumen de cuenta Basadella desde \u00faltimo pago",
            "Resumen de cuentas Basadella desde \u00faltimo pago",
            "Estado Basadella desde \u00faltimo pago",
            "Estado de cuenta Basadella desde \u00faltimo pago",
            "Estado de cuentas Basadella desde \u00faltimo pago",
        ]
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    telegram_access_bot.parse_command(phrase),
                    ("estado_pdf_ultimo_pago", {"cliente": "Basadella"}),
                )
                self.assertEqual(telegram_access_bot.strip_client_from_account_text(phrase), "Basadella")

    def test_range_keeps_document_and_caption(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "estado.pdf"
            pdf.write_bytes(b"%PDF")
            with patch.object(telegram_access_bot, "EstadoCuentaPdfPowerShellAdapter", lambda settings: object()):
                with patch.object(telegram_access_bot, "generar_estado_cuenta_pdf", return_value=self.success(pdf)):
                    result = telegram_access_bot.handle_command(
                        "estado_pdf",
                        {"cliente": "123", "cliente_nombre": "CLIENTE", "desde": "2026-07-01", "hasta": "2026-07-20", "chat_id": "1"},
                    )
        self.assertEqual(result, ("document", pdf, "Estado de cuenta: CLIENTE | 2026-07-01 al 2026-07-20"))

    def test_open_balance_keeps_document_and_caption(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "estado.pdf"
            pdf.write_bytes(b"%PDF")
            with patch.object(telegram_access_bot, "EstadoCuentaPdfPowerShellAdapter", lambda settings: object()):
                with patch.object(telegram_access_bot, "generar_estado_cuenta_pdf", return_value=self.success(pdf)):
                    result = telegram_access_bot.handle_command(
                        "estado_pdf_abierto", {"cliente": "123", "cliente_nombre": "CLIENTE", "chat_id": "1"}
                    )
        self.assertEqual(result, ("document", pdf, "Estado de cuenta abierto: CLIENTE"))

    def test_since_last_payment_keeps_document_and_caption(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "estado.pdf"
            pdf.write_bytes(b"%PDF")
            with patch.object(telegram_access_bot, "EstadoCuentaPdfPowerShellAdapter", lambda settings: object()):
                with patch.object(telegram_access_bot, "generar_estado_cuenta_pdf", return_value=self.success(pdf)):
                    result = telegram_access_bot.handle_command(
                        "estado_pdf_ultimo_pago", {"cliente": "123", "cliente_nombre": "CLIENTE", "chat_id": "1"}
                    )
        self.assertEqual(result, ("document", pdf, "Estado de cuenta desde el ultimo pago: CLIENTE"))

    def test_missing_pdf_keeps_text_response(self):
        failure = Result(
            success=False,
            message="salida original",
            error=ErrorInfo(code="pdf_no_generado", message="No se genero el PDF."),
        )
        with patch.object(telegram_access_bot, "EstadoCuentaPdfPowerShellAdapter", lambda settings: object()):
            with patch.object(telegram_access_bot, "generar_estado_cuenta_pdf", return_value=failure):
                result = telegram_access_bot.handle_command(
                    "estado_pdf_abierto", {"cliente": "123", "cliente_nombre": "CLIENTE", "chat_id": "1"}
                )
        self.assertEqual(result, ("text", "salida original"))

    def test_current_execution_pdf_rejection_keeps_text_response_without_document(self):
        failure = Result(
            success=False,
            message="El PDF no corresponde a la ejecucion actual.",
            error=ErrorInfo(
                code="pdf_no_corresponde_ejecucion",
                message="El PDF no corresponde a la ejecucion actual.",
            ),
        )
        with patch.object(telegram_access_bot, "EstadoCuentaPdfPowerShellAdapter", lambda settings: object()):
            with patch.object(telegram_access_bot, "generar_estado_cuenta_pdf", return_value=failure):
                result = telegram_access_bot.handle_command(
                    "estado_pdf_ultimo_pago", {"cliente": "Basadella", "chat_id": "1"}
                )
        self.assertEqual(result, ("text", "El PDF no corresponde a la ejecucion actual."))

    def test_all_field_previous_pdf_is_not_used_for_basadella_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_pdf = Path(tmp) / "factura_ALL_FKELD_SAS_2026-07-23_FTS_A_200004450.pdf"
            old_pdf.write_bytes(b"%PDF-old")
            new_pdf = Path(tmp) / "estado_basaldella_nadia_soledad_desde_ultimo_pago.pdf"
            new_pdf.write_bytes(b"%PDF-new")
            with patch.object(telegram_access_bot, "EstadoCuentaPdfPowerShellAdapter", lambda settings: object()):
                with patch.object(telegram_access_bot, "generar_estado_cuenta_pdf", return_value=self.success(new_pdf)) as service:
                    kind, params = telegram_access_bot.parse_command("Resumen Basadella desde \u00faltimo pago")
                    result = telegram_access_bot.handle_command(kind, {**params, "chat_id": "1"})
        self.assertEqual(kind, "estado_pdf_ultimo_pago")
        self.assertEqual(params["cliente"], "Basadella")
        self.assertEqual(result[0], "document")
        self.assertEqual(result[1], new_pdf)
        self.assertNotEqual(result[1], old_pdf)
        self.assertEqual(service.call_count, 1)

    def test_failed_basadella_generation_does_not_send_previous_pdf(self):
        failure = Result(
            success=False,
            message="No encontre cliente: Basadella",
            error=ErrorInfo(code="cliente_no_encontrado", message="No encontre cliente: Basadella"),
        )
        with patch.object(telegram_access_bot, "EstadoCuentaPdfPowerShellAdapter", lambda settings: object()):
            with patch.object(telegram_access_bot, "generar_estado_cuenta_pdf", return_value=failure):
                kind, params = telegram_access_bot.parse_command("Resumen Basadella desde \u00faltimo pago")
                result = telegram_access_bot.handle_command(kind, {**params, "chat_id": "1"})
        self.assertEqual(result, ("text", "No encontre cliente: Basadella"))

    def test_unauthorized_user_does_not_execute_service(self):
        bot = FakeBot()
        with patch.object(telegram_access_bot, "authorize_command", return_value=(False, "No autorizado")):
            with patch.object(telegram_access_bot, "handle_command") as handler:
                telegram_access_bot.reply_menu_result(bot, 1, ("execute", "estado_pdf_abierto", {"cliente": "CLIENTE"}))
        handler.assert_not_called()
        self.assertEqual(bot.messages, [(1, "No autorizado")])

    def test_cancel_or_menu_does_not_execute_service(self):
        service = Mock()
        with patch.object(telegram_access_bot, "generar_estado_cuenta_pdf", service):
            kind, params = telegram_access_bot.parse_command("menu")
        self.assertEqual((kind, params), ("menu_principal", {}))
        service.assert_not_called()

    def test_facturas_pdf_regression_modes_still_parse_outside_estado_pdf(self):
        by_number = telegram_access_bot.parse_command("Factura FTS A 200004450")
        latest = telegram_access_bot.parse_command("Ultima factura de ALL FIELD")
        by_period = telegram_access_bot.parse_command("Facturas PDF de ALL FIELD desde 2026-07-01 hasta 2026-07-31")
        self.assertEqual(by_number[0], "factura_pdf")
        self.assertEqual(latest[0], "facturas_ultimas_cliente_pdf")
        self.assertEqual(by_period[0], "facturas_cliente_pdf")


if __name__ == "__main__":
    unittest.main()
