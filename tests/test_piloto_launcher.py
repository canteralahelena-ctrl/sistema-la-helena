import unittest
from pathlib import Path


class PilotoLauncherTests(unittest.TestCase):
    def setUp(self):
        self.script = Path(__file__).resolve().parents[1] / "piloto_work_v2.ps1"
        self.text = self.script.read_text(encoding="utf-8-sig")

    def test_refresh_runs_before_pilot_mode_is_enabled(self):
        refresh_index = self.text.index("actualizar_copia_base.ps1")
        pilot_index = self.text.index('$env:HELENA_PILOT_MODE = "1"')
        self.assertLess(refresh_index, pilot_index)

    def test_refresh_reuses_existing_updater_with_selected_base(self):
        self.assertIn('$updateScript = Join-Path $pilotRoot "actualizar_copia_base.ps1"', self.text)
        self.assertIn("-File $updateScript -Destino $resolvedBase", self.text)
        self.assertIn("$env:HELENA_LOCAL_DATABASE = $resolvedBase", self.text)

    def test_refresh_failure_requires_existing_local_copy(self):
        self.assertIn("ADVERTENCIA: no se pudo refrescar la copia local antes del piloto", self.text)
        self.assertIn("No existe copia local valida para continuar el piloto", self.text)


if __name__ == "__main__":
    unittest.main()
