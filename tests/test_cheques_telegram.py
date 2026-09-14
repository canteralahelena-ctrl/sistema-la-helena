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


def summary_data():
    return {
        "fecha_consulta": "2026-07-24",
        "tipo": "TODOS",
        "filtro_fiscal": "TODOS",
        "vacio": False,
        "total_cartera": {"cantidad": 2, "total": 300},
        "por_tipo": {
            "ECHEQ": {"cantidad": 1, "total": 100},
            "CHEQUE FISICO": {"cantidad": 1, "total": 200},
        },
        "a_cobrar": {"cantidad": 1, "total": 100},
        "a_depositar": {
            "0-7 DIAS": {"cantidad": 1, "total": 200},
            "8-15 DIAS": {"cantidad": 0, "total": 0},
            "16-30 DIAS": {"cantidad": 0, "total": 0},
            "MAS DE 30 DIAS": {"cantidad": 0, "total": 0},
        },
        "por_filtro_fiscal": {
            "NN": {"cantidad": 1, "total": 100},
            "BLANCO": {"cantidad": 1, "total": 200},
        },
        "cheques": [],
    }


class ChequesTelegramCompatibilityTests(unittest.TestCase):
    def test_core_composition_builds_request_and_propagates_error(self):
        with patch.object(telegram_access_bot, "ChequesPowerShellAdapter", return_value=object()):
            with patch.object(
                telegram_access_bot,
                "consultar_cheques",
                return_value=Result(success=True, data=summary_data()),
            ) as service:
                data = telegram_access_bot.execute_cheques_core(
                    "cheques.resumen",
                    {"tipo": "TODOS"},
                    chat_id=7,
                )
        self.assertEqual(data["total_cartera"]["total"], 300)
        request = service.call_args.args[0]
        self.assertEqual(request.capability, "cheques.resumen")
        self.assertEqual(request.user_context.channel_user_id, "7")

        failure = Result(
            success=False,
            message="fallo controlado",
            error=ErrorInfo(code="cheques_error", message="fallo controlado"),
        )
        with patch.object(telegram_access_bot, "ChequesPowerShellAdapter", return_value=object()):
            with patch.object(telegram_access_bot, "consultar_cheques", return_value=failure):
                with self.assertRaisesRegex(RuntimeError, "fallo controlado"):
                    telegram_access_bot.execute_cheques_core("cheques.resumen")

    def test_summary_handler_uses_core_and_preserves_wording(self):
        with patch.object(telegram_access_bot, "refresh_access") as refresh:
            with patch.object(
                telegram_access_bot, "execute_cheques_core", return_value=summary_data()
            ) as core:
                with patch.object(telegram_access_bot, "run_script") as direct:
                    result = telegram_access_bot.handle_command(
                        "cheques_resumen",
                        {"tipo": "TODOS", "filtro_fiscal": "TODOS", "chat_id": 7},
                    )
        refresh.assert_called_once()
        direct.assert_not_called()
        core.assert_called_once()
        self.assertIn("💰 Total cartera", result[1])
        self.assertIn("📅 A cobrar", result[1])
        self.assertIn("0-7 días", result[1])
        self.assertIn("8-15 días", result[1])
        self.assertNotIn("para depositar hoy", result[1])

    def test_depositables_and_vencimientos_use_core_without_files(self):
        depositables = {
            "accion": "depositables",
            "filtro_fiscal": "TODOS",
            "vacio": False,
            "texto_legacy": (
                "Disponible para depositar hoy\nFiltro: Todos\nFecha: 24/07/2026\n"
                "CHEQUE FISICO: 1, $ 10,00\nECHEQ: 0, $ 0,00\nTOTAL: $ 10,00"
            ),
        }
        vencimientos = {
            "fecha_consulta": "2026-07-24",
            "fecha_limite": "2026-07-31",
            "plazo_dias": 7,
            "tipo": "TODOS",
            "filtro_fiscal": "TODOS",
            "cantidad": 1,
            "total": 10,
            "cheques": [
                {
                    "tipo": "ECHEQ",
                    "banco": "BANCO Ñ",
                    "numero": "123",
                    "cliente": "CLIENTE Á",
                    "importe": 10,
                    "fecha_cobro": "2026-07-25",
                    "dias_restantes": 1,
                }
            ],
        }
        with patch.object(telegram_access_bot, "refresh_access"):
            with patch.object(
                telegram_access_bot,
                "execute_cheques_core",
                side_effect=[depositables, vencimientos],
            ):
                with patch.object(telegram_access_bot, "run_script") as direct:
                    cobrar = telegram_access_bot.handle_command(
                        "cheques_depositables", {"filtro_fiscal": "TODOS"}
                    )
                    vencer = telegram_access_bot.handle_command(
                        "cheques_vencimientos",
                        {"tipo": "TODOS", "filtro_fiscal": "TODOS", "dias": 7},
                    )
        direct.assert_not_called()
        self.assertTrue(cobrar[1].startswith("A cobrar"))
        self.assertIn("Vencimientos próximos 7 días", vencer[1])
        self.assertIn("BANCO Ñ", vencer[1])

    def test_empty_outputs_keep_existing_messages(self):
        empty_summary = {**summary_data(), "vacio": True}
        empty_vencimientos = {
            "fecha_consulta": "2026-07-24",
            "fecha_limite": "2026-07-31",
            "plazo_dias": 7,
            "tipo": "TODOS",
            "filtro_fiscal": "NN",
            "cantidad": 0,
            "total": 0,
            "cheques": [],
        }
        self.assertEqual(
            telegram_access_bot.format_cheques_resumen_telegram(empty_summary),
            "No hay valores para ese filtro.\n\nFiltro: Todos",
        )
        with patch.object(telegram_access_bot, "refresh_access"):
            with patch.object(
                telegram_access_bot,
                "execute_cheques_core",
                return_value=empty_vencimientos,
            ):
                result = telegram_access_bot.handle_command(
                    "cheques_vencimientos",
                    {"tipo": "TODOS", "filtro_fiscal": "NN", "dias": 7},
                )
        self.assertEqual(
            result[1],
            "Filtro: NN / sin factura\nPeríodo: próximos 7 días\n\n"
            "No hay valores para ese filtro.",
        )

    def test_dashboard_and_alerts_use_core_without_changing_presentation(self):
        with patch.object(
            telegram_access_bot, "execute_cheques_core", return_value=summary_data()
        ) as core:
            with patch.object(telegram_access_bot, "run_script") as direct:
                dashboard = telegram_access_bot.dashboard_cheques_values()
        direct.assert_not_called()
        self.assertEqual(
            dashboard,
            {
                "total": "$ 300,00",
                "cobrar_hoy": "$ 100,00",
                "depositar_0_7": "$ 200,00",
            },
        )
        self.assertEqual(core.call_args.args[0], "cheques.resumen")

        bot = FakeBot()
        alert = {
            "accion": "alertas",
            "plazo_dias": 3,
            "hay_alertas": True,
            "texto_legacy": "Cheques proximos a vencer\nTotal: $ 10,00",
        }
        with patch.object(
            telegram_access_bot,
            "CONFIG",
            {"cheque_alerts": {"enabled": True, "hour": 0, "warning_days": 3}},
            create=True,
        ):
            with patch.object(telegram_access_bot.time, "monotonic", return_value=1000):
                with patch.object(telegram_access_bot, "read_cheque_alert_state", return_value={}):
                    with patch.object(telegram_access_bot, "write_cheque_alert_state"):
                        with patch.object(telegram_access_bot, "owner_chat_ids", return_value=[7]):
                            with patch.object(telegram_access_bot, "refresh_access"):
                                with patch.object(
                                    telegram_access_bot,
                                    "execute_cheques_core",
                                    return_value=alert,
                                ) as alert_core:
                                    with patch.object(telegram_access_bot, "run_script") as direct:
                                        original_poll = telegram_access_bot.LAST_CHEQUE_ALERT_POLL
                                        telegram_access_bot.LAST_CHEQUE_ALERT_POLL = 0
                                        try:
                                            telegram_access_bot.maybe_send_cheque_alerts(bot)
                                        finally:
                                            telegram_access_bot.LAST_CHEQUE_ALERT_POLL = original_poll
        direct.assert_not_called()
        alert_core.assert_called_once()
        self.assertEqual(bot.messages, [(7, "Cheques proximos a vencer\nTotal: $ 10,00")])

    def test_permissions_navigation_repeat_and_payment_flows_remain_separate(self):
        self.assertEqual(telegram_access_bot.COMMAND_PERMISSIONS["cheques_resumen"], "cheques")
        bot = FakeBot()
        with patch.object(telegram_access_bot, "authorize_command", return_value=(False, "No autorizado")):
            with patch.object(telegram_access_bot, "registrar_actividad"):
                with patch.object(telegram_access_bot, "execute_cheques_core") as core:
                    telegram_access_bot.reply_menu_result(
                        bot,
                        7,
                        ("execute", "cheques_resumen", {"tipo": "TODOS"}),
                    )
        core.assert_not_called()
        self.assertEqual(bot.messages, [(7, "No autorizado")])

        chat_id = 705
        telegram_access_bot.MENU_STATES[chat_id] = {
            "pantalla": "menu_cheques_pagos",
            "anterior": "menu_consultas_rapidas",
        }
        with patch.object(telegram_access_bot, "log_event"):
            payment = telegram_access_bot.consume_menu_navigation(chat_id, "4")
        self.assertIsInstance(payment, str)
        self.assertEqual(
            telegram_access_bot.MENU_STATES[chat_id]["pantalla"],
            "menu_pago_rapido",
        )
        telegram_access_bot.MENU_STATES.pop(chat_id, None)


if __name__ == "__main__":
    unittest.main()
