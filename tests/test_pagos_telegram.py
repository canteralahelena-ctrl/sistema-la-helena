import unittest
from unittest.mock import patch

import telegram_access_bot
from helena_core.application.contracts import Result


def payment_data(*, fragmented=False):
    payment = {
        "numero_pago": 1,
        "plazo": {"tipo": "DIAS", "dias": 30},
        "importe_objetivo": 1000000,
        "texto_legacy": "PAGO OPTIMO\nTotal: $ 950.000,00",
        "total_seleccionado": 950000,
        "faltante": 50000,
        "excedente": 0,
        "accion_faltante": "TRANSFERIR",
        "resultado": "POR_DEBAJO",
    }
    return {
        "modo": "MIXTO",
        "filtro_fiscal": "TODOS",
        "importe_objetivo": 1000000,
        "cantidad_pagos": 1,
        "pagos": [payment],
        "fraccionado": fragmented,
        "importe_por_plazo": 1000000,
        **payment,
    }


def fragmented_data():
    assignment = {
        "plazo": {"tipo": "DIAS", "dias": 30},
        "fecha_objetivo": "2026-09-03",
        "objetivo_cents": 100000000,
        "terceros_cents": 95000000,
        "own_cents": 5000000,
        "target_accum": 100000000,
        "final_accum": 100000000,
        "instrumentos": [
            {
                "id_entrega": 10,
                "tipo": "ECHEQ",
                "numero": "1",
                "importe_cents": 95000000,
                "fecha_cobro": "2026-09-03",
                "desviacion_dias": 0,
            }
        ],
    }
    plan = {
        "id": "ESTRICTA",
        "nombre": "ESTRICTA",
        "asignaciones": [assignment],
        "total_terceros_cents": 95000000,
        "total_propios_cents": 5000000,
        "total_final_cents": 100000000,
        "diferencia_cents": 0,
        "metricas": {
            "cumplimiento_temporal": 100,
            "desviacion_maxima_dias": 0,
            "concentracion_maxima": 0.95,
            "ahorro_propios_vs_estricta_cents": 0,
        },
        "advertencias": [],
    }
    return {
        "modo": "ECHEQ",
        "filtro_fiscal": "BLANCO",
        "importe_objetivo": 1000000,
        "fraccionado": True,
        "plazos": [{"tipo": "DIAS", "dias": 30}],
        "propuestas": [plan],
    }


