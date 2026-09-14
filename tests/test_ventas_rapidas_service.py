import unittest

from helena_core.application.contracts import Request
from helena_core.business.ventas.rapidas import consultar_ventas_rapidas


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

    def consultar_ventas_rapidas(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class VentasRapidasServiceTests(unittest.TestCase):
    def request(self, desde="2026-07-01", hasta="2026-07-20"):
        return Request(
            capability="ventas.rapidas",
            parameters={"fecha_desde": desde, "fecha_hasta": hasta},
        )

    def payload(self, desde="2026-07-01", hasta="2026-07-20"):
        return {
            "estado": "OK",
            "fecha_desde": desde,
            "fecha_hasta": hasta,
            "periodo_desde": "01/07/2026",
            "periodo_hasta": "20/07/2026",
            "total": "$ 100,00",
            "facturado": "$ 80,00",
            "remitos": "$ 20,00",
            "clasificado": "$ 100,00",
            "no_clasificado": "$ 0,00",
            "categorias": [],
        }

    def test_returns_structured_data_for_requested_period(self):
        adapter = RecordingAdapter(AdapterResult(payload=self.payload()))
        result = consultar_ventas_rapidas(self.request(), adapter=adapter)
        self.assertTrue(result.success)
        self.assertEqual(result.data["total"], "$ 100,00")
        self.assertEqual(
            adapter.calls,
            [{"fecha_desde": "2026-07-01", "fecha_hasta": "2026-07-20"}],
        )

    def test_accepts_zero_sales_without_categories(self):
        payload = self.payload()
        payload.update(
            total="$ 0,00",
            facturado="$ 0,00",
            remitos="$ 0,00",
            clasificado="$ 0,00",
            no_clasificado="$ 0,00",
        )
        result = consultar_ventas_rapidas(
            self.request(), adapter=RecordingAdapter(AdapterResult(payload=payload))
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["categorias"], [])

    def test_rejects_invalid_or_inverted_dates_before_adapter(self):
        for desde, hasta, code in (
            ("01/07/2026", "2026-07-20", "fecha_invalida"),
            ("2026-07-21", "2026-07-20", "rango_invertido"),
        ):
            with self.subTest(code=code):
                adapter = RecordingAdapter(AdapterResult(payload=self.payload()))
                result = consultar_ventas_rapidas(self.request(desde, hasta), adapter=adapter)
                self.assertFalse(result.success)
                self.assertEqual(result.error.code, code)
                self.assertEqual(adapter.calls, [])

    def test_propagates_adapter_error_and_timeout(self):
        error = consultar_ventas_rapidas(
            self.request(),
            adapter=RecordingAdapter(AdapterResult(success=False, stderr="Error controlado")),
        )
        timeout = consultar_ventas_rapidas(
            self.request(),
            adapter=RecordingAdapter(AdapterResult(success=False, timed_out=True)),
        )
        self.assertEqual(error.error.code, "ventas_rapidas_error")
        self.assertEqual(error.message, "Error controlado")
        self.assertEqual(timeout.error.code, "ventas_rapidas_timeout")

    def test_rejects_response_from_another_period(self):
        payload = self.payload(desde="2026-06-01", hasta="2026-06-30")
        result = consultar_ventas_rapidas(
            self.request(), adapter=RecordingAdapter(AdapterResult(payload=payload))
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "respuesta_no_corresponde")


if __name__ == "__main__":
    unittest.main()
