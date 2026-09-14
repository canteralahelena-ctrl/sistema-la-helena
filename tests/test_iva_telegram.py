import unittest
from datetime import date
from unittest.mock import patch

from helena_core.application.contracts import ErrorInfo, Result

import telegram_access_bot


class FakeBot:
    def __init__(self):
        self.messages = []

    def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))

    def send_action(self, chat_id, action):
        pass


class IvaTelegramCompatibilityTests(unittest.TestCase):
    def core_data(self):
        return {
            "periodo": "2026-07",
            "iva_ventas": "$ 1.000,00",
            "iva_gastos": "$ 400,00",
            "saldo_iva": "$ 600,00",
            "ventas_comprobantes": 10,
            "gastos_comprobantes": 4,
            "detalle_csv": "detalle.csv",
            "resumen": "resumen.txt",
        }

    def core_result(self):
        return Result(success=True, data=self.core_data())

    def test_handler_uses_core_and_preserves_exact_visible_text(self):
        with patch.object(telegram_access_bot, "IvaPowerShellAdapter", return_value=object()):
            with patch.object(
                telegram_access_bot, "consultar_iva_mensual", return_value=self.core_result()
            ) as service:
                with patch.object(telegram_access_bot, "run_ps") as direct_runner:
                    result = telegram_access_bot.handle_command(
                        "iva_mensual", {"anio": 2026, "mes": 7, "chat_id": 7}
                    )
        direct_runner.assert_not_called()
        service.assert_called_once()
        request = service.call_args.args[0]
        self.assertEqual(request.capability, "iva.mensual")
        self.assertEqual(request.parameters, {"anio": 2026, "mes": 7})
        self.assertEqual(request.user_context.channel_user_id, "7")
        self.assertEqual(
            result,
            (
                "text",
                "🧾 IVA estimado\n\nPeríodo: Julio 2026\n\n"
                "IVA ventas: $ 1.000,00\nIVA gastos: $ 400,00\nSaldo IVA: $ 600,00",
            ),
        )

    def test_core_error_keeps_existing_error_path(self):
        failure = Result(
            success=False,
            message="fallo controlado",
            error=ErrorInfo(code="iva_mensual_error", message="fallo controlado"),
        )
        with patch.object(telegram_access_bot, "IvaPowerShellAdapter", return_value=object()):
            with patch.object(telegram_access_bot, "consultar_iva_mensual", return_value=failure):
                with self.assertRaisesRegex(RuntimeError, "fallo controlado"):
                    telegram_access_bot.handle_command("iva_mensual", {"anio": 2026, "mes": 7})

    def test_dashboard_uses_core_with_original_timeout(self):
        with patch.object(telegram_access_bot, "execute_iva_core", return_value=self.core_data()) as core:
            with patch.object(telegram_access_bot, "run_ps") as direct_runner:
                result = telegram_access_bot.dashboard_iva_values()
        direct_runner.assert_not_called()
        core.assert_called_once_with(
            date.today().year,
            date.today().month,
            timeout_seconds=telegram_access_bot.SETTINGS.timeouts.default_script_seconds,
        )
        self.assertEqual(
            result,
            {"ventas": "$ 1.000,00", "gastos": "$ 400,00", "saldo": "$ 600,00"},
        )

    def test_monthly_alert_uses_core_once_and_preserves_message(self):
        bot = FakeBot()
        with patch.object(
            telegram_access_bot,
            "CONFIG",
            {"iva_alerts": {"enabled": True, "hour": 0}},
            create=True,
        ):
            with patch.object(
                telegram_access_bot,
                "first_business_day_last_week",
                return_value=date.today(),
            ):
                with patch.object(telegram_access_bot, "read_iva_alert_state", return_value={}):
                    with patch.object(telegram_access_bot, "write_iva_alert_state"):
                        with patch.object(telegram_access_bot, "admin_chat_ids", return_value=[7]):
                            with patch.object(
                                telegram_access_bot,
                                "execute_iva_core",
                                return_value=self.core_data(),
                            ) as core:
                                with patch.object(telegram_access_bot, "run_ps") as direct_runner:
                                    telegram_access_bot.maybe_send_iva_monthly_alert(bot)
        direct_runner.assert_not_called()
        core.assert_called_once_with(date.today().year, date.today().month)
        self.assertEqual(len(bot.messages), 1)
        self.assertIn("IVA ventas: $ 1.000,00", bot.messages[0][1])
        self.assertIn("Revisar antes del cierre mensual.", bot.messages[0][1])

    def test_menu_periods_permissions_repeat_and_navigation_are_unchanged(self):
        self.assertEqual(telegram_access_bot.COMMAND_PERMISSIONS["iva_mensual"], "reportes")
        self.assertEqual(
            telegram_access_bot.parse_iva_period_request("IVA julio 2026"),
            {"anio": 2026, "mes": 7},
        )
        self.assertIn(
            "rango exacto no está implementado",
            telegram_access_bot.parse_iva_period_request(
                "IVA de 01/07/2026 a 20/07/2026"
            )["error"],
        )
        chat_id = 704
        telegram_access_bot.MENU_STATES[chat_id] = {
            "pantalla": "menu_iva_estimado",
            "anterior": "menu_consultas_rapidas",
        }
        with patch.object(telegram_access_bot, "log_event"):
            current = telegram_access_bot.consume_menu_navigation(chat_id, "1")
        self.assertEqual(current[0:2], ("execute", "iva_mensual"))
        self.assertEqual(
            telegram_access_bot.MENU_STATES[chat_id]["pantalla"],
            "menu_iva_estimado",
        )
        with patch.object(telegram_access_bot, "log_event"):
            with patch.object(
                telegram_access_bot,
                "render_menu_consultas_rapidas",
                return_value="Menú consultas",
            ):
                back = telegram_access_bot.consume_menu_navigation(chat_id, "volver")
        self.assertIsInstance(back, str)
        self.assertEqual(
            telegram_access_bot.MENU_STATES[chat_id]["pantalla"],
            "menu_consultas_rapidas",
        )
        telegram_access_bot.MENU_STATES.pop(chat_id, None)

    def test_unauthorized_user_does_not_execute_core(self):
        bot = FakeBot()
        with patch.object(telegram_access_bot, "authorize_command", return_value=(False, "No autorizado")):
            with patch.object(telegram_access_bot, "registrar_actividad"):
                with patch.object(telegram_access_bot, "execute_iva_core") as core:
                    telegram_access_bot.reply_menu_result(
                        bot,
                        7,
                        ("execute", "iva_mensual", {"anio": 2026, "mes": 7}),
                    )
        core.assert_not_called()
        self.assertEqual(bot.messages, [(7, "No autorizado")])

    def test_menu_text_error_is_not_reported_as_audio(self):
        bot = FakeBot()
        with patch.object(telegram_access_bot, "authorize_command", return_value=(True, "")):
            with patch.object(telegram_access_bot, "prepare_client_query", return_value=("ready", "iva_mensual", {})):
                with patch.object(telegram_access_bot, "auditar_consulta"):
                    with patch.object(
                        telegram_access_bot,
                        "handle_command",
                        side_effect=RuntimeError("fallo controlado"),
                    ):
                        with patch.object(telegram_access_bot, "registrar_actividad"):
                            telegram_access_bot.reply_menu_result(
                                bot,
                                7,
                                ("execute", "iva_mensual", {"anio": 2026, "mes": 7}),
                            )
        self.assertEqual(bot.messages, [(7, "No pude procesar la consulta: fallo controlado")])
        self.assertEqual(
            telegram_access_bot.friendly_error(RuntimeError("fallo controlado")),
            "No pude procesar el audio: fallo controlado",
        )


if __name__ == "__main__":
    unittest.main()
