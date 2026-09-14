import calendar
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from helena_core.application.contracts import ErrorInfo, Result

import telegram_access_bot


class FakeBot:
    def __init__(self):
        self.messages = []

    def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))


class VentasRapidasTelegramCompatibilityTests(unittest.TestCase):
    def core_result(self):
        return Result(
            success=True,
            data={
                "estado": "OK",
                "fecha_desde": "2026-07-01",
                "fecha_hasta": "2026-07-20",
                "periodo_desde": "01/07/2026",
                "periodo_hasta": "20/07/2026",
                "total": "$ 1.000,00",
                "facturado": "$ 800,00",
                "remitos": "$ 200,00",
                "clasificado": "$ 900,00",
                "no_clasificado": "$ 100,00",
                "categorias": [
                    {"codigo": "ARIDOS", "importe": "$ 600,00", "porcentaje": "60,00%"},
                    {"codigo": "GRAVAS", "importe": "$ 200,00", "porcentaje": "20,00%"},
                ],
            },
        )

    def test_handler_uses_core_once_and_keeps_exact_visible_text(self):
        with patch.object(telegram_access_bot, "refresh_access") as refresh:
            with patch.object(telegram_access_bot, "VentasRapidasPowerShellAdapter", return_value=object()):
                with patch.object(
                    telegram_access_bot, "consultar_ventas_rapidas", return_value=self.core_result()
                ) as service:
                    with patch.object(telegram_access_bot, "run_script") as direct_runner:
                        result = telegram_access_bot.handle_command(
                            "ventas_rapidas",
                            {"desde": "2026-07-01", "hasta": "2026-07-20", "chat_id": 7},
                        )
        refresh.assert_called_once()
        service.assert_called_once()
        direct_runner.assert_not_called()
        request = service.call_args.args[0]
        self.assertEqual(request.capability, "ventas.rapidas")
        self.assertEqual(
            request.parameters,
            {"fecha_desde": "2026-07-01", "fecha_hasta": "2026-07-20"},
        )
        self.assertEqual(request.user_context.channel_user_id, "7")
        self.assertEqual(
            result,
            (
                "text",
                "📊 Ventas rápidas\n\nPeríodo:\n01/07/2026 a 20/07/2026\n\n"
                "Total:\n$ 1.000,00\n\nFacturado:\n$ 800,00\n\nRemitos:\n$ 200,00\n\n"
                "Categorías:\n\nÁridos:\n$ 600,00 - 60,00%\n\nGravas:\n$ 200,00 - 20,00%\n\n"
                "Clasificado: $ 900,00\nNo clasificado: $ 100,00",
            ),
        )

    def test_core_error_keeps_existing_command_error_path(self):
        failure = Result(
            success=False,
            message="fallo controlado",
            error=ErrorInfo(code="ventas_rapidas_error", message="fallo controlado"),
        )
        with patch.object(telegram_access_bot, "refresh_access"):
            with patch.object(telegram_access_bot, "VentasRapidasPowerShellAdapter", return_value=object()):
                with patch.object(telegram_access_bot, "consultar_ventas_rapidas", return_value=failure):
                    with self.assertRaisesRegex(RuntimeError, "fallo controlado"):
                        telegram_access_bot.handle_command(
                            "ventas_rapidas", {"desde": "2026-07-01", "hasta": "2026-07-20"}
                        )

    def test_period_interpretation_is_unchanged(self):
        today = date.today()
        self.assertEqual(
            telegram_access_bot.parse_quick_report_period("ventas de ayer"),
            ((today - timedelta(days=1)).isoformat(), (today - timedelta(days=1)).isoformat()),
        )
        self.assertEqual(
            telegram_access_bot.parse_quick_report_period("ventas de hoy"),
            (today.isoformat(), today.isoformat()),
        )
        self.assertEqual(
            telegram_access_bot.parse_quick_report_period("ventas del mes"),
            (
                date(today.year, today.month, 1).isoformat(),
                date(today.year, today.month, calendar.monthrange(today.year, today.month)[1]).isoformat(),
            ),
        )
        self.assertEqual(
            telegram_access_bot.parse_quick_report_period(
                "ventas desde 01/06/2026 hasta 20/06/2026"
            ),
            ("2026-06-01", "2026-06-20"),
        )

    def test_menu_state_supports_repeat_and_back_navigation(self):
        chat_id = 701
        telegram_access_bot.MENU_STATES[chat_id] = {
            "pantalla": "consultas_ventas_esperando_consulta",
            "anterior": "menu_consultas_rapidas",
        }
        with patch.object(telegram_access_bot, "log_event"):
            first = telegram_access_bot.consume_menu_navigation(chat_id, "ventas de hoy")
            second = telegram_access_bot.consume_menu_navigation(chat_id, "ventas de ayer")
        self.assertEqual(first[0:2], ("execute", "ventas_rapidas"))
        self.assertEqual(second[0:2], ("execute", "ventas_rapidas"))
        self.assertEqual(
            telegram_access_bot.MENU_STATES[chat_id]["pantalla"],
            "consultas_ventas_esperando_consulta",
        )
        with patch.object(telegram_access_bot, "log_event"):
            with patch.object(telegram_access_bot, "render_menu_consultas_rapidas", return_value="Menú consultas"):
                back = telegram_access_bot.consume_menu_navigation(chat_id, "volver")
        self.assertIsInstance(back, str)
        self.assertEqual(
            telegram_access_bot.MENU_STATES[chat_id]["pantalla"],
            "menu_consultas_rapidas",
        )
        telegram_access_bot.MENU_STATES.pop(chat_id, None)

    def test_unauthorized_user_does_not_execute_service(self):
        bot = FakeBot()
        with patch.object(telegram_access_bot, "authorize_command", return_value=(False, "No autorizado")):
            with patch.object(telegram_access_bot, "registrar_actividad"):
                with patch.object(telegram_access_bot, "consultar_ventas_rapidas") as service:
                    telegram_access_bot.reply_menu_result(
                        bot,
                        7,
                        ("execute", "ventas_rapidas", {"desde": "2026-07-01", "hasta": "2026-07-20"}),
                    )
        service.assert_not_called()
        self.assertEqual(bot.messages, [(7, "No autorizado")])

    def test_products_not_classified_uses_its_own_core_capability(self):
        with patch.object(telegram_access_bot, "refresh_access"):
            with patch.object(telegram_access_bot, "VentasRapidasPowerShellAdapter", return_value=object()):
                with patch.object(
                    telegram_access_bot,
                    "consultar_productos_no_clasificados",
                    return_value=Result(
                        success=True,
                        data={
                            "fecha_desde": "2026-07-01",
                            "fecha_hasta": "2026-07-20",
                            "cantidad_total": 0,
                            "importe_total": "0",
                            "grupos": [],
                        },
                    ),
                ) as products_service:
                    with patch.object(telegram_access_bot, "consultar_ventas_rapidas") as quick_service:
                        telegram_access_bot.handle_command(
                            "productos_no_clasificados",
                            {"desde": "2026-07-01", "hasta": "2026-07-20"},
                        )
        products_service.assert_called_once()
        quick_service.assert_not_called()


if __name__ == "__main__":
    unittest.main()
