import unittest

from helena_core.application.contracts import Request
from helena_core.business.ventas.productos_no_clasificados import consultar_productos_no_clasificados


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
        self.calls = []

    def consultar_productos_no_clasificados(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class ProductosNoClasificadosServiceTests(unittest.TestCase):
    def request(self):
        return Request(
            capability="ventas.productos_no_clasificados",
            parameters={"fecha_desde": "2026-07-01", "fecha_hasta": "2026-07-20"},
        )

    def payload(self, records):
        return {
            "estado": "OK",
            "fecha_desde": "2026-07-01",
            "fecha_hasta": "2026-07-20",
            "registros": records,
            "cantidad_total": len(records),
            "advertencias": [],
            "archivo_csv": "salida.no_clasificados.csv",
            "archivos_generados": [],
        }

    def test_returns_complete_grouped_structure_in_legacy_order(self):
        records = [
            {"producto_descripcion": "Árido especial", "importe": "20", "cliente": "B"},
            {"producto_descripcion": "Otro", "importe": "5", "cliente": "C"},
            {"producto_descripcion": "Árido especial", "importe": "80", "cliente": "A"},
        ]
        adapter = Adapter(Technical(payload=self.payload(records)))
        result = consultar_productos_no_clasificados(self.request(), adapter=adapter)
        self.assertTrue(result.success)
        self.assertEqual(result.data["cantidad_total"], 3)
        self.assertEqual(result.data["importe_total"], "105")
        self.assertEqual([item["producto"] for item in result.data["grupos"]], ["Árido especial", "Otro"])
        self.assertEqual(result.data["grupos"][0]["registros"][0]["importe"], "80")
        self.assertEqual(
            adapter.calls,
            [{"fecha_desde": "2026-07-01", "fecha_hasta": "2026-07-20"}],
        )

    def test_empty_result_is_valid(self):
        result = consultar_productos_no_clasificados(
            self.request(), adapter=Adapter(Technical(payload=self.payload([])))
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["grupos"], [])
        self.assertEqual(result.data["importe_total"], "0")

    def test_applies_existing_limits_without_losing_full_records(self):
        records = []
        for product in range(10):
            for item in range(6):
                records.append(
                    {
                        "producto_descripcion": f"Producto {product}",
                        "importe": str(1000 - product * 10 - item),
                    }
                )
        result = consultar_productos_no_clasificados(
            self.request(), adapter=Adapter(Technical(payload=self.payload(records)))
        )
        self.assertEqual(len(result.data["registros"]), 60)
        self.assertEqual(len(result.data["grupos"]), 8)
        self.assertEqual(len(result.data["grupos"][0]["registros"]), 5)
        self.assertEqual(result.data["productos_ocultos"], 2)
        self.assertTrue(result.data["truncado"])

    def test_adapter_error_and_timeout_are_structured(self):
        failed = consultar_productos_no_clasificados(
            self.request(), adapter=Adapter(Technical(success=False, stderr="fallo controlado"))
        )
        timeout = consultar_productos_no_clasificados(
            self.request(), adapter=Adapter(Technical(success=False, timed_out=True))
        )
        self.assertEqual(failed.error.code, "productos_no_clasificados_error")
        self.assertEqual(timeout.error.code, "productos_no_clasificados_timeout")


if __name__ == "__main__":
    unittest.main()
