import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import telegram_access_bot


ROOT = Path(__file__).resolve().parents[1]


class PilotModeTests(unittest.TestCase):
    def test_launcher_is_safe_by_default_and_uses_isolated_paths(self):
        launcher = (ROOT / "piloto_work_v2.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('HELENA_PILOT_MODE = "1"', launcher)
        self.assertIn('HELENA_PILOT_TELEGRAM = if ($IniciarTelegram)', launcher)
        self.assertIn('"outputs\\pilot"', launcher)
        self.assertIn('"logs\\pilot"', launcher)
        self.assertIn('"data\\pilot"', launcher)
        self.assertIn('HELENA_LOCAL_DATABASE', launcher)
        self.assertIn('HELENA_PRIVATE_CONFIG', launcher)
        self.assertIn('HELENA_TELEGRAM_USERS', launcher)
        self.assertIn('HELENA_TELEGRAM_PENDING_USERS', launcher)
        self.assertIn('HELENA_LOCK_PORT = "47826"', launcher)
        self.assertIn("Telegram no fue iniciado", launcher)
        self.assertIn("HELENA_PYTHON_EXECUTABLE", launcher)
        self.assertIn("Resolve-PilotPython", launcher)
        self.assertIn("WindowsApps", launcher)
        self.assertIn("No se encontro un Python valido", launcher)

    def test_launcher_rejects_windowsapps_python_alias(self):
        launcher = (ROOT / "piloto_work_v2.ps1").read_text(encoding="utf-8-sig")

        self.assertIn('WindowsApps\\\\python(?:3)?\\.exe', launcher)
        self.assertIn("alias de WindowsApps", launcher)

    def test_pilot_user_keeps_real_read_permissions_for_hugo(self):
        data = json.loads((ROOT / "config" / "pilot.telegram_usuarios.json").read_text(encoding="utf-8-sig"))
        users = data.get("usuarios") or []
        roles = data.get("roles") or {}
        admin_permissions = set((roles.get("administrador") or {}).get("permisos") or [])

        self.assertEqual(len(users), 1)
        self.assertEqual(users[0].get("nombre"), "Hugo")
        self.assertEqual(users[0].get("rol"), "administrador")
        self.assertTrue(users[0].get("activo"))
        self.assertTrue(
            {"saldos", "facturas", "clientes", "reportes", "cheques", "caja"}.issubset(admin_permissions)
        )

    def test_critical_runtime_files_do_not_route_to_work(self):
        files = [
            "actualizar_copia_base.ps1",
            "cache_access.ps1",
            "consulta_cache.ps1",
            "consultas_rapidas.ps1",
            "auditoria_usuario_3.ps1",
            "auditoria_semanal_maxi.ps1",
            "generar_excel_auditoria.py",
        ]
        for relative in files:
            with self.subTest(file=relative):
                text = (ROOT / relative).read_text(encoding="utf-8-sig").lower()
                self.assertNotIn('join-path $root "work\\', text)
                self.assertNotIn('root / "work"', text)

    def test_pilot_blocks_server_copy_audits_and_email(self):
        for relative in (
            "actualizar_copia_base.ps1",
            "auditoria_semanal_maxi.ps1",
            "enviar_mail_auditoria.ps1",
        ):
            with self.subTest(file=relative):
                text = (ROOT / relative).read_text(encoding="utf-8-sig")
                self.assertIn('HELENA_PILOT_MODE -eq "1"', text)

    def test_bot_pilot_has_explicit_read_only_whitelist_and_label(self):
        text = (ROOT / "telegram_access_bot.py").read_text(encoding="utf-8-sig")
        self.assertIn("PILOT_READ_ONLY_KINDS", text)
        self.assertIn("kind not in PILOT_READ_ONLY_KINDS", text)
        self.assertIn("[work_v2 PILOTO]", text)
        self.assertNotIn('"auditoria_mail_only",\n}', text)
        self.assertIn("diccionario_intencion", telegram_access_bot.PILOT_READ_ONLY_KINDS)
        self.assertNotIn("auditoria_mail_only", telegram_access_bot.PILOT_READ_ONLY_KINDS)

    def transcribe_fixture(self, text):
        class Bot:
            def get_file(self, file_id):
                return {"result": {"file_path": "voice/file.oga"}}

            def download_file(self, file_path, target):
                Path(target).write_text("audio", encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(telegram_access_bot, "VOICE_DIR", Path(tmp)):
                with patch.object(telegram_access_bot, "convert_voice_to_mp3", side_effect=lambda path: path):
                    with patch.object(telegram_access_bot, "transcribe_audio", return_value=text):
                        return telegram_access_bot.handle_voice(Bot(), {"audio": {"file_id": "audio-file-id"}})

    def test_audio_attachment_is_transcribed_as_text_input(self):
        transcript, kind, params = self.transcribe_fixture("saldo Basadella")

        self.assertEqual("saldo Basadella", transcript)
        self.assertEqual("saldo", kind)
        self.assertEqual("Basadella", params["cliente"])

    def test_audio_sales_query_reaches_dictionary_parser_as_read_query(self):
        intent = {
            "id": "ventas_rapidas",
            "descripcion": "Ventas rapidas",
            "script": "work/analisis_categorias.ps1",
            "parametros_base": {"Tipos": "Ambos"},
            "frase_usuario": "ventas de ayer",
            "texto_original": "ventas de ayer",
            "parametros": {},
        }
        with patch.object(telegram_access_bot, "match_intent_dictionary", return_value=intent):
            transcript, kind, params = self.transcribe_fixture("ventas de ayer")

        self.assertEqual("ventas de ayer", transcript)
        self.assertEqual("diccionario_intencion", kind)
        self.assertEqual("ventas_rapidas", params["id"])
        self.assertIn(kind, telegram_access_bot.PILOT_READ_ONLY_KINDS)

    def test_transcribed_allowed_query_uses_normal_text_pipeline(self):
        class Bot:
            def __init__(self):
                self.messages = []
                self.actions = []

            def send_action(self, chat_id, action):
                self.actions.append((chat_id, action))

            def send_message(self, chat_id, text):
                self.messages.append((chat_id, text))

        bot = Bot()
        with patch.object(telegram_access_bot, "PILOT_MODE", True):
            with patch.object(telegram_access_bot, "log_event"):
                with patch.object(telegram_access_bot, "parse_command", return_value=("saldo", {"cliente": "Basadella"})):
                    with patch.object(telegram_access_bot, "authorize_command", return_value=(True, "")):
                        with patch.object(
                            telegram_access_bot,
                            "prepare_client_query",
                            return_value=("execute", "saldo", {"cliente": "Basadella", "chat_id": 7}),
                        ):
                            with patch.object(telegram_access_bot, "auditar_consulta"):
                                with patch.object(telegram_access_bot, "handle_command", return_value=("text", "OK saldo")):
                                    with patch.object(
                                        telegram_access_bot, "CONFIG", {"max_text_chars": 3500}, create=True
                                    ):
                                        telegram_access_bot.process_text_query(
                                            bot,
                                            7,
                                            "saldo Basadella",
                                            source_object="Audio",
                                            unknown_description="Audio no interpretado",
                                        )

        self.assertIn((7, "OK saldo"), bot.messages)

    def test_normal_text_pipeline_is_unchanged(self):
        class Bot:
            def __init__(self):
                self.messages = []
                self.actions = []

            def send_action(self, chat_id, action):
                self.actions.append((chat_id, action))

            def send_message(self, chat_id, text):
                self.messages.append((chat_id, text))

        bot = Bot()
        with patch.object(telegram_access_bot, "PILOT_MODE", True):
            with patch.object(telegram_access_bot, "log_event"):
                with patch.object(telegram_access_bot, "parse_command", return_value=("saldo", {"cliente": "Basadella"})):
                    with patch.object(telegram_access_bot, "authorize_command", return_value=(True, "")):
                        with patch.object(
                            telegram_access_bot,
                            "prepare_client_query",
                            return_value=("ready", "saldo", {"cliente": "Basadella", "chat_id": 7}),
                        ):
                            with patch.object(telegram_access_bot, "auditar_consulta"):
                                with patch.object(telegram_access_bot, "handle_command", return_value=("text", "OK texto")):
                                    with patch.object(
                                        telegram_access_bot, "CONFIG", {"max_text_chars": 3500}, create=True
                                    ):
                                        telegram_access_bot.process_text_query(bot, 7, "saldo Basadella")

        self.assertEqual([(7, "OK texto")], bot.messages)

    def test_dictionary_read_intent_is_allowed_in_pilot(self):
        intent = {
            "id": "ventas_rapidas",
            "descripcion": "Ventas rapidas",
            "script": "work/analisis_categorias.ps1",
            "parametros_base": {"Tipos": "Ambos"},
            "frase_usuario": "ventas de ayer",
            "texto_original": "ventas de ayer",
            "parametros": {},
        }
        with patch.object(telegram_access_bot, "match_intent_dictionary", return_value=intent):
            kind, _params = telegram_access_bot.parse_command("ventas de ayer")
        self.assertEqual("diccionario_intencion", kind)
        self.assertIn(kind, telegram_access_bot.PILOT_READ_ONLY_KINDS)

    def test_transcribed_write_action_stays_blocked_in_pilot(self):
        class Bot:
            def __init__(self):
                self.messages = []
                self.actions = []

            def send_action(self, chat_id, action):
                self.actions.append((chat_id, action))

            def send_message(self, chat_id, text):
                self.messages.append((chat_id, text))

        bot = Bot()
        with patch.object(telegram_access_bot, "PILOT_MODE", True):
            with patch.object(telegram_access_bot, "log_event"):
                with patch.object(telegram_access_bot, "parse_command", return_value=("auditoria_mail_only", {})):
                    with patch.object(telegram_access_bot, "authorize_command", return_value=(True, "")):
                        with patch.object(
                            telegram_access_bot,
                            "prepare_client_query",
                            return_value=("execute", "auditoria_mail_only", {"chat_id": 7}),
                        ):
                            with patch.object(telegram_access_bot, "auditar_consulta"):
                                with patch.object(
                                    telegram_access_bot, "CONFIG", {"max_text_chars": 3500}, create=True
                                ):
                                    telegram_access_bot.process_text_query(
                                        bot,
                                        7,
                                        "enviar auditoria",
                                        source_object="Audio",
                                        unknown_description="Audio no interpretado",
                                    )

        self.assertEqual(
            [(7, "Modo piloto: accion deshabilitada; solo se permiten consultas de lectura.")],
            bot.messages,
        )


if __name__ == "__main__":
    unittest.main()
