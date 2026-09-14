import unittest
from dataclasses import dataclass
from datetime import date, timedelta

from combinar_pagos import PaymentItem
from helena_core.application.contracts import Request
from helena_core.business.pagos.propuestas import consultar_propuesta_pago


@dataclass
class Technical:
    success: bool = True
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    timeout: int = 60
    timed_out: bool = False
    payload: dict | None = None


class Adapter:
    def __init__(self, totals=None, *, failure=None, items=None, no_combination=False):
        self.totals = list(totals or [])
        self.failure = failure
        self.items = list(items or [])
        self.no_combination = no_combination
        self.calls = []
        self.portfolio_calls = []

    def proponer(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure == "timeout":
            return Technical(success=False, timed_out=True, payload={})
        if self.failure == "error":
            return Technical(success=False, returncode=1, stderr="fallo controlado", payload={})
        total = self.totals.pop(0) if self.totals else None
        text = "No se encuentra combinación de cheques." if self.no_combination else "No encontre una alternativa viable."
        if total is not None:
            text = f"PAGO OPTIMO\nTotal: $ {total:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return Technical(
            payload={
                "texto_legacy": text,
                "total_seleccionado": total,
                "opciones": [],
                "cheques_seleccionados": [],
            }
        )

    def cargar_cartera(self, **kwargs):
        self.portfolio_calls.append(kwargs)
        if self.failure == "timeout":
            return Technical(success=False, timed_out=True, payload={})
        if self.failure == "error":
            return Technical(success=False, returncode=1, stderr="fallo controlado", payload={})
        return Technical(payload={"items": self.items})


def request(**parameters):
    return Request(capability="pagos.propuesta", parameters=parameters)


