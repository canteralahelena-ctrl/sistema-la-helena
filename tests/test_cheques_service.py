import unittest
from datetime import date

from helena_core.application.contracts import Request
from helena_core.business.cheques.consultas import consultar_cheques


class AdapterResult:
    def __init__(self, *, success=True, payload=None, stderr="", timed_out=False):
        self.success = success
        self.returncode = 0 if success else 1
        self.stdout = ""
        self.stderr = stderr
        self.timeout = 180
        self.payload = payload or {}
        self.timed_out = timed_out


class RecordingAdapter:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def consultar(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def raw_record(**overrides):
    record = {
        "IdENTREGA": 1,
        "IdPAGO": 2,
        "Tipo": "ECHEQ",
        "TipoOriginal": "ECHEQ",
        "Banco": "BANCO Ñ",
        "Numero": "123",
        "FechaCobro": "2026-07-24",
        "FechaVencimiento": "2026-08-23",
        "DiasRestantes": 0,
        "DiasAlVencimiento": 30,
        "Tramo": "0-7 DIAS",
        "Importe": 100.5,
        "IdCLIENTE": 3,
        "Cliente": "CLIENTE Á",
        "Estado": "EN CAJA",
        "DepositadoEn": "",
        "FechaEndoso": "",
        "Destinatario": "",
        "UserID": 4,
        "Observacion": "NN",
    }
    record.update(overrides)
    return record


class ChequesServiceTests(unittest.TestCase):
    def request(self, capability="cheques.resumen", **parameters):
        defaults = {"tipo": "TODOS", "filtro_fiscal": "TODOS"}
        defaults.update(parameters)
        return Request(capability=capability, parameters=defaults)

    def test_summary_returns_structured_totals_types_buckets_and_fiscal_groups(self):
        records = [
            raw_record(),
            raw_record(
                IdENTREGA=5,
                Tipo="CHEQUE FISICO",
                TipoOriginal="CHEQUE",
                DiasRestantes=10,
                Tramo="8-15 DIAS",
                Importe=200,
                Observacion="",
            ),
            raw_record(
                IdENTREGA=6,
                FechaCobro="2026-06-11",
                Tramo="VENCIDO",
                Importe=999,
            ),
        ]
        adapter = RecordingAdapter(
            AdapterResult(
                payload={
                    "accion": "resumen",
                    "FechaConsulta": "2026-07-24",
                    "Registros": records,
                }
            )
        )
        result = consultar_cheques(self.request(), adapter=adapter)
        self.assertTrue(result.success)
        self.assertEqual(result.data["total_cartera"], {"cantidad": 2, "total": 300.5})
        self.assertEqual(result.data["a_cobrar"], {"cantidad": 1, "total": 100.5})
        self.assertEqual(result.data["a_depositar"]["8-15 DIAS"]["total"], 200)
        self.assertEqual(result.data["por_filtro_fiscal"]["NN"]["cantidad"], 1)
        self.assertEqual(result.data["por_tipo"]["ECHEQ"]["cantidad"], 1)

    def test_operational_window_includes_29_and_30_business_days_but_excludes_31(self):
        records = [
            raw_record(IdENTREGA=29, FechaCobro="2026-06-15", Tramo="VENCIDO"),
            raw_record(IdENTREGA=30, FechaCobro="2026-06-12", Tramo="VENCIDO"),
            raw_record(IdENTREGA=31, FechaCobro="2026-06-11", Tramo="VENCIDO"),
        ]
        result = consultar_cheques(
            self.request(),
            adapter=RecordingAdapter(
                AdapterResult(payload={"accion": "resumen", "FechaConsulta": "2026-07-24", "Registros": records})
            ),
        )
        self.assertTrue(result.success)
        self.assertEqual(
            [row["identificador"] for row in result.data["cheques"]],
            [29, 30],
        )

    def test_fiscal_marks_include_confirmed_account_variants_and_unknowns_are_excluded(self):
        records = [
            raw_record(IdENTREGA=1, Observacion=""),
            raw_record(IdENTREGA=2, Observacion=None),
            raw_record(IdENTREGA=3, Observacion="   "),
            raw_record(IdENTREGA=4, Observacion="*"),
            raw_record(IdENTREGA=5, Observacion="NN"),
            raw_record(IdENTREGA=6, Observacion="EN CUENTA HUGO"),
            raw_record(IdENTREGA=7, Observacion="EN CUENTA GASTON"),
            raw_record(IdENTREGA=8, Observacion="EN CUENTA DE HUGO"),
            raw_record(IdENTREGA=9, Observacion="EN CUENTA DE GASTON"),
            raw_record(IdENTREGA=10, Observacion="Cuenta Hugo"),
            raw_record(IdENTREGA=11, Observacion="Cuenta Gaston"),
            raw_record(IdENTREGA=12, Observacion="Cuneta Hugo"),
            raw_record(IdENTREGA=13, Observacion="Cuneta Gaston"),
            raw_record(IdENTREGA=14, Observacion="Con factura"),
        ]
        result = consultar_cheques(
            self.request(),
            adapter=RecordingAdapter(
                AdapterResult(payload={"accion": "resumen", "FechaConsulta": "2026-07-24", "Registros": records})
            ),
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["por_filtro_fiscal"]["BLANCO"]["cantidad"], 3)
        self.assertEqual(result.data["por_filtro_fiscal"]["NN"]["cantidad"], 10)
        self.assertEqual(result.data["total_cartera"]["cantidad"], 13)
        self.assertNotIn(14, [row["identificador"] for row in result.data["cheques"]])

    def test_summary_keeps_values_without_client_for_manual_review(self):
        result = consultar_cheques(
            self.request(),
            adapter=RecordingAdapter(
                AdapterResult(
                    payload={
                        "accion": "resumen",
                        "FechaConsulta": "2026-07-24",
                        "Registros": [
                            raw_record(
                                IdENTREGA=21202,
                                IdPAGO=15227,
                                Cliente=None,
                                IdCLIENTE=None,
                                Importe=470371.06,
                                Observacion="Cuenta Hugo",
                            )
                        ],
                    }
                )
            ),
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["total_cartera"], {"cantidad": 1, "total": 470371.06})
        self.assertEqual(result.data["por_filtro_fiscal"]["NN"]["cantidad"], 1)
        self.assertEqual(result.data["cheques"][0]["identificador"], 21202)
        self.assertEqual(result.data["cheques"][0]["cliente"], "")
        self.assertEqual(result.data["cheques"][0]["diagnostico_cliente"], "CLIENTE_PENDIENTE")

    def test_non_caja_states_are_excluded(self):
        records = [
            raw_record(IdENTREGA=1, Estado="EN CAJA"),
            raw_record(IdENTREGA=2, Estado="ENTREGADO"),
            raw_record(IdENTREGA=3, Estado="DEPOSITADO"),
        ]
        result = consultar_cheques(
            self.request(),
            adapter=RecordingAdapter(
                AdapterResult(payload={"accion": "resumen", "FechaConsulta": "2026-07-24", "Registros": records})
            ),
        )
        self.assertTrue(result.success)
        self.assertEqual([row["identificador"] for row in result.data["cheques"]], [1])

    def test_summary_accepts_empty_portfolio(self):
        result = consultar_cheques(
            self.request(),
            adapter=RecordingAdapter(
                AdapterResult(
                    payload={
                        "accion": "resumen",
                        "FechaConsulta": "2026-07-24",
                        "Registros": [],
                    }
                )
            ),
        )
        self.assertTrue(result.success)
        self.assertTrue(result.data["vacio"])
        self.assertEqual(result.data["total_cartera"]["total"], 0)

    def test_vencimientos_preserves_records_and_builds_requested_limit(self):
        result = consultar_cheques(
            self.request("cheques.vencimientos", dias=15, tipo="ECHEQ"),
            adapter=RecordingAdapter(
                AdapterResult(
                    payload={
                        "accion": "vencimientos",
                        "FechaConsulta": "2026-07-24",
                        "Registros": [raw_record(Importe=0)],
                    }
                )
            ),
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["fecha_limite"], "2026-08-08")
        self.assertEqual(result.data["cantidad"], 1)
        self.assertEqual(result.data["total"], 0)
        self.assertEqual(result.data["cheques"][0]["cliente"], "CLIENTE Á")

    def test_depositables_and_alerts_keep_adapter_contract(self):
        for capability, payload in (
            (
                "cheques.depositables",
                {
                    "accion": "depositables",
                    "vacio": False,
                    "texto_legacy": "Disponible para depositar hoy",
                },
            ),
            (
                "cheques.alertas",
                {
                    "accion": "alertas",
                    "hay_alertas": False,
                    "texto_legacy": "SIN_ALERTAS",
                },
            ),
        ):
            with self.subTest(capability=capability):
                result = consultar_cheques(
                    self.request(capability, dias=3),
                    adapter=RecordingAdapter(AdapterResult(payload=payload)),
                )
                self.assertTrue(result.success)
                self.assertEqual(result.data["accion"], payload["accion"])

    def test_validates_types_filters_and_days_before_adapter(self):
        cases = (
            (self.request(tipo="OTRO"), "tipo_invalido"),
            (self.request(filtro_fiscal="OTRO"), "filtro_invalido"),
            (self.request("cheques.vencimientos", dias=0), "plazo_invalido"),
            (self.request("cheques.vencimientos", dias=181), "plazo_invalido"),
            (self.request("cheques.alertas", dias=31), "plazo_invalido"),
        )
        for request, code in cases:
            with self.subTest(code=code):
                adapter = RecordingAdapter(AdapterResult())
                result = consultar_cheques(request, adapter=adapter)
                self.assertFalse(result.success)
                self.assertEqual(result.error.code, code)
                self.assertEqual(adapter.calls, [])

    def test_propagates_adapter_error_timeout_and_wrong_action(self):
        error = consultar_cheques(
            self.request(),
            adapter=RecordingAdapter(AdapterResult(success=False, stderr="fallo controlado")),
        )
        timeout = consultar_cheques(
            self.request(),
            adapter=RecordingAdapter(AdapterResult(success=False, timed_out=True)),
        )
        wrong = consultar_cheques(
            self.request(),
            adapter=RecordingAdapter(AdapterResult(payload={"accion": "vencimientos"})),
        )
        self.assertEqual(error.error.code, "cheques_error")
        self.assertEqual(timeout.error.code, "cheques_timeout")
        self.assertEqual(wrong.error.code, "respuesta_no_corresponde")


if __name__ == "__main__":
    unittest.main()
