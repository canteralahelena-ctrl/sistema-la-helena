import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from helena_core.integrations.powershell.cliente_saldo_adapter import ClienteSaldoPowerShellAdapter
from helena_core.settings import load_settings


@dataclass
class Completed:
    returncode: int
    stdout: str
    stderr: str


class RecordingRunner:
    def __init__(self, completed):
        self.completed = completed
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return self.completed


class ClienteSaldoAdapterTests(unittest.TestCase):
    def make_settings(self, root):
        config_dir = Path(root) / "config"
        config_dir.mkdir(parents=True)
        config_path = config_dir / "environment.json"
        config_path.write_text(
            json.dumps(
                {
                    "executables": {"powershell": "pwsh-test"},
                    "timeouts": {"default_script_seconds": 77},
                }
            ),
            encoding="utf-8",
        )
        return load_settings(root=root, config_path=config_path, environ={})

    def make_settings_with_database(self, root):
        config_dir = Path(root) / "config"
        config_dir.mkdir(parents=True)
        database = Path(root) / "data" / "test.accdb"
        database.parent.mkdir(parents=True)
        database.write_bytes(b"test")
        config_path = config_dir / "environment.json"
        config_path.write_text(
            json.dumps(
                {
                    "local_database_path": "data/test.accdb",
                    "executables": {"powershell": "pwsh-test"},
                    "timeouts": {"default_script_seconds": 77},
                }
            ),
            encoding="utf-8",
        )
        return load_settings(root=root, config_path=config_path, environ={})

    def test_command_uses_cliente_rapido_script_and_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.make_settings(Path(tmp))
            adapter = ClienteSaldoPowerShellAdapter(settings=settings, runner=RecordingRunner(Completed(0, "", "")))

            command = adapter.build_command("CLIENTE")

        self.assertEqual(command[0], "pwsh-test")
        self.assertEqual(command[1:5], ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"])
        self.assertEqual(Path(command[5]).name, "cliente_rapido.ps1")
        self.assertEqual(command[-1], "CLIENTE")

    def test_development_command_passes_existing_local_database_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.make_settings_with_database(Path(tmp))
            adapter = ClienteSaldoPowerShellAdapter(settings=settings, runner=RecordingRunner(Completed(0, "", "")))

            command = adapter.build_command("CLIENTE")

        self.assertIn("-DatabasePath", command)
        self.assertEqual(command[-2], "-DatabasePath")
        self.assertEqual(Path(command[-1]).name, "test.accdb")

    def test_missing_local_database_does_not_add_database_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.make_settings(Path(tmp))
            adapter = ClienteSaldoPowerShellAdapter(settings=settings, runner=RecordingRunner(Completed(0, "", "")))

            command = adapter.build_command("CLIENTE")

        self.assertNotIn("-DatabasePath", command)

    def test_runner_receives_flags_cwd_timeout_and_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.make_settings(Path(tmp))
            runner = RecordingRunner(Completed(0, "Cliente: CLIENTE", ""))
            adapter = ClienteSaldoPowerShellAdapter(settings=settings, runner=runner)

            result = adapter.consultar_saldo("CLIENTE")

        command, kwargs = runner.calls[0]
        self.assertEqual(command[-1], "CLIENTE")
        self.assertEqual(kwargs["cwd"], str(settings.paths.root))
        self.assertTrue(kwargs["capture_output"])
        self.assertEqual(kwargs["timeout"], 77)
        self.assertTrue(result.success)
        self.assertEqual(result.stdout, "Cliente: CLIENTE")

    def test_captures_return_code_stdout_and_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.make_settings(Path(tmp))
            runner = RecordingRunner(Completed(2, "salida", "error"))
            adapter = ClienteSaldoPowerShellAdapter(settings=settings, runner=runner)

            result = adapter.consultar_saldo("CLIENTE")

        self.assertFalse(result.success)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "salida")
        self.assertEqual(result.stderr, "error")

    def test_adapter_does_not_import_telegram(self):
        import helena_core.integrations.powershell.cliente_saldo_adapter as adapter_module

        self.assertFalse(hasattr(adapter_module, "telegram"))
        self.assertNotIn("telegram", (adapter_module.__doc__ or "").lower())


if __name__ == "__main__":
    unittest.main()
