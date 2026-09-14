import unittest
from unittest.mock import patch

from helena_core.application.contracts import ErrorInfo, Result

import telegram_access_bot


class FakeBot:
    def __init__(self):
        self.messages = []

    def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))

    def send_action(self, chat_id, action="typing"):
        return None


class VentasModuloTelegramTests(unittest.TestCase):
    def products_result(self, *, empty=False):
        records = [] if empty else [
            {
                "tipo_comprobante": "FT A",
                "numero_comprobante": "0001",
                "fecha_mostrada": "01/07/2026",
                "cliente": "CLIENTE Á",
                "importe": "1234.5",
                "cantidad": "2",
                "unidad": "TN",
            }
        ]
        groups = [] if empty else [
            {
                "producto": "Árido especial",
                "importe_total": "1234.5",
                "cantidad_lineas": 1,
                "registros": records,
                "lineas_ocultas": 0,
            }
        ]
        return Result(
            success=True,
            data={
                "estado": "OK",
                "fecha_desde": "2026-07-01",
                "fecha_hasta": "2026-07-20",
                "registros": records,
                "cantidad_total": len(records),
                "importe_total": "0" if empty else "1234.5",
                "grupos": groups,
                "productos_ocultos": 0,
                "registros_mostrados": len(records),
                "truncado": False,
                "archivo_csv": "salida.no_clasificados.csv",
                "advertencias": [],
            },
        )

    def test_products_calls_core_once_and_keeps_visible_text(self):
        with patch.object(telegram_access_bot, "refresh_access"):
            with patch.object(telegram_access_bot, "VentasRapidasPowerShellAdapter", return_value=object()):
                with patch.object(
                    telegram_access_bot,
                    "consultar_productos_no_clasificados",
                    return_value=self.products_result(),
                ) as service:
                    with patch.object(telegram_access_bot, "run_script") as direct_runner:
                        result = telegram_access_bot.handle_command(
                            "productos_no_clasificados",
                            {"desde": "2026-07-01", "hasta": "2026-07-20", "chat_id": 7},
                        )
        direct_runner.assert_not_called()
        service.assert_called_once()
        request = service.call_args.args[0]
        self.assertEqual(request.capability, "ventas.productos_no_clasificados")
        self.assertEqual(
            result,
            (
                "text",
                "📦 PRODUCTOS NO CLASIFICADOS\n\nPeríodo:\n01/07/2026 al 20/07/2026\n\n"
                "Total no clasificado:\n$ 1.234,50\n\nCantidad:\n1 líneas\n\n━━━━━━━━━━━━━━━━━━\n\n"
                "1️⃣ ÁRIDO ESPECIAL\nTotal: $ 1.234,50\nLíneas: 1\n\nComprobantes:\n"
                "• FT A 0001 — 01/07/2026 — CLIENTE Á — $ 1.234,50 — Cant. 2 TN\n\n"
                "━━━━━━━━━━━━━━━━━━\n\n0️⃣ Volver",
            ),
        )

    def test_products_empty_message_is_unchanged(self):
        with patch.object(telegram_access_bot, "refresh_access"):
            with patch.object(telegram_access_bot, "VentasRapidasPowerShellAdapter", return_value=object()):
                with patch.object(
                    telegram_access_bot,
                    "consultar_productos_no_clasificados",
                    return_value=self.products_result(empty=True),
                ):
                    result = telegram_access_bot.handle_command(
                        "productos_no_clasificados",
                        {"desde": "2026-07-01", "hasta": "2026-07-20"},
                    )
        self.assertIn("No hay productos no clasificados en el período.", result[1])
        self.assertIn("Cantidad:\n0 líneas", result[1])

    def test_analysis_dictionary_flow_uses_core_and_preserves_legacy_text(self):
        core_result = Result(
            success=True,
            data={
                "estado": "OK",
                "fecha_desde": "2026-01-01",
                "fecha_hasta": "2026-07-23",
                "total": "$ 100,00",
                "categorias": [],
                "advertencias": [],
                "texto_resumido": "SALIDA LEGACY",
            },
        )
        params = {
            "id": "analisis_categorias",
            "frase_usuario": "ventas por categoria",
            "texto_original": "ventas por categoria",
            "parametros_base": {},
            "chat_id": 7,
        }
        with patch.object(telegram_access_bot, "VentasRapidasPowerShellAdapter", return_value=object()):
            with patch.object(
                telegram_access_bot,
                "consultar_analisis_categorias",
                return_value=core_result,
            ) as service:
                with patch.object(telegram_access_bot, "run_script") as direct_runner:
                    result = telegram_access_bot.handle_command("diccionario_intencion", params)
        direct_runner.assert_not_called()
        service.assert_called_once()
        self.assertEqual(service.call_args.args[0].capability, "ventas.analisis_categorias")
        self.assertEqual(
            result[1],
            "Frase detectada:\nventas por categoria\n\nIntencion:\nanalisis_categorias\n\n"
            "Script:\nanalisis_categorias.ps1\n\nEjecutando consulta...\n\nSALIDA LEGACY",
        )

    def test_core_errors_follow_existing_error_path(self):
        failure = Result(
            success=False,
            message="fallo controlado",
            error=ErrorInfo(code="ventas_error", message="fallo controlado"),
        )
        with patch.object(telegram_access_bot, "refresh_access"):
            with patch.object(telegram_access_bot, "VentasRapidasPowerShellAdapter", return_value=object()):
                with patch.object(
                    telegram_access_bot,
                    "consultar_productos_no_clasificados",
                    return_value=failure,
                ):
                    with self.assertRaisesRegex(RuntimeError, "fallo controlado"):
                        telegram_access_bot.handle_command(
                            "productos_no_clasificados",
                            {"desde": "2026-07-01", "hasta": "2026-07-20"},
                        )

    def test_permissions_and_navigation_remain_in_existing_dispatch(self):
        for kind, params, service_name in (
            (
                "productos_no_clasificados",
                {"desde": "2026-07-01", "hasta": "2026-07-20"},
                "consultar_productos_no_clasificados",
            ),
            (
                "diccionario_intencion",
                {"id": "analisis_categorias", "frase_usuario": "ventas por categoria"},
                "consultar_analisis_categorias",
            ),
        ):
            with self.subTest(kind=kind):
                bot = FakeBot()
                with patch.object(telegram_access_bot, "authorize_command", return_value=(False, "No autorizado")):
                    with patch.object(telegram_access_bot, "registrar_actividad"):
                        with patch.object(telegram_access_bot, service_name) as service:
                            telegram_access_bot.reply_menu_result(bot, 7, ("execute", kind, dict(params)))
                service.assert_not_called()
                self.assertEqual(bot.messages, [(7, "No autorizado")])

        chat_id = 702
        telegram_access_bot.MENU_STATES[chat_id] = {
            "pantalla": "consultas_ventas_esperando_consulta",
            "anterior": "menu_consultas_rapidas",
        }
        with patch.object(telegram_access_bot, "log_event"):
            execute = telegram_access_bot.consume_menu_navigation(
                chat_id, "productos no clasificados julio 2026"
            )
        self.assertEqual(execute[0:2], ("execute", "productos_no_clasificados"))
        self.assertEqual(
            telegram_access_bot.MENU_STATES[chat_id]["pantalla"],
            "consultas_ventas_esperando_consulta",
        )
        telegram_access_bot.MENU_STATES.pop(chat_id, None)

    def test_authorized_analysis_records_normal_sales_activity_without_recursion(self):
        bot = FakeBot()
        params = {
            "id": "analisis_categorias",
            "frase_usuario": "ventas por categoria",
            "texto_original": "ventas por categoria",
            "parametros_base": {},
        }
        with patch.object(telegram_access_bot, "authorize_command", return_value=(True, "")):
            with patch.object(telegram_access_bot, "registrar_actividad") as activity:
                with patch.object(
                    telegram_access_bot,
                    "handle_command",
                    return_value=("text", "resultado"),
                ):
                    with patch.object(telegram_access_bot, "reply_result"):
                        telegram_access_bot.reply_menu_result(
                            bot,
                            7,
                            ("execute", "diccionario_intencion", params),
                        )
        self.assertEqual(
            telegram_access_bot.modulo_actividad_para_comando(
                "diccionario_intencion",
                {"id": "analisis_categorias"},
            ),
            "Ventas",
        )
        activity.assert_called_once()
        call = activity.call_args.kwargs
        self.assertEqual(call["chat_id"], 7)
        self.assertEqual(call["modulo"], "Ventas")
        self.assertEqual(call["accion"], "Consulta")
        self.assertEqual(call["objeto"], "diccionario_intencion")
        self.assertEqual(call["nivel"], "INFO")


if __name__ == "__main__":
    unittest.main()
