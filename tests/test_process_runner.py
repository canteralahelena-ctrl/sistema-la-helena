import sys
import unittest
from pathlib import Path

from helena_core.process_runner import (
    PS_UTF8_SETUP,
    powershell_file_command,
    powershell_inline_command,
    ps_quote,
    run_text_subprocess,
    subprocess_utf8_env,
)


class ProcessRunnerTests(unittest.TestCase):
    def test_powershell_file_command_preserves_flags_and_arguments(self):
        command = powershell_file_command(
            Path("script.ps1"),
            ["uno", 2],
            powershell_executable="pwsh",
        )

        self.assertEqual(
            command,
            [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                "script.ps1",
                "uno",
                "2",
            ],
        )

    def test_powershell_inline_command_adds_utf8_setup(self):
        command = powershell_inline_command("Write-Output 'ok'", powershell_executable="pwsh")

        self.assertEqual(command[:5], ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"])
        self.assertIn(PS_UTF8_SETUP, command[5])
        self.assertTrue(command[5].endswith("Write-Output 'ok'"))

    def test_ps_quote_escapes_apostrophe(self):
        self.assertEqual(ps_quote("O'Brien"), "'O''Brien'")

    def test_subprocess_utf8_env_preserves_extra_values(self):
        env = subprocess_utf8_env({"HELENA_TEST_VALUE": "1"})

        self.assertEqual(env["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(env["HELENA_TEST_VALUE"], "1")

    def test_run_text_subprocess_reads_utf8_text(self):
        completed = run_text_subprocess(
            [sys.executable, "-c", "print('áéíóú ñ')"],
            capture_output=True,
            check=True,
        )

        self.assertEqual(completed.stdout.strip(), "áéíóú ñ")


if __name__ == "__main__":
    unittest.main()
