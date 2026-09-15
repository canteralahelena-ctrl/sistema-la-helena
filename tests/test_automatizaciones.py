import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import ejecutar_automatizacion


ROOT = Path(__file__).resolve().parents[1]


class AutomatizacionesTests(unittest.TestCase):
    def config(self, directory, **overrides):
        data = {
            "environment": "production",
            "telegram_enabled": True,
            "automatic_alerts_enabled": True,
            "scheduled_tasks_enabled": True,
        }
        data.update(overrides)
        path = Path(directory) / "environment.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_guard_rejects_development_disabled_flags_and_pilot(self):
        with tempfile.TemporaryDirectory() as tmp:
            development = self.config(tmp, environment="development")
            with self.assertRaisesRegex(RuntimeError, "no productivo"):
                ejecutar_automatizacion.validate_automation_environment(development)
            disabled = self.config(tmp, automatic_alerts_enabled=False)
            with self.assertRaisesRegex(RuntimeError, "automatic_alerts_enabled"):
                ejecutar_automatizacion.validate_automation_environment(disabled)
            enabled = self.config(tmp)
            with patch.dict(os.environ, {"HELENA_PILOT_MODE": "1"}):
                with self.assertRaisesRegex(RuntimeError, "piloto"):
                    ejecutar_automatizacion.validate_automation_environment(enabled)

    def test_one_shot_delegates_to_existing_cheque_and_dashboard_functions(self):
        client = Mock()
        with (
            patch.object(ejecutar_automatizacion, "validate_automation_environment"),
            patch.object(ejecutar_automatizacion.telegram_bot, "load_config", return_value={"telegram_bot_token": "fixture"}),
            patch.object(ejecutar_automatizacion.telegram_bot, "Telegram", return_value=client),
            patch.object(ejecutar_automatizacion.telegram_bot, "maybe_send_cheque_alerts") as cheques,
            patch.object(ejecutar_automatizacion.telegram_bot, "maybe_send_dashboard_gerencial_weekly") as resumen,
        ):
            ejecutar_automatizacion.run("cheques")
            ejecutar_automatizacion.run("resumen-gerencial")
        cheques.assert_called_once_with(client)
        resumen.assert_called_once_with(client)

    def test_windows_scripts_keep_pilot_and_central_flag_guards(self):
        runner = (ROOT / "ejecutar_automatizacion.ps1").read_text(encoding="utf-8-sig")
        installer = (ROOT / "instalar_automatizaciones.ps1").read_text(encoding="utf-8-sig")
        for text in (runner, installer):
            self.assertIn('HELENA_PILOT_MODE -eq "1"', text)
            self.assertIn("scheduled_tasks_enabled", text)
            self.assertIn("environment.json", text)
        self.assertIn('"auditoria_semanal_maxi.ps1"', runner)
        self.assertIn("maybe_send_cheque_alerts", Path(ROOT / "ejecutar_automatizacion.py").read_text())
        self.assertEqual(installer.count('Schedule = "WEEKLY"'), 2)
        self.assertEqual(installer.count('Schedule = "DAILY"'), 1)


if __name__ == "__main__":
    unittest.main()
