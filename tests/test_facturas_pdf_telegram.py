import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from helena_core.application.contracts import ErrorInfo, Result

import telegram_access_bot


class FakeBot:
    def __init__(self):
        self.documents = []
        self.messages = []

    def send_document(self, chat_id, path, caption=""):
        self.documents.append((chat_id, Path(path), caption))

    def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))

    def send_action(self, chat_id, action="typing"):
        return None


class FacturasPdfTelegramCompatibilityTests(unittest.TestCase):
    def success(self, path, caption, *, found=1, total=1, missing=0):
        return Result(
            success=True,
            data={
                "file_path": str(path),
                "Caption": caption,
                "Encontrados": found,
                "TotalComprobantes": total,
                "Faltantes": missing,
            },
            files=[str(path)],
        )

    def core_patches(self, result):
        return (
            patch.object(telegram_access_bot, "refresh_access"),
            patch.object(telegram_access_bot, "FacturasPdfPowerShellAdapter", lambda settings: object()),
            patch.object(telegram_access_bot, "generar_facturas_pdf", return_value=result),
        )

    def test_by_number_keeps_caption_and_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "FTA00001_00000001.pdf"
            pdf.write_bytes(b"%PDF")
            patches = self.core_patches(self.success(pdf, "PDF encontrado: FTS A 1"))
            with patches[0], patches[1], patches[2]:
                result = telegram_access_bot.handle_command(
                    "factura_pdf", {"tipo": "FTS A", "numero": "1", "chat_id": "7"}
                )
        self.assertEqual(result, ("document", pdf, "PDF encontrado: FTS A 1"))

    def test_by_number_missing_keeps_visible_message(self):
        failure = Result(
            success=False,
            data={"Mensaje": "No encontre el PDF solicitado.", "Esperado": "2026\\FT A\\archivo.pdf"},
            error=ErrorInfo(code="archivo_no_encontrado", message="No encontrado"),
        )
        patches = self.core_patches(failure)
        with patches[0], patches[1], patches[2]:
            result = telegram_access_bot.handle_command("factura_pdf", {"tipo": "", "numero": "1"})
        self.assertEqual(
            result,
            (
                "text",
                "No encontre el PDF solicitado.\nEsperado: 2026\\FT A\\archivo.pdf"
                "\nProbe factura A/B, nota de credito y nota de debito con ese numero.",
            ),
        )

    def test_period_keeps_script_caption_and_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "facturas.zip"
            archive.write_bytes(b"PK")
            patches = self.core_patches(self.success(archive, "Facturas PDF: CLIENTE | periodo", total=2, found=2))
            with patches[0], patches[1], patches[2]:
                result = telegram_access_bot.handle_command(
                    "facturas_cliente_pdf",
                    {"cliente": "123", "desde": "2026-07-01", "hasta": "2026-07-02", "chat_id": "7"},
                )
        self.assertEqual(result, ("document", archive, "Facturas PDF: CLIENTE | periodo"))

    def test_period_with_missing_pdfs_keeps_visible_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "facturas.zip"
            archive.write_bytes(b"PK")
            patches = self.core_patches(
                self.success(archive, "Facturas PDF: CLIENTE | encontradas 0 de 1", found=0, missing=1)
            )
            with patches[0], patches[1], patches[2]:
                result = telegram_access_bot.handle_command(
                    "facturas_cliente_pdf",
                    {"cliente": "123", "desde": "2026-07-01", "hasta": "2026-07-02"},
                )
        self.assertEqual(
            result,
            (
                "text",
                "Encontre el/los comprobantes en Access, pero no encontre el PDF en la carpeta de facturas.\n"
                "Facturas PDF: CLIENTE | encontradas 0 de 1",
            ),
        )

    def test_latest_keeps_caption_and_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "factura.pdf"
            pdf.write_bytes(b"%PDF")
            patches = self.core_patches(self.success(pdf, "Factura PDF: CLIENTE | ultimas 1"))
            with patches[0], patches[1], patches[2]:
                result = telegram_access_bot.handle_command(
                    "facturas_ultimas_cliente_pdf", {"cliente": "123", "cantidad": 1, "chat_id": "7"}
                )
        self.assertEqual(result, ("document", pdf, "Factura PDF: CLIENTE | ultimas 1"))

    def test_client_without_invoices_keeps_message(self):
        failure = Result(
            success=False,
            data={"Mensaje": "No encontre facturas/notas para ese cliente y periodo."},
            error=ErrorInfo(code="sin_comprobantes", message="Sin comprobantes"),
        )
        patches = self.core_patches(failure)
        with patches[0], patches[1], patches[2]:
            result = telegram_access_bot.handle_command(
                "facturas_ultimas_cliente_pdf", {"cliente": "123", "cantidad": 1}
            )
        self.assertEqual(result, ("text", "No encontre facturas/notas para ese cliente y periodo."))

    def test_since_last_payment_uses_core_and_keeps_document_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "facturas.zip"
            archive.write_bytes(b"PK")
            core_result = self.success(archive, "Facturas PDF: CLIENTE | periodo", found=2, total=2)
            patches = self.core_patches(core_result)
            with patches[0], patches[1], patches[2] as core_service:
                with patch.object(telegram_access_bot, "run_script") as old_runner:
                    result = telegram_access_bot.handle_command(
                        "facturas_cliente_pdf",
                        {
                            "cliente": "123",
                            "desde": telegram_access_bot.DESDE_ULTIMO_PAGO,
                            "hasta": "2026-07-20",
                        },
                    )
        old_runner.assert_not_called()
        request = core_service.call_args.args[0]
        self.assertEqual(request.parameters["modo"], telegram_access_bot.FACTURAS_MODE_SINCE_LAST_PAYMENT)
        self.assertEqual(request.parameters["hasta"], "2026-07-20")
        self.assertEqual(result, ("document", archive, "Facturas PDF: CLIENTE | periodo"))

    def test_since_last_payment_keeps_legacy_resolution_messages(self):
        expected = {
            "ultimo_pago_no_encontrado": "No encontré un último pago para ese cliente.",
            "cliente_no_encontrado": "No encontré el cliente indicado.",
            "cliente_ambiguo": "Encontré varios clientes parecidos. Indicá el cliente con más detalle.",
        }
        for code, message in expected.items():
            with self.subTest(code=code):
                failure = Result(success=False, error=ErrorInfo(code=code, message="interno"))
                patches = self.core_patches(failure)
                with patches[0], patches[1], patches[2]:
                    result = telegram_access_bot.handle_command(
                        "facturas_cliente_pdf",
                        {"cliente": "123", "desde": telegram_access_bot.DESDE_ULTIMO_PAGO},
                    )
                self.assertEqual(result, ("text", message))

    def test_ambiguous_client_is_resolved_before_service(self):
        choices = [{"IdCLIENTE": 1, "RazonSocial": "CLIENTE A"}, {"IdCLIENTE": 2, "RazonSocial": "CLIENTE B"}]
        with patch.object(telegram_access_bot, "resolve_client", return_value=("choices", choices)):
            prepared = telegram_access_bot.prepare_client_query(
                7, "facturas_ultimas_cliente_pdf", {"cliente": "CLIENTE", "cantidad": 1}
            )
        self.assertEqual(prepared[0], "choices")
        self.assertIn(7, telegram_access_bot.PENDING_SELECTIONS)
        telegram_access_bot.PENDING_SELECTIONS.pop(7, None)

    def test_invoice_menu_defers_numeric_reply_to_pending_client_selection(self):
        choices = [{"IdCLIENTE": 1, "RazonSocial": "CLIENTE A"}, {"IdCLIENTE": 2, "RazonSocial": "CLIENTE B"}]
        telegram_access_bot.MENU_STATES[7] = {
            "pantalla": "clientes_facturas_pdf_esperando_consulta",
            "anterior": "menu_clientes",
        }
        telegram_access_bot.PENDING_SELECTIONS[7] = {
            "kind": "facturas_ultimas_cliente_pdf",
            "params": {"cliente": "CLIENTE", "cantidad": 1, "chat_id": 7},
            "choices": choices,
            "created": time.time(),
        }
        try:
            self.assertIsNone(telegram_access_bot.consume_menu_navigation(7, "2"))
            selection = telegram_access_bot.consume_client_selection(7, "2")
            self.assertEqual(selection[0], "ready")
            self.assertEqual(selection[1], "facturas_ultimas_cliente_pdf")
            self.assertEqual(selection[2]["cliente"], "2")
            self.assertEqual(selection[2]["cliente_nombre"], "CLIENTE B")
            bot = FakeBot()
            document = Path("factura_cliente_b.pdf")
            with patch.object(telegram_access_bot, "CONFIG", {"max_text_chars": 3500}, create=True):
                with patch.object(
                    telegram_access_bot,
                    "handle_command",
                    return_value=("document", document, "Factura PDF: CLIENTE B"),
                ) as handler:
                    result = telegram_access_bot.handle_command(selection[1], selection[2])
                    telegram_access_bot.reply_result(bot, 7, result)
            handler.assert_called_once_with("facturas_ultimas_cliente_pdf", selection[2])
            self.assertEqual(bot.documents, [(7, document, "Factura PDF: CLIENTE B")])
        finally:
            telegram_access_bot.PENDING_SELECTIONS.pop(7, None)
            telegram_access_bot.MENU_STATES.pop(7, None)

    def test_invalid_invoice_client_selection_stays_pending(self):
        telegram_access_bot.MENU_STATES[7] = {
            "pantalla": "clientes_facturas_pdf_esperando_consulta",
            "anterior": "menu_clientes",
        }
        telegram_access_bot.PENDING_SELECTIONS[7] = {
            "kind": "facturas_ultimas_cliente_pdf",
            "params": {"cliente": "CLIENTE", "cantidad": 1, "chat_id": 7},
            "choices": [{"IdCLIENTE": 1, "RazonSocial": "CLIENTE A"}],
            "created": time.time(),
        }
        try:
            self.assertIsNone(telegram_access_bot.consume_menu_navigation(7, "2"))
            selection = telegram_access_bot.consume_client_selection(7, "2")
            self.assertEqual(selection, ("error", "Elegi un numero entre 1 y 1."))
            self.assertIn(7, telegram_access_bot.PENDING_SELECTIONS)
        finally:
            telegram_access_bot.PENDING_SELECTIONS.pop(7, None)
            telegram_access_bot.MENU_STATES.pop(7, None)

    def test_unauthorized_user_does_not_execute_service(self):
        bot = FakeBot()
        with patch.object(telegram_access_bot, "authorize_command", return_value=(False, "No autorizado")):
            with patch.object(telegram_access_bot, "generar_facturas_pdf") as service:
                telegram_access_bot.reply_menu_result(
                    bot,
                    7,
                    ("execute", "facturas_ultimas_cliente_pdf", {"cliente": "CLIENTE", "cantidad": 1}),
                )
        service.assert_not_called()
        self.assertEqual(bot.messages, [(7, "No autorizado")])

    def test_authorized_menu_executes_existing_dispatch(self):
        bot = FakeBot()
        expected = ("text", "Sin facturas")
        with patch.object(telegram_access_bot, "CONFIG", {"max_text_chars": 3500}, create=True):
            with patch.object(telegram_access_bot, "authorize_command", return_value=(True, "")):
                with patch.object(
                    telegram_access_bot,
                    "prepare_client_query",
                    return_value=("ready", "facturas_ultimas_cliente_pdf", {"cliente": "123", "cantidad": 1}),
                ):
                    with patch.object(telegram_access_bot, "auditar_consulta"):
                        with patch.object(telegram_access_bot, "handle_command", return_value=expected) as handler:
                            telegram_access_bot.reply_menu_result(
                                bot,
                                7,
                                ("execute", "facturas_ultimas_cliente_pdf", {"cliente": "CLIENTE", "cantidad": 1}),
                            )
        handler.assert_called_once()
        self.assertEqual(bot.messages, [(7, "Sin facturas")])

    def test_cancel_does_not_execute_service(self):
        with patch.object(telegram_access_bot, "generar_facturas_pdf") as service:
            reply = telegram_access_bot.consume_global_navigation(7, "cancelar")
        self.assertEqual(reply, "Operación cancelada.")
        service.assert_not_called()

    def test_reply_result_still_sends_document(self):
        bot = FakeBot()
        path = Path("factura.pdf")
        with patch.object(telegram_access_bot, "CONFIG", {"max_text_chars": 3500}, create=True):
            telegram_access_bot.reply_result(bot, 7, ("document", path, "Factura PDF"))
        self.assertEqual(bot.documents, [(7, path, "Factura PDF")])


if __name__ == "__main__":
    unittest.main()
