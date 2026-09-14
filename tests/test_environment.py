import json
import tempfile
import unittest
from pathlib import Path

from helena_core.environment import load_environment


class EnvironmentTests(unittest.TestCase):
    def write_config(self, directory, data):
        path = Path(directory) / "environment.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_reads_development_file_with_safe_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_config(
                tmp,
                {
                    "environment": "development",
                    "telegram_enabled": True,
                    "automatic_alerts_enabled": True,
                    "server_writes_enabled": True,
                    "scheduled_tasks_enabled": True,
                    "use_local_database_only": False,
                },
            )
            settings = load_environment(path)

        self.assertEqual(settings.environment, "development")
        self.assertFalse(settings.telegram_enabled)
        self.assertFalse(settings.automatic_alerts_enabled)
        self.assertFalse(settings.server_writes_enabled)
        self.assertFalse(settings.scheduled_tasks_enabled)
        self.assertTrue(settings.use_local_database_only)
        self.assertIn("telegram_enabled", settings.neutralized_keys)
        self.assertIn("use_local_database_only", settings.neutralized_keys)

    def test_missing_file_uses_safe_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = load_environment(Path(tmp) / "missing.json")

        self.assertEqual(
            settings.as_dict(),
            {
                "environment": "development",
                "pilot_mode": False,
                "telegram_enabled": False,
                "automatic_alerts_enabled": False,
                "server_writes_enabled": False,
                "scheduled_tasks_enabled": False,
                "use_local_database_only": True,
            },
        )
        self.assertFalse(settings.source_found)

    def test_pilot_mode_is_read_only_and_requires_explicit_telegram_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_config(tmp, {"environment": "development"})
            safe = load_environment(path, environ={"HELENA_PILOT_MODE": "1"})
            telegram = load_environment(
                path,
                environ={"HELENA_PILOT_MODE": "1", "HELENA_PILOT_TELEGRAM": "1"},
            )

        self.assertTrue(safe.pilot_mode)
        self.assertFalse(safe.telegram_enabled)
        self.assertFalse(safe.automatic_alerts_enabled)
        self.assertFalse(safe.server_writes_enabled)
        self.assertFalse(safe.scheduled_tasks_enabled)
        self.assertTrue(safe.use_local_database_only)
        self.assertTrue(telegram.pilot_mode)
        self.assertTrue(telegram.telegram_enabled)

    def test_non_development_is_neutralized(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_config(
                tmp,
                {
                    "environment": "production",
                    "telegram_enabled": True,
                    "automatic_alerts_enabled": True,
                    "server_writes_enabled": True,
                    "scheduled_tasks_enabled": True,
                    "use_local_database_only": False,
                },
            )
            settings = load_environment(path)

        self.assertEqual(settings.environment, "development")
        self.assertEqual(settings.invalid_environment, "production")
        self.assertFalse(settings.telegram_enabled)
        self.assertFalse(settings.automatic_alerts_enabled)
        self.assertFalse(settings.server_writes_enabled)
        self.assertFalse(settings.scheduled_tasks_enabled)
        self.assertTrue(settings.use_local_database_only)

    def test_unknown_private_values_are_not_exposed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_config(
                tmp,
                {
                    "environment": "development",
                    "private_api_key": "hidden-value",
                    "mail_password": "hidden-value",
                },
            )
            settings = load_environment(path)

        exported = settings.as_dict()
        self.assertNotIn("private_api_key", exported)
        self.assertNotIn("mail_password", exported)
        self.assertNotIn("hidden-value", str(exported))


if __name__ == "__main__":
    unittest.main()
