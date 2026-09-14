import importlib
import io
import subprocess
import os
import sys
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class BotEnvironmentGuardTests(unittest.TestCase):
    def test_importing_bot_module_does_not_start_telegram(self):
        module = importlib.import_module("telegram_access_bot")

        self.assertTrue(callable(module.main))
        self.assertTrue((ROOT / "config" / "environment.json").exists())

    def test_refresh_access_after_import_does_not_require_loaded_telegram_config(self):
        module = importlib.import_module("telegram_access_bot")
        if hasattr(module, "CONFIG"):
            delattr(module, "CONFIG")

        output = io.StringIO()
        with patch.object(module, "run_text_subprocess") as runner, redirect_stdout(output):
            module.refresh_access()

        runner.assert_called_once()
        self.assertNotIn("CONFIG", output.getvalue())

    def test_load_config_accepts_json_with_or_without_utf8_bom(self):
        module = importlib.import_module("telegram_access_bot")

        for encoding in ("utf-8", "utf-8-sig"):
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory() as tmp:
                config_path = Path(tmp) / "pilot.telegram.json"
                config_path.write_text(
                    json.dumps({"telegram_bot_token": ""}),
                    encoding=encoding,
                )

                with (
                    patch.object(module, "CONFIG_PATH", config_path),
                    patch.object(module, "EXAMPLE_CONFIG_PATH", Path(tmp) / "example.json"),
                    patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fixture-token"}, clear=False),
                ):
                    config = module.load_config()

                self.assertEqual(config["telegram_bot_token"], "fixture-token")
                self.assertIn("allowed_chat_ids", config)

    def test_load_config_invalid_json_still_fails(self):
        module = importlib.import_module("telegram_access_bot")

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "pilot.telegram.json"
            config_path.write_text("{", encoding="utf-8-sig")

            with (
                patch.object(module, "CONFIG_PATH", config_path),
                patch.object(module, "EXAMPLE_CONFIG_PATH", Path(tmp) / "example.json"),
                patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fixture-token"}, clear=False),
            ):
                with self.assertRaises(json.JSONDecodeError):
                    module.load_config()

    def test_development_execution_finishes_without_polling(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "telegram_access_bot.py")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        output = (completed.stdout or "") + (completed.stderr or "")

        self.assertEqual(completed.returncode, 0)
        self.assertIn("Telegram deshabilitado por entorno de desarrollo", output)
        self.assertNotIn("getUpdates", output)
        self.assertNotIn("Bot conectado", output)

    def test_pilot_refuses_production_config_and_never_polls(self):
        env = os.environ.copy()
        env.update(
            {
                "HELENA_PILOT_MODE": "1",
                "HELENA_PILOT_TELEGRAM": "1",
                "TELEGRAM_BOT_TOKEN": "fixture-token-not-real",
            }
        )
        completed = subprocess.run(
            [sys.executable, str(ROOT / "telegram_access_bot.py")],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        output = (completed.stdout or "") + (completed.stderr or "")

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("HELENA_PRIVATE_CONFIG separado", output)
        self.assertNotIn("getUpdates", output)


if __name__ == "__main__":
    unittest.main()
