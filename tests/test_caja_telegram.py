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


class CajaTelegramCompatibilityTests(unittest.TestCase):
    def core_result(self):
        return Result(
            success=True,
            data={
                "fecha_desde": "2026-07-01",
                "fecha_hasta_exclusiva": "2026-07-03",
                "periodo_desde": "01/07/2026",
                "periodo_hasta": "02/07/2026",
                "medio": "todos",
                "medio_mostrado": "TODOS",
                "cantidad_registros": 3,
                "total": "$ 1.000,00",
                "medios_de_pago": [],
                "texto_legacy": (
                    "Cobros por medio: TODOS\nPeriodo: 01/07/2026 al 02/07/2026\n"
                    "Registros: 3\nTotal: $ 1.000,00"
                ),
            },
        )

    def test_handler_uses_core_once_and_preserves_exact_visible_text(self):
        with patch.object(telegram_access_bot, "CajaPowerShellAdapter", return_value=object()):
            with patch.object(
                telegram_access_bot, "consultar_cobros", return_value=self.core_result()
            ) as service:
                with patch.object(telegram_access_bot, "run_ps") as direct_runner:
                    result = telegram_access_bot.handle_command(
                        "cobros",
                        {
                            "medio": "todos",
                            "desde": "2026-07-01",
                            "hasta": "2026-07-03",
                            "chat_id": 7,
                        },
                    )
        service.assert_called_once()
        direct_runner.assert_not_called()
        request = service.call_args.args[0]
        self.assertEqual(request.capability, "caja.cobros")
        self.assertEqual(
            request.parameters,
            {
                "medio": "todos",
                "fecha_desde": "2026-07-01",
                "fecha_hasta": "2026-07-03",
            },
        )
        self.assertEqual(request.user_context.channel_user_id, "7")
        self.assertEqual(result, ("text", self.core_result().data["texto_legacy"]))

    def test_core_error_keeps_existing_error_path(self):
        failure = Result(
            success=False,
            message="fallo controlado",
            error=ErrorInfo(code="caja_cobros_error", message="fallo controlado"),
        )
        with patch.object(telegram_access_bot, "CajaPowerShellAdapter", return_value=object()):
            with patch.object(telegram_access_bot, "consultar_cobros", return_value=failure):
                with self.assertRaisesRegex(RuntimeError, "fallo controlado"):
                    telegram_access_bot.handle_command(
                        "cobros",
                        {"medio": "todos", "desde": "2026-07-01", "hasta": "2026-07-03"},
                    )

    def test_menu_periods_today_yesterday_month_and_custom_range_are_unchanged(self):
        today = date.today()
        cases = (
            ("caja de hoy", today, today),
            ("caja de ayer", today - timedelta(days=1), today - timedelta(days=1)),
            (
                "caja del mes",
                date(today.year, today.month, 1),
                date(today.year, today.month, calendar.monthrange(today.year, today.month)[1]),
            ),
            ("caja desde 01/06/2026 hasta 20/06/2026", date(2026, 6, 1), date(2026, 6, 20)),
        )
        chat_id = 702
        for text, expected_from, expected_inclusive in cases:
            with self.subTest(text=text):
                telegram_access_bot.MENU_STATES[chat_id] = {
                    "pantalla": "consultas_caja_esperando_consulta",
                    "anterior": "menu_consultas_rapidas",
                }
                with patch.object(telegram_access_bot, "log_event"):
                    result = telegram_access_bot.consume_menu_navigation(chat_id, text)
                self.assertEqual(result[0:2], ("execute", "cobros"))
                self.assertEqual(result[2]["desde"], expected_from.isoformat())
                self.assertEqual(
                    result[2]["hasta"],
                    (expected_inclusive + timedelta(days=1)).isoformat(),
                )
        telegram_access_bot.MENU_STATES.pop(chat_id, None)

    def test_direct_command_keeps_payment_medium_and_exclusive_period(self):
        kind, params = telegram_access_bot.parse_command("se cobró por retención hoy")
        self.assertEqual(kind, "cobros")
        self.assertEqual(params["medio"], "retencion")
        self.assertEqual(params["desde"], date.today().isoformat())
        self.assertEqual(params["hasta"], (date.today() + timedelta(days=1)).isoformat())
        empty_kind, empty_params = telegram_access_bot.parse_command("/cobros")
        self.assertEqual(empty_kind, "cobros")
        self.assertEqual(empty_params["medio"], "todos")
        self.assertEqual(empty_params["desde"], date.today().isoformat())
        self.assertEqual(empty_params["hasta"], (date.today() + timedelta(days=1)).isoformat())

    def test_repeat_back_navigation_and_permissions_are_unchanged(self):
        chat_id = 703
        telegram_access_bot.MENU_STATES[chat_id] = {
            "pantalla": "consultas_caja_esperando_consulta",
            "anterior": "menu_consultas_rapidas",
        }
        with patch.object(telegram_access_bot, "log_event"):
            first = telegram_access_bot.consume_menu_navigation(chat_id, "caja de hoy")
            second = telegram_access_bot.consume_menu_navigation(chat_id, "caja de ayer")
        self.assertEqual(first[0:2], ("execute", "cobros"))
        self.assertEqual(second[0:2], ("execute", "cobros"))
        self.assertEqual(
            telegram_access_bot.MENU_STATES[chat_id]["pantalla"],
            "consultas_caja_esperando_consulta",
        )
        with patch.object(telegram_access_bot, "log_event"):
            with patch.object(telegram_access_bot, "render_menu_consultas_rapidas", return_value="Menú"):
                back = telegram_access_bot.consume_menu_navigation(chat_id, "volver")
        self.assertEqual(back, "Menú")
        self.assertEqual(telegram_access_bot.COMMAND_PERMISSIONS["cobros"], "caja")
        telegram_access_bot.MENU_STATES.pop(chat_id, None)

    def test_unauthorized_user_does_not_execute_core(self):
        bot = FakeBot()
        with patch.object(telegram_access_bot, "authorize_command", return_value=(False, "No autorizado")):
            with patch.object(telegram_access_bot, "registrar_actividad"):
                with patch.object(telegram_access_bot, "consultar_cobros") as service:
                    telegram_access_bot.reply_menu_result(
                        bot,
                        7,
                        ("execute", "cobros", {"medio": "todos", "desde": "2026-07-01", "hasta": "2026-07-03"}),
                    )
        service.assert_not_called()
        self.assertEqual(bot.messages, [(7, "No autorizado")])


if __name__ == "__main__":
    unittest.main()