class PagosTelegramTests(unittest.TestCase):
    def test_core_helper_composes_request_and_adapter(self):
        success = Result(success=True, data=payment_data())
        with patch.object(telegram_access_bot, "PagosPowerShellAdapter", return_value=object()):
            with patch.object(telegram_access_bot, "consultar_propuesta_pago", return_value=success) as service:
                data = telegram_access_bot.execute_pagos_core(
                    "pagos.propuesta",
                    {"importe": 1000, "plazo": {"tipo": "DIAS", "dias": 30}},
                    chat_id="7",
                )
        self.assertEqual(data["modo"], "MIXTO")
        request = service.call_args.args[0]
        self.assertEqual(request.capability, "pagos.propuesta")
        self.assertEqual(request.user_context.channel_user_id, "7")

    def test_execution_uses_core_and_not_direct_powershell(self):
        with patch.object(telegram_access_bot, "refresh_access"):
            with patch.object(telegram_access_bot, "execute_pagos_core", return_value=payment_data()) as core:
                with patch.object(telegram_access_bot, "run_script") as direct:
                    with patch.object(telegram_access_bot, "log_event"):
                        kind, text = telegram_access_bot.handle_command(
                            "armar_pago_optimo",
                            {
                                "importe": 1000000,
                                "plazo": {"tipo": "DIAS", "dias": 30},
                                "modo": "MIXTO",
                                "filtro_fiscal": "TODOS",
                            },
                        )
        self.assertEqual(kind, "text")
        self.assertIn("Transferir faltante", text)
        self.assertEqual(core.call_args.args[0], "pagos.propuesta")
        direct.assert_not_called()

    def test_fragmented_conversation_sends_terms_without_splitting_in_telegram(self):
        chat_id = 90210
        telegram_access_bot.MENU_STATES[chat_id] = {
            "pantalla": "esperando_datos_pago_rapido_fraccionado",
            "modo": "ECHEQ",
            "filtro_fiscal": "NN",
        }
        try:
            with patch.object(telegram_access_bot, "log_event"):
                action = telegram_access_bot.consume_menu_navigation(chat_id, "100,01 a 30,60,90")
        finally:
            telegram_access_bot.MENU_STATES.pop(chat_id, None)
        self.assertEqual(action[0:2], ("execute", "armar_pago_optimo"))
        self.assertTrue(action[2]["fraccionado"])
        self.assertEqual([term["dias"] for term in action[2]["plazos"]], [30, 60, 90])
        self.assertNotIn("tramos", action[2])
        self.assertNotIn("importe_por_plazo", action[2])

    def test_navigation_permissions_and_intents_remain_compatible(self):
        self.assertEqual(telegram_access_bot.COMMAND_PERMISSIONS["armar_pago_optimo"], "cheques")
        self.assertEqual(telegram_access_bot.COMMAND_PERMISSIONS["armar_pago_echeq"], "cheques")
        kind, params = telegram_access_bot.parse_command("pago mixto de 1.000.000 a 60 dias")
        self.assertEqual(kind, "armar_pago_optimo")
        self.assertEqual(params["modo"], "MIXTO")
        self.assertEqual(params["plazo"]["dias"], 60)

    def test_real_payment_text_parses_amount_and_45_day_term(self):
        amount, term = telegram_access_bot.parse_pago_rapido_datos("847255 a 45 dias")
        self.assertEqual(amount, 847255)
        self.assertEqual(term, {"tipo": "DIAS", "dias": 45})

    def test_confirmed_payment_texts_keep_decimal_amount_and_terms(self):
        amount, term = telegram_access_bot.parse_pago_rapido_datos("345000,75 a 40 dias")
        self.assertEqual(amount, 345000.75)
        self.assertEqual(term, {"tipo": "DIAS", "dias": 40})
        amount, term = telegram_access_bot.parse_pago_rapido_datos("852412 a 45 dias")
        self.assertEqual(amount, 852412)
        self.assertEqual(term, {"tipo": "DIAS", "dias": 45})

    def test_text_error_does_not_claim_audio(self):
        self.assertEqual(
            telegram_access_bot.friendly_error(RuntimeError("fallo controlado"), input_kind="text"),
            "No pude procesar la consulta: fallo controlado",
        )
        self.assertEqual(
            telegram_access_bot.friendly_error(RuntimeError("fallo controlado")),
            "No pude procesar el audio: fallo controlado",
        )

    def test_formatting_uses_structured_adjustment_and_preserves_legacy_text(self):
        text = telegram_access_bot.format_pago_rapido_unico(payment_data())
        self.assertIn("PAGO RÁPIDO", text)
        self.assertIn("PAGO OPTIMO\nTotal: $ 950.000,00", text)
        self.assertIn("➡️ Transferir faltante: $ 50.000,00", text)
        self.assertTrue(text.endswith("0️⃣ Volver"))

    def test_simple_relaxed_fallback_shows_dates_totals_and_deviation(self):
        data = payment_data()
        payment = data["pagos"][0]
        payment.update(
            {
                "alternativa_fuera_ventana_estricta": True,
                "total_seleccionado": 800000,
                "diferencia": 45901,
                "propuesta_relaxed": {
                    "asignaciones": [
                        {
                            "instrumentos": [
                                {
                                    "tipo": "ECHEQ",
                                    "numero": "21114",
                                    "importe_cents": 80000000,
                                    "fecha_cobro": "2026-11-11",
                                    "desviacion_dias": -27,
                                }
                            ]
                        }
                    ]
                },
            }
        )
        data.update(payment)
        text = telegram_access_bot.format_pago_rapido_unico(data)
        self.assertIn("Alternativa fuera de la ventana estricta", text)
        self.assertIn("2026-11-11", text)
        self.assertIn("27 días anticipado", text)
        self.assertIn("Total sugerido: $ 800.000,00", text)
        self.assertIn("Diferencia: $ 200.000,00", text)

    def test_simple_excess_and_fragmented_ranking_do_not_promise_credit_note(self):
        data = payment_data()
        payment = data["pagos"][0]
        payment.update({"faltante": 0, "excedente": 100, "accion_faltante": None, "resultado": "POR_ENCIMA"})
        data.update(payment)
        simple = telegram_access_bot.format_pago_rapido_unico(data)
        fragmented = telegram_access_bot.format_pago_rapido_fraccionado(fragmented_data())
        self.assertIn("Excedente", simple)
        self.assertNotIn("Genera nota de crédito", simple)
        self.assertIn("PAGO FRACCIONADO", fragmented)
        self.assertNotIn("Genera nota de crédito", fragmented)

    def test_fragmented_ranking_navigation_opens_detail_and_returns(self):
        chat_id = 90300
        ranking = telegram_access_bot.payment_ranking_state_data(fragmented_data())
        telegram_access_bot.MENU_STATES[chat_id] = {
            "pantalla": "pago_fraccionado_ranking",
            "ranking": ranking,
        }
        try:
            with patch.object(telegram_access_bot, "log_event"):
                detail = telegram_access_bot.consume_menu_navigation(chat_id, "1")
                self.assertIn("IdENTREGA: 10", detail)
                self.assertEqual(telegram_access_bot.MENU_STATES[chat_id]["pantalla"], "pago_fraccionado_detalle")
                summary = telegram_access_bot.consume_menu_navigation(chat_id, "0")
                self.assertIn("PAGO FRACCIONADO", summary)
                self.assertEqual(telegram_access_bot.MENU_STATES[chat_id]["pantalla"], "pago_fraccionado_ranking")
                prompt = telegram_access_bot.consume_menu_navigation(chat_id, "0")
                self.assertIn("Ingresá monto total y plazos", prompt)
        finally:
            telegram_access_bot.MENU_STATES.pop(chat_id, None)

    def test_fragmented_execution_saves_minimal_ranking_state_and_uses_core(self):
        chat_id = 90301
        try:
            with patch.object(telegram_access_bot, "refresh_access"):
                with patch.object(telegram_access_bot, "execute_pagos_core", return_value=fragmented_data()) as core:
                    with patch.object(telegram_access_bot, "run_script") as direct:
                        with patch.object(telegram_access_bot, "log_event"):
                            kind, text = telegram_access_bot.handle_command(
                                "armar_pago_optimo",
                                {
                                    "importe": 1000000,
                                    "fraccionado": True,
                                    "plazos": [{"tipo": "DIAS", "dias": 30}, {"tipo": "DIAS", "dias": 60}],
                                    "modo": "ECHEQ",
                                    "filtro_fiscal": "BLANCO",
                                    "chat_id": chat_id,
                                },
                            )
            self.assertEqual(kind, "text")
            self.assertIn("PAGO FRACCIONADO", text)
            self.assertEqual(core.call_args.args[0], "pagos.propuesta")
            direct.assert_not_called()
            state = telegram_access_bot.MENU_STATES[chat_id]
            self.assertEqual(state["pantalla"], "pago_fraccionado_ranking")
            self.assertNotIn("stats", str(state))
            self.assertNotIn("texto_legacy", str(state))
        finally:
            telegram_access_bot.MENU_STATES.pop(chat_id, None)

    def test_fragmented_parser_accepts_zero_sorts_and_deduplicates(self):
        terms = telegram_access_bot.parse_pago_rapido_plazos("60,0,30,15,30")
        self.assertEqual([0 if term["tipo"] == "ACOBRAR" else term["dias"] for term in terms], [0, 15, 30, 60])
        self.assertEqual(telegram_access_bot.parse_pago_rapido_plazos("30,-1,60"), [])


if __name__ == "__main__":
    unittest.main()