class PagosServiceTests(unittest.TestCase):
    @staticmethod
    def item(identity, amount, days, item_type="ECHEQ"):
        today = date.today()
        return PaymentItem(
            raw={"IdENTREGA": identity},
            amount_cents=int(round(amount * 100)),
            item_type=item_type,
            bank="BANCO",
            number=str(identity),
            client="CLIENTE",
            due_date=today + timedelta(days=days),
            days=days,
            expiration_days=days + 30,
        )

    def test_classifies_exact_under_over_and_preserves_threshold(self):
        cases = [
            (1000, 1000, "EXACTO", None),
            (1000, 900, "POR_DEBAJO", "TRANSFERIR"),
            (200000, 100000, "POR_DEBAJO", "AGREGAR_PROPIO"),
            (1000, 1100, "POR_ENCIMA", None),
        ]
        for target, selected, status, action in cases:
            with self.subTest(status=status, action=action):
                result = consultar_propuesta_pago(
                    request(
                        importe=target,
                        plazo={"tipo": "DIAS", "dias": 30},
                        modo="MIXTO",
                        filtro_fiscal="TODOS",
                    ),
                    adapter=Adapter([selected]),
                )
                self.assertTrue(result.success)
                self.assertEqual(result.data["resultado"], status)
                self.assertEqual(result.data["accion_faltante"], action)

    def test_fragmentation_assigns_cents_to_last_payment_and_normalizes_order(self):
        adapter = Adapter()
        result = consultar_propuesta_pago(
            request(
                importe=100,
                fraccionado=True,
                plazos=[
                    {"tipo": "DIAS", "dias": 30},
                    {"tipo": "DIAS", "dias": 60},
                    {"tipo": "ACOBRAR", "dias": None},
                ],
                modo="ECHEQ",
                filtro_fiscal="NN",
            ),
            adapter=adapter,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["objetivos_cents"], [3333, 3333, 3334])
        self.assertEqual([0 if item["tipo"] == "ACOBRAR" else item["dias"] for item in result.data["plazos"]], [0, 30, 60])
        self.assertEqual(adapter.calls, [])
        self.assertEqual(adapter.portfolio_calls, [{"modo": "ECHEQ", "filtro_fiscal": "NN"}])
        self.assertTrue(result.data["exclusion_entre_pagos"])

    def test_simple_own_instrument_follows_mode_without_changing_fragmented(self):
        for mode, expected in (
            ("ECHEQ", "eCheq"),
            ("CHEQUE", "cheque"),
            ("MIXTO", "cheque/eCheq"),
            ("OPTIMO", "cheque/eCheq"),
        ):
            result = consultar_propuesta_pago(
                request(
                    importe=200000,
                    plazo={"tipo": "DIAS", "dias": 30},
                    modo=mode,
                    filtro_fiscal="TODOS",
                ),
                adapter=Adapter([50000]),
            )
            self.assertTrue(result.success)
            self.assertEqual(result.data["accion_faltante"], "AGREGAR_PROPIO")
            self.assertEqual(result.data["instrumento_faltante"], expected)

        fragmented = consultar_propuesta_pago(
            request(
                importe=400000,
                fraccionado=True,
                plazos=[{"tipo": "DIAS", "dias": 30}, {"tipo": "DIAS", "dias": 60}],
                modo="CHEQUE",
                filtro_fiscal="TODOS",
            ),
            adapter=Adapter(),
        )
        self.assertTrue(fragmented.success)
        strict = fragmented.data["propuestas"][0]
        self.assertEqual(strict["total_propios_cents"], 40000000)
        self.assertEqual(strict["total_final_cents"], 40000000)
        self.assertNotIn("TRANSFERIR", str(strict))

    def test_modes_filters_and_legacy_echeq_contract(self):
        for mode in ("OPTIMO", "ECHEQ", "CHEQUE", "MIXTO"):
            result = consultar_propuesta_pago(
                request(
                    importe=500,
                    plazo={"tipo": "DIAS", "dias": 120},
                    modo=mode,
                    filtro_fiscal="BLANCO",
                ),
                adapter=Adapter([500]),
            )
            self.assertTrue(result.success)
            self.assertEqual(result.data["modo"], mode)
            self.assertEqual(result.data["filtro_fiscal"], "BLANCO")

        result = consultar_propuesta_pago(
            Request(
                capability="pagos.echeq_legacy",
                parameters={"importe": 500, "plazo": {"tipo": "DIAS", "dias": 30}},
            ),
            adapter=Adapter([500]),
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["modo"], "ECHEQ")

    def test_single_fragmented_term_keeps_simple_payment_flow(self):
        adapter = Adapter([100])
        result = consultar_propuesta_pago(
            request(
                importe=100,
                fraccionado=True,
                plazos=[{"tipo": "ACOBRAR", "dias": None}],
                modo="ECHEQ",
                filtro_fiscal="TODOS",
            ),
            adapter=adapter,
        )
        self.assertTrue(result.success)
        self.assertFalse(result.data["fraccionado"])
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(adapter.portfolio_calls, [])

    def test_simple_payment_uses_existing_relaxed_ranking_only_after_exact_no_combination(self):
        adapter = Adapter(
            no_combination=True,
            items=[
                self.item(21082, 554954.40, 35, "CHEQUE FISICO"),
                self.item(21070, 254100, 35, "CHEQUE FISICO"),
                self.item(21333, 35458, 3),
            ],
        )
        result = consultar_propuesta_pago(
            request(
                importe=845901,
                plazo={"tipo": "DIAS", "dias": 90},
                modo="MIXTO",
                filtro_fiscal="BLANCO",
            ),
            adapter=adapter,
        )
        self.assertTrue(result.success)
        self.assertTrue(result.data["alternativa_fuera_ventana_estricta"])
        self.assertEqual(result.data["total_seleccionado"], 844512.40)
        self.assertEqual(result.data["diferencia"], 1388.60)
        self.assertEqual(result.data["propuesta_relaxed"]["id"], "CARTERA_OPTIMA")
        instruments = result.data["propuesta_relaxed"]["asignaciones"][0]["instrumentos"]
        self.assertEqual({instrument["id_entrega"] for instrument in instruments}, {21082, 21070, 21333})
        self.assertEqual(adapter.portfolio_calls, [{"modo": "MIXTO", "filtro_fiscal": "BLANCO"}])

    def test_simple_payment_falls_back_to_another_relaxed_plan_when_portfolio_is_not_distinct(self):
        adapter = Adapter(no_combination=True, items=[self.item(21114, 800000, 63)])
        result = consultar_propuesta_pago(
            request(
                importe=845901,
                plazo={"tipo": "DIAS", "dias": 90},
                modo="MIXTO",
                filtro_fiscal="BLANCO",
            ),
            adapter=adapter,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["propuesta_relaxed"]["id"], "EQUILIBRADA")
        self.assertEqual(result.data["total_seleccionado"], 800000)

    def test_simple_payment_does_not_load_relaxed_portfolio_when_strict_succeeds(self):
        adapter = Adapter([845901], no_combination=True, items=[self.item(1, 800000, 63)])
        result = consultar_propuesta_pago(
            request(
                importe=845901,
                plazo={"tipo": "DIAS", "dias": 90},
                modo="MIXTO",
                filtro_fiscal="BLANCO",
            ),
            adapter=adapter,
        )
        self.assertTrue(result.success)
        self.assertNotIn("alternativa_fuera_ventana_estricta", result.data)
        self.assertEqual(adapter.portfolio_calls, [])

    def test_simple_payment_keeps_no_combination_when_relaxed_has_no_usable_items(self):
        adapter = Adapter(no_combination=True, items=[])
        result = consultar_propuesta_pago(
            request(
                importe=845901,
                plazo={"tipo": "DIAS", "dias": 90},
                modo="MIXTO",
                filtro_fiscal="BLANCO",
            ),
            adapter=adapter,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["texto_legacy"], "No se encuentra combinación de cheques.")
        self.assertIsNone(result.data["total_seleccionado"])
        self.assertNotIn("alternativa_fuera_ventana_estricta", result.data)

    def test_empty_result_errors_and_validation(self):
        empty = consultar_propuesta_pago(
            request(importe=500, plazo={"tipo": "DIAS", "dias": 30}, modo="OPTIMO"),
            adapter=Adapter([None]),
        )
        self.assertTrue(empty.success)
        self.assertEqual(empty.data["resultado"], "SIN_RESULTADO")

        for parameters, code in [
            ({"importe": 0, "plazo": {"tipo": "DIAS", "dias": 30}}, "importe_invalido"),
            ({"importe": -1, "plazo": {"tipo": "DIAS", "dias": 30}}, "importe_invalido"),
            ({"importe": 1, "plazo": {"tipo": "DIAS", "dias": 0}}, "plazo_invalido"),
            ({"importe": 1, "plazo": {"tipo": "DIAS", "dias": 181}}, "plazo_invalido"),
            ({"importe": 1, "plazo": {"tipo": "DIAS", "dias": 30}, "modo": "OTRO"}, "modo_invalido"),
        ]:
            result = consultar_propuesta_pago(request(**parameters), adapter=Adapter([1]))
            self.assertFalse(result.success)
            self.assertEqual(result.error.code, code)

        timeout = consultar_propuesta_pago(
            request(importe=1, plazo={"tipo": "DIAS", "dias": 30}),
            adapter=Adapter(failure="timeout"),
        )
        error = consultar_propuesta_pago(
            request(importe=1, plazo={"tipo": "DIAS", "dias": 30}),
            adapter=Adapter(failure="error"),
        )
        self.assertEqual(timeout.error.code, "pagos_timeout")
        self.assertEqual(error.error.code, "pagos_error")


if __name__ == "__main__":
    unittest.main()
