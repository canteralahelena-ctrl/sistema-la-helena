import unittest

from helena_core.application.contracts import Request
from helena_core.business.iva.mensual import consultar_iva_mensual


class AdapterResult:
    def __init__(self, *, success=True, payload=None, stderr="", timed_out=False):
        self.success = success
        self.returncode = 0 if success else 1
        self.stdout = ""
        self.stderr = stderr
        self.timeout = 240
        self.payload = payload or {}
        self.timed_out = timed_out


class RecordingAdapter:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def consultar_iva_mensual(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class IvaMensualServiceTests(unittest.TestCase):
    def request(self, anio=2026, mes=7):
        return Request(capability="iva.mensual", parameters={"anio": anio, "mes": mes})

    def payload(self, periodo="2026-07"):
        return {
            "periodo": periodo,
            "iva_ventas": "$ 100,00",
            "iva_gastos": "$ 40,00",
            "saldo_iva": "$ 60,00",
            "ventas_comprobantes": 2,
            "gastos_comprobantes": 1,
            "detalle_csv": "detalle.csv",
            "resumen": "resumen.txt",
        }

    def test_returns_structured_legacy_values(self):
        adapter = RecordingAdapter(AdapterResult(payload=self.payload()))
        result = consultar_iva_mensual(self.request(), adapter=adapter)
        self.assertTrue(result.success)
        self.assertEqual(result.data["saldo_iva"], "$ 60,00")
        self.assertEqual(adapter.calls, [{"anio": 2026, "mes": 7}])

    def test_accepts_zero_and_negative_values_without_recalculating(self):
        payload = self.payload()
        payload.update(iva_ventas="$ 0,00", iva_gastos="$ 10,00", saldo_iva="-$ 10,00")
        result = consultar_iva_mensual(
            self.request(), adapter=RecordingAdapter(AdapterResult(payload=payload))
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["saldo_iva"], "-$ 10,00")

    def test_rejects_invalid_period_before_adapter(self):
        for anio, mes in ((None, 7), (2026, 0), (2026, 13), (0, 1)):
            with self.subTest(anio=anio, mes=mes):
                adapter = RecordingAdapter(AdapterResult(payload=self.payload()))
                result = consultar_iva_mensual(self.request(anio, mes), adapter=adapter)
                self.assertFalse(result.success)
                self.assertEqual(result.error.code, "periodo_invalido")
                self.assertEqual(adapter.calls, [])

    def test_propagates_adapter_error_and_timeout(self):
        error = consultar_iva_mensual(
            self.request(),
            adapter=RecordingAdapter(AdapterResult(success=False, stderr="fallo controlado")),
        )
        timeout = consultar_iva_mensual(
            self.request(),
            adapter=RecordingAdapter(AdapterResult(success=False, timed_out=True)),
        )
        self.assertEqual(error.error.code, "iva_mensual_error")
        self.assertEqual(error.message, "fallo controlado")
        self.assertEqual(timeout.error.code, "iva_mensual_timeout")

    def test_rejects_response_for_another_period(self):
        result = consultar_iva_mensual(
            self.request(),
            adapter=RecordingAdapter(AdapterResult(payload=self.payload("2026-06"))),
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "respuesta_no_corresponde")


if __name__ == "__main__":
    unittest.main()
