import unittest

from helena_core.application.contracts import Request
from helena_core.business.ventas.analisis_categorias import consultar_analisis_categorias


class Technical:
    def __init__(self, *, success=True, payload=None, stderr="", timed_out=False):
        self.success = success
        self.payload = payload or {}
        self.stderr = stderr
        self.stdout = ""
        self.returncode = 0 if success else 1
        self.timeout = 240
        self.timed_out = timed_out


class Adapter:
    def __init__(self, result):
        self.result = result

    def consultar_analisis_categorias(self):
        return self.result


class AnalisisCategoriasServiceTests(unittest.TestCase):
    def request(self):
        return Request(capability="ventas.analisis_categorias")

    def payload(self):
        return {
            "estado": "OK",
            "fecha_desde": "2026-01-01",
            "fecha_hasta": "2026-07-23",
            "total": "$ 100,00",
            "categorias": [{"codigo": "ARIDOS", "importe": "$ 100,00", "porcentaje": "100,00%"}],
            "advertencias": ["AVISO: pendiente"],
            "texto_resumido": "salida legacy",
        }

    def test_returns_reusable_structured_result(self):
        result = consultar_analisis_categorias(
            self.request(), adapter=Adapter(Technical(payload=self.payload()))
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["total"], "$ 100,00")
        self.assertEqual(result.data["categorias"][0]["porcentaje"], "100,00%")
        self.assertEqual(result.warnings, ["AVISO: pendiente"])

    def test_accepts_period_without_sales(self):
        payload = self.payload()
        payload.update(total="$ 0,00", categorias=[], advertencias=[])
        result = consultar_analisis_categorias(
            self.request(), adapter=Adapter(Technical(payload=payload))
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["categorias"], [])

    def test_adapter_error_timeout_and_incomplete_payload(self):
        failed = consultar_analisis_categorias(
            self.request(), adapter=Adapter(Technical(success=False, stderr="fallo"))
        )
        timeout = consultar_analisis_categorias(
            self.request(), adapter=Adapter(Technical(success=False, timed_out=True))
        )
        invalid = consultar_analisis_categorias(
            self.request(), adapter=Adapter(Technical(payload={"estado": "OK"}))
        )
        self.assertEqual(failed.error.code, "analisis_categorias_error")
        self.assertEqual(timeout.error.code, "analisis_categorias_timeout")
        self.assertEqual(invalid.error.code, "respuesta_invalida")


if __name__ == "__main__":
    unittest.main()
