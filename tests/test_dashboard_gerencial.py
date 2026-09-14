import json
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import telegram_access_bot


class DashboardGerencialIntegrationTests(unittest.TestCase):
    def test_access_dashboard_treats_nullable_amounts_as_zero(self):
        periods = {
            "previous_week": {
                "start": date(2026, 9, 7),
                "end": date(2026, 9, 13),
            }
        }
        payload = json.dumps({"Estado": "OK", "Registros": [], "Clientes": []})

        with patch.object(telegram_access_bot, "CONFIG", {"powershell": "powershell"}, create=True):
            with patch.object(
                telegram_access_bot,
                "powershell_inline_command",
                side_effect=lambda script, **_: script,
            ):
                with patch.object(
                    telegram_access_bot,
                    "run_text_subprocess",
                    return_value=SimpleNamespace(returncode=0, stdout=payload, stderr=""),
                ) as runner:
                    result = telegram_access_bot.dashboard_access_data_for_periods(periods)

        script = runner.call_args.args[0]
        for field in (
            "Emitido",
            "PendienteActual",
            "CobradoAplicado",
            "CobradoPorSaldo",
            "DiferenciaControl",
            "Importe",
        ):
            self.assertRegex(
                script,
                rf'{field}.*ConvertTo-HelenaDecimal .* "ZERO"',
            )
        self.assertEqual(result, {"Registros": [], "Clientes": []})

    def test_iva_keeps_ids_and_dates_strict_but_accepts_nullable_amounts(self):
        script = (Path(telegram_access_bot.ROOT) / "iva_mensual.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn(
            'ConvertTo-HelenaDecimal $v.IMPORTE "COMPROVANTES.IMPORTE" "ZERO"',
            script,
        )
        self.assertIn(
            'ConvertTo-HelenaDecimal $g.IMPORTE "COMPROVANTES DE GASTOS.IMPORTE" "ZERO"',
            script,
        )
        self.assertIn(
            'ConvertTo-HelenaInteger $v.Id "COMPROVANTES.IdCOMPROVANTE" "BLOCK"',
            script,
        )
        self.assertIn(
            'ConvertTo-HelenaDate $g.FECHA "COMPROVANTES DE GASTOS.FECHA" "BLOCK"',
            script,
        )

    def test_cheques_dashboard_preserves_work_scope_over_core_payload(self):
        data = {
            "total_cartera": {"total": 1500},
            "a_cobrar": {"total": 900},
            "a_depositar": {"0-7 DIAS": {"total": 600}},
            "cheques": [
                {"importe": 100, "dias_restantes": 0, "dias_al_vencimiento": 30, "tramo": "0-7 DIAS", "observacion": ""},
                {"importe": 200, "dias_restantes": 3, "dias_al_vencimiento": 33, "tramo": "0-7 DIAS", "observacion": "NN"},
                {"importe": 400, "dias_restantes": 2, "dias_al_vencimiento": 32, "tramo": "0-7 DIAS", "observacion": "EN CUENTA DE HUGO"},
                {"importe": 800, "dias_restantes": -31, "dias_al_vencimiento": -1, "tramo": "VENCIDO", "observacion": ""},
            ],
        }
        with patch.object(telegram_access_bot, "execute_cheques_core", return_value=data):
            result = telegram_access_bot.dashboard_cheques_values()

        self.assertEqual(
            result,
            {
                "total": "$ 300,00",
                "cobrar_hoy": "$ 100,00",
                "depositar_0_7": "$ 200,00",
            },
        )


if __name__ == "__main__":
    unittest.main()
