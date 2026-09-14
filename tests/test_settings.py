import json
import tempfile
import unittest
from pathlib import Path

from helena_core.settings import load_settings


class SettingsTests(unittest.TestCase):
    def write_config(self, root, data):
        config_dir = Path(root) / "config"
        config_dir.mkdir(parents=True)
        path = config_dir / "environment.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_detects_work_v2_root_and_default_paths(self):
        settings = load_settings()
        root = Path(__file__).resolve().parents[1]

        self.assertEqual(settings.paths.root, root)
        self.assertEqual(settings.paths.scripts, root)
        self.assertEqual(settings.paths.outputs, root / "outputs")
        self.assertEqual(settings.paths.logs, root / "logs")
        self.assertEqual(settings.private_config.telegram_bot_config, root / "telegram_bot_config.json")
        self.assertEqual(settings.technical.powershell_executable, "powershell")
        self.assertEqual(settings.databases.local_database, root / "data" / "test_database" / "CANTERA_LA_HELENA_TEST.accdb")
        self.assertFalse(settings.databases.allow_database_writes)
        self.assertEqual(settings.environment.environment, "development")

    def test_resolves_relative_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sample"
            config_path = self.write_config(
                root,
                {
                    "paths": {
                        "scripts": "scripts",
                        "outputs": "out",
                        "logs": "log",
                        "data": "data_files",
                        "private_config": "private/app.json",
                        "local_database": "data/test.accdb",
                    },
                    "executables": {"powershell": "pwsh", "ffmpeg": "ffmpeg-local", "lock_port": 49000},
                    "databases": {"server_ref": "configured-reference"},
                    "timeouts": {"payment_seconds": 75, "dashboard_cache_ttl_seconds": 30},
                },
            )

            settings = load_settings(root=root, config_path=config_path, environ={})

        self.assertEqual(settings.paths.scripts, root / "scripts")
        self.assertEqual(settings.paths.outputs, root / "out")
        self.assertEqual(settings.paths.logs, root / "log")
        self.assertEqual(settings.private_config.telegram_bot_config, root / "private" / "app.json")
        self.assertEqual(settings.databases.local_database, root / "data" / "test.accdb")
        self.assertEqual(settings.databases.server_database_ref, "configured-reference")
        self.assertEqual(settings.technical.powershell_executable, "pwsh")
        self.assertEqual(settings.technical.ffmpeg_executable, "ffmpeg-local")
        self.assertEqual(settings.technical.lock_port, 49000)
        self.assertEqual(settings.timeouts.payment_seconds, 75)
        self.assertEqual(settings.timeouts.dashboard_cache_ttl_seconds, 30)

    def test_environment_overrides_are_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sample"
            config_path = self.write_config(root, {"paths": {"outputs": "from_config"}})
            env_outputs = Path(tmp) / "env_outputs"
            settings = load_settings(
                root=root,
                config_path=config_path,
                environ={
                    "HELENA_OUTPUTS_DIR": str(env_outputs),
                    "HELENA_POWERSHELL_EXE": "pwsh",
                    "HELENA_FFMPEG_EXE": "ffmpeg-env",
                    "HELENA_SERVER_DATABASE_REF": "env-reference",
                },
            )

        self.assertEqual(settings.paths.outputs, env_outputs)
        self.assertEqual(settings.technical.powershell_executable, "pwsh")
        self.assertEqual(settings.technical.ffmpeg_executable, "ffmpeg-env")
        self.assertEqual(settings.databases.server_database_ref, "env-reference")

    def test_top_level_local_database_path_is_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sample"
            config_path = self.write_config(
                root,
                {
                    "local_database_path": "data/test.accdb",
                    "allow_database_writes": True,
                },
            )
            settings = load_settings(root=root, config_path=config_path, environ={})

        self.assertEqual(settings.databases.local_database, root / "data" / "test.accdb")
        self.assertFalse(settings.databases.allow_database_writes)

    def test_missing_config_fails_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "missing_root"
            settings = load_settings(root=root, config_path=root / "config" / "missing.json", environ={})

        self.assertFalse(settings.source_found)
        self.assertFalse(settings.environment.telegram_enabled)
        self.assertFalse(settings.environment.server_writes_enabled)
        self.assertEqual(settings.paths.outputs, root / "outputs")
        self.assertEqual(settings.databases.local_database, None)

    def test_load_does_not_create_output_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sample"
            config_path = self.write_config(root, {"paths": {"outputs": "out", "logs": "logs", "data": "data"}})
            outputs = root / "out"
            logs = root / "logs"
            data = root / "data"

            load_settings(root=root, config_path=config_path, environ={})

            self.assertFalse(outputs.exists())
            self.assertFalse(logs.exists())
            self.assertFalse(data.exists())

    def test_private_values_are_not_exposed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sample"
            config_path = self.write_config(
                root,
                {
                    "private_value": "hidden-value",
                    "private_config": {"email_config": "email_config.json"},
                },
            )
            settings = load_settings(root=root, config_path=config_path, environ={})

        exported = settings.as_dict()
        self.assertNotIn("private_value", exported)
        self.assertNotIn("hidden-value", str(exported))

    def test_settings_module_has_no_external_runtime_access(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "helena_core" / "settings.py").read_text(encoding="utf-8")

        for value in ("subprocess", "urllib", "socket", "pyodbc", "win32com", "ADODB"):
            self.assertNotIn(value, text)

    def test_new_module_does_not_embed_machine_paths(self):
        root = Path(__file__).resolve().parents[1]
        checked = [
            root / "helena_core" / "settings.py",
            root / "tests" / "test_settings.py",
        ]
        forbidden = ("C:" + "\\", "Users" + "\\", "Documents" + "\\", "Co" + "dex", "\\" + "Server")

        for path in checked:
            text = path.read_text(encoding="utf-8")
            for value in forbidden:
                self.assertNotIn(value, text)


if __name__ == "__main__":
    unittest.main()
