import unittest

from helena_core.application.contracts import ErrorInfo, Request, Result, UserContext


class ContractTests(unittest.TestCase):
    def test_valid_request_can_be_built(self):
        request = Request(
            capability="clientes.saldo",
            parameters={"cliente": "CLIENTE"},
            user_context=UserContext(user_id="u1", roles=["operador"]),
            channel="test",
        )

        self.assertEqual(request.capability, "clientes.saldo")
        self.assertEqual(request.parameters["cliente"], "CLIENTE")
        self.assertEqual(request.user_context.roles, ["operador"])
        self.assertEqual(request.channel, "test")
        self.assertTrue(request.request_id)

    def test_valid_result_can_be_built(self):
        error = ErrorInfo(code="codigo", message="mensaje")
        result = Result(success=False, message="texto", error=error)

        self.assertFalse(result.success)
        self.assertEqual(result.message, "texto")
        self.assertEqual(result.error.code, "codigo")

    def test_defaults_are_safe_and_isolated(self):
        first = Result(success=True)
        second = Result(success=True)
        first.warnings.append("aviso")

        self.assertEqual(first.data, {})
        self.assertEqual(second.warnings, [])
        self.assertEqual(first.files, [])
        self.assertIsNone(second.error)

    def test_contracts_do_not_depend_on_telegram(self):
        import helena_core.application.contracts as contracts

        self.assertNotIn("telegram", (contracts.__doc__ or "").lower())
        self.assertFalse(hasattr(contracts, "Update"))
        self.assertFalse(hasattr(contracts, "Context"))
        self.assertFalse(hasattr(contracts, "Message"))
        self.assertFalse(hasattr(contracts, "Bot"))


if __name__ == "__main__":
    unittest.main()
