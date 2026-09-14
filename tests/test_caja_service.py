import unittest

from helena_core.application.contracts import Request
from helena_core.business.caja.cobros import consultar_cobros


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

    def consultar_cobros(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class CajaServiceTests(unittest.TestCase):
    def request(self, desde="2026-07-01", hasta="2026-07-02", medio="todos"):
        return Request(
            capability="caja.cobros",
            parameters={"medio": medio, "fecha_desde": desde, "fecha_hasta": hasta},
        )

    def payload(self, desde="2026-07-01", hasta="2026-07-02", medio="todos"):
        return {
            "fecha_desde": desde,
            "fecha_hasta_exclusiva": hasta,
            "periodo_desde": "01/07/2026",
            "periodo_hasta": "01/07/2026",
            "medio": medio,
            "medio_mostrado": medio.upper(),
            "cantidad_registros": 2,
            "total": "$ 100,00",
            "medios_de_pago": [],
            "texto_legacy": "Cobros por medio: TODOS",
        }

    def test_returns_complete_structured_result(self):
        adapter = RecordingAdapter(AdapterResult(payload=self.payload()))
        result = consultar_cobros(self.request(), adapter=adapter)
        self.assertTrue(result.success)
        self.assertEqual(result.data["cantidad_registros"], 2)
        self.assertEqual(result.data["total"], "$ 100,00")
        self.assertEqual(
            adapter.calls,
            [{"medio": "todos", "fecha_desde": "2026-07-01", "fecha_hasta": "2026-07-02"}],
        )

    def test_accepts_empty_result(self):
        payload = self.payload()
        payload.update(cantidad_registros=0, total="$ 0,00", medios_de_pago=[])
        result = consultar_cobros(
            self.request(), adapter=RecordingAdapter(AdapterResult(payload=payload))
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["cantidad_registros"], 0)

    def test_rejects_invalid_empty_or_inverted_period(self):
        for desde, hasta, code in (
            ("01/07/2026", "2026-07-02", "fecha_invalida"),
            ("2026-07-01", "", "fecha_invalida"),
            ("2026-07-02", "2026-07-02", "rango_invalido"),
            ("2026-07-03", "2026-07-02", "rango_invalido"),
        ):
            with self.subTest(code=code):
                adapter = RecordingAdapter(AdapterResult(payload=self.payload()))
                result = consultar_cobros(self.request(desde, hasta), adapter=adapter)
                self.assertFalse(result.success)
                self.assertEqual(result.error.code, code)
                self.assertEqual(adapter.calls, [])

    def test_propagates_adapter_error_and_timeout(self):
        error = consultar_cobros(
            self.request(),
            adapter=RecordingAdapter(AdapterResult(success=False, stderr="fallo controlado")),
        )
        timeout = consultar_cobros(
            self.request(),
            adapter=RecordingAdapter(AdapterResult(success=False, timed_out=True)),
        )
        self.assertEqual(error.error.code, "caja_cobros_error")
        self.assertEqual(error.message, "fallo controlado")
        self.assertEqual(timeout.error.code, "caja_cobros_timeout")

    def test_rejects_response_for_another_request(self):
        result = consultar_cobros(
            self.request(),
            adapter=RecordingAdapter(
                AdapterResult(payload=self.payload(desde="2026-06-01", hasta="2026-06-02"))
            ),
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "respuesta_no_corresponde")


if __name__ == "__main__":
    unittest.main()
