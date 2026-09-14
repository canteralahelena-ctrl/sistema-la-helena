import json
import calendar
import atexit
import csv
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import traceback
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path
from datetime import date, datetime, timedelta

from helena_core.application.contracts import Request, UserContext
from helena_core.business.caja.cobros import consultar_cobros
from helena_core.business.cheques.consultas import consultar_cheques
from helena_core.business.iva.mensual import consultar_iva_mensual
from helena_core.business.pagos.propuestas import consultar_propuesta_pago
from helena_core.business.clientes.facturas_pdf import (
    MODE_BY_NUMBER,
    MODE_BY_PERIOD,
    MODE_LATEST,
    MODE_SINCE_LAST_PAYMENT as FACTURAS_MODE_SINCE_LAST_PAYMENT,
    generar_facturas_pdf,
)
from helena_core.business.clientes.estado_pdf import (
    MODE_OPEN_BALANCE,
    MODE_RANGE,
    MODE_SINCE_LAST_PAYMENT as ESTADO_MODE_SINCE_LAST_PAYMENT,
    generar_estado_cuenta_pdf,
)
from helena_core.business.clientes.saldo import consultar_saldo_cliente
from helena_core.business.ventas.analisis_categorias import consultar_analisis_categorias
from helena_core.business.ventas.productos_no_clasificados import consultar_productos_no_clasificados
from helena_core.business.ventas.rapidas import consultar_ventas_rapidas
from helena_core.integrations.powershell.estado_pdf_adapter import EstadoCuentaPdfPowerShellAdapter
from helena_core.integrations.powershell.facturas_pdf_adapter import FacturasPdfPowerShellAdapter
from helena_core.integrations.powershell.cliente_saldo_adapter import ClienteSaldoPowerShellAdapter
from helena_core.integrations.powershell.caja_adapter import CajaPowerShellAdapter
from helena_core.integrations.powershell.cheques_adapter import ChequesPowerShellAdapter
from helena_core.integrations.powershell.iva_adapter import IvaPowerShellAdapter
from helena_core.integrations.powershell.pagos_adapter import PagosPowerShellAdapter
from helena_core.integrations.powershell.ventas_rapidas_adapter import VentasRapidasPowerShellAdapter
from helena_core.process_runner import (
    PS_UTF8_SETUP,
    powershell_file_command,
    powershell_inline_command,
    ps_quote,
    run_text_subprocess,
    subprocess_utf8_env,
)
from helena_core.settings import load_settings


SETTINGS = load_settings(root=Path(__file__).resolve().parent)
PILOT_MODE = SETTINGS.environment.pilot_mode
PILOT_LABEL = "[work_v2 PILOTO]"
PILOT_READ_ONLY_KINDS = {
    "help", "menu_principal", "bot_version", "dashboard_gerencial", "saldo", "deudores",
    "ventas_rapidas", "productos_no_clasificados", "cobros", "iva_mensual", "cheques_resumen",
    "cheques_depositables", "cheques_vencimientos", "armar_pago_echeq", "armar_pago_optimo",
    "material", "estado_pdf", "estado_pdf_abierto", "estado_pdf_ultimo_pago", "factura_pdf",
    "facturas_cliente_pdf", "facturas_ultimas_cliente_pdf", "diccionario_intencion", "unknown",
}
ROOT = SETTINGS.paths.root
WORK = SETTINGS.paths.scripts
OUTPUTS = SETTINGS.paths.outputs
CONFIG_PATH = SETTINGS.private_config.telegram_bot_config
EXAMPLE_CONFIG_PATH = SETTINGS.private_config.telegram_bot_config_example
LOCK_PORT = SETTINGS.technical.lock_port
CACHE_DIR = SETTINGS.paths.data / "cache"
VOICE_DIR = SETTINGS.paths.data / "telegram_voice"
CLIENT_CACHE_PATH = CACHE_DIR / "access_fast_cache.json"
CHEQUE_ALERT_STATE_PATH = CACHE_DIR / "cheque_alert_state.json"
IVA_ALERT_STATE_PATH = CACHE_DIR / "iva_alert_state.json"
DASHBOARD_GERENCIAL_ALERT_STATE_PATH = CACHE_DIR / "dashboard_gerencial_alert_state.json"
DASHBOARD_GERENCIAL_CACHE_TTL_SECONDS = SETTINGS.timeouts.dashboard_cache_ttl_seconds
BOT_DEBUG_LOG_PATH = SETTINGS.paths.logs / "telegram_bot_debug.log"
BOT_PID_PATH = SETTINGS.paths.data / "telegram_bot.pid"
ACTIVIDAD_SISTEMA_PATH = CACHE_DIR / "actividad_sistema.jsonl"
INTENT_DICTIONARY_PATH = SETTINGS.business_config.intent_dictionary
TELEGRAM_USERS_PATH = SETTINGS.user_config.telegram_users
TELEGRAM_PENDING_USERS_PATH = SETTINGS.user_config.telegram_pending_users
LOG_TO_CONSOLE = False
PENDING_SELECTIONS = {}
PENDING_INTENT_ADDS = {}
PENDING_USER_MANAGEMENT = {}
PENDING_RESTARTS = {}
MENU_STATES = {}
CHAT_LAST_ACTIVITY = {}
BOT_STARTED_AT = datetime.now()
LAST_CHEQUE_ALERT_POLL = 0.0
LAST_DASHBOARD_GERENCIAL_ALERT_POLL = 0.0
LAST_CLIENT_CACHE_REFRESH = 0.0
DASHBOARD_GERENCIAL_CACHE = {"key": None, "created_at": 0.0, "text": None, "timings": None}
LAST_DASHBOARD_GERENCIAL_TIMINGS = {}
DESDE_ULTIMO_PAGO = "__ULTIMO_PAGO__"
MENU_STATE_TTL_SECONDS = 5 * 60
PAYMENT_TIMEOUT_SECONDS = SETTINGS.timeouts.payment_seconds
PAYMENT_TIMEOUT_MESSAGE = (
    "La consulta de pago demoró demasiado y fue cancelada. "
    "Probá con un importe menor o revisá si la base está bloqueada."
)

RESTART_DISABLED_MESSAGE = (
    "El reinicio desde Telegram está deshabilitado temporalmente. "
    "Reiniciar manualmente desde la PC."
)

QUERY_COMMANDS = {
    "help",
    "menu_principal",
    "bot_restart_hint",
    "saldo",
    "deudores",
    "material",
    "estado_pdf",
    "estado_pdf_abierto",
    "estado_pdf_ultimo_pago",
    "factura_pdf",
    "facturas_cliente_pdf",
    "facturas_ultimas_cliente_pdf",
    "auditoria_mail_only",
    "diccionario_intencion",
    "dashboard_gerencial",
    "productos_no_clasificados",
    "unknown",
}

OWNER_COMMANDS = set()
OWNER_COMMANDS.update(
    {
        "cobros",
        "ventas_rapidas",
        "productos_no_clasificados",
        "iva_mensual",
        "cheques_resumen",
        "cheques_depositables",
        "cheques_vencimientos",
        "armar_pago_optimo",
        "armar_pago_echeq",
        "dashboard_gerencial",
        "bot_version",
    }
)

COMMAND_PERMISSIONS = {
    "help": None,
    "menu_principal": None,
    "unknown": None,
    "diccionario_intencion": None,
    "saldo": "saldos",
    "deudores": "clientes",
    "material": "reportes",
    "estado_pdf": "saldos",
    "estado_pdf_abierto": "saldos",
    "estado_pdf_ultimo_pago": "saldos",
    "factura_pdf": "facturas",
    "facturas_cliente_pdf": "facturas",
    "facturas_ultimas_cliente_pdf": "facturas",
    "cobros": "caja",
    "ventas_rapidas": "reportes",
    "productos_no_clasificados": "reportes",
    "iva_mensual": "reportes",
    "cheques_resumen": "cheques",
    "cheques_depositables": "cheques",
    "cheques_vencimientos": "cheques",
    "armar_pago_optimo": "cheques",
    "armar_pago_echeq": "cheques",
    "dashboard_gerencial": "gerencial",
    "auditoria_mail_only": "auditoria",
    "usuarios_menu": "usuarios",
    "bot_restart_hint": None,
    "bot_version": "usuarios",
}

INTENT_PERMISSIONS = {
    "clientes_saldo": "saldos",
    "clientes_resumen_pdf": "saldos",
    "clientes_resumen_ultimo_pago": "saldos",
    "clientes_factura_ultima": "facturas",
    "clientes_facturas_periodo": "facturas",
    "clientes_factura_numero": "facturas",
    "ventas_rapidas": "reportes",
    "productos_no_clasificados": "reportes",
    "caja_rapida": "caja",
    "iva_estimado": "reportes",
    "cheques_resumen": "cheques",
    "mejores_clientes": "rankings",
    "peores_clientes": "rankings",
    "mayores_deudores": "clientes",
    "analisis_categorias": "reportes",
    "iva_mensual": "reportes",
    "cheques": "cheques",
}

INTENCIONES_VALIDAS = {
    "clientes_saldo": {
        "descripcion": "Consultar saldo de cliente",
        "kind": "saldo",
        "script": "work/consultas_rapidas.ps1",
        "parametros_base": {"Comando": "cliente"},
        "fuente": "menu_clientes/parse_command/handle_command",
    },
    "clientes_resumen_pdf": {
        "descripcion": "Resumen de cuenta PDF",
        "kind": "estado_pdf",
        "script": "work/generar_estado_cuenta_pdf.ps1",
        "parametros_base": {"AccionBot": "estado_pdf"},
        "fuente": "menu_clientes/parse_command/handle_command",
    },
    "clientes_resumen_ultimo_pago": {
        "descripcion": "Resumen de cuenta desde ultimo pago",
        "kind": "estado_pdf_ultimo_pago",
        "script": "work/generar_estado_desde_ultimo_pago.ps1",
        "parametros_base": {"AccionBot": "estado_pdf_ultimo_pago"},
        "fuente": "menu_clientes/parse_command/handle_command",
    },
    "clientes_factura_ultima": {
        "descripcion": "Ultima factura cliente",
        "kind": "facturas_ultimas_cliente_pdf",
        "script": "work/facturas_pdf.ps1",
        "parametros_base": {"Accion": "ultimas-cliente", "Cantidad": 1},
        "fuente": "menu_clientes/parse_command/handle_command",
    },
    "clientes_facturas_periodo": {
        "descripcion": "Facturas PDF por periodo",
        "kind": "facturas_cliente_pdf",
        "script": "work/facturas_pdf.ps1",
        "parametros_base": {"Accion": "cliente"},
        "fuente": "menu_clientes/parse_command/handle_command",
    },
    "clientes_facturas_desde_ultimo_pago": {
        "descripcion": "Facturas PDF desde ultimo pago",
        "kind": "facturas_cliente_pdf",
        "script": "work/facturas_pdf.ps1",
        "parametros_base": {"Accion": "cliente", "Desde": DESDE_ULTIMO_PAGO},
        "fuente": "menu_clientes/handle_command",
    },
    "clientes_factura_numero": {
        "descripcion": "Factura PDF por numero",
        "kind": "factura_pdf",
        "script": "work/facturas_pdf.ps1",
        "parametros_base": {"Accion": "factura"},
        "fuente": "menu_clientes/parse_command/handle_command",
    },
    "ventas_rapidas": {
        "descripcion": "Ventas rapidas",
        "kind": "ventas_rapidas",
        "script": "work/analisis_categorias.ps1",
        "parametros_base": {"Tipos": "Ambos"},
        "fuente": "menu_consultas_rapidas/handle_command",
    },
    "productos_no_clasificados": {
        "descripcion": "Productos no clasificados",
        "kind": "productos_no_clasificados",
        "script": "work/analisis_categorias.ps1",
        "parametros_base": {"Tipos": "Ambos"},
        "fuente": "menu_consultas_rapidas/handle_command",
    },
    "caja_rapida": {
        "descripcion": "Caja rapida",
        "kind": "cobros",
        "script": "work/consultas_rapidas.ps1",
        "parametros_base": {"Comando": "cobros", "medio": "todos"},
        "fuente": "menu_consultas_rapidas/handle_command",
    },
    "iva_estimado": {
        "descripcion": "IVA estimado",
        "kind": "iva_mensual",
        "script": "work/iva_mensual.ps1",
        "parametros_base": {},
        "fuente": "menu_consultas_rapidas/parse_command/handle_command",
    },
    "mayores_deudores": {
        "descripcion": "Mayores deudores",
        "kind": "deudores",
        "script": "work/consultas_rapidas.ps1",
        "parametros_base": {"Comando": "deudores", "Top": 10},
        "fuente": "diccionario/handle_command",
    },
    "mejores_clientes": {
        "descripcion": "Mejores clientes",
        "kind": "diccionario_intencion",
        "script": "work/ranking_clientes.ps1",
        "parametros_base": {"Accion": "mejores", "Top": 10},
        "fuente": "diccionario/handle_command",
    },
    "peores_clientes": {
        "descripcion": "Peores clientes",
        "kind": "diccionario_intencion",
        "script": "work/ranking_clientes.ps1",
        "parametros_base": {"Accion": "peores", "Top": 10},
        "fuente": "diccionario/handle_command",
    },
    "analisis_categorias": {
        "descripcion": "Analisis categorias",
        "kind": "diccionario_intencion",
        "script": "work/analisis_categorias.ps1",
        "parametros_base": {},
        "fuente": "diccionario/handle_command",
    },
    "cheques_resumen": {
        "descripcion": "Cheques y eCheq",
        "kind": "cheques_resumen",
        "script": "work/gestion_cheques.ps1",
        "parametros_base": {"Accion": "resumen"},
        "fuente": "parse_command/handle_command",
    },
}

INTENT_ID_ALIASES = {
    "saldo_cliente": "clientes_saldo",
    "estado_cuenta_cliente": "clientes_resumen_pdf",
    "estado_cuenta_ultimo_pago": "clientes_resumen_ultimo_pago",
    "ultima_factura_cliente": "clientes_factura_ultima",
    "facturas_periodo_cliente": "clientes_facturas_periodo",
    "facturas_desde_ultimo_pago_cliente": "clientes_facturas_desde_ultimo_pago",
    "factura_por_numero": "clientes_factura_numero",
    "cobros": "caja_rapida",
    "iva_mensual": "iva_estimado",
    "cheques": "cheques_resumen",
}


def canonical_intent_id(intent_id):
    return INTENT_ID_ALIASES.get(intent_id, intent_id)


def load_config():
    if not CONFIG_PATH.exists():
        raise SystemExit(
            f"No existe {CONFIG_PATH}. Copia {EXAMPLE_CONFIG_PATH.name} como "
            f"{CONFIG_PATH.name} y pega el token de BotFather."
        )
    with CONFIG_PATH.open("r", encoding="utf-8-sig") as f:
        config = json.load(f)
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or config.get("telegram_bot_token")
    if not token or token == "PEGAR_TOKEN_DE_BOTFATHER":
        raise SystemExit("Falta telegram_bot_token en telegram_bot_config.json.")
    config["telegram_bot_token"] = token
    config.setdefault("allowed_chat_ids", [])
    config.setdefault("powershell", SETTINGS.technical.powershell_executable)
    config.setdefault("max_text_chars", 3500)
    config.setdefault("openai_api_key", "")
    config.setdefault("transcription_model", "gpt-4o-mini-transcribe")
    config.setdefault("intent_classifier_model", "gpt-4o-mini")
    config.setdefault("ffmpeg_path", SETTINGS.technical.ffmpeg_executable)
    config.setdefault("telegram_users", {})
    config.setdefault("access_users", {})
    config.setdefault(
        "cheque_alerts",
        {"enabled": True, "hour": 8, "warning_days": 3},
    )
    config.setdefault("iva_alerts", {"enabled": True, "hour": 10})
    config.setdefault("dashboard_gerencial_alerts", {"enabled": True, "hour": 10})
    return config


def fix_outgoing_text(text):
    value = str(text or "")
    if not any(marker in value for marker in ("\u00c3", "\u00c2", "\u00e2", "\u00f0\u0178", "\u00ef\u00b8")):
        return value
    raw = bytearray()
    try:
        for char in value:
            codepoint = ord(char)
            if codepoint <= 255:
                raw.append(codepoint)
            else:
                raw.extend(char.encode("cp1252"))
        fixed = bytes(raw).decode("utf-8")
    except UnicodeError:
        return value
    if fixed and fixed != value:
        return fixed
    return value


class Telegram:
    def __init__(self, token):
        self.base = f"https://api.telegram.org/bot{token}"

    def call(self, method, data=None, files=None, timeout=120):
        url = f"{self.base}/{method}"
        if files:
            boundary = "----LaHelenaBotBoundary"
            body = bytearray()
            for key, value in (data or {}).items():
                body.extend(f"--{boundary}\r\n".encode())
                body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
                body.extend(str(value).encode("utf-8"))
                body.extend(b"\r\n")
            for key, path in files.items():
                path = Path(path)
                body.extend(f"--{boundary}\r\n".encode())
                body.extend(
                    (
                        f'Content-Disposition: form-data; name="{key}"; '
                        f'filename="{path.name}"\r\n'
                    ).encode()
                )
                body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
                body.extend(path.read_bytes())
                body.extend(b"\r\n")
            body.extend(f"--{boundary}--\r\n".encode())
            request = urllib.request.Request(
                url,
                data=bytes(body),
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
        else:
            payload = urllib.parse.urlencode(data or {}).encode("utf-8")
            request = urllib.request.Request(url, data=payload)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_updates(self, offset=None, timeout=30):
        data = {"timeout": timeout}
        if offset is not None:
            data["offset"] = offset
        return self.call("getUpdates", data=data, timeout=timeout + 10)

    def get_file(self, file_id):
        return self.call("getFile", {"file_id": file_id})

    def download_file(self, file_path, destination):
        url = f"{self.base.replace('/bot', '/file/bot')}/{file_path}"
        with urllib.request.urlopen(url, timeout=120) as response:
            Path(destination).write_bytes(response.read())
        return Path(destination)

    def send_message(self, chat_id, text):
        outgoing = f"{PILOT_LABEL}\n{text}" if PILOT_MODE else text
        return self.call("sendMessage", {"chat_id": chat_id, "text": fix_outgoing_text(outgoing)})

    def send_action(self, chat_id, action="typing"):
        return self.call("sendChatAction", {"chat_id": chat_id, "action": action})

    def send_document(self, chat_id, path, caption=""):
        outgoing_caption = f"{PILOT_LABEL} {caption}" if PILOT_MODE else caption
        return self.call(
            "sendDocument",
            data={"chat_id": chat_id, "caption": fix_outgoing_text(outgoing_caption)},
            files={"document": path},
            timeout=180,
        )

    def delete_message(self, chat_id, message_id):
        return self.call(
            "deleteMessage",
            {"chat_id": chat_id, "message_id": message_id},
        )


def normalize(text):
    text = (text or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def log_event(message):
    try:
        safe_message = str(message)
    except Exception:
        safe_message = "<mensaje de log no convertible>"
    line = f"{datetime.now().isoformat(timespec='seconds')} {safe_message}"
    try:
        with BOT_DEBUG_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if LOG_TO_CONSOLE:
        try:
            print(safe_message)
        except Exception:
            pass


def rol_telegram_para_auditoria(chat_id):
    if chat_id in (None, ""):
        return ""
    try:
        user, _ = find_telegram_user(chat_id)
        if user:
            return str(user.get("rol") or "")
        if "CONFIG" in globals():
            legacy = legacy_telegram_user(chat_id)
            return str(legacy.get("role") or "")
    except Exception:
        pass
    return ""


def usuario_telegram_para_auditoria(chat_id, usuario=None):
    if usuario:
        return str(usuario)
    if chat_id in (None, ""):
        return ""
    try:
        user, _ = find_telegram_user(chat_id)
        if user:
            return str(user.get("nombre") or user.get("name") or "")
        if "CONFIG" in globals():
            legacy = legacy_telegram_user(chat_id)
            return str(legacy.get("name") or "")
    except Exception:
        pass
    return ""


def registrar_actividad(
    chat_id=None,
    usuario=None,
    modulo="",
    accion="",
    objeto="",
    id_objeto="",
    descripcion="",
    nivel="INFO",
    extra=None,
):
    try:
        nivel_normalizado = str(nivel or "INFO").upper()
        if nivel_normalizado not in {"INFO", "WARNING", "CRITICO", "ERROR"}:
            nivel_normalizado = "INFO"
        event = {
            "fecha_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "chat_id": "" if chat_id is None else str(chat_id),
            "usuario": usuario_telegram_para_auditoria(chat_id, usuario),
            "rol": rol_telegram_para_auditoria(chat_id),
            "modulo": str(modulo or ""),
            "accion": str(accion or ""),
            "objeto": str(objeto or ""),
            "id_objeto": str(id_objeto or ""),
            "descripcion": str(descripcion or "")[:500],
            "nivel": nivel_normalizado,
            "origen": "telegram",
            "extra": extra if isinstance(extra, dict) else {},
        }
        ACTIVIDAD_SISTEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
        with ACTIVIDAD_SISTEMA_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:
        log_event(f"AUDITORIA error_no_bloqueante {exc}")


def modulo_actividad_para_comando(kind, params=None):
    params = params or {}
    if kind in {
        "saldo",
        "deudores",
        "material",
        "estado_pdf",
        "estado_pdf_abierto",
        "estado_pdf_ultimo_pago",
        "factura_pdf",
        "facturas_cliente_pdf",
        "facturas_ultimas_cliente_pdf",
    }:
        return "Clientes"
    if kind in {"iva_mensual"}:
        return "IVA"
    if kind in {"cheques_resumen", "cheques_depositables", "cheques_vencimientos"}:
        return "Cheques"
    if kind in {"armar_pago_optimo", "armar_pago_echeq"}:
        return "Pagos"
    if kind in {"cobros"}:
        return "Caja"
    if kind in {"ventas_rapidas", "productos_no_clasificados"}:
        return "Ventas"
    if kind in {"usuarios_menu"}:
        return "Usuarios"
    if kind == "dashboard_gerencial":
        return "Gerencial"
    if kind == "diccionario_intencion":
        intent_id = params.get("id", "")
        if intent_id == "analisis_categorias":
            return "Ventas"
        catalog_kind = INTENCIONES_VALIDAS.get(intent_id, {}).get("kind", "")
        return modulo_actividad_para_comando(catalog_kind, params)
    return "Sistema"


def descripcion_actividad_para_comando(kind, params=None):
    if kind == "unknown":
        return "Comando desconocido"
    if kind in {"armar_pago_optimo", "armar_pago_echeq"}:
        return "Uso de pago rápido"
    if kind == "iva_mensual":
        return "Uso de IVA"
    if kind in {"cheques_resumen", "cheques_depositables", "cheques_vencimientos"}:
        return "Uso de cheques"
    if kind == "dashboard_gerencial":
        return "Uso dashboard"
    if kind == "productos_no_clasificados":
        return "Uso de productos no clasificados"
    if modulo_actividad_para_comando(kind, params) == "Clientes":
        return "Uso de clientes"
    return "Consulta ejecutada"


def auditar_consulta(chat_id, kind, params=None, nivel="INFO", descripcion=None):
    params = params or {}
    safe_extra = {
        key: value
        for key, value in params.items()
        if key
        in {
            "anio",
            "mes",
            "desde",
            "hasta",
            "tipo",
            "dias",
            "modo",
            "filtro_fiscal",
            "top",
            "medio",
        }
    }
    registrar_actividad(
        chat_id=chat_id,
        modulo=modulo_actividad_para_comando(kind, params),
        accion="Consulta",
        objeto=str(kind or ""),
        descripcion=descripcion or descripcion_actividad_para_comando(kind, params),
        nivel=nivel,
        extra=safe_extra,
    )


def repair_common_text_glitches(text):
    value = str(text or "")
    replacements = {
        "\u00c2\u00a1": "i",
        "\u00c3\u0192\u00c2\u00a1": "a",
        "\u00c3\u0192\u00c2\u00a9": "e",
        "\u00c3\u0192\u00c2\u00ad": "i",
        "\u00c3\u0192\u00c2\u00b3": "o",
        "\u00c3\u0192\u00c2\u00ba": "u",
        "\u00c3\u0192\u00c2\u00b1": "n",
        "\u00c3\u0192\u00c2\u0081": "A",
        "\u00c3\u0192\u00e2\u20ac\u00b0": "E",
        "\u00c3\u0192\u00c2\u008d": "I",
        "\u00c3\u0192\u00e2\u20ac\u0153": "O",
        "\u00c3\u0192\u00c5\u00a1": "U",
        "\u00c3\u0192\u00e2\u20ac\u02dc": "N",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return value


def fold_accents(text):
    return "".join(
        char
        for char in unicodedata.normalize("NFD", text or "")
        if unicodedata.category(char) != "Mn"
    )


def clean_client_name(text):
    value = normalize(repair_common_text_glitches(text))
    value = re.sub(
        r"^(necesito|quiero|quisiera|dame|enviame|enviar|mandame|pasame|generame|por favor)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\b(ultima|ultimas|ultimo|ultimos)\s+(facturas?|comprobantes?)\b", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\b(facturas?|comprobantes?)\b", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^(el|la|los|las)\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^(de|del|para)\s+", "", value, flags=re.IGNORECASE)
    return value.strip(" ,.-")


def client_key(text):
    value = unicodedata.normalize("NFD", str(text or "").upper())
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    value = re.sub(r"\b(SRL|S\.R\.L|SA|S\.A|SAS|S\.A\.S)\b", " ", value)
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return normalize(value)


def load_clients():
    if not CLIENT_CACHE_PATH.exists():
        return []
    try:
        with CLIENT_CACHE_PATH.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data.get("Clientes", [])
    except Exception:
        return []


def refresh_client_cache_if_needed():
    global LAST_CLIENT_CACHE_REFRESH
    now = time.time()
    if now - LAST_CLIENT_CACHE_REFRESH < 300:
        return False
    LAST_CLIENT_CACHE_REFRESH = now
    command = powershell_file_command(WORK / "cache_access.ps1", powershell_executable=CONFIG["powershell"])
    run_text_subprocess(command, cwd=str(ROOT), capture_output=True, timeout=180)
    return True


def client_matches(query, limit=6):
    if str(query).isdigit():
        return []
    query_norm = client_key(query)
    if not query_norm:
        return []
    query_tokens = set(query_norm.split())
    scored = []
    for client in load_clients():
        name = client.get("RazonSocial", "")
        name_norm = client_key(name)
        if not name_norm:
            continue
        name_tokens = set(name_norm.split())
        if query_norm == name_norm:
            score = 1.0
        elif query_norm in name_norm:
            score = 0.94 - min(0.15, (len(name_norm) - len(query_norm)) / 200)
        else:
            exact_token_score = len(query_tokens & name_tokens) / max(len(query_tokens), 1)
            fuzzy_hits = 0
            for query_token in query_tokens:
                if any(SequenceMatcher(None, query_token, name_token).ratio() >= 0.78 for name_token in name_tokens):
                    fuzzy_hits += 1
            fuzzy_token_score = fuzzy_hits / max(len(query_tokens), 1)
            token_score = max(exact_token_score, fuzzy_token_score * 0.92)
            sequence_score = SequenceMatcher(None, query_norm, name_norm).ratio()
            score = (token_score * 0.65) + (sequence_score * 0.35)
        if score >= 0.46:
            scored.append((score, client))
    scored.sort(key=lambda item: (-item[0], client_key(item[1].get("RazonSocial", ""))))
    return scored[:limit]


def resolve_client(query):
    matches = client_matches(query)
    if not matches and refresh_client_cache_if_needed():
        matches = client_matches(query)
    if not matches:
        return ("none", None)
    top_score = matches[0][0]
    matches = [item for item in matches if item[0] >= top_score - 0.18]
    if len(matches) == 1:
        return ("selected", matches[0][1])
    second_score = matches[1][0]
    if top_score >= 0.84 and top_score - second_score >= 0.10:
        return ("selected", matches[0][1])
    return ("choices", [client for _, client in matches])


def client_choice_text(query, choices):
    lines = [f"Encontre varios clientes parecidos a '{query}':", ""]
    for index, client in enumerate(choices, start=1):
        locality = client.get("LOCALIDAD") or ""
        suffix = f" - {locality}" if locality else ""
        lines.append(f"{index}. {client.get('RazonSocial')}{suffix}")
    lines.extend(["", "Responde solamente con el numero de la opcion."])
    return "\n".join(lines)


def parse_date(text):
    match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", text)
    if not match:
        return None
    day, month, year = match.groups()
    if len(year) == 2:
        year = "20" + year
    return f"{year}-{int(month):02d}-{int(day):02d}"


def parse_dates(text):
    results = []
    for day, month, year in re.findall(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", text or ""):
        if len(year) == 2:
            year = "20" + year
        results.append(f"{year}-{int(month):02d}-{int(day):02d}")
    return results


MONTHS_ES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def parse_account_period(text):
    explicit = parse_dates(text)
    if len(explicit) >= 2:
        return explicit[0], explicit[1]
    if len(explicit) == 1:
        if "hoy" in client_key(text).lower():
            return explicit[0], date.today().isoformat()
        return explicit[0], None

    lower = client_key(text).lower()
    today = date.today()
    month_pattern = "|".join(MONTHS_ES)
    month_matches = list(
        re.finditer(
            rf"\b({month_pattern})\b(?:\s+de\s+(\d{{4}}))?",
            lower,
            flags=re.IGNORECASE,
        )
    )
    if not month_matches:
        return None, None

    first = month_matches[0]
    start_month = MONTHS_ES[first.group(1).lower()]
    start_year = int(first.group(2)) if first.group(2) else today.year
    day_match = re.search(
        rf"(?:desde\s+)?(?:el\s+)?(\d{{1,2}})\s+de\s+{first.group(1)}",
        lower,
        flags=re.IGNORECASE,
    )
    start_day = int(day_match.group(1)) if day_match else 1
    start = date(start_year, start_month, start_day)

    if "hasta hoy" in lower or re.search(r"\bhoy\b", lower):
        end = today
    elif len(month_matches) > 1:
        last = month_matches[1]
        end_month = MONTHS_ES[last.group(1).lower()]
        end_year = int(last.group(2)) if last.group(2) else start_year
        end_day_match = re.search(
            rf"(?:hasta\s+)?(?:el\s+)?(\d{{1,2}})\s+de\s+{last.group(1)}",
            lower,
            flags=re.IGNORECASE,
        )
        end_day = (
            int(end_day_match.group(1))
            if end_day_match
            else calendar.monthrange(end_year, end_month)[1]
        )
        end = date(end_year, end_month, end_day)
    else:
        end = today
    return start.isoformat(), end.isoformat()


def parse_period(text):
    lower = (text or "").lower()
    today = date.today()
    if "ayer" in lower:
        start = today - timedelta(days=1)
        return start.isoformat(), (start + timedelta(days=1)).isoformat()
    if "hoy" in lower:
        return today.isoformat(), (today + timedelta(days=1)).isoformat()
    parsed = parse_date(text)
    if parsed:
        start = datetime.strptime(parsed, "%Y-%m-%d").date()
        return start.isoformat(), (start + timedelta(days=1)).isoformat()
    return today.isoformat(), (today + timedelta(days=1)).isoformat()


def parse_quick_report_period(text):
    lower = fold_accents(text or "").lower()
    today = date.today()
    if "ayer" in lower:
        start = today - timedelta(days=1)
        return start.isoformat(), start.isoformat()
    if "hoy" in lower:
        return today.isoformat(), today.isoformat()
    if "mes" in lower:
        start = date(today.year, today.month, 1)
        end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
        return start.isoformat(), end.isoformat()
    desde, hasta = parse_account_period(text)
    if desde:
        if not hasta:
            hasta = date.today().isoformat()
        return desde, hasta
    parsed = parse_date(text)
    if parsed:
        return parsed, parsed
    return today.isoformat(), today.isoformat()


def parse_iva_month(text):
    lower = fold_accents(text or "").lower()
    today = date.today()

    month_year = re.search(r"\b(\d{1,2})[/-](\d{4})\b", lower)
    if month_year:
        month = max(1, min(int(month_year.group(1)), 12))
        return int(month_year.group(2)), month

    month_year_words = re.search(r"\bmes\s+(\d{1,2})\s+(?:anio|ano|año)\s+(\d{4})\b", lower)
    if month_year_words:
        month = max(1, min(int(month_year_words.group(1)), 12))
        return int(month_year_words.group(2)), month

    dates = parse_dates(text)
    if dates:
        parsed = datetime.strptime(dates[0], "%Y-%m-%d").date()
        return parsed.year, parsed.month

    month_pattern = "|".join(MONTHS_ES)
    month_match = re.search(rf"\b({month_pattern})\b(?:\s+de\s+(\d{{4}}))?", lower)
    if month_match:
        month = MONTHS_ES[month_match.group(1).lower()]
        year = int(month_match.group(2)) if month_match.group(2) else today.year
        return year, month

    return today.year, today.month


IVA_PERIOD_EXAMPLES = (
    "Ejemplos:\n"
    "IVA de 01/06/2026 a 30/06/2026\n"
    "IVA junio 2026\n"
    "IVA mes 6 año 2026"
)


def parse_iva_period_request(text):
    lower = fold_accents(text or "").lower()
    dates = parse_dates(text)
    if len(dates) >= 2:
        return {
            "error": "Por ahora IVA por rango exacto no está implementado; usá mes y año.",
        }

    month_year = re.search(r"\b(\d{1,2})[/-](\d{4})\b", lower)
    if month_year:
        month = max(1, min(int(month_year.group(1)), 12))
        return {"anio": int(month_year.group(2)), "mes": month}

    month_year_words = re.search(r"\bmes\s+(\d{1,2})\s+(?:anio|ano)\s+(\d{4})\b", lower)
    if month_year_words:
        month = max(1, min(int(month_year_words.group(1)), 12))
        return {"anio": int(month_year_words.group(2)), "mes": month}

    month_pattern = "|".join(MONTHS_ES)
    month_match = re.search(rf"\b({month_pattern})\b(?:\s+de\s+|\s+)?(\d{{4}})\b", lower)
    if month_match:
        return {
            "anio": int(month_match.group(2)),
            "mes": MONTHS_ES[month_match.group(1).lower()],
        }

    if len(dates) == 1:
        parsed_date = datetime.strptime(dates[0], "%Y-%m-%d").date()
        return {"anio": parsed_date.year, "mes": parsed_date.month}

    return {
        "error": "No pude entender el período.\n\n" + IVA_PERIOD_EXAMPLES,
    }


def parse_medio_pago(text):
    lower = (text or "").lower()
    if "efect" in lower:
        return "efectivo"
    if "transfer" in lower or "transf" in lower:
        return "transferencia"
    if "echeq" in lower or "e-cheq" in lower:
        return "echeq"
    if "cheque" in lower:
        return "cheque"
    if "flete" in lower:
        return "flete"
    if "retenc" in lower:
        return "retencion"
    if "material" in lower:
        return "materiales"
    return "todos"


def parse_money_amount(text):
    lower = client_key(text).lower()
    million_match = re.search(r"(\d+(?:[.,]\d+)?)\s*mill(?:on|ones)?", lower)
    if million_match:
        number = million_match.group(1).replace(",", ".")
        return float(number) * 1_000_000

    candidates = re.findall(r"\$?\s*(\d[\d.,]*)", text or "")
    values = []
    for raw in candidates:
        compact = raw.replace(" ", "")
        if "." in compact and "," in compact:
            normalized = compact.replace(".", "").replace(",", ".")
        elif compact.count(".") > 1:
            normalized = compact.replace(".", "")
        elif compact.count(",") > 1:
            normalized = compact.replace(",", "")
        elif "." in compact:
            left, right = compact.rsplit(".", 1)
            normalized = compact.replace(".", "") if len(right) == 3 else compact
        elif "," in compact:
            left, right = compact.rsplit(",", 1)
            normalized = compact.replace(",", "") if len(right) == 3 else compact.replace(",", ".")
        else:
            normalized = compact
        try:
            values.append(float(normalized))
        except ValueError:
            continue
    return max(values) if values else None


def parse_days(text, default=7):
    match = re.search(r"(?:a\s+no\s+mas\s+de\s+|en\s+|proximos?\s+)?(\d+)\s*dias?", client_key(text).lower())
    return int(match.group(1)) if match else default


def run_ps(args, timeout=180):
    command = powershell_file_command(
        WORK / "consultas_rapidas.ps1",
        args,
        powershell_executable=CONFIG["powershell"],
    )
    completed = run_text_subprocess(
        command,
        cwd=str(ROOT),
        capture_output=True,
        timeout=timeout,
    )
    output = (completed.stdout or "").strip()
    error = (completed.stderr or "").strip()
    if completed.returncode != 0:
        raise RuntimeError(clean_script_error(error or output or f"PowerShell salio con codigo {completed.returncode}"))
    return output or "Consulta ejecutada."


def refresh_access():
    script = WORK / "actualizar_copia_base.ps1"
    try:
        run_text_subprocess(
            powershell_file_command(script, powershell_executable=SETTINGS.technical.powershell_executable),
            cwd=str(ROOT),
            capture_output=True,
            timeout=180,
        )
    except Exception as exc:
        print(f"No se pudo refrescar Access; uso copia local: {exc}", flush=True)


def run_script(script_name, args=None, timeout=180, encoding=None):
    command = powershell_file_command(
        WORK / script_name,
        list(args or []),
        powershell_executable=CONFIG["powershell"],
    )
    run_options = {
        "cwd": str(ROOT),
        "capture_output": True,
        "timeout": timeout,
    }
    if encoding:
        run_options["encoding"] = encoding
        run_options["errors"] = "replace"
    started = time.time()
    log_event(f"RUN_SCRIPT inicio script={script_name} timeout={timeout} args={list(args or [])!r}")
    try:
        completed = run_text_subprocess(
            command,
            **run_options,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.time() - started
        log_event(f"RUN_SCRIPT timeout script={script_name} elapsed={elapsed:.1f}s timeout={timeout}")
        raise TimeoutError(f"{script_name} supero timeout de {timeout} segundos") from exc
    elapsed = time.time() - started
    log_event(f"RUN_SCRIPT fin script={script_name} elapsed={elapsed:.1f}s returncode={completed.returncode}")
    output = (completed.stdout or "").strip()
    error = (completed.stderr or "").strip()
    if error:
        log_event(f"RUN_SCRIPT stderr script={script_name} {error[-1000:]}")
    if completed.returncode != 0:
        raise RuntimeError(clean_script_error(error or output or f"PowerShell salio con codigo {completed.returncode}"))
    return output or "Consulta ejecutada."


def format_money_ar(value):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    formatted = f"{number:,.2f}"
    return "$ " + formatted.replace(",", "_").replace(".", ",").replace("_", ".")


CHEQUE_SUMMARY_BUCKETS = (
    ("0-7 DIAS", "0-7 días"),
    ("8-15 DIAS", "8-15 días"),
    ("16-30 DIAS", "16-30 días"),
    ("MAS DE 30 DIAS", "+30 días"),
)


MONTH_NAMES_ES = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}


def format_iva_estimated_output(data, anio=None, mes=None):
    period = str(data.get("periodo") or "").strip()
    if re.match(r"^\d{4}-\d{2}$", period):
        year, month = period.split("-")
        period_label = f"{MONTH_NAMES_ES.get(int(month), month)} {year}"
    elif anio and mes:
        period_label = f"{MONTH_NAMES_ES.get(int(mes), int(mes))} {int(anio):04d}"
    else:
        period_label = period or "-"

    return (
        "🧾 IVA estimado\n\n"
        f"Período: {period_label}\n\n"
        f"IVA ventas: {data.get('iva_ventas', '-')}\n"
        f"IVA gastos: {data.get('iva_gastos', '-')}\n"
        f"Saldo IVA: {data.get('saldo_iva', '-')}"
    )


def execute_iva_core(anio, mes, *, chat_id="", timeout_seconds=None):
    result = consultar_iva_mensual(
        Request(
            capability="iva.mensual",
            parameters={"anio": anio, "mes": mes},
            user_context=UserContext(
                channel="telegram",
                channel_user_id=str(chat_id),
            ),
            channel="telegram",
        ),
        adapter=IvaPowerShellAdapter(
            settings=SETTINGS,
            timeout_seconds=timeout_seconds,
        ),
    )
    if not result.success:
        raise RuntimeError(clean_script_error(result.error.message if result.error else result.message))
    return result.data


CHEQUES_FISCAL_LABELS = {
    "NN": "NN / sin factura",
    "BLANCO": "Blanco / con factura",
    "TODOS": "Todos",
}


def normalize_cheques_fiscal_filter(value):
    filtro = str(value or "TODOS").upper()
    return filtro if filtro in CHEQUES_FISCAL_LABELS else "TODOS"


def format_cheques_resumen_telegram(data):
    filtro = normalize_cheques_fiscal_filter(data.get("filtro_fiscal"))
    if data.get("vacio"):
        return f"No hay valores para ese filtro.\n\nFiltro: {CHEQUES_FISCAL_LABELS[filtro]}"

    total_cartera = data.get("total_cartera") or {}
    por_tipo = data.get("por_tipo") or {}
    echeq = por_tipo.get("ECHEQ") or {}
    cheque = por_tipo.get("CHEQUE FISICO") or {}
    cobrar = data.get("a_cobrar") or {}
    lines = [
        "💳 CARTERA DE VALORES",
        "",
        f"Filtro: {CHEQUES_FISCAL_LABELS[filtro]}",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "💰 Total cartera",
        format_money_ar(total_cartera.get("total")),
        f"{int(total_cartera.get('cantidad') or 0)} valores",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "🏦 eCheq",
        f"{int(echeq.get('cantidad') or 0)} valores",
        format_money_ar(echeq.get("total")),
        "",
        "🏦 Cheques físicos",
        f"{int(cheque.get('cantidad') or 0)} valores",
        format_money_ar(cheque.get("total")),
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "📅 A cobrar",
        f"Hoy: {format_money_ar(cobrar.get('total'))}",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "📆 A depositar",
        "",
    ]

    buckets = data.get("a_depositar") or {}
    for bucket, label in CHEQUE_SUMMARY_BUCKETS:
        values = buckets.get(bucket) or {}
        lines.extend(
            [
                label,
                f"{int(values.get('cantidad') or 0)} valores",
                format_money_ar(values.get("total")),
                "",
            ]
        )

    if filtro == "TODOS":
        fiscal = data.get("por_filtro_fiscal") or {}
        nn_values = fiscal.get("NN") or {}
        blanco_values = fiscal.get("BLANCO") or {}
        lines.extend(
            [
                "━━━━━━━━━━━━━━━━━━",
                "",
                "⚫ NN / sin factura",
                f"{int(nn_values.get('cantidad') or 0)} valores",
                format_money_ar(nn_values.get("total")),
                "",
                "⚪ Blanco / con factura",
                f"{int(blanco_values.get('cantidad') or 0)} valores",
                format_money_ar(blanco_values.get("total")),
            ]
        )

    return "\n".join(lines)


def format_cheques_depositables_telegram(data):
    filtro = normalize_cheques_fiscal_filter(data.get("filtro_fiscal"))
    if data.get("vacio"):
        return f"No hay valores para ese filtro.\n\nFiltro: {CHEQUES_FISCAL_LABELS[filtro]}"
    return str(data.get("texto_legacy") or "").replace(
        "Disponible para depositar hoy",
        "A cobrar",
        1,
    )


def execute_cheques_core(capability, parameters=None, *, chat_id="", timeout_seconds=None):
    result = consultar_cheques(
        Request(
            capability=capability,
            parameters=dict(parameters or {}),
            user_context=UserContext(
                channel="telegram",
                channel_user_id=str(chat_id),
            ),
            channel="telegram",
        ),
        adapter=ChequesPowerShellAdapter(
            settings=SETTINGS,
            timeout_seconds=timeout_seconds,
        ),
    )
    if not result.success:
        raise RuntimeError(clean_script_error(result.error.message if result.error else result.message))
    return result.data


def execute_pagos_core(capability, parameters=None, *, chat_id="", timeout_seconds=None):
    result = consultar_propuesta_pago(
        Request(
            capability=capability,
            parameters=dict(parameters or {}),
            user_context=UserContext(
                channel="telegram",
                channel_user_id=str(chat_id),
            ),
            channel="telegram",
        ),
        adapter=PagosPowerShellAdapter(
            settings=SETTINGS,
            timeout_seconds=timeout_seconds,
        ),
    )
    if not result.success:
        message = clean_script_error(result.error.message if result.error else result.message)
        if result.error and result.error.code == "pagos_timeout":
            raise TimeoutError(message)
        raise RuntimeError(message)
    return result.data


def extract_money_value(text, pattern):
    match = re.search(pattern, str(text or ""), flags=re.IGNORECASE)
    if not match:
        return "No disponible"
    return match.group(1).strip()


def money_text_to_float(text):
    value = str(text or "").strip()
    if not value or value == "No disponible":
        return None
    match = re.search(r"-?\s*\$?\s*[\d\.,]+", value)
    if not match:
        return None
    compact = match.group(0).replace("$", "").replace(" ", "")
    if "." in compact and "," in compact:
        normalized = compact.replace(".", "").replace(",", ".")
    elif compact.count(".") > 1:
        normalized = compact.replace(".", "")
    elif compact.count(",") > 1:
        normalized = compact.replace(",", "")
    elif "," in compact:
        normalized = compact.replace(".", "").replace(",", ".")
    else:
        normalized = compact
    try:
        return float(normalized)
    except ValueError:
        return None


def format_percentage_ar(value):
    try:
        return f"{float(value):.1f}%".replace(".", ",")
    except (TypeError, ValueError):
        return "No disponible"


def add_months(day, months):
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def dashboard_sales_report(desde, hasta):
    output = run_script(
        "analisis_categorias.ps1",
        ["-AgruparPor", "total", "-Tipos", "Ambos", "-Desde", desde, "-Hasta", hasta],
        timeout=180,
    )
    total = extract_money_value(output, r"Total real ventas:\s*([^\r\n]+)")
    if total == "No disponible":
        total = extract_money_value(output, r"Importe total considerado:\s*([^\r\n]+)")
    if total == "No disponible":
        total = extract_money_value(output, r"Total:\s*([^\r\n]+)")
    no_clasificado = extract_money_value(output, r"No clasificado:\s*([^\r\n]+)")
    return {
        "total_text": total,
        "total": money_text_to_float(total),
        "no_clasificado_text": no_clasificado,
        "no_clasificado": money_text_to_float(no_clasificado),
        "output": output,
    }


def dashboard_sales_total(desde, hasta):
    return dashboard_sales_report(desde, hasta)["total_text"]


def dashboard_cobros_report(desde, hasta):
    hasta_exclusive = (datetime.strptime(hasta, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
    output = run_ps(["cobros", "todos", "-Desde", desde, "-Hasta", hasta_exclusive], timeout=240)
    total = extract_money_value(output, r"Total:\s*([^\r\n]+)")
    return {"total_text": total, "total": money_text_to_float(total), "output": output}


SALES_COLLECTION_TYPES = ("FTS A", "FT A", "FTS B", "FT B", "FP A", "FP B")
SALES_REMIT_TYPES = ("RMT",)
COLLECTION_CONTROL_TOLERANCE = 1.0


def access_date_literal(day):
    if isinstance(day, str):
        parsed = datetime.strptime(day, "%Y-%m-%d").date()
    else:
        parsed = day
    return f"#{parsed.month:02d}/{parsed.day:02d}/{parsed.year:04d}#"


def safe_float(value, default=0.0):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_date_ar(day):
    if isinstance(day, str):
        parsed = datetime.strptime(day, "%Y-%m-%d").date()
    else:
        parsed = day
    return parsed.strftime("%d/%m/%Y")


def format_period_ar(start, end):
    return f"{format_date_ar(start)} al {format_date_ar(end)}"


def dashboard_gerencial_periods(today):
    current_week_start = today - timedelta(days=today.weekday())
    last_week_start = current_week_start - timedelta(days=7)
    last_week_end = current_week_start - timedelta(days=1)
    previous_week_start = current_week_start - timedelta(days=14)
    previous_week_end = current_week_start - timedelta(days=8)
    current_month_start = today.replace(day=1)
    previous_month_start = add_months(current_month_start, -1)
    previous_month_end = add_months(today, -1)
    previous_three_month_start = add_months(current_month_start, -3)
    previous_three_month_end = current_month_start - timedelta(days=1)
    return {
        "last_week": {"start": last_week_start, "end": last_week_end},
        "previous_week": {"start": previous_week_start, "end": previous_week_end},
        "current_month": {"start": current_month_start, "end": today},
        "previous_month_same": {"start": previous_month_start, "end": previous_month_end},
        "previous_three_months": {"start": previous_three_month_start, "end": previous_three_month_end},
    }


def empty_period_summary(start, end):
    return {
        "start": start,
        "end": end,
        "sales": {"total": 0.0, "facturado": 0.0, "remitos": 0.0},
        "collection": {
            "count": 0,
            "emitido": 0.0,
            "applied_total": 0.0,
            "trusted_collected": 0.0,
            "pending": 0.0,
            "saldo_collected": 0.0,
            "difference_review_total": 0.0,
            "review_count": 0,
            "hard_inconsistency_count": 0,
            "collected_pct": None,
            "review_rows": [],
        },
    }


def dashboard_access_data_for_periods(periods):
    starts = [period["start"] for period in periods.values()]
    ends = [period["end"] for period in periods.values()]
    global_start = min(starts)
    global_end_exclusive = max(ends) + timedelta(days=1)
    type_list = ", ".join(f"'{tipo}'" for tipo in SALES_COLLECTION_TYPES)
    all_type_list = ", ".join(f"'{tipo}'" for tipo in SALES_COLLECTION_TYPES + SALES_REMIT_TYPES)
    sql = f"""
SELECT
    C.IdCOMPROVANTE,
    C.TIPO,
    C.[Nº] AS Numero,
    C.FECHA,
    C.IdCLIENTE,
    CL.[RAZ SOCIAL] AS Cliente,
    C.IMPORTE AS Emitido,
    C.SALDO AS PendienteActual,
    IIf(IsNull(A.CobradoAplicado),0,A.CobradoAplicado) AS CobradoAplicado,
    (C.IMPORTE - C.SALDO) AS CobradoPorSaldo,
    ((C.IMPORTE - C.SALDO) - IIf(IsNull(A.CobradoAplicado),0,A.CobradoAplicado)) AS DiferenciaControl
FROM (COMPROVANTES AS C
LEFT JOIN
(
    SELECT IdCOMPROVANTE, Sum(IMPORTE) AS CobradoAplicado
    FROM DETPAGO
    WHERE IdCOMPROVANTE IN
    (
        SELECT IdCOMPROVANTE
        FROM COMPROVANTES
        WHERE FECHA >= {access_date_literal(global_start)}
          AND FECHA < {access_date_literal(global_end_exclusive)}
          AND TIPO IN ({type_list})
    )
    GROUP BY IdCOMPROVANTE
) AS A
ON C.IdCOMPROVANTE = A.IdCOMPROVANTE)
LEFT JOIN CLIENTES AS CL
ON C.IdCLIENTE = CL.IdCLIENTE
WHERE C.FECHA >= {access_date_literal(global_start)}
  AND C.FECHA < {access_date_literal(global_end_exclusive)}
  AND C.TIPO IN ({all_type_list})
ORDER BY C.FECHA, C.TIPO, C.[Nº]
""".strip()
    client_sql = f"""
SELECT
    C.IdCLIENTE,
    CL.[RAZ SOCIAL] AS Cliente,
    C.FECHA,
    C.IMPORTE AS Importe
FROM COMPROVANTES AS C
LEFT JOIN CLIENTES AS CL
ON C.IdCLIENTE = CL.IdCLIENTE
WHERE C.FECHA >= {access_date_literal(global_start)}
  AND C.FECHA < {access_date_literal(global_end_exclusive)}
  AND C.IdCLIENTE Is Not Null
ORDER BY C.FECHA, C.IdCLIENTE
""".strip()
    dashboard_database = (
        SETTINGS.databases.local_database
        or ROOT.parent / "CANTERA LA HELENA 1.0_be.accdb"
    )
    database_literal = str(dashboard_database).replace("'", "''")
    hardening_literal = str(ROOT / "access_hardening.ps1").replace("'", "''")
    script = (
        f"$dbPath = '{database_literal}'\n"
        f"$hardeningPath = '{hardening_literal}'\n"
        f"$sql = @'\n{sql}\n'@\n"
        f"$clientSql = @'\n{client_sql}\n'@\n"
        + r"""
$ErrorActionPreference = "Stop"
. $hardeningPath
$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")
$rs = $null
$rsClients = $null
try {
    $rs = $conn.Execute($sql)
    $rows = @()
    while (-not $rs.EOF) {
        $idComprobante = ConvertTo-HelenaInteger $rs.Fields.Item("IdCOMPROVANTE").Value "COMPROVANTES.IdCOMPROVANTE" "BLOCK" "resumen_gerencial"
        $rows += [pscustomobject]@{
            IdCOMPROVANTE = $idComprobante
            Tipo = ConvertTo-HelenaText $rs.Fields.Item("TIPO").Value "COMPROVANTES.TIPO" "BLOCK" "IdCOMPROVANTE=$idComprobante"
            Numero = ConvertTo-HelenaInteger $rs.Fields.Item("Numero").Value "COMPROVANTES.Nº" "BLOCK" "IdCOMPROVANTE=$idComprobante"
            Fecha = (ConvertTo-HelenaDate $rs.Fields.Item("FECHA").Value "COMPROVANTES.FECHA" "BLOCK" "IdCOMPROVANTE=$idComprobante").ToString("yyyy-MM-dd")
            IdCLIENTE = ConvertTo-HelenaInteger $rs.Fields.Item("IdCLIENTE").Value "COMPROVANTES.IdCLIENTE" "NULL" "IdCOMPROVANTE=$idComprobante"
            Cliente = ConvertTo-HelenaText $rs.Fields.Item("Cliente").Value "CLIENTES.RAZ SOCIAL" "EMPTY" "IdCOMPROVANTE=$idComprobante"
            Emitido = ConvertTo-HelenaDecimal $rs.Fields.Item("Emitido").Value "COMPROVANTES.IMPORTE" "ZERO" "IdCOMPROVANTE=$idComprobante"
            PendienteActual = ConvertTo-HelenaDecimal $rs.Fields.Item("PendienteActual").Value "COMPROVANTES.SALDO" "ZERO" "IdCOMPROVANTE=$idComprobante"
            CobradoAplicado = ConvertTo-HelenaDecimal $rs.Fields.Item("CobradoAplicado").Value "DETPAGO.IMPORTE_AGRUPADO" "ZERO" "IdCOMPROVANTE=$idComprobante"
            CobradoPorSaldo = ConvertTo-HelenaDecimal $rs.Fields.Item("CobradoPorSaldo").Value "COBRADO_POR_SALDO" "ZERO" "IdCOMPROVANTE=$idComprobante"
            DiferenciaControl = ConvertTo-HelenaDecimal $rs.Fields.Item("DiferenciaControl").Value "DIFERENCIA_CONTROL" "ZERO" "IdCOMPROVANTE=$idComprobante"
        }
        $rs.MoveNext()
    }
    $rsClients = $conn.Execute($clientSql)
    $clientRows = @()
    while (-not $rsClients.EOF) {
        $clientRows += [pscustomobject]@{
            IdCLIENTE = ConvertTo-HelenaInteger $rsClients.Fields.Item("IdCLIENTE").Value "COMPROVANTES.IdCLIENTE" "BLOCK" "resumen_gerencial_clientes"
            Cliente = ConvertTo-HelenaText $rsClients.Fields.Item("Cliente").Value "CLIENTES.RAZ SOCIAL" "EMPTY" "resumen_gerencial_clientes"
            Fecha = (ConvertTo-HelenaDate $rsClients.Fields.Item("FECHA").Value "COMPROVANTES.FECHA" "BLOCK" "resumen_gerencial_clientes").ToString("yyyy-MM-dd")
            Importe = ConvertTo-HelenaDecimal $rsClients.Fields.Item("Importe").Value "COMPROVANTES.IMPORTE" "ZERO" "resumen_gerencial_clientes"
        }
        $rsClients.MoveNext()
    }
    [pscustomobject]@{ Estado = "OK"; Registros = $rows; Clientes = $clientRows } | ConvertTo-Json -Depth 6 -Compress
}
catch {
    throw (Format-HelenaErrorDetail "resumen_gerencial" "leer_ventas_cobranza" $_)
}
finally {
    if ($rs -and $rs.State -eq 1) { $rs.Close() }
    if ($rsClients -and $rsClients.State -eq 1) { $rsClients.Close() }
    if ($conn.State -eq 1) { $conn.Close() }
}
"""
    )
    completed = run_text_subprocess(
        powershell_inline_command(script, powershell_executable=CONFIG["powershell"]),
        cwd=str(ROOT),
        capture_output=True,
        timeout=180,
    )
    output = (completed.stdout or "").strip()
    error = (completed.stderr or "").strip()
    if completed.returncode != 0:
        raise RuntimeError(clean_script_error(error or output or f"PowerShell salio con codigo {completed.returncode}"))
    data = json.loads(output or "{}")
    if data.get("Estado") != "OK":
        raise RuntimeError("No se pudo leer cobranza real por comprobante.")
    rows = data.get("Registros") or []
    if isinstance(rows, dict):
        rows = [rows]
    client_rows = data.get("Clientes") or []
    if isinstance(client_rows, dict):
        client_rows = [client_rows]
    return {"Registros": rows, "Clientes": client_rows}


def dashboard_access_rows_for_periods(periods):
    return dashboard_access_data_for_periods(periods)["Registros"]


def collection_row_reasons(row):
    emitido = safe_float(row.get("Emitido"))
    pendiente = safe_float(row.get("PendienteActual"))
    aplicado = safe_float(row.get("CobradoAplicado"))
    cobrado_saldo = safe_float(row.get("CobradoPorSaldo"))
    diferencia = safe_float(row.get("DiferenciaControl"))
    reasons = []
    if abs(diferencia) > COLLECTION_CONTROL_TOLERANCE:
        reasons.append("diferencia_control")
    if aplicado - emitido > COLLECTION_CONTROL_TOLERANCE:
        reasons.append("cobrado_mayor_emitido")
    if pendiente < -COLLECTION_CONTROL_TOLERANCE:
        reasons.append("pendiente_negativo")
    if cobrado_saldo - emitido > COLLECTION_CONTROL_TOLERANCE:
        reasons.append("cobrado_por_saldo_mayor_emitido")
    return reasons


def summarize_collection_rows(rows):
    emitido_total = 0.0
    pending_total = 0.0
    applied_total = 0.0
    saldo_collected_total = 0.0
    trusted_collected = 0.0
    difference_review_total = 0.0
    review_count = 0
    hard_inconsistency_count = 0
    review_rows = []

    for row in rows:
        emitido = safe_float(row.get("Emitido"))
        pendiente = safe_float(row.get("PendienteActual"))
        aplicado = safe_float(row.get("CobradoAplicado"))
        cobrado_saldo = safe_float(row.get("CobradoPorSaldo"))
        diferencia = safe_float(row.get("DiferenciaControl"))

        emitido_total += emitido
        pending_total += pendiente
        applied_total += aplicado
        saldo_collected_total += cobrado_saldo

        reasons = collection_row_reasons(row)
        if "diferencia_control" in reasons:
            difference_review_total += abs(diferencia)

        if reasons:
            review_count += 1
            if any(reason != "diferencia_control" for reason in reasons):
                hard_inconsistency_count += 1
            review_row = dict(row)
            review_row["Motivos"] = reasons
            review_rows.append(review_row)
        else:
            trusted_collected += aplicado

    collected_pct = None
    if emitido_total > 0 and trusted_collected <= emitido_total + COLLECTION_CONTROL_TOLERANCE:
        collected_pct = (trusted_collected / emitido_total) * 100

    return {
        "count": len(rows),
        "emitido": emitido_total,
        "applied_total": applied_total,
        "trusted_collected": trusted_collected,
        "pending": pending_total,
        "saldo_collected": saldo_collected_total,
        "difference_review_total": difference_review_total,
        "review_count": review_count,
        "hard_inconsistency_count": hard_inconsistency_count,
        "collected_pct": collected_pct,
        "review_rows": review_rows,
    }


def dashboard_access_summary(periods):
    data = dashboard_access_data_for_periods(periods)
    rows = data["Registros"]
    client_movements = data["Clientes"]
    summary = {
        "periods": {
            key: empty_period_summary(value["start"], value["end"])
            for key, value in periods.items()
        },
        "review_rows": [],
        "client_rows": {key: [] for key in periods},
    }

    invoice_types = set(SALES_COLLECTION_TYPES)
    remit_types = set(SALES_REMIT_TYPES)
    rows_by_period = {key: [] for key in periods}

    for row in rows:
        fecha = datetime.strptime(row.get("Fecha"), "%Y-%m-%d").date()
        tipo = str(row.get("Tipo") or "").strip().upper()
        importe = safe_float(row.get("Emitido"))
        for key, period in periods.items():
            if not (period["start"] <= fecha <= period["end"]):
                continue
            sales = summary["periods"][key]["sales"]
            if tipo in invoice_types:
                sales["facturado"] += importe
                rows_by_period[key].append(row)
            elif tipo in remit_types:
                sales["remitos"] += importe
            sales["total"] = sales["facturado"] + sales["remitos"]

    review_by_id = {}
    for key, period_rows in rows_by_period.items():
        collection = summarize_collection_rows(period_rows)
        summary["periods"][key]["collection"] = collection
        for row in collection["review_rows"]:
            row_key = int(row.get("IdCOMPROVANTE") or 0)
            existing = review_by_id.setdefault(row_key, dict(row))
            periods_seen = set(existing.get("Periodos") or [])
            periods_seen.add(key)
            existing["Periodos"] = sorted(periods_seen)
            review_by_id[row_key] = existing

    summary["review_rows"] = sorted(
        review_by_id.values(),
        key=lambda item: abs(safe_float(item.get("DiferenciaControl"))),
        reverse=True,
    )

    client_totals_by_period = {key: {} for key in periods}
    for row in client_movements:
        fecha = datetime.strptime(row.get("Fecha"), "%Y-%m-%d").date()
        for key, period in periods.items():
            if not (period["start"] <= fecha <= period["end"]):
                continue
            client_id = str(row.get("IdCLIENTE") or "").strip()
            if not client_id:
                continue
            client_totals = client_totals_by_period[key].setdefault(
                client_id,
                {
                    "id": client_id,
                    "cliente": str(row.get("Cliente") or "").strip() or "Cliente sin nombre",
                    "total": 0.0,
                },
            )
            client_totals["total"] += safe_float(row.get("Importe"))

    for key, client_totals in client_totals_by_period.items():
        summary["client_rows"][key] = [
            row for row in client_totals.values()
            if row["total"] > 0
        ]

    return summary


def dashboard_real_collection_rows(desde, hasta):
    start = datetime.strptime(desde, "%Y-%m-%d").date()
    end = datetime.strptime(hasta, "%Y-%m-%d").date()
    periods = {"requested": {"start": start, "end": end}}
    return dashboard_access_rows_for_periods(periods)


def dashboard_real_collection_report(desde, hasta):
    rows = dashboard_real_collection_rows(desde, hasta)
    rows = [row for row in rows if str(row.get("Tipo") or "").strip().upper() in set(SALES_COLLECTION_TYPES)]
    return summarize_collection_rows(rows)


def collection_sales_report(collection):
    total = (collection or {}).get("emitido")
    return {"total": total, "total_text": format_money_ar(total)}


def report_total_text(report):
    text = str((report or {}).get("total_text") or "").strip()
    if text and text != "No disponible":
        return text
    total = (report or {}).get("total")
    return format_money_ar(total) if total is not None else "No disponible"


def sales_drop_severity(drop_pct):
    if drop_pct > 35:
        return "🔴"
    if drop_pct > 25:
        return "🟠"
    if drop_pct > 15:
        return "🟡"
    return None


def collection_severity(collected_pct):
    if collected_pct is None:
        return None
    if collected_pct < 40:
        return "🔴"
    if collected_pct < 60:
        return "🟠"
    return None


def collection_difference_severity(amount):
    if amount <= COLLECTION_CONTROL_TOLERANCE:
        return None
    if amount >= 1_000_000:
        return "🟠"
    return "🟡"


def worst_alert_severity(*severities):
    order = {"🟡": 1, "🟠": 2, "🔴": 3}
    valid = [severity for severity in severities if severity in order]
    if not valid:
        return None
    return max(valid, key=lambda severity: order[severity])


def sales_variation_pct(current, previous):
    current_total = (current or {}).get("total")
    previous_total = (previous or {}).get("total")
    if previous_total is None or previous_total <= 0 or current_total is None:
        return None
    return ((current_total - previous_total) / previous_total) * 100


def collection_period_lines(label, collection):
    pending = collection.get("pending")
    pending_text = "No confiable" if pending is not None and pending < -COLLECTION_CONTROL_TOLERANCE else format_money_ar(max(0.0, safe_float(pending)))
    pct = collection.get("collected_pct")
    pct_text = format_percentage_ar(min(100.0, pct)) if pct is not None and pct <= 100 else "No confiable"
    return [
        f"{label}:",
        f"Emitido: {format_money_ar(collection.get('emitido'))}",
        f"Cobrado aplicado: {format_money_ar(collection.get('trusted_collected'))}",
        f"Pendiente: {pending_text}",
        f"Cobrado: {pct_text}",
        "",
        "Pendiente incluye comprobantes que pueden no haber vencido todavía.",
    ]


def comparison_lines(title, current_label, current, previous_label, previous):
    current_total = current.get("total")
    previous_total = previous.get("total")
    variation_pct = sales_variation_pct(current, previous)
    return [
        f"{title}:",
        f"{current_label}:",
        report_total_text({"total": current_total}),
        f"{previous_label}:",
        report_total_text({"total": previous_total}),
        "Variación:",
        format_percentage_ar(variation_pct),
    ]


def sales_collection_alert(label, current, previous, collection):
    current_total = current.get("total")
    previous_total = previous.get("total")
    if current_total is None:
        return None

    variation_pct = None
    drop_severity = None
    if previous_total is not None and previous_total > 0:
        variation_pct = sales_variation_pct(current, previous)
        drop_pct = -variation_pct
        drop_severity = sales_drop_severity(drop_pct)

    cobranza_severity = collection_severity(collection.get("collected_pct"))

    severity = worst_alert_severity(drop_severity, cobranza_severity)
    if not severity:
        return None

    lines = [f"{severity} 💵 COBRANZA DE VENTAS EMITIDAS", ""]
    lines.extend(collection_period_lines(label, collection))
    return "\n".join(lines)


def safe_unlink_output_csv(csv_path):
    try:
        path = Path(csv_path)
        resolved_path = path.resolve()
        resolved_outputs = OUTPUTS.resolve()
        if resolved_outputs not in resolved_path.parents:
            return
        if not path.name.startswith("ranking_clientes_"):
            return
        path.unlink(missing_ok=True)
    except Exception as exc:
        log_event(f"DASHBOARD ranking_clientes_csv_cleanup_error {exc}")


def dashboard_client_sales_rows(desde, hasta):
    pattern = f"ranking_clientes_todos_{desde}_{hasta}_*.csv"
    before = {path.resolve() for path in OUTPUTS.glob(pattern)}
    output = run_script(
        "ranking_clientes.ps1",
        ["-Accion", "todos", "-Top", "10000", "-Desde", desde, "-Hasta", hasta, "-ExportCsv"],
        timeout=300,
    )

    csv_path = None
    match = re.search(r"CSV exportado:\s*(.+?\.csv)", output, flags=re.IGNORECASE)
    if match:
        candidate = Path(match.group(1).strip().strip('"'))
        if candidate.exists():
            csv_path = candidate

    if csv_path is None:
        generated = [path for path in OUTPUTS.glob(pattern) if path.resolve() not in before]
        if not generated:
            generated = list(OUTPUTS.glob(pattern))
        if generated:
            csv_path = max(generated, key=lambda path: path.stat().st_mtime)

    if csv_path is None or not csv_path.exists():
        return []

    rows = []
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                total = money_text_to_float(row.get("TotalVendido"))
                if total is None or total <= 0:
                    continue
                cliente = str(row.get("Cliente") or "").strip() or "Cliente sin nombre"
                rows.append(
                    {
                        "id": str(row.get("IdCLIENTE") or "").strip(),
                        "cliente": cliente,
                        "total": total,
                    }
                )
    finally:
        safe_unlink_output_csv(csv_path)

    return rows


def client_sales_key(row):
    client_id = str((row or {}).get("id") or "").strip()
    if client_id:
        return f"id:{client_id}"
    return f"cliente:{client_key((row or {}).get('cliente') or '')}"


def client_concentration_alert(month_sales, client_rows):
    total_month = (month_sales or {}).get("total")
    if total_month is None or total_month <= 0:
        return None
    top_clients = sorted(client_rows or [], key=lambda row: row["total"], reverse=True)[:3]
    if len(top_clients) < 3:
        return None
    top_total = sum(row["total"] for row in top_clients)
    top_pct = (top_total / total_month) * 100
    if top_pct <= 50:
        return None

    lines = [f"🟠 Los 3 principales clientes concentran {format_percentage_ar(top_pct)} de las ventas del mes."]
    for row in top_clients:
        client_pct = (row["total"] / total_month) * 100
        lines.append(f"{row['cliente']}: {format_money_ar(row['total'])} / {format_percentage_ar(client_pct)}")
    return "\n".join(lines)


def client_behavior_alert(current_rows, previous_three_month_rows):
    current_by_client = {client_sales_key(row): row for row in current_rows or []}
    drops = []
    for previous in previous_three_month_rows or []:
        previous_average = previous["total"] / 3
        if previous_average <= 1_000_000:
            continue
        current_total = current_by_client.get(client_sales_key(previous), {}).get("total", 0)
        drop_pct = ((previous_average - current_total) / previous_average) * 100
        if drop_pct > 40:
            drops.append(
                {
                    "cliente": previous["cliente"],
                    "drop_pct": drop_pct,
                    "previous_average": previous_average,
                    "current_total": current_total,
                }
            )

    if not drops:
        return None

    drops.sort(key=lambda row: (row["drop_pct"], row["previous_average"]), reverse=True)
    lines = ["🟠 CAMBIO DE COMPORTAMIENTO DE CLIENTES"]
    for row in drops[:5]:
        lines.extend(
            [
                "",
                f"• {row['cliente']}",
                "",
                "Promedio últimos 3 meses:",
                format_money_ar(row["previous_average"]),
                "",
                "Mes actual:",
                format_money_ar(row["current_total"]),
                "",
                "Variación:",
                f"-{format_percentage_ar(row['drop_pct'])}",
            ]
        )
    return "\n".join(lines)


def dashboard_iva_review_alert(today):
    settings = CONFIG.get("iva_alerts") or {}
    if not settings.get("enabled", True):
        return None
    target_day = first_business_day_last_week(today.year, today.month)
    if today < target_day:
        return None
    period = f"{today.year:04d}-{today.month:02d}"
    return f"🟡 IVA: corresponde revisar IVA mensual del período {period}."


def sales_report_from_summary(period_summary):
    sales = (period_summary or {}).get("sales") or {}
    return {"total": sales.get("total"), "total_text": format_money_ar(sales.get("total"))}


def collection_alert_severity(access_summary):
    periods = access_summary["periods"]
    severities = []
    weekly_variation = sales_variation_pct(
        sales_report_from_summary(periods["last_week"]),
        sales_report_from_summary(periods["previous_week"]),
    )
    monthly_variation = sales_variation_pct(
        sales_report_from_summary(periods["current_month"]),
        sales_report_from_summary(periods["previous_month_same"]),
    )
    if weekly_variation is not None:
        severities.append(sales_drop_severity(-weekly_variation))
    if monthly_variation is not None:
        severities.append(sales_drop_severity(-monthly_variation))
    severities.append(collection_severity(periods["last_week"]["collection"].get("collected_pct")))
    severities.append(collection_severity(periods["current_month"]["collection"].get("collected_pct")))
    total_difference = sum(
        abs(safe_float(row.get("DiferenciaControl")))
        for row in access_summary.get("review_rows") or []
    )
    severities.append(collection_difference_severity(total_difference))
    return worst_alert_severity(*severities)


def dashboard_collection_alert(access_summary):
    severity = collection_alert_severity(access_summary)
    if not severity:
        return None
    periods = access_summary["periods"]
    lines = [f"{severity} 💵 COBRANZA DE VENTAS EMITIDAS", ""]
    lines.extend(collection_period_lines("Semana anterior", periods["last_week"]["collection"]))
    lines.extend(["", *comparison_lines(
        "Comparación semanal",
        "Semana anterior",
        sales_report_from_summary(periods["last_week"]),
        "Semana previa",
        sales_report_from_summary(periods["previous_week"]),
    )])
    lines.extend(["", "━━━━━━━━━━━━━━━━━━", ""])
    lines.extend(collection_period_lines("Mes actual", periods["current_month"]["collection"]))
    lines.extend(["", *comparison_lines(
        "Comparación mensual",
        "Mes actual hasta hoy",
        sales_report_from_summary(periods["current_month"]),
        "Mismo tramo del mes anterior",
        sales_report_from_summary(periods["previous_month_same"]),
    )])
    if (
        periods["last_week"]["collection"].get("hard_inconsistency_count")
        or periods["current_month"]["collection"].get("hard_inconsistency_count")
    ):
        lines.extend(["", "⚠️ Hay comprobantes con cobrado mayor al emitido o pendiente negativo. Revisar."])
    return "\n".join(lines)


def format_review_comprobante(row):
    lines = [
        f"• Id {row.get('IdCOMPROVANTE')}",
        f"Tipo y número: {row.get('Tipo')} {row.get('Numero')}",
        f"Cliente: {row.get('Cliente') or row.get('IdCLIENTE') or '-'}",
        f"Importe: {format_money_ar(row.get('Emitido'))}",
        f"Saldo: {format_money_ar(row.get('PendienteActual'))}",
        f"Pagos imputados: {format_money_ar(row.get('CobradoAplicado'))}",
        f"Diferencia: {format_money_ar(row.get('DiferenciaControl'))}",
    ]
    if abs(safe_float(row.get("Emitido"))) <= COLLECTION_CONTROL_TOLERANCE and abs(safe_float(row.get("PendienteActual"))) > COLLECTION_CONTROL_TOLERANCE:
        lines.append("⚠️ Comprobante con saldo sin importe. Revisar.")
    return "\n".join(lines)


def dashboard_collection_review_alert(access_summary):
    review_rows = list(access_summary.get("review_rows") or [])
    if not review_rows:
        return None
    total_difference = sum(abs(safe_float(row.get("DiferenciaControl"))) for row in review_rows)
    severity = collection_difference_severity(total_difference) or "🟡"
    lines = [
        f"{severity} ⚠️ Comprobantes con diferencias entre pagos imputados y saldo",
        "",
        "Diferencia entre pagos imputados y saldo",
        f"Importe de diferencia: {format_money_ar(total_difference)}",
        f"Comprobantes afectados: {len(review_rows)}",
        "",
    ]
    for row in review_rows[:5]:
        lines.append(format_review_comprobante(row))
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    if len(review_rows) > 5:
        lines.append(f"... y {len(review_rows) - 5} comprobantes más.")
    return "\n".join(lines)


def dashboard_gerencial_alert_lines(today, month_sales=None, access_summary=None):
    alerts = []
    periods = dashboard_gerencial_periods(today)
    current_month_start = today.replace(day=1)

    try:
        if access_summary is None:
            access_summary = dashboard_access_summary(periods)
        alert = dashboard_collection_alert(access_summary)
        if alert:
            alerts.append(alert)
    except Exception as exc:
        log_event(f"DASHBOARD alerta_ventas_cobranza_error {exc}")

    try:
        if access_summary is None:
            access_summary = dashboard_access_summary(periods)
        alert = dashboard_collection_review_alert(access_summary)
        if alert:
            alerts.append(alert)
    except Exception as exc:
        log_event(f"DASHBOARD alerta_diferencia_cobranza_error {exc}")

    current_month_client_rows = None
    try:
        if month_sales is None:
            month_sales = sales_report_from_summary(access_summary["periods"]["current_month"])
        current_month_client_rows = access_summary.get("client_rows", {}).get("current_month", [])
        alert = client_concentration_alert(month_sales, current_month_client_rows)
        if alert:
            alerts.append(alert)
    except Exception as exc:
        log_event(f"DASHBOARD alerta_concentracion_clientes_error {exc}")

    try:
        if current_month_client_rows is None:
            current_month_client_rows = access_summary.get("client_rows", {}).get("current_month", [])
        previous_three_month_rows = access_summary.get("client_rows", {}).get("previous_three_months", [])
        alert = client_behavior_alert(current_month_client_rows, previous_three_month_rows)
        if alert:
            alerts.append(alert)
    except Exception as exc:
        log_event(f"DASHBOARD alerta_comportamiento_clientes_error {exc}")

    try:
        alert = dashboard_iva_review_alert(today)
        if alert:
            alerts.append(alert)
    except Exception as exc:
        log_event(f"DASHBOARD alerta_iva_error {exc}")

    try:
        if month_sales is None:
            month_sales = dashboard_sales_report(current_month_start.isoformat(), today.isoformat())
        no_clasificado = month_sales.get("no_clasificado")
        if no_clasificado is not None and no_clasificado > 0:
            alerts.append(
                "🟡 PRODUCTOS NO CLASIFICADOS\n\n"
                "Importe del mes:\n"
                f"{month_sales['no_clasificado_text']}\n\n"
                "Revisar consulta:\n"
                "productos no clasificados"
            )
    except Exception as exc:
        log_event(f"DASHBOARD alerta_no_clasificado_error {exc}")

    if not alerts:
        return ["✅ No se detectaron situaciones que requieran atención."]
    return [f"• {alert}" for alert in alerts]


def dashboard_iva_values():
    anio = date.today().year
    mes = date.today().month
    data = execute_iva_core(
        anio,
        mes,
        timeout_seconds=SETTINGS.timeouts.default_script_seconds,
    )
    return {
        "ventas": str(data.get("iva_ventas") or "No disponible"),
        "gastos": str(data.get("iva_gastos") or "No disponible"),
        "saldo": str(data.get("saldo_iva") or "No disponible"),
    }


def dashboard_cheques_values():
    data = execute_cheques_core(
        "cheques.resumen",
        {"tipo": "TODOS", "filtro_fiscal": "TODOS"},
        timeout_seconds=SETTINGS.timeouts.default_script_seconds,
    )
    rows = data.get("cheques")
    if isinstance(rows, list) and rows:
        legacy_nn_markers = {"*", "NN", "EN CUENTA HUGO", "EN CUENTA GASTON"}

        def legacy_observation_in_scope(item):
            observation = fold_accents(str(item.get("observacion") or "")).strip().upper()
            return not observation or observation in legacy_nn_markers

        def integer_value(item, field):
            try:
                return int(item.get(field))
            except (TypeError, ValueError):
                return None

        current = [
            item
            for item in rows
            if legacy_observation_in_scope(item)
            and integer_value(item, "dias_al_vencimiento") is not None
            and integer_value(item, "dias_al_vencimiento") >= 0
        ]
        cobrar = [
            item
            for item in current
            if integer_value(item, "dias_restantes") is not None
            and integer_value(item, "dias_restantes") <= 0
        ]
        depositar = [
            item
            for item in current
            if integer_value(item, "dias_restantes") is not None
            and integer_value(item, "dias_restantes") > 0
            and str(item.get("tramo") or "").strip().upper() == "0-7 DIAS"
        ]
        amount = lambda items: sum(safe_float(item.get("importe")) for item in items)
        return {
            "total": format_money_ar(amount(current)),
            "cobrar_hoy": format_money_ar(amount(cobrar)),
            "depositar_0_7": format_money_ar(amount(depositar)),
        }
    total = data.get("total_cartera") or {}
    cobrar = data.get("a_cobrar") or {}
    depositar = (data.get("a_depositar") or {}).get("0-7 DIAS") or {}
    return {
        "total": format_money_ar(total.get("total")),
        "cobrar_hoy": format_money_ar(cobrar.get("total")),
        "depositar_0_7": format_money_ar(depositar.get("total")),
    }


def dashboard_empty_access_summary(periods):
    return {
        "periods": {
            key: empty_period_summary(value["start"], value["end"])
            for key, value in periods.items()
        },
        "review_rows": [],
    }


def timed_dashboard_block(timings, name, callback):
    started = time.perf_counter()
    try:
        return callback()
    finally:
        timings[name] = round(time.perf_counter() - started, 3)


def dashboard_log_timings(timings):
    try:
        log_event(f"DASHBOARD_GERENCIAL_TIMINGS {json.dumps(timings, ensure_ascii=False, sort_keys=True)}")
    except Exception:
        pass


def dashboard_sales_week_section(period_summary):
    sales = (period_summary or {}).get("sales") or {}
    start = (period_summary or {}).get("start")
    end = (period_summary or {}).get("end")
    return (
        "💰 Ventas semana anterior\n"
        f"Período: {format_period_ar(start, end)}\n"
        f"Total: {format_money_ar(sales.get('total'))}\n"
        f"Facturado: {format_money_ar(sales.get('facturado'))}\n"
        f"Remitos: {format_money_ar(sales.get('remitos'))}"
    )


def handle_dashboard_gerencial(use_cache=True):
    global LAST_DASHBOARD_GERENCIAL_TIMINGS
    today = date.today()
    cache_key = today.isoformat()
    cached_at = safe_float(DASHBOARD_GERENCIAL_CACHE.get("created_at"))
    if (
        use_cache
        and DASHBOARD_GERENCIAL_CACHE.get("key") == cache_key
        and DASHBOARD_GERENCIAL_CACHE.get("text")
        and time.time() - cached_at < DASHBOARD_GERENCIAL_CACHE_TTL_SECONDS
    ):
        timings = {"cache": 1, "total": 0.0}
        LAST_DASHBOARD_GERENCIAL_TIMINGS = timings
        dashboard_log_timings(timings)
        return DASHBOARD_GERENCIAL_CACHE["text"]

    started_total = time.perf_counter()
    timings = {"cache": 0}
    month_start = today.replace(day=1)
    periods = dashboard_gerencial_periods(today)
    month_sales = None
    access_summary = None

    try:
        timed_dashboard_block(timings, "refresh_access", refresh_access)
    except Exception as exc:
        log_event(f"DASHBOARD refresh_access_error {exc}")

    try:
        access_summary = timed_dashboard_block(
            timings,
            "access_ventas_cobranza",
            lambda: dashboard_access_summary(periods),
        )
    except Exception as exc:
        log_event(f"DASHBOARD access_ventas_cobranza_error {exc}")
        access_summary = dashboard_empty_access_summary(periods)

    try:
        month_sales = timed_dashboard_block(
            timings,
            "ventas_categorias_mes",
            lambda: dashboard_sales_report(month_start.isoformat(), today.isoformat()),
        )
    except Exception as exc:
        log_event(f"DASHBOARD ventas_mes_error {exc}")
        month_sales = sales_report_from_summary(access_summary["periods"]["current_month"])

    try:
        iva = timed_dashboard_block(timings, "iva", dashboard_iva_values)
    except Exception as exc:
        log_event(f"DASHBOARD iva_error {exc}")
        iva = {"ventas": "No disponible", "gastos": "No disponible", "saldo": "No disponible"}

    try:
        cheques = timed_dashboard_block(timings, "cheques", dashboard_cheques_values)
    except Exception as exc:
        log_event(f"DASHBOARD cheques_error {exc}")
        cheques = {"total": "No disponible", "cobrar_hoy": "No disponible", "depositar_0_7": "No disponible"}

    alert_lines = timed_dashboard_block(
        timings,
        "alertas",
        lambda: dashboard_gerencial_alert_lines(today, month_sales, access_summary),
    )

    text = (
        "📊 RESUMEN GERENCIAL\n\n"
        f"Fecha: {today.strftime('%d/%m/%Y')}\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"{dashboard_sales_week_section(access_summary['periods']['last_week'])}\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🧾 IVA estimado\n"
        f"IVA ventas: {iva['ventas']}\n"
        f"IVA gastos: {iva['gastos']}\n"
        f"Saldo IVA: {iva['saldo']}\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💳 Cartera cheques/eCheq\n"
        f"Total cartera: {cheques['total']}\n"
        f"A cobrar hoy: {cheques['cobrar_hoy']}\n"
        f"A depositar 0-7 días: {cheques['depositar_0_7']}\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "⚠️ Alertas\n"
        + "\n".join(alert_lines)
    )
    timings["total"] = round(time.perf_counter() - started_total, 3)
    LAST_DASHBOARD_GERENCIAL_TIMINGS = timings
    DASHBOARD_GERENCIAL_CACHE.update(
        {
            "key": cache_key,
            "created_at": time.time(),
            "text": text,
            "timings": dict(timings),
        }
    )
    dashboard_log_timings(timings)
    return text


def format_cheques_vencimientos_telegram(data):
    rows = list(data.get("cheques") or [])
    dias = int(data.get("plazo_dias") or 7)
    fecha_limite_text = str(data.get("fecha_limite") or "")
    try:
        fecha_limite = date.fromisoformat(fecha_limite_text)
    except ValueError:
        fecha_limite = date.today() + timedelta(days=dias)
    cantidad = int(data.get("cantidad") or 0)
    label_cantidad = "cheque" if cantidad == 1 else "cheques"
    lines = [
        f"💳 Vencimientos próximos {dias} días",
        "",
        f"Total: {format_money_ar(data.get('total'))}",
        f"Cantidad: {cantidad} {label_cantidad}",
        f"Período: hoy al {fecha_limite.strftime('%d/%m/%Y')}",
    ]

    if not rows:
        lines.append("")
        lines.append("No hay vencimientos en el período.")
        return "\n".join(lines)

    current_date = None
    for item in rows:
        try:
            fecha_cobro = date.fromisoformat(str(item.get("fecha_cobro") or ""))
        except ValueError:
            fecha_cobro = None
        if fecha_cobro != current_date:
            current_date = fecha_cobro
            dias_restantes = item.get("dias_restantes")
            try:
                dias_restantes = int(dias_restantes)
            except (TypeError, ValueError):
                dias_restantes = None
            if dias_restantes == 1:
                leyenda = "falta 1 día"
            elif dias_restantes is None:
                leyenda = "sin días calculados"
            else:
                leyenda = f"faltan {dias_restantes} días"
            fecha_texto = fecha_cobro.strftime("%d/%m/%Y") if fecha_cobro else "Sin fecha"
            lines.extend(["", f"{fecha_texto} — {leyenda}"])

        tipo = str(item.get("tipo") or "").replace("CHEQUE FISICO", "CHEQUE FÍSICO")
        banco = str(item.get("banco") or "").strip()
        numero = str(item.get("numero") or "").strip()
        cliente = str(item.get("cliente") or "").strip() or "Sin cliente"
        encabezado = " ".join(part for part in [tipo, banco, numero] if part)
        lines.append(f"• {encabezado}")
        lines.append(f"  {cliente}")
        lines.append(f"  {format_money_ar(item.get('importe'))}")

    return "\n".join(lines)


def parse_facturas_desde_ultimo_pago(text):
    normalized = normalize(repair_common_text_glitches(text))
    lower = fold_accents(normalized).lower()
    if "facturas" not in lower or not re.search(r"\bdesde\s+(?:el\s+)?ultimo\s+pago\b", lower):
        return None

    cliente = re.sub(
        r"\bdesde\s+(?:el\s+)?(?:ultimo|último)\s+pago\b.*$",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip()
    cliente = re.sub(
        r"^(?:dame|enviame|enviar|mandame|pasame|pasar|quiero|necesito)\s+",
        "",
        cliente,
        flags=re.IGNORECASE,
    ).strip()
    cliente = re.sub(r"^facturas(?:\s+pdf)?(?:\s+de)?\s+", "", cliente, flags=re.IGNORECASE).strip()
    cliente = re.sub(r"^(?:de|del|para)\s+", "", cliente, flags=re.IGNORECASE).strip()
    cliente = clean_client_name(cliente)
    if not cliente:
        return None
    return cliente


def parse_facturas_periodo_cliente(text):
    normalized = normalize(repair_common_text_glitches(text))
    lower = fold_accents(normalized).lower()
    if "facturas" not in lower or not re.search(r"\b(?:desde|entre)\b", lower):
        return None
    if re.search(r"\bdesde\s+(?:el\s+)?ultimo\s+pago\b", lower):
        return None

    desde, hasta = parse_account_period(normalized)
    if not desde:
        return {"error": "Indicá la fecha. Ejemplo: facturas CLIENTE_A desde 01/05/2026"}

    body = re.sub(
        r"\b(?:desde|entre)\b.*$",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip()
    body = re.sub(
        r"\b(?:dame|enviame|enviar|mandame|pasame|pasar|quiero|necesito|pdf)\b",
        "",
        body,
        flags=re.IGNORECASE,
    ).strip()
    body = re.sub(
        r"^facturas(?:\s+cliente)?(?:\s+de)?\s+",
        "",
        body,
        flags=re.IGNORECASE,
    ).strip()
    body = re.sub(r"^(?:de|del|para)\s+", "", body, flags=re.IGNORECASE).strip()
    cliente = clean_client_name(body)
    if not cliente:
        return {"error": "Indicá la fecha. Ejemplo: facturas CLIENTE_A desde 01/05/2026"}

    return {"cliente": cliente, "desde": desde, "hasta": hasta}


def normalize_intent_phrase(text):
    normalized = fold_accents(normalize(repair_common_text_glitches(text))).lower().strip()
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def load_intent_dictionary():
    if not INTENT_DICTIONARY_PATH.exists():
        return []
    with INTENT_DICTIONARY_PATH.open("r", encoding="utf-8-sig") as fh:
        return json.load(fh).get("intenciones", [])


def load_intent_dictionary_data():
    if not INTENT_DICTIONARY_PATH.exists():
        return {"version": 1, "intenciones": []}
    with INTENT_DICTIONARY_PATH.open("r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def save_intent_dictionary_data(data):
    INTENT_DICTIONARY_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def today_iso():
    return date.today().isoformat()


def normalize_learned_phrase(text):
    normalized = fold_accents(normalize(repair_common_text_glitches(text))).lower().strip()
    normalized = re.sub(r"[^\w\s/{}áéíóúüñÁÉÍÓÚÜÑ]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def normalize_learned_phrase(text):
    normalized = fold_accents(normalize(repair_common_text_glitches(text))).lower().strip()
    normalized = re.sub(r"[^\w\s/{}]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def extraer_cliente_desde_frase(frase, intencion):
    text = normalize(repair_common_text_glitches(frase)).strip()
    normalized = normalize_intent_phrase(text)
    prefixes = {
        "clientes_saldo": [
            "saldo de",
            "saldo",
            "cuanto debe",
            "cuanto me debe",
            "que deuda tiene",
            "deuda de",
            "deuda",
        ],
        "clientes_resumen_pdf": [
            "resumen de cuenta de",
            "resumen de cuenta",
            "estado de cuenta de",
            "estado de cuenta",
        ],
        "clientes_resumen_ultimo_pago": [
            "resumen de cuenta de",
            "resumen de cuenta",
            "estado de cuenta de",
            "estado de cuenta",
        ],
        "clientes_factura_ultima": [
            "ultima factura de",
            "factura de",
            "ultima factura",
        ],
        "clientes_facturas_desde_ultimo_pago": [
            "facturas de",
            "facturas",
        ],
    }
    for prefix in prefixes.get(canonical_intent_id(intencion), []):
        prefix_normalized = normalize_intent_phrase(prefix)
        if normalized == prefix_normalized:
            return ""
        if normalized.startswith(prefix_normalized + " "):
            prefix_word_count = len(prefix_normalized.split())
            words = text.split()
            if len(words) <= prefix_word_count:
                return ""
            return clean_client_name(" ".join(words[prefix_word_count:]))
    return ""


def extraer_parametros(frase, intencion, params_existentes=None):
    parametros = {
        "cliente": None,
        "desde": None,
        "hasta": None,
        "tipo": None,
        "numero": None,
        "cantidad": None,
        "medio": None,
        "anio": None,
        "mes": None,
        "top": None,
    }
    if params_existentes:
        for key in parametros:
            if params_existentes.get(key) is not None:
                parametros[key] = params_existentes.get(key)

    intent_id = canonical_intent_id(intencion)
    if parametros.get("cliente"):
        return parametros

    if intent_id == "clientes_facturas_desde_ultimo_pago":
        cliente = parse_facturas_desde_ultimo_pago(frase)
        if cliente:
            parametros["cliente"] = cliente
    elif intent_id == "clientes_facturas_periodo":
        parsed = parse_facturas_periodo_cliente(frase)
        if parsed and not parsed.get("error") and parsed.get("cliente"):
            parametros["cliente"] = parsed.get("cliente")
    elif intent_id in {
        "clientes_saldo",
        "clientes_resumen_pdf",
        "clientes_resumen_ultimo_pago",
        "clientes_factura_ultima",
    }:
        cliente = extraer_cliente_desde_frase(frase, intent_id)
        if cliente:
            parametros["cliente"] = cliente

    return parametros


def touch_usage(entry):
    entry["usos"] = int(entry.get("usos", 0) or 0) + 1
    entry["ultimo_uso"] = today_iso()
    entry.setdefault("creado", today_iso())


CLIENT_PATTERN_INTENTS = {
    "clientes_saldo",
    "clientes_resumen_pdf",
    "clientes_factura_ultima",
    "clientes_facturas_desde_ultimo_pago",
    "clientes_resumen_ultimo_pago",
}


def infer_client_pattern(intent_id, phrase):
    intent_id = canonical_intent_id(intent_id)
    if intent_id not in CLIENT_PATTERN_INTENTS:
        return None
    learned = normalize_learned_phrase(phrase)
    if not learned:
        return None

    rules = {
        "clientes_saldo": [
            r"^(saldo\s+de)\s+(.+)$",
            r"^(saldo)\s+(.+)$",
            r"^(cuanto\s+debe)\s+(.+)$",
            r"^(cuanto\s+me\s+debe)\s+(.+)$",
            r"^(que\s+deuda\s+tiene)\s+(.+)$",
            r"^(deuda\s+de)\s+(.+)$",
            r"^(deuda)\s+(.+)$",
        ],
        "clientes_resumen_pdf": [
            r"^(resumen\s+de\s+cuenta\s+de)\s+(.+)$",
            r"^(resumen\s+de\s+cuenta)\s+(.+)$",
            r"^(estado\s+de\s+cuenta\s+de)\s+(.+)$",
            r"^(estado\s+de\s+cuenta)\s+(.+)$",
        ],
        "clientes_resumen_ultimo_pago": [
            r"^(resumen\s+de\s+cuenta\s+de)\s+(.+?)\s+desde\s+(?:el\s+)?ultimo\s+pago$",
            r"^(estado\s+de\s+cuenta\s+de)\s+(.+?)\s+desde\s+(?:el\s+)?ultimo\s+pago$",
        ],
        "clientes_factura_ultima": [
            r"^(ultima\s+factura\s+de)\s+(.+)$",
            r"^(ultima\s+factura)\s+(.+)$",
            r"^(dame\s+ultima\s+factura\s+de)\s+(.+)$",
            r"^(dame\s+ultima\s+factura)\s+(.+)$",
            r"^(quiero\s+ultima\s+factura\s+de)\s+(.+)$",
            r"^(quiero\s+ultima\s+factura)\s+(.+)$",
        ],
        "clientes_facturas_desde_ultimo_pago": [
            r"^(facturas\s+de)\s+(.+?)\s+desde\s+(?:el\s+)?ultimo\s+pago$",
            r"^(facturas)\s+(.+?)\s+desde\s+(?:el\s+)?ultimo\s+pago$",
        ],
    }
    for pattern in rules.get(intent_id, []):
        match = re.match(pattern, learned, flags=re.IGNORECASE)
        if match and match.group(2).strip():
            return f"{match.group(1).strip()} {{cliente}}"
    return None


def pattern_regex(pattern):
    normalized = normalize_learned_phrase(pattern)
    parts = normalized.split("{cliente}")
    if len(parts) != 2:
        return None
    prefix = re.escape(parts[0].strip())
    suffix = re.escape(parts[1].strip())
    if suffix:
        return re.compile(rf"^{prefix}\s+(.+?)\s+{suffix}$", re.IGNORECASE)
    return re.compile(rf"^{prefix}\s+(.+)$", re.IGNORECASE)


def extract_client_from_pattern(pattern, original_text, fallback):
    normalized = normalize_learned_phrase(pattern)
    parts = normalized.split("{cliente}")
    if len(parts) != 2:
        return clean_client_name(fallback)
    prefix_words = parts[0].strip().split()
    suffix_words = parts[1].strip().split()
    original_words = str(original_text or "").strip().split()
    if len(original_words) <= len(prefix_words) + len(suffix_words):
        return clean_client_name(fallback)
    start = len(prefix_words)
    end = len(original_words) - len(suffix_words) if suffix_words else len(original_words)
    return clean_client_name(" ".join(original_words[start:end]))


def find_or_create_dictionary_intent(data, selected):
    intent_id = canonical_intent_id(selected.get("id", ""))
    dictionary_intents = data.setdefault("intenciones", [])
    for item in dictionary_intents:
        if canonical_intent_id(item.get("id", "")) == intent_id:
            item["id"] = intent_id
            item["descripcion"] = selected.get("descripcion", item.get("descripcion", ""))
            item["script"] = selected.get("script", item.get("script", ""))
            item["parametros_base"] = selected.get("parametros_base", item.get("parametros_base", {}))
            item.setdefault("frases", [])
            item.setdefault("patrones", [])
            return item
    item = {
        "id": intent_id,
        "descripcion": selected.get("descripcion", ""),
        "script": selected.get("script", ""),
        "parametros_base": selected.get("parametros_base", {}),
        "frases": [],
        "patrones": [],
    }
    dictionary_intents.append(item)
    return item


def executable_intentions():
    return [
        {"id": intent_id, **intent}
        for intent_id, intent in INTENCIONES_VALIDAS.items()
    ]


def available_intentions_for_add():
    data = load_intent_dictionary_data()
    by_id = {intent["id"]: dict(intent) for intent in executable_intentions()}
    for intent in data.get("intenciones", []):
        intent_id = canonical_intent_id(intent.get("id", ""))
        if intent_id not in by_id:
            continue
        item = {
            "id": intent_id,
            "descripcion": by_id[intent_id].get("descripcion", ""),
            "script": by_id[intent_id].get("script", ""),
            "parametros_base": by_id[intent_id].get("parametros_base", {}),
            "fuente": "diccionario",
        }
        by_id[intent_id].update(item)
    return list(by_id.values())


def load_telegram_users_data():
    if not TELEGRAM_USERS_PATH.exists():
        return None
    try:
        with TELEGRAM_USERS_PATH.open("r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception as exc:
        print(f"No se pudo cargar telegram_usuarios.json: {exc}", flush=True)
        return None


def save_telegram_users_data(data):
    TELEGRAM_USERS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_pending_telegram_users_data():
    if not TELEGRAM_PENDING_USERS_PATH.exists():
        return {"version": 1, "usuarios": []}
    try:
        with TELEGRAM_PENDING_USERS_PATH.open("r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        data.setdefault("version", 1)
        data.setdefault("usuarios", [])
        return data
    except Exception as exc:
        print(f"No se pudo cargar telegram_pending_users.json: {exc}", flush=True)
        return {"version": 1, "usuarios": []}


def save_pending_telegram_users_data(data):
    TELEGRAM_PENDING_USERS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def pending_user_display_name(user):
    first = str(user.get("first_name") or "").strip()
    last = str(user.get("last_name") or "").strip()
    full = " ".join(part for part in (first, last) if part).strip()
    return full or str(user.get("username") or "").strip() or f"Chat {user.get('chat_id')}"


def remove_pending_telegram_user(chat_id):
    data = load_pending_telegram_users_data()
    before = len(data.get("usuarios", []))
    data["usuarios"] = [
        user for user in data.get("usuarios", [])
        if str(user.get("chat_id")) != str(chat_id)
    ]
    if len(data["usuarios"]) != before:
        save_pending_telegram_users_data(data)


def register_pending_telegram_user(message):
    chat_id = message.get("chat", {}).get("id")
    if chat_id is None:
        return
    if allowed(chat_id):
        remove_pending_telegram_user(chat_id)
        return
    from_user = message.get("from") or {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data = load_pending_telegram_users_data()
    users = data.setdefault("usuarios", [])
    pending = next((user for user in users if str(user.get("chat_id")) == str(chat_id)), None)
    if not pending:
        pending = {
            "chat_id": chat_id,
            "first_name": from_user.get("first_name", ""),
            "last_name": from_user.get("last_name", ""),
            "username": from_user.get("username", ""),
            "primer_intento": now,
            "ultimo_intento": now,
        }
        users.append(pending)
    else:
        pending.update(
            {
                "first_name": from_user.get("first_name", pending.get("first_name", "")),
                "last_name": from_user.get("last_name", pending.get("last_name", "")),
                "username": from_user.get("username", pending.get("username", "")),
                "ultimo_intento": now,
            }
        )
        pending.setdefault("primer_intento", now)
    save_pending_telegram_users_data(data)
    log_event(f"TELEGRAM_PENDING registrado chat_id={chat_id} username={pending.get('username', '')!r}")
    registrar_actividad(
        chat_id=chat_id,
        usuario=pending_user_display_name(pending),
        modulo="Usuarios",
        accion="Solicitud de acceso",
        objeto="Usuario Telegram",
        id_objeto=chat_id,
        descripcion="Usuario no autorizado registrado como pendiente",
        nivel="WARNING",
        extra={"username": pending.get("username", "")},
    )


def format_pending_users_for_add():
    data = load_pending_telegram_users_data()
    authorized_ids = set()
    users_data = load_telegram_users_data() or {}
    for user in users_data.get("usuarios", []):
        if user.get("chat_id") not in (None, "") and user.get("activo", False):
            authorized_ids.add(str(user.get("chat_id")))
    config_ids = {str(item) for item in (CONFIG.get("allowed_chat_ids") or [])}
    authorized_ids.update(config_ids)
    pending_users = [
        user for user in data.get("usuarios", [])
        if str(user.get("chat_id")) not in authorized_ids
    ]
    if len(pending_users) != len(data.get("usuarios", [])):
        data["usuarios"] = pending_users
        save_pending_telegram_users_data(data)
    if not pending_users:
        return [], "No hay usuarios pendientes.\n\n0️⃣ Volver"

    lines = ["Usuarios pendientes", ""]
    for index, user in enumerate(pending_users, start=1):
        username = str(user.get("username") or "").strip()
        username_text = f"@{username}" if username else "-"
        lines.extend(
            [
                f"{index}️⃣ {pending_user_display_name(user)}",
                f"Usuario: {username_text}",
                f"Chat ID: {user.get('chat_id')}",
                "",
            ]
        )
    lines.append("0️⃣ Volver")
    return pending_users, "\n".join(lines).strip()


def ensure_telegram_users_data():
    data = load_telegram_users_data()
    if data:
        data.setdefault("usuarios", [])
        data.setdefault("roles", {})
        return data
    return {"version": 1, "roles": {}, "usuarios": []}


def format_users_menu():
    return (
        "Usuarios Telegram\n\n"
        "1️⃣ Listar usuarios\n"
        "2️⃣ Agregar usuario\n"
        "3️⃣ Cambiar rol\n"
        "4️⃣ Activar/desactivar usuario\n"
        "5️⃣ Ver mi usuario"
    )


def format_users_list(data):
    rows = ["Usuarios Telegram\n"]
    for idx, user in enumerate(data.get("usuarios", []), start=1):
        chat_id = user.get("chat_id")
        chat_label = "pendiente" if chat_id in (None, "") else f"...{str(chat_id)[-4:]}"
        rows.append(
            f"{idx}. {user.get('nombre')} | rol {user.get('rol')} | "
            f"Access UserID {user.get('access_user_id')} | activo {user.get('activo')} | chat_id {chat_label}"
        )
    return "\n".join(rows)


def is_admin_chat(chat_id):
    user, data = find_telegram_user(chat_id)
    legacy = legacy_telegram_user(chat_id)
    if legacy.get("role") == "owner":
        return True
    if has_configured_telegram_users(data):
        return bool(user and user.get("activo", False) and user.get("rol") == "administrador")
    return False


def is_gerencial(chat_id):
    user, data = find_telegram_user(chat_id)
    legacy = legacy_telegram_user(chat_id)
    if legacy.get("role") == "owner":
        return True
    if has_configured_telegram_users(data):
        return bool(
            user
            and user.get("activo", False)
            and user.get("rol") in {"administrador", "owner"}
        )
    return legacy.get("role") in {"owner", "administrador"}


def consume_restart_confirmation(chat_id, text):
    pending = PENDING_RESTARTS.get(int(chat_id))
    if not pending:
        return None
    PENDING_RESTARTS.pop(int(chat_id), None)
    log_event(f"RESTART pendiente_viejo_neutralizado chat_id={chat_id}")
    return {"message": RESTART_DISABLED_MESSAGE, "restart": False}

def render_menu_principal(chat_id):
    lines = [
        "🤖 BOT DE CONSULTAS LA HELENA",
        "",
        "💬 Podés escribir o enviar audios.",
        "",
        "Ejemplos:",
        "• saldo CLIENTE",
        "• última factura CLIENTE",
        "• facturas CLIENTE desde 01/05/2026",
        "• ventas de ayer",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "⌨️ COMANDOS",
        "",
        "/ayuda → ayuda rápida",
        "/menu → menú principal",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "🧭 NAVEGACIÓN",
        "",
        "0️⃣ Volver",
        "cancelar, salir o x → cancelar la operación actual",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "🏠 MENÚ PRINCIPAL",
        "",
    ]
    if is_gerencial(chat_id):
        lines.extend(
            [
                "1️⃣ Resumen Gerencial",
                "2️⃣ Clientes",
                "3️⃣ Consultas rápidas",
                "4️⃣ Administración",
            ]
        )
    else:
        lines.extend(
            [
                "1️⃣ Clientes",
                "2️⃣ Consultas rápidas",
            ]
        )
    return "\n".join(lines)


def render_menu_clientes(chat_id):
    return (
        "👥 CLIENTES\n\n"
        "1️⃣ Consultar saldo\n"
        "2️⃣ Resumen de cuenta PDF\n"
        "3️⃣ Facturas PDF\n\n"
        "0️⃣ Menú principal"
    )


def render_menu_consultas_rapidas(chat_id):
    lines = [
        "📋 CONSULTAS RÁPIDAS",
        "",
        "1️⃣ Ventas",
        "2️⃣ Caja",
        "3️⃣ IVA estimado",
    ]
    authorized, _ = authorize_command(chat_id, "cheques_resumen", {})
    if authorized:
        lines.append("4️⃣ Cheques y pagos")
    lines.extend(["", "0️⃣ Menú principal"])
    return "\n".join(lines)


def render_menu_iva_estimado(chat_id):
    return (
        "🧾 IVA estimado\n\n"
        "1️⃣ IVA mes en curso\n"
        "2️⃣ Consultar otro período\n\n"
        "0️⃣ Volver"
    )


def iva_periodo_prompt():
    return "Ingresá el período a consultar.\n\n" + IVA_PERIOD_EXAMPLES


def render_menu_administracion(chat_id):
    return (
        "⚙️ ADMINISTRACIÓN\n\n"
        "1️⃣ Usuarios\n"
        "0️⃣ Volver"
    )


def render_menu_cheques_pagos(chat_id):
    return (
        "🧾 CHEQUES Y PAGOS\n\n"
        "1️⃣ Resumen de cheques/eCheq\n"
        "2️⃣ A cobrar\n"
        "3️⃣ A depositar\n"
        "4️⃣ Armar pago rápido\n\n"
        "0️⃣ Volver"
    )


def render_menu_cheques_filtro(chat_id):
    return (
        "Elegí tipo de valores:\n\n"
        "1️⃣ NN / sin factura\n"
        "2️⃣ Blanco / con factura\n"
        "3️⃣ Todos\n"
        "0️⃣ Volver"
    )


def cheques_vencimientos_dias_prompt():
    return (
        "¿A cuántos días querés consultar?\n\n"
        "Ejemplo:\n"
        "7 días\n"
        "15 días\n"
        "30 días"
    )


def render_menu_pago_rapido(chat_id):
    return (
        "💳 Armar pago rápido\n\n"
        "¿Qué tipo de valores querés usar?\n\n"
        "1️⃣ Pagos NN / sin factura\n"
        "2️⃣ Pagos con factura / cheques en blanco\n"
        "3️⃣ No importa / cualquier cheque\n"
        "0️⃣ Volver"
    )


def render_menu_pago_rapido_instrumento(chat_id):
    return (
        "Elegí instrumento:\n\n"
        "1️⃣ Pago con eCheq\n"
        "2️⃣ Pago con cheques\n"
        "3️⃣ Pago mixto\n"
        "0️⃣ Volver"
    )


def render_menu_pago_rapido_modalidad(chat_id):
    return (
        "Elegí modalidad:\n\n"
        "1️⃣ Pago único\n"
        "2️⃣ Pago fraccionado por plazos\n"
        "0️⃣ Volver"
    )


def pago_rapido_prompt():
    return (
        "Ingresá monto y plazo.\n\n"
        "Ejemplos:\n"
        "$345.000,75 a 40 días\n"
        "$345.000,75 a cobrar\n\n"
        "0️⃣ Volver"
    )


def pago_rapido_fraccionado_prompt():
    return (
        "Ingresá monto total y plazos.\n\n"
        "Ejemplos:\n"
        "Total: 1.000.000\n"
        "Plazos: 30,60,90,a cobrar\n\n"
        "También podés escribir:\n"
        "1.000.000 a 30,60,90,a cobrar\n\n"
        "0️⃣ Volver"
    )


def parse_pago_rapido_plazos(text):
    lower = fold_accents(str(text or "")).lower()
    lower = re.sub(r"\ba\s+cobrar\b", " acobrar ", lower)
    if re.search(r"(?<!\d)-\d+", lower):
        return []
    tokens = re.findall(r"\bacobrar\b|\b\d{1,3}\b", lower)
    days = set()
    for token in tokens:
        if token == "acobrar":
            days.add(0)
            continue
        dias = int(token)
        if 0 <= dias <= 180:
            days.add(dias)
    return [
        {"tipo": "ACOBRAR", "dias": None} if dias == 0 else {"tipo": "DIAS", "dias": dias}
        for dias in sorted(days)
    ]


def parse_pago_rapido_datos(text):
    original = str(text or "")
    lower = fold_accents(original).lower()
    es_a_cobrar = re.search(r"\ba\s+cobrar\b", lower) is not None
    has_days = re.search(r"\b\d+\s*dias?\b", lower) is not None
    dias = parse_days(original, 0) if has_days else 0
    amount_source = re.sub(r"\ba\s+\d+\s*dias?\b", "", lower)
    amount_source = re.sub(r"\ba\s+cobrar\b", "", amount_source)
    importe = parse_money_amount(amount_source)
    if es_a_cobrar:
        return importe, {"tipo": "ACOBRAR", "dias": None}
    if dias:
        return importe, {"tipo": "DIAS", "dias": dias}
    return importe, None


def parse_pago_rapido_fraccionado_datos(text):
    original = str(text or "")
    lower = fold_accents(original).lower()
    amount_source = original
    total_match = re.search(r"total\s*:\s*([^\r\n]+)", original, flags=re.I)
    if total_match:
        amount_source = total_match.group(1)
    else:
        split_match = re.search(r"\ba\s+", lower)
        if split_match:
            amount_source = original[: split_match.start()]
    importe = parse_money_amount(amount_source)
    plazos_text = lower
    match = re.search(r"plazos?\s*:\s*(.+)", lower, flags=re.S)
    if match:
        plazos_text = match.group(1)
    else:
        match = re.search(r"\ba\s+(.+)", lower, flags=re.S)
        if match:
            plazos_text = match.group(1)
    plazos = parse_pago_rapido_plazos(plazos_text)
    return importe, plazos


def pago_rapido_plazo_label(plazo):
    if plazo and plazo.get("tipo") == "ACOBRAR":
        return "A cobrar"
    dias = int((plazo or {}).get("dias") or 0)
    return f"A {dias} días"


def pago_rapido_plazo_resumen(plazo):
    if plazo and plazo.get("tipo") == "ACOBRAR":
        return "A cobrar"
    dias = int((plazo or {}).get("dias") or 0)
    return f"{dias} días"


def pago_rapido_ajuste_linea(resultado, *, pago_simple=False):
    accion = resultado.get("accion_faltante")
    if accion == "TRANSFERIR":
        return f"➡️ Transferir faltante: {format_money_ar(resultado.get('faltante'))}"
    if accion == "AGREGAR_PROPIO":
        instrumento = resultado.get("instrumento_faltante") or "cheque/eCheq"
        return f"➡️ Agregar {instrumento} propio por: {format_money_ar(resultado.get('faltante'))}"
    excedente = resultado.get("excedente")
    if excedente:
        if pago_simple:
            return f"➡️ Excedente: {format_money_ar(excedente)}"
        return f"➡️ Genera nota de crédito por: {format_money_ar(excedente)}"
    return None


def format_pago_rapido_unico(resultado):
    pagos = list(resultado.get("pagos") or [])
    pago = pagos[0] if pagos else resultado
    ajuste = pago_rapido_ajuste_linea(pago, pago_simple=True)
    lines = [
        "💳 PAGO RÁPIDO",
        "",
        f"Tipo: {resultado.get('modo')}",
        f"Filtro: {resultado.get('filtro_fiscal')}",
        f"Plazo: {pago_rapido_plazo_resumen(pago.get('plazo'))}",
        f"Objetivo: {format_money_ar(pago.get('importe_objetivo'))}",
    ]
    if pago.get("alternativa_fuera_ventana_estricta"):
        plan = pago.get("propuesta_relaxed") or {}
        lines.extend(["", "⚠️ Alternativa fuera de la ventana estricta.", "", "Combinación sugerida:"])
        for assignment in plan.get("asignaciones") or []:
            for item in assignment.get("instrumentos") or []:
                deviation = int(item.get("desviacion_dias") or 0)
                direction = "posterior" if deviation > 0 else "anticipado" if deviation < 0 else "en fecha"
                lines.extend(
                    [
                        f"• {item.get('tipo')} {item.get('numero')} — {format_money_ar((item.get('importe_cents') or 0) / 100)}",
                        f"  FechaCobro: {item.get('fecha_cobro')} | Desviación: {abs(deviation)} días {direction}",
                    ]
                )
        selected = float(pago.get("total_seleccionado") or 0)
        difference = max(0.0, float(pago.get("importe_objetivo") or 0) - selected)
        lines.extend(
            [
                "",
                f"Total sugerido: {format_money_ar(selected)}",
                f"Diferencia: {format_money_ar(difference)}",
            ]
        )
    else:
        lines.extend(["", "Cheques sugeridos:", str(pago.get("texto_legacy") or "").strip()])
    if ajuste:
        lines.extend(["", ajuste])
    lines.extend(["", "━━━━━━━━━━━━━━━━━━", "", "0️⃣ Volver"])
    return "\n".join(lines)


def format_pago_rapido_fraccionado(resultado):
    propuestas = list(resultado.get("propuestas") or [])
    plazos = ", ".join(str(0 if item.get("tipo") == "ACOBRAR" else item.get("dias")) for item in resultado.get("plazos") or [])
    lines = [
        "💳 PAGO FRACCIONADO — PROPUESTAS",
        "",
        f"Total solicitado: {format_money_ar(resultado.get('importe_objetivo'))}",
        f"Plazos: {plazos}",
        f"Modo: {resultado.get('modo')}",
        f"Filtro: {resultado.get('filtro_fiscal')}",
    ]
    for index, plan in enumerate(propuestas, start=1):
        metrics = plan.get("metricas") or {}
        lines.extend(
            [
                "",
                f"{index} — {plan.get('nombre')}",
                f"Terceros: {format_money_ar((plan.get('total_terceros_cents') or 0) / 100)}",
                f"Propios: {format_money_ar((plan.get('total_propios_cents') or 0) / 100)}",
                f"Cumplimiento temporal: {float(metrics.get('cumplimiento_temporal') or 0):.1f}%",
                f"Desviación máxima: {int(metrics.get('desviacion_maxima_dias') or 0)} días",
            ]
        )
        if index > 1:
            lines.append(
                f"Ahorro vs estricta: {format_money_ar((metrics.get('ahorro_propios_vs_estricta_cents') or 0) / 100)}"
            )
            lines.append(f"Concentración: {float(metrics.get('concentracion_maxima') or 0) * 100:.1f}%")
    lines.extend(["", "Elegí 1, 2 o 3 para ver el detalle.", "0️⃣ Volver"])
    return "\n".join(lines)


def _own_instrument_text(mode, term, cents):
    days = 0 if term.get("tipo") == "ACOBRAR" else int(term.get("dias") or 0)
    due = "a cobrar" if days == 0 else f"a {days} días"
    instrument = {"ECHEQ": "eCheq propio", "CHEQUE": "cheque propio"}.get(mode, "cheque/eCheq propio")
    return f"{instrument} {due}: {format_money_ar(cents / 100)}"


def format_payment_plan_detail(plan, resultado):
    lines = [
        f"💳 {plan.get('nombre')}",
        "",
    ]
    for assignment in plan.get("asignaciones") or []:
        term = assignment.get("plazo") or {}
        target_days = 0 if term.get("tipo") == "ACOBRAR" else int(term.get("dias") or 0)
        lines.extend(
            [
                f"PLAZO: {'A cobrar' if target_days == 0 else str(target_days) + ' días'}",
                f"Fecha objetivo: {assignment.get('fecha_objetivo')}",
                f"Objetivo: {format_money_ar((assignment.get('objetivo_cents') or 0) / 100)}",
                f"Terceros: {format_money_ar((assignment.get('terceros_cents') or 0) / 100)}",
            ]
        )
        for item in assignment.get("instrumentos") or []:
            deviation = int(item.get("desviacion_dias") or 0)
            direction = "posterior" if deviation > 0 else "anticipado" if deviation < 0 else "en fecha"
            lines.extend(
                [
                    f"• {item.get('tipo')} {item.get('numero')} — {format_money_ar((item.get('importe_cents') or 0) / 100)}",
                    f"  FechaCobro: {item.get('fecha_cobro')} | Desviación: {abs(deviation)} días {direction} | IdENTREGA: {item.get('id_entrega')}",
                ]
            )
        own_cents = int(assignment.get("own_cents") or 0)
        if own_cents:
            lines.append(_own_instrument_text(resultado.get("modo"), term, own_cents))
        lines.extend(
            [
                f"Objetivo acumulado: {format_money_ar((assignment.get('target_accum') or 0) / 100)}",
                f"Acumulado final: {format_money_ar((assignment.get('final_accum') or 0) / 100)}",
                "",
            ]
        )
    metrics = plan.get("metricas") or {}
    lines.extend(
        [
            "RESUMEN",
            f"Total solicitado: {format_money_ar(resultado.get('importe_objetivo'))}",
            f"Terceros: {format_money_ar((plan.get('total_terceros_cents') or 0) / 100)}",
            f"Propios: {format_money_ar((plan.get('total_propios_cents') or 0) / 100)}",
            f"Total final: {format_money_ar((plan.get('total_final_cents') or 0) / 100)}",
            f"Diferencia: {format_money_ar((plan.get('diferencia_cents') or 0) / 100)}",
            f"Ahorro contra estricta: {format_money_ar((metrics.get('ahorro_propios_vs_estricta_cents') or 0) / 100)}",
        ]
    )
    warnings = list(plan.get("advertencias") or [])
    if warnings:
        lines.extend(["", "Advertencias:"] + [f"• {warning}" for warning in warnings])
    lines.extend(["", "ℹ️ Propuesta informativa.", "No se modificó ni endosó ningún cheque.", "", "0️⃣ Volver"])
    return "\n".join(lines)


def payment_ranking_state_data(resultado):
    return {
        "importe_objetivo": resultado.get("importe_objetivo"),
        "modo": resultado.get("modo"),
        "filtro_fiscal": resultado.get("filtro_fiscal"),
        "plazos": list(resultado.get("plazos") or []),
        "propuestas": [
            {key: value for key, value in plan.items() if key != "stats"}
            for plan in resultado.get("propuestas") or []
        ],
    }
def clear_chat_states(chat_id, include_restart=False):
    key = int(chat_id)
    MENU_STATES.pop(key, None)
    PENDING_USER_MANAGEMENT.pop(key, None)
    PENDING_INTENT_ADDS.pop(key, None)
    PENDING_SELECTIONS.pop(key, None)
    if include_restart:
        PENDING_RESTARTS.pop(key, None)


def reset_inactive_chat_state(chat_id):
    key = int(chat_id)
    now = time.time()
    last_activity = CHAT_LAST_ACTIVITY.get(key)
    expired = bool(last_activity and now - last_activity > MENU_STATE_TTL_SECONDS)
    if expired:
        clear_chat_states(chat_id, include_restart=True)
        log_event(
            f"MENU_TIMEOUT chat_id={chat_id} segundos={int(now - last_activity)} "
            "estado_limpiado=True"
        )
    CHAT_LAST_ACTIVITY[key] = now
    return expired


def activate_main_menu(chat_id):
    key = int(chat_id)
    clear_chat_states(chat_id, include_restart=False)
    MENU_STATES[key] = {"pantalla": "menu_principal", "anterior": None}
    return render_menu_principal(chat_id)


def consume_global_navigation(chat_id, text):
    normalized = normalize_intent_phrase(text)
    key = int(chat_id)

    if normalized == "0" and key in MENU_STATES and MENU_STATES[key].get("pantalla") != "menu_principal":
        return None

    if normalized in {"0", "menu", "start"}:
        return activate_main_menu(chat_id)

    if normalized in {"cancelar", "salir", "x"}:
        clear_chat_states(chat_id, include_restart=True)
        return "Operación cancelada."

    return None


def consume_menu_navigation(chat_id, text):
    key = int(chat_id)
    state = MENU_STATES.get(key)
    log_event(f"MENU_NAV entrada chat_id={chat_id} key={key} texto={text!r} estado={state!r}")
    if not state:
        log_event(f"MENU_NAV sin_estado chat_id={chat_id} key={key}")
        return None
    if key in PENDING_SELECTIONS:
        return None

    normalized = normalize_intent_phrase(text)
    if normalized in {"cancelar", "salir"}:
        MENU_STATES.pop(key, None)
        log_event(f"MENU_NAV cancelar chat_id={chat_id} key={key} estado=None")
        return "Operación cancelada."

    if state.get("pantalla") in {"pago_fraccionado_ranking", "pago_fraccionado_detalle"}:
        ranking = state.get("ranking") or {}
        proposals = list(ranking.get("propuestas") or [])
        if normalized in {"menu", "/menu", "/start"}:
            MENU_STATES[key] = {"pantalla": "menu_principal", "anterior": None}
            return render_menu_principal(chat_id)
        if normalized in {"0", "volver"}:
            if state.get("pantalla") == "pago_fraccionado_detalle":
                MENU_STATES[key] = {
                    "pantalla": "pago_fraccionado_ranking",
                    "anterior": "esperando_datos_pago_rapido_fraccionado",
                    "ranking": ranking,
                }
                return format_pago_rapido_fraccionado(ranking)
            MENU_STATES[key] = {
                "pantalla": "esperando_datos_pago_rapido_fraccionado",
                "anterior": "menu_pago_rapido_modalidad",
                "modo": ranking.get("modo", "ECHEQ"),
                "filtro_fiscal": ranking.get("filtro_fiscal", "TODOS"),
            }
            return pago_rapido_fraccionado_prompt()
        if normalized.isdigit():
            index = int(normalized) - 1
            if 0 <= index < len(proposals):
                MENU_STATES[key] = {
                    "pantalla": "pago_fraccionado_detalle",
                    "anterior": "pago_fraccionado_ranking",
                    "ranking": ranking,
                    "propuesta": index,
                }
                return format_payment_plan_detail(proposals[index], ranking)
            return "No hay una propuesta disponible para ese número. Elegí una de las opciones mostradas."
        return format_pago_rapido_fraccionado(ranking)

    if state.get("pantalla") == "clientes_saldo_esperando_consulta":
        if normalized in {"0", "volver"}:
            MENU_STATES[key] = {
                "pantalla": "menu_clientes",
                "anterior": "menu_principal",
            }
            log_event(f"MENU_NAV saldo_volver_clientes chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return render_menu_clientes(chat_id)
        if normalized in {"menu", "/menu", "/start"}:
            MENU_STATES[key] = {"pantalla": "menu_principal", "anterior": None}
            log_event(f"MENU_NAV saldo_volver_principal chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return render_menu_principal(chat_id)
        MENU_STATES[key] = {
            "pantalla": "clientes_saldo_esperando_consulta",
            "anterior": "menu_clientes",
        }
        query_text = str(text or "").strip()
        if not normalize_intent_phrase(query_text).startswith("saldo"):
            query_text = f"saldo {query_text}"
        log_event(f"MENU_NAV saldo_consulta_texto chat_id={chat_id} key={key} texto={query_text!r} estado={MENU_STATES.get(key)!r}")
        return ("parse_text", query_text)

    if state.get("pantalla") == "clientes_resumen_pdf_esperando_consulta":
        if normalized in {"0", "volver"}:
            MENU_STATES[key] = {
                "pantalla": "menu_clientes",
                "anterior": "menu_principal",
            }
            log_event(f"MENU_NAV resumen_volver_clientes chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return render_menu_clientes(chat_id)
        if normalized in {"menu", "/menu", "/start"}:
            MENU_STATES[key] = {"pantalla": "menu_principal", "anterior": None}
            log_event(f"MENU_NAV resumen_volver_principal chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return render_menu_principal(chat_id)
        MENU_STATES[key] = {
            "pantalla": "clientes_resumen_pdf_esperando_consulta",
            "anterior": "menu_clientes",
        }
        query_text = str(text or "").strip()
        query_key = normalize_intent_phrase(query_text)
        if (
            "resumen" not in query_key
            and "estado de cuenta" not in query_key
            and "cuenta corriente" not in query_key
        ):
            query_text = f"resumen de cuenta {query_text}"
        log_event(f"MENU_NAV resumen_consulta_texto chat_id={chat_id} key={key} texto={query_text!r} estado={MENU_STATES.get(key)!r}")
        return ("parse_text", query_text)

    if state.get("pantalla") == "clientes_facturas_pdf_esperando_consulta":
        if normalized in {"0", "volver"}:
            MENU_STATES[key] = {
                "pantalla": "menu_clientes",
                "anterior": "menu_principal",
            }
            log_event(f"MENU_NAV facturas_volver_clientes chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return render_menu_clientes(chat_id)
        if normalized in {"menu", "/menu", "/start"}:
            MENU_STATES[key] = {"pantalla": "menu_principal", "anterior": None}
            log_event(f"MENU_NAV facturas_volver_principal chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return render_menu_principal(chat_id)
        MENU_STATES[key] = {
            "pantalla": "clientes_facturas_pdf_esperando_consulta",
            "anterior": "menu_clientes",
        }
        query_text = str(text or "").strip()
        query_key = normalize_intent_phrase(query_text)
        if re.search(r"\b(?:fta|ftb|a|b)\s*\d+\b", query_key) and "factura" not in query_key:
            query_text = f"factura {query_text}"
        log_event(f"MENU_NAV facturas_consulta_texto chat_id={chat_id} key={key} texto={query_text!r} estado={MENU_STATES.get(key)!r}")
        return ("parse_text", query_text)

    if state.get("pantalla") == "consultas_ventas_esperando_consulta":
        if normalized in {"0", "volver"}:
            MENU_STATES[key] = {
                "pantalla": "menu_consultas_rapidas",
                "anterior": "menu_principal",
            }
            log_event(f"MENU_NAV ventas_volver_consultas chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return render_menu_consultas_rapidas(chat_id)
        MENU_STATES[key] = {
            "pantalla": "consultas_ventas_esperando_consulta",
            "anterior": "menu_consultas_rapidas",
        }
        if productos_no_clasificados_requested(text):
            desde, hasta = parse_productos_no_clasificados_period(text)
            log_event(f"MENU_NAV no_clasificados_consulta chat_id={chat_id} key={key} desde={desde} hasta={hasta} estado={MENU_STATES.get(key)!r}")
            return ("execute", "productos_no_clasificados", {"desde": desde, "hasta": hasta})
        desde, hasta = parse_quick_report_period(text)
        log_event(f"MENU_NAV ventas_consulta chat_id={chat_id} key={key} desde={desde} hasta={hasta} estado={MENU_STATES.get(key)!r}")
        return ("execute", "ventas_rapidas", {"desde": desde, "hasta": hasta})

    if state.get("pantalla") == "consultas_caja_esperando_consulta":
        if normalized in {"0", "volver"}:
            MENU_STATES[key] = {
                "pantalla": "menu_consultas_rapidas",
                "anterior": "menu_principal",
            }
            log_event(f"MENU_NAV caja_volver_consultas chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return render_menu_consultas_rapidas(chat_id)
        MENU_STATES[key] = {
            "pantalla": "consultas_caja_esperando_consulta",
            "anterior": "menu_consultas_rapidas",
        }
        desde, hasta_inclusive = parse_quick_report_period(text)
        hasta_date = datetime.strptime(hasta_inclusive, "%Y-%m-%d").date() + timedelta(days=1)
        hasta = hasta_date.isoformat()
        log_event(f"MENU_NAV caja_consulta chat_id={chat_id} key={key} desde={desde} hasta={hasta} estado={MENU_STATES.get(key)!r}")
        return ("execute", "cobros", {"medio": "todos", "desde": desde, "hasta": hasta})

    if state.get("pantalla") == "menu_iva_estimado" and normalized in {"0", "volver"}:
        MENU_STATES[key] = {
            "pantalla": "menu_consultas_rapidas",
            "anterior": "menu_principal",
        }
        log_event(f"MENU_NAV iva_volver_consultas chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return render_menu_consultas_rapidas(chat_id)

    if state.get("pantalla") == "esperando_periodo_iva":
        if normalized in {"0", "volver"}:
            MENU_STATES[key] = {
                "pantalla": "menu_iva_estimado",
                "anterior": "menu_consultas_rapidas",
            }
            log_event(f"MENU_NAV iva_periodo_volver chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return render_menu_iva_estimado(chat_id)
        parsed_iva_period = parse_iva_period_request(text)
        if parsed_iva_period.get("error"):
            log_event(f"MENU_NAV iva_periodo_error chat_id={chat_id} key={key} texto={text!r} error={parsed_iva_period.get('error')!r}")
            return parsed_iva_period["error"]
        anio = parsed_iva_period["anio"]
        mes = parsed_iva_period["mes"]
        MENU_STATES[key] = {
            "pantalla": "esperando_periodo_iva",
            "anterior": "menu_iva_estimado",
        }
        log_event(f"MENU_NAV iva_periodo_ejecutar chat_id={chat_id} key={key} anio={anio} mes={mes} estado={MENU_STATES.get(key)!r}")
        return ("execute", "iva_mensual", {"anio": anio, "mes": mes})

    if state.get("pantalla") == "menu_cheques_pagos" and normalized in {"0", "volver"}:
        MENU_STATES[key] = {
            "pantalla": "menu_consultas_rapidas",
            "anterior": "menu_principal",
        }
        log_event(f"MENU_NAV cheques_volver_consultas chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return render_menu_consultas_rapidas(chat_id)

    if state.get("pantalla") == "menu_pago_rapido" and normalized in {"0", "volver"}:
        MENU_STATES[key] = {
            "pantalla": "menu_cheques_pagos",
            "anterior": "menu_consultas_rapidas",
        }
        log_event(f"MENU_NAV pago_rapido_volver_cheques chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return render_menu_cheques_pagos(chat_id)

    if state.get("pantalla") == "menu_cheques_filtro" and normalized in {"0", "volver"}:
        MENU_STATES[key] = {
            "pantalla": "menu_cheques_pagos",
            "anterior": "menu_consultas_rapidas",
        }
        log_event(f"MENU_NAV cheques_filtro_volver chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return render_menu_cheques_pagos(chat_id)

    if state.get("pantalla") == "cheques_vencimientos_esperando_dias" and normalized in {"0", "volver"}:
        MENU_STATES[key] = {
            "pantalla": "menu_cheques_filtro",
            "anterior": "menu_cheques_pagos",
            "accion_cheques": "cheques_vencimientos",
        }
        log_event(f"MENU_NAV cheques_vencimientos_dias_volver chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return render_menu_cheques_filtro(chat_id)

    if state.get("pantalla") == "menu_pago_rapido_instrumento" and normalized in {"0", "volver"}:
        MENU_STATES[key] = {
            "pantalla": "menu_pago_rapido",
            "anterior": "menu_cheques_pagos",
        }
        log_event(f"MENU_NAV pago_rapido_instrumento_volver chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return render_menu_pago_rapido(chat_id)

    if state.get("pantalla") == "menu_pago_rapido_modalidad" and normalized in {"0", "volver"}:
        MENU_STATES[key] = {
            "pantalla": "menu_pago_rapido_instrumento",
            "anterior": "menu_pago_rapido",
            "filtro_fiscal": state.get("filtro_fiscal", "TODOS"),
        }
        log_event(f"MENU_NAV pago_rapido_modalidad_volver chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return render_menu_pago_rapido_instrumento(chat_id)

    if state.get("pantalla") == "esperando_datos_pago_rapido":
        if normalized in {"0", "volver"}:
            MENU_STATES[key] = {
                "pantalla": "menu_pago_rapido_modalidad",
                "anterior": "menu_pago_rapido_instrumento",
                "modo": state.get("modo", "ECHEQ"),
                "filtro_fiscal": state.get("filtro_fiscal", "TODOS"),
            }
            log_event(f"MENU_NAV pago_rapido_datos_volver chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return render_menu_pago_rapido_modalidad(chat_id)
        importe, plazo = parse_pago_rapido_datos(text)
        if not importe or importe <= 0:
            log_event(f"MENU_NAV pago_rapido_sin_importe chat_id={chat_id} key={key} texto={text!r}")
            return "No pude entender el importe. Escribilo así: $345.000,75 a 40 días"
        if not plazo:
            log_event(f"MENU_NAV pago_rapido_sin_plazo chat_id={chat_id} key={key} texto={text!r}")
            return "No pude entender el plazo. Escribilo así: $345.000,75 a 40 días o $345.000,75 a cobrar"
        modo = state.get("modo", "ECHEQ")
        filtro_fiscal = state.get("filtro_fiscal", "TODOS")
        MENU_STATES[key] = {
            "pantalla": "esperando_datos_pago_rapido",
            "anterior": "menu_pago_rapido_modalidad",
            "modo": modo,
            "filtro_fiscal": filtro_fiscal,
        }
        log_event(f"MENU_NAV pago_rapido_ejecutar chat_id={chat_id} key={key} modo={modo} filtro_fiscal={filtro_fiscal} importe={importe} plazo={plazo} estado={MENU_STATES.get(key)!r}")
        return ("execute", "armar_pago_optimo", {"importe": importe, "plazo": plazo, "modo": modo, "filtro_fiscal": filtro_fiscal})

    if state.get("pantalla") == "esperando_datos_pago_rapido_fraccionado":
        if normalized in {"0", "volver"}:
            MENU_STATES[key] = {
                "pantalla": "menu_pago_rapido_modalidad",
                "anterior": "menu_pago_rapido_instrumento",
                "modo": state.get("modo", "ECHEQ"),
                "filtro_fiscal": state.get("filtro_fiscal", "TODOS"),
            }
            log_event(f"MENU_NAV pago_rapido_fraccionado_volver chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return render_menu_pago_rapido_modalidad(chat_id)
        importe, plazos = parse_pago_rapido_fraccionado_datos(text)
        if not importe or importe <= 0:
            log_event(f"MENU_NAV pago_rapido_fraccionado_sin_importe chat_id={chat_id} key={key} texto={text!r}")
            return "No pude entender el importe total. Escribilo así: Total: 1.000.000 Plazos: 30,60,90,a cobrar"
        if not plazos:
            log_event(f"MENU_NAV pago_rapido_fraccionado_sin_plazos chat_id={chat_id} key={key} texto={text!r}")
            return "No pude entender los plazos. Escribilos así: Plazos: 30,60,90,a cobrar"
        modo = state.get("modo", "ECHEQ")
        filtro_fiscal = state.get("filtro_fiscal", "TODOS")
        MENU_STATES[key] = {
            "pantalla": "esperando_datos_pago_rapido_fraccionado",
            "anterior": "menu_pago_rapido_modalidad",
            "modo": modo,
            "filtro_fiscal": filtro_fiscal,
        }
        log_event(f"MENU_NAV pago_rapido_fraccionado_ejecutar chat_id={chat_id} key={key} modo={modo} filtro_fiscal={filtro_fiscal} importe={importe} plazos={plazos} estado={MENU_STATES.get(key)!r}")
        return ("execute", "armar_pago_optimo", {"fraccionado": True, "importe": importe, "plazos": plazos, "modo": modo, "filtro_fiscal": filtro_fiscal})

    if state.get("pantalla") == "cheques_vencimientos_esperando_dias":
        dias = parse_days(text, 0)
        if not dias:
            match = re.search(r"\b(\d{1,3})\b", str(text or ""))
            dias = int(match.group(1)) if match else 0
        if not dias:
            log_event(f"MENU_NAV cheques_vencimientos_sin_dias chat_id={chat_id} key={key} texto={text!r}")
            return cheques_vencimientos_dias_prompt()
        filtro_fiscal = normalize_cheques_fiscal_filter(state.get("filtro_fiscal"))
        MENU_STATES[key] = {
            "pantalla": "cheques_vencimientos_esperando_dias",
            "anterior": "menu_cheques_filtro",
            "filtro_fiscal": filtro_fiscal,
        }
        log_event(f"MENU_NAV cheques_vencimientos_ejecutar chat_id={chat_id} key={key} filtro_fiscal={filtro_fiscal} dias={dias} estado={MENU_STATES.get(key)!r}")
        return ("execute", "cheques_vencimientos", {"tipo": "TODOS", "dias": dias, "filtro_fiscal": filtro_fiscal})

    if normalized in {"0", "menu", "/menu", "/start"}:
        MENU_STATES[key] = {"pantalla": "menu_principal", "anterior": None}
        log_event(f"MENU_NAV volver_principal chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return render_menu_principal(chat_id)

    if state.get("pantalla") == "menu_principal" and is_gerencial(chat_id) and normalized == "1":
        log_event(f"MENU_NAV principal_a_dashboard chat_id={chat_id} key={key}")
        return ("execute", "dashboard_gerencial", {})

    if state.get("pantalla") == "menu_principal" and (
        (is_gerencial(chat_id) and normalized == "2")
        or (not is_gerencial(chat_id) and normalized == "1")
    ):
        MENU_STATES[key] = {
            "pantalla": "menu_clientes",
            "anterior": "menu_principal",
        }
        log_event(f"MENU_NAV principal_a_clientes chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return render_menu_clientes(chat_id)

    if state.get("pantalla") == "menu_principal" and (
        (is_gerencial(chat_id) and normalized == "3")
        or (not is_gerencial(chat_id) and normalized == "2")
    ):
        MENU_STATES[key] = {
            "pantalla": "menu_consultas_rapidas",
            "anterior": "menu_principal",
        }
        log_event(f"MENU_NAV principal_a_consultas_rapidas chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return render_menu_consultas_rapidas(chat_id)

    if state.get("pantalla") == "menu_principal" and is_gerencial(chat_id) and normalized == "4":
        if not is_gerencial(chat_id):
            log_event(f"MENU_NAV admin_denegado chat_id={chat_id} key={key}")
            return "No tenés permiso para acceder a Administración."
        MENU_STATES[key] = {
            "pantalla": "menu_administracion",
            "anterior": "menu_principal",
        }
        log_event(f"MENU_NAV principal_a_administracion chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return render_menu_administracion(chat_id)

    if state.get("pantalla") == "menu_administracion":
        if normalized == "1":
            MENU_STATES.pop(key, None)
            PENDING_USER_MANAGEMENT[key] = {"stage": "menu"}
            log_event(f"MENU_NAV administracion_usuarios chat_id={chat_id} key={key}")
            return format_users_menu()
        log_event(f"MENU_NAV administracion_texto_libre chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return None

    if state.get("pantalla") == "menu_cheques_pagos":
        if normalized in {"0", "volver"}:
            MENU_STATES[key] = {
                "pantalla": "menu_consultas_rapidas",
                "anterior": "menu_principal",
            }
            log_event(f"MENU_NAV cheques_volver_consultas chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return render_menu_consultas_rapidas(chat_id)
        if normalized == "1":
            MENU_STATES[key] = {
                "pantalla": "menu_cheques_filtro",
                "anterior": "menu_cheques_pagos",
                "accion_cheques": "cheques_resumen",
            }
            log_event(f"MENU_NAV cheques_resumen_filtro chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return render_menu_cheques_filtro(chat_id)
        if normalized == "2":
            MENU_STATES[key] = {
                "pantalla": "menu_cheques_filtro",
                "anterior": "menu_cheques_pagos",
                "accion_cheques": "cheques_depositables",
            }
            log_event(f"MENU_NAV cheques_depositables_filtro chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return render_menu_cheques_filtro(chat_id)
        if normalized == "3":
            MENU_STATES[key] = {
                "pantalla": "menu_cheques_filtro",
                "anterior": "menu_cheques_pagos",
                "accion_cheques": "cheques_vencimientos",
            }
            log_event(f"MENU_NAV cheques_vencimientos_filtro chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return render_menu_cheques_filtro(chat_id)
        if normalized == "4":
            MENU_STATES[key] = {
                "pantalla": "menu_pago_rapido",
                "anterior": "menu_cheques_pagos",
            }
            log_event(f"MENU_NAV cheques_pago_rapido chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return render_menu_pago_rapido(chat_id)
        log_event(f"MENU_NAV cheques_texto_libre chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return None

    if state.get("pantalla") == "menu_cheques_filtro":
        fiscal_filters = {"1": "NN", "2": "BLANCO", "3": "TODOS"}
        if normalized in fiscal_filters:
            accion = state.get("accion_cheques", "cheques_resumen")
            filtro_fiscal = fiscal_filters[normalized]
            if accion == "cheques_vencimientos":
                MENU_STATES[key] = {
                    "pantalla": "cheques_vencimientos_esperando_dias",
                    "anterior": "menu_cheques_filtro",
                    "filtro_fiscal": filtro_fiscal,
                }
                log_event(f"MENU_NAV cheques_filtro_vencimientos chat_id={chat_id} key={key} filtro_fiscal={filtro_fiscal} estado={MENU_STATES.get(key)!r}")
                return cheques_vencimientos_dias_prompt()
            MENU_STATES[key] = {
                "pantalla": "menu_cheques_pagos",
                "anterior": "menu_consultas_rapidas",
            }
            log_event(f"MENU_NAV cheques_filtro_ejecutar chat_id={chat_id} key={key} accion={accion} filtro_fiscal={filtro_fiscal} estado={MENU_STATES.get(key)!r}")
            return ("execute", accion, {"tipo": "TODOS", "filtro_fiscal": filtro_fiscal})
        log_event(f"MENU_NAV cheques_filtro_texto_libre chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return None

    if state.get("pantalla") == "menu_pago_rapido":
        fiscal_filters = {"1": "NN", "2": "BLANCO", "3": "TODOS"}
        if normalized in fiscal_filters:
            MENU_STATES[key] = {
                "pantalla": "menu_pago_rapido_instrumento",
                "anterior": "menu_pago_rapido",
                "filtro_fiscal": fiscal_filters[normalized],
            }
            log_event(f"MENU_NAV pago_rapido_filtro chat_id={chat_id} key={key} filtro_fiscal={fiscal_filters[normalized]} estado={MENU_STATES.get(key)!r}")
            return render_menu_pago_rapido_instrumento(chat_id)
        log_event(f"MENU_NAV pago_rapido_texto_libre chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return None

    if state.get("pantalla") == "menu_pago_rapido_instrumento":
        modes = {"1": "ECHEQ", "2": "CHEQUE", "3": "MIXTO"}
        if normalized in modes:
            MENU_STATES[key] = {
                "pantalla": "menu_pago_rapido_modalidad",
                "anterior": "menu_pago_rapido_instrumento",
                "modo": modes[normalized],
                "filtro_fiscal": state.get("filtro_fiscal", "TODOS"),
            }
            log_event(f"MENU_NAV pago_rapido_modo chat_id={chat_id} key={key} modo={modes[normalized]} filtro_fiscal={state.get('filtro_fiscal', 'TODOS')} estado={MENU_STATES.get(key)!r}")
            return render_menu_pago_rapido_modalidad(chat_id)
        log_event(f"MENU_NAV pago_rapido_instrumento_texto_libre chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return None

    if state.get("pantalla") == "menu_pago_rapido_modalidad":
        if normalized == "1":
            MENU_STATES[key] = {
                "pantalla": "esperando_datos_pago_rapido",
                "anterior": "menu_pago_rapido_modalidad",
                "modo": state.get("modo", "ECHEQ"),
                "filtro_fiscal": state.get("filtro_fiscal", "TODOS"),
            }
            log_event(f"MENU_NAV pago_rapido_modalidad_unico chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return pago_rapido_prompt()
        if normalized == "2":
            MENU_STATES[key] = {
                "pantalla": "esperando_datos_pago_rapido_fraccionado",
                "anterior": "menu_pago_rapido_modalidad",
                "modo": state.get("modo", "ECHEQ"),
                "filtro_fiscal": state.get("filtro_fiscal", "TODOS"),
            }
            log_event(f"MENU_NAV pago_rapido_modalidad_fraccionado chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return pago_rapido_fraccionado_prompt()
        log_event(f"MENU_NAV pago_rapido_modalidad_texto_libre chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return None

    if state.get("pantalla") == "menu_iva_estimado":
        if normalized == "1":
            MENU_STATES[key] = {
                "pantalla": "menu_iva_estimado",
                "anterior": "menu_consultas_rapidas",
            }
            log_event(f"MENU_NAV iva_mes_actual chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return ("execute", "iva_mensual", {"anio": date.today().year, "mes": date.today().month})
        if normalized == "2":
            MENU_STATES[key] = {
                "pantalla": "esperando_periodo_iva",
                "anterior": "menu_iva_estimado",
            }
            log_event(f"MENU_NAV iva_otro_periodo chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return iva_periodo_prompt()
        log_event(f"MENU_NAV iva_texto_libre chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return None

    if state.get("pantalla") == "menu_consultas_rapidas":
        if normalized == "1":
            MENU_STATES[key] = {
                "pantalla": "consultas_ventas_esperando_consulta",
                "anterior": "menu_consultas_rapidas",
            }
            log_event(f"MENU_NAV consultas_ventas chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return (
                "Ventas seleccionado.\n\n"
                "Podés escribir o enviar audio con consultas como:\n\n"
                "- ventas de ayer\n"
                "- ventas de hoy\n"
                "- ventas del mes\n"
                "- ventas desde 01/06/2026 hasta 20/06/2026\n"
                "- ventas entre 01/06/2026 y 20/06/2026\n\n"
                "Productos sin clasificar:\n\n"
                "- productos no clasificados\n"
                "- no clasificados junio 2026\n"
                "- productos sin clasificar desde 01/06/2026 hasta 20/06/2026\n\n"
                "Para volver escribí:\n"
                "0, volver, menu o cancelar"
            )
        if normalized == "2":
            MENU_STATES[key] = {
                "pantalla": "consultas_caja_esperando_consulta",
                "anterior": "menu_consultas_rapidas",
            }
            log_event(f"MENU_NAV consultas_caja chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return (
                "Caja seleccionado.\n\n"
                "Podés escribir o enviar audio con consultas como:\n\n"
                "- caja de ayer\n"
                "- caja de hoy\n"
                "- caja del mes\n"
                "- caja desde 01/06/2026 hasta 20/06/2026\n"
                "- caja entre 01/06/2026 y 20/06/2026\n\n"
                "Para volver escribí:\n"
                "0, volver, menu o cancelar"
            )
        if normalized == "3":
            MENU_STATES[key] = {
                "pantalla": "menu_iva_estimado",
                "anterior": "menu_consultas_rapidas",
            }
            log_event(f"MENU_NAV consultas_iva_menu chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return render_menu_iva_estimado(chat_id)
        if normalized == "4":
            authorized, reason = authorize_command(chat_id, "cheques_resumen", {})
            if not authorized:
                log_event(f"MENU_NAV consultas_cheques_denegado chat_id={chat_id} key={key}")
                return reason
            MENU_STATES[key] = {
                "pantalla": "menu_cheques_pagos",
                "anterior": "menu_consultas_rapidas",
            }
            log_event(f"MENU_NAV consultas_cheques chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return render_menu_cheques_pagos(chat_id)
        log_event(f"MENU_NAV consultas_texto_libre chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return None

    if state.get("pantalla") == "menu_clientes":
        if normalized == "1":
            MENU_STATES[key] = {
                "pantalla": "clientes_saldo_esperando_consulta",
                "anterior": "menu_clientes",
            }
            log_event(f"MENU_NAV clientes_saldo chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return (
                "Consulta de saldos seleccionada.\n\n"
                "Podés escribir o enviar audio con consultas como:\n\n"
                "* saldo CLIENTE_A\n"
                "* saldo CLIENTE_A entre 01/06/2026 y 18/06/2026\n"
                "* saldo CLIENTE_A desde último pago\n\n"
                "También podés escribir solo el nombre del cliente:\n\n"
                "* Acosta Matías\n\n"
                "Para volver escribí:\n"
                "0, volver, menu o cancelar"
            )
        if normalized == "2":
            MENU_STATES[key] = {
                "pantalla": "clientes_resumen_pdf_esperando_consulta",
                "anterior": "menu_clientes",
            }
            log_event(f"MENU_NAV clientes_resumen_pdf chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return (
                "Resumen de cuenta PDF seleccionado.\n\n"
                "Podés escribir o enviar audio con consultas como:\n\n"
                "* resumen de cuenta CLIENTE_A entre 01/06/2026 y 18/06/2026\n"
                "* estado de cuenta CLIENTE_A entre 01/06/2026 y 18/06/2026\n"
                "* resumen de cuenta CLIENTE_A desde último pago\n\n"
                "Para volver escribí:\n"
                "0, volver, menu o cancelar"
            )
        if normalized == "3":
            MENU_STATES[key] = {
                "pantalla": "clientes_facturas_pdf_esperando_consulta",
                "anterior": "menu_clientes",
            }
            log_event(f"MENU_NAV clientes_facturas_pdf chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
            return (
                "Facturas PDF seleccionado.\n\n"
                "Podés escribir o enviar audio con consultas como:\n\n"
                "* última factura CLIENTE\n"
                "* factura FTA NUMERO\n"
                "* factura FTB NUMERO\n"
                "* facturas CLIENTE desde 01/05/2026\n"
                "* facturas CLIENTE entre 01/05/2026 y 15/06/2026\n"
                "* facturas CLIENTE desde último pago\n\n"
                "Para volver escribí:\n"
                "0, volver, menu o cancelar"
            )
        log_event(f"MENU_NAV clientes_texto_libre chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
        return None

    log_event(f"MENU_NAV sin_respuesta chat_id={chat_id} key={key} estado={MENU_STATES.get(key)!r}")
    return None


def consume_user_management(chat_id, text):
    pending = PENDING_USER_MANAGEMENT.get(int(chat_id))
    if not pending:
        return None
    if not is_admin_chat(chat_id):
        PENDING_USER_MANAGEMENT.pop(int(chat_id), None)
        return "Esta accion esta reservada para administradores."

    answer = str(text or "").strip()
    normalized = normalize_intent_phrase(answer)
    if normalized in {"cancelar", "salir", "volver", "menu", "/menu", "/start", "0"}:
        PENDING_USER_MANAGEMENT.pop(int(chat_id), None)
        if normalized in {"menu", "/menu", "/start"}:
            return render_menu_principal(chat_id)
        return "Operación de usuarios cancelada."
    data = ensure_telegram_users_data()

    if pending.get("stage") == "menu":
        if normalized == "1":
            PENDING_USER_MANAGEMENT.pop(int(chat_id), None)
            return format_users_list(data)
        if normalized == "2":
            pending_users, pending_text = format_pending_users_for_add()
            if not pending_users:
                return pending_text
            pending.update({"stage": "select_pending_user", "pending_users": pending_users})
            PENDING_USER_MANAGEMENT[int(chat_id)] = pending
            return pending_text
        if normalized == "3":
            pending["stage"] = "change_role_user"
            PENDING_USER_MANAGEMENT[int(chat_id)] = pending
            return format_users_list(data) + "\n\nIngrese el numero del usuario para cambiar rol."
        if normalized == "4":
            pending["stage"] = "toggle_user"
            PENDING_USER_MANAGEMENT[int(chat_id)] = pending
            return format_users_list(data) + "\n\nIngrese el numero del usuario para activar/desactivar."
        if normalized == "5":
            PENDING_USER_MANAGEMENT.pop(int(chat_id), None)
            result = handle_command("usuarios_menu", {"accion": "mi", "chat_id": chat_id})
            return result[1]
        PENDING_USER_MANAGEMENT.pop(int(chat_id), None)
        return "Opcion invalida. Ejecute /usuarios nuevamente."

    if pending.get("stage") == "select_pending_user":
        if not normalized.isdigit():
            return "Ingrese el numero del usuario pendiente."
        pending_users, pending_text = format_pending_users_for_add()
        index = int(normalized) - 1
        if index < 0 or index >= len(pending_users):
            return "Numero invalido.\n\n" + pending_text
        pending["new_user"] = pending_users[index]
        pending["stage"] = "add_pending_role"
        PENDING_USER_MANAGEMENT[int(chat_id)] = pending
        return (
            "Elegir rol:\n\n"
            "1️⃣ Administrador\n"
            "2️⃣ Administrativo"
        )

    if pending.get("stage") == "add_chat_id":
        if not re.fullmatch(r"\d+", answer):
            return "chat_id invalido. Ingrese solo numeros."
        pending["new_user"]["chat_id"] = answer
        pending["stage"] = "add_name"
        PENDING_USER_MANAGEMENT[int(chat_id)] = pending
        return "Ingrese el nombre del usuario."

    if pending.get("stage") == "add_name":
        if not answer:
            return "Nombre invalido. Ingrese el nombre del usuario."
        pending["new_user"]["nombre"] = answer
        pending["stage"] = "add_role"
        PENDING_USER_MANAGEMENT[int(chat_id)] = pending
        return "Seleccione rol:\n1️⃣ administrador\n2️⃣ administrativo_contratado"

    if pending.get("stage") == "add_role":
        roles = {"1": "administrador", "2": "administrativo_contratado"}
        role = roles.get(normalized)
        if not role:
            return "Rol invalido. Responda 1 o 2."
        new_user = pending["new_user"]
        users = data.setdefault("usuarios", [])
        existing = next((u for u in users if str(u.get("chat_id")) == str(new_user["chat_id"])), None)
        if existing:
            existing.update({
                "nombre": new_user["nombre"],
                "rol": role,
                "activo": True,
            })
        else:
            users.append({
                "chat_id": new_user["chat_id"],
                "nombre": new_user["nombre"],
                "access_user_id": None,
                "rol": role,
                "activo": True,
                "fecha_alta": date.today().isoformat(),
                "creado_por": str(chat_id),
            })
        save_telegram_users_data(data)
        registrar_actividad(
            chat_id=chat_id,
            modulo="Usuarios",
            accion="Alta usuario",
            objeto="Usuario Telegram",
            id_objeto=new_user["chat_id"],
            descripcion="Alta o actualización de usuario Telegram",
            nivel="INFO",
            extra={"rol": role},
        )
        PENDING_USER_MANAGEMENT.pop(int(chat_id), None)
        return (
            "Usuario agregado correctamente.\n\n"
            f"Nombre: {new_user['nombre']}\n"
            f"Rol: {role}\n"
            f"chat_id: ...{str(new_user['chat_id'])[-4:]}"
        )

    if pending.get("stage") == "add_pending_role":
        roles = {"1": "administrador", "2": "administrativo_contratado"}
        role = roles.get(normalized)
        if not role:
            return "Rol invalido. Responda 1 o 2."
        new_user = pending["new_user"]
        users = data.setdefault("usuarios", [])
        chat_text = str(new_user.get("chat_id"))
        nombre = pending_user_display_name(new_user)
        existing = next((u for u in users if str(u.get("chat_id")) == chat_text), None)
        if existing:
            existing.update(
                {
                    "nombre": nombre,
                    "rol": role,
                    "activo": True,
                }
            )
        else:
            users.append(
                {
                    "chat_id": chat_text,
                    "nombre": nombre,
                    "access_user_id": None,
                    "rol": role,
                    "activo": True,
                    "fecha_alta": date.today().isoformat(),
                    "creado_por": str(chat_id),
                    "telegram": {
                        "first_name": new_user.get("first_name", ""),
                        "last_name": new_user.get("last_name", ""),
                        "username": new_user.get("username", ""),
                    },
                }
            )
        save_telegram_users_data(data)
        remove_pending_telegram_user(chat_text)
        registrar_actividad(
            chat_id=chat_id,
            modulo="Usuarios",
            accion="Alta usuario",
            objeto="Usuario Telegram",
            id_objeto=chat_text,
            descripcion="Usuario pendiente autorizado",
            nivel="INFO",
            extra={"rol": role},
        )
        PENDING_USER_MANAGEMENT.pop(int(chat_id), None)
        return "Usuario agregado correctamente."

    if pending.get("stage") == "change_role_user":
        if not normalized.isdigit():
            return "Ingrese el numero del usuario."
        index = int(normalized) - 1
        users = data.get("usuarios", [])
        if index < 0 or index >= len(users):
            return "Numero invalido."
        pending["target_index"] = index
        pending["stage"] = "change_role_value"
        PENDING_USER_MANAGEMENT[int(chat_id)] = pending
        return "Seleccione nuevo rol:\n1️⃣ administrador\n2️⃣ administrativo_contratado"

    if pending.get("stage") == "change_role_value":
        roles = {"1": "administrador", "2": "administrativo_contratado"}
        role = roles.get(normalized)
        if not role:
            return "Rol invalido. Responda 1 o 2."
        users = data.get("usuarios", [])
        target = users[pending["target_index"]]
        target["rol"] = role
        save_telegram_users_data(data)
        registrar_actividad(
            chat_id=chat_id,
            modulo="Usuarios",
            accion="Cambio rol",
            objeto="Usuario Telegram",
            id_objeto=target.get("chat_id", ""),
            descripcion="Cambio de rol de usuario Telegram",
            nivel="INFO",
            extra={"rol": role},
        )
        PENDING_USER_MANAGEMENT.pop(int(chat_id), None)
        return f"Rol actualizado: {target.get('nombre')} -> {role}"

    if pending.get("stage") == "toggle_user":
        if not normalized.isdigit():
            return "Ingrese el numero del usuario."
        index = int(normalized) - 1
        users = data.get("usuarios", [])
        if index < 0 or index >= len(users):
            return "Numero invalido."
        target = users[index]
        target["activo"] = not bool(target.get("activo", False))
        save_telegram_users_data(data)
        registrar_actividad(
            chat_id=chat_id,
            modulo="Usuarios",
            accion="Activación usuario",
            objeto="Usuario Telegram",
            id_objeto=target.get("chat_id", ""),
            descripcion="Cambio de estado activo de usuario Telegram",
            nivel="INFO",
            extra={"activo": target.get("activo", False)},
        )
        PENDING_USER_MANAGEMENT.pop(int(chat_id), None)
        return f"Usuario actualizado: {target.get('nombre')} activo={target.get('activo')}"

    PENDING_USER_MANAGEMENT.pop(int(chat_id), None)
    return "Operacion cancelada."


def find_telegram_user(chat_id):
    data = load_telegram_users_data()
    if not data:
        return None, data
    chat_text = str(chat_id)
    for user in data.get("usuarios", []):
        user_chat = user.get("chat_id")
        if user_chat is not None and str(user_chat) == chat_text:
            return user, data
    return None, data


def has_configured_telegram_users(data):
    if not data:
        return False
    for user in data.get("usuarios", []):
        if user.get("chat_id") not in (None, ""):
            return True
    return False


def legacy_telegram_user(chat_id):
    users = CONFIG.get("telegram_users") or {}
    return users.get(str(chat_id), {"name": "Usuario", "role": "query_only"})


def role_permissions(data, role):
    role_data = ((data or {}).get("roles") or {}).get(role, {})
    allowed_permissions = set(role_data.get("permisos") or [])
    denied_permissions = set(role_data.get("permisos_prohibidos") or [])
    if role == "administrativo_contratado":
        denied_permissions.update({"cheques", "caja", "auditoria", "usuarios"})
    return allowed_permissions, denied_permissions


def command_permission(kind, params=None):
    if kind == "diccionario_intencion":
        intent_id = (params or {}).get("id", "")
        return INTENT_PERMISSIONS.get(intent_id, "reportes")
    return COMMAND_PERMISSIONS.get(kind)


def telegram_user_display(chat_id):
    user, data = find_telegram_user(chat_id)
    if user:
        return user, data, "telegram_usuarios.json"
    return legacy_telegram_user(chat_id), data, "telegram_bot_config.json"


def match_intent_dictionary(text):
    frase = normalize(repair_common_text_glitches(text))
    frase_normalizada = normalize_intent_phrase(frase)
    if not frase_normalizada:
        return None

    data = load_intent_dictionary_data()
    touched = False
    coincidencias = []

    def build_match(intent, intent_id, catalog_intent, phrase, parametros=None):
        return {
            "id": intent_id,
            "descripcion": catalog_intent.get("descripcion", ""),
            "script": catalog_intent.get("script", ""),
            "parametros_base": intent.get("parametros_base") or catalog_intent.get("parametros_base", {}),
            "frase_detectada": phrase,
            "frase_usuario": frase_normalizada,
            "texto_original": frase,
            "parametros": parametros or {},
        }

    for intent in data.get("intenciones", []):
        intent_id = canonical_intent_id(intent.get("id", ""))
        catalog_intent = INTENCIONES_VALIDAS.get(intent_id)
        if not catalog_intent:
            continue

        for phrase_entry in intent.get("frases", []):
            if isinstance(phrase_entry, dict):
                phrase = phrase_entry.get("frase", "")
            else:
                phrase = str(phrase_entry or "")
            phrase_normalized = normalize_intent_phrase(phrase)
            if frase_normalizada == phrase_normalized:
                if isinstance(phrase_entry, dict):
                    touch_usage(phrase_entry)
                else:
                    stats = intent.setdefault("frases_estadisticas", {})
                    usage = stats.setdefault(phrase_normalized, {"creado": today_iso(), "usos": 0})
                    touch_usage(usage)
                touched = True
                coincidencias.append(build_match(intent, intent_id, catalog_intent, phrase))

        for pattern_entry in intent.get("patrones", []):
            if not isinstance(pattern_entry, dict):
                continue
            patterns = [pattern_entry.get("patron", "")]
            patterns.extend(pattern_entry.get("alias") or [])
            for pattern in patterns:
                regex = pattern_regex(pattern)
                if not regex:
                    continue
                match = regex.match(frase_normalizada)
                if not match:
                    continue
                cliente = extract_client_from_pattern(pattern, frase, match.group(1).strip())
                touch_usage(pattern_entry)
                touched = True
                coincidencias.append(
                    build_match(
                        intent,
                        intent_id,
                        catalog_intent,
                        pattern,
                        {"cliente": cliente},
                    )
                )
                break
    if touched:
        save_intent_dictionary_data(data)

    if len(coincidencias) == 1:
        if (
            coincidencias[0].get("id") == "mayores_deudores"
            and normalize_intent_phrase(coincidencias[0].get("frase_detectada", "")) == "principal deudor"
        ):
            params = dict(coincidencias[0].get("parametros_base") or {})
            params["Top"] = 1
            coincidencias[0]["parametros_base"] = params
        return coincidencias[0]
    if len(coincidencias) > 1:
        return {"ambigua": True, "frase_usuario": frase_normalizada, "coincidencias": coincidencias}
    return {"sin_coincidencia": True, "frase_usuario": frase_normalizada}


def dictionary_header(intent, script=None):
    selected_script = script or intent.get("script", "")
    return (
        "Frase detectada:\n"
        f"{intent.get('frase_usuario', '')}\n\n"
        "Intencion:\n"
        f"{intent.get('id', '')}\n\n"
        "Script:\n"
        f"{Path(selected_script).name if selected_script else ''}\n\n"
        "Ejecutando consulta...\n\n"
    )


def clean_account_client_query(text):
    value = str(text or "").strip()
    value = re.sub(r"^(dame|enviame|mandame|pasame|generame)\s+", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"\b(en pdf|pdf)\b", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"^(saldo|consultar saldo|consulta saldo)(\s+de)?\s+", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"^(estado|resumen)(?:\s+de\s+cuentas?)?(?:\s+de)?\s+", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"^cuentas?(?:\s+corrientes?)?(?:\s+de)?\s+", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"\bdesde\s+(?:el\s+)?(?:ultimo|último)\s+pago\b.*$", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"\b(?:ultimo|último)\s+pago\b.*$", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"\bpor\s+periodo\b.*$", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"\bdesde\s+\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s+hasta\s+\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b.*$", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"\b(?:desde|entre)\b.*$", "", value, flags=re.IGNORECASE).strip()
    return clean_client_name(value)


def strip_client_from_account_text(text):
    value = str(text or "").strip()
    for intent_id in (
        "clientes_saldo",
        "clientes_resumen_pdf",
        "clientes_resumen_ultimo_pago",
        "clientes_factura_ultima",
        "clientes_facturas_desde_ultimo_pago",
    ):
        cliente = extraer_cliente_desde_frase(value, intent_id)
        if cliente:
            return clean_account_client_query(cliente)
    return clean_account_client_query(value)


def command_from_catalog_intent(intent, original_text):
    intent_id = canonical_intent_id(intent.get("id", ""))
    base = dict(intent.get("parametros_base") or {})
    text = str(original_text or intent.get("texto_original") or intent.get("frase_usuario") or "").strip()
    extracted = extraer_parametros(text, intent_id, intent.get("parametros") or {})
    lower = fold_accents(text).lower()

    if intent_id == "clientes_saldo":
        return "saldo", {"cliente": extracted.get("cliente") or strip_client_from_account_text(text)}

    if intent_id == "clientes_resumen_pdf":
        if "ultimo pago" in lower or "último pago" in lower:
            return "estado_pdf_ultimo_pago", {"cliente": strip_client_from_account_text(text)}
        desde, hasta = parse_account_period(text)
        cliente = extracted.get("cliente") or strip_client_from_account_text(text)
        if not desde:
            return "estado_pdf_abierto", {"cliente": cliente}
        return "estado_pdf", {"cliente": cliente, "desde": desde, "hasta": hasta}

    if intent_id == "clientes_resumen_ultimo_pago":
        return "estado_pdf_ultimo_pago", {"cliente": extracted.get("cliente") or strip_client_from_account_text(text)}

    if intent_id == "clientes_factura_ultima":
        if extracted.get("cliente"):
            return "facturas_ultimas_cliente_pdf", {"cliente": extracted["cliente"], "cantidad": int(base.get("Cantidad", 1) or 1)}
        parsed = parse_latest_invoice_client_pattern(text)
        if parsed:
            return parsed
        cliente = re.sub(r"^(dame|enviame|mandame|pasame|quiero)\s+", "", text, flags=re.IGNORECASE).strip()
        cliente = re.sub(r"\b(ultima|última|ultimas|últimas|factura|facturas|de|del)\b", " ", cliente, flags=re.IGNORECASE)
        cliente = clean_client_name(re.sub(r"\s+", " ", cliente).strip())
        return "facturas_ultimas_cliente_pdf", {"cliente": cliente, "cantidad": int(base.get("Cantidad", 1) or 1)}

    if intent_id == "clientes_facturas_desde_ultimo_pago":
        return "facturas_cliente_pdf", {
            "cliente": extracted.get("cliente") or parse_facturas_desde_ultimo_pago(text) or strip_client_from_account_text(text),
            "desde": DESDE_ULTIMO_PAGO,
            "hasta": date.today().isoformat(),
        }

    if intent_id == "clientes_facturas_periodo":
        if cliente_ultimo_pago := parse_facturas_desde_ultimo_pago(text):
            return "facturas_cliente_pdf", {
                "cliente": cliente_ultimo_pago,
                "desde": DESDE_ULTIMO_PAGO,
                "hasta": date.today().isoformat(),
            }
        parsed = parse_facturas_periodo_cliente(text)
        if parsed and not parsed.get("error"):
            return "facturas_cliente_pdf", parsed
        return "unknown", {"text": text}

    if intent_id == "clientes_factura_numero":
        return parse_factura_pdf_command(text)

    if intent_id == "ventas_rapidas":
        desde, hasta = parse_quick_report_period(text)
        return "ventas_rapidas", {"desde": desde, "hasta": hasta}

    if intent_id == "productos_no_clasificados":
        desde, hasta = parse_productos_no_clasificados_period(text)
        return "productos_no_clasificados", {"desde": desde, "hasta": hasta}

    if intent_id == "caja_rapida":
        desde, hasta_inclusive = parse_quick_report_period(text)
        hasta_date = datetime.strptime(hasta_inclusive, "%Y-%m-%d").date() + timedelta(days=1)
        return "cobros", {"medio": "todos", "desde": desde, "hasta": hasta_date.isoformat()}

    if intent_id == "iva_estimado":
        anio, mes = parse_iva_month(text)
        return "iva_mensual", {"anio": anio, "mes": mes}

    if intent_id == "cheques_resumen":
        return "cheques_resumen", {"tipo": "TODOS"}

    if intent_id == "mayores_deudores":
        return "deudores", {"top": str(base.get("Top", 10))}

    return None


def readable_intent_label(intent_id):
    intent_id = canonical_intent_id(intent_id)
    intent = INTENCIONES_VALIDAS.get(intent_id, {})
    description = intent.get("descripcion") or intent_id
    sections = {
        "clientes": "Clientes",
        "ventas": "Consultas rapidas",
        "caja": "Consultas rapidas",
        "iva": "Consultas rapidas",
        "cheques": "Cheques",
        "mayores": "Rankings",
        "mejores": "Rankings",
        "peores": "Rankings",
        "analisis": "Reportes",
    }
    section = sections.get(intent_id.split("_", 1)[0], "Consultas")
    return f"{section} -> {description}"


def manual_intent_selection_prompt(chat_id, phrase):
    options = available_intentions_for_add()
    if not options:
        PENDING_INTENT_ADDS.pop(int(chat_id), None)
        return "No hay intenciones disponibles para agregar la frase."
    PENDING_INTENT_ADDS[int(chat_id)] = {
        "stage": "choose",
        "phrase": phrase,
        "options": options,
    }
    return "No conozco esta consulta.\nSeleccione la intencion:\n\n" + format_intent_options()


def suggest_intent_with_ai(phrase):
    api_key = os.environ.get("OPENAI_API_KEY") or CONFIG.get("openai_api_key", "")
    if not api_key:
        return None

    catalog = [
        {
            "id": intent_id,
            "nombre": intent.get("descripcion", intent_id),
        }
        for intent_id, intent in INTENCIONES_VALIDAS.items()
    ]
    prompt = (
        "Clasifica la frase del usuario contra este catalogo de intenciones. "
        "No respondas la consulta ni inventes datos. Devuelve solo JSON con "
        "intencion_sugerida, confianza y motivo. Si no estas seguro, usa confianza baja.\n\n"
        f"Frase: {phrase}\n"
        f"Catalogo: {json.dumps(catalog, ensure_ascii=False)}"
    )
    payload = json.dumps(
        {
            "model": CONFIG.get("intent_classifier_model", "gpt-4o-mini"),
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": "Sos un clasificador de intenciones. Devolves solo JSON valido.",
                },
                {"role": "user", "content": prompt},
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        suggestion = json.loads(content)
    except Exception as exc:
        log_event(f"IA_INTENCION error={exc}")
        return None

    intent_id = canonical_intent_id(suggestion.get("intencion_sugerida", ""))
    if intent_id not in INTENCIONES_VALIDAS:
        log_event(f"IA_INTENCION invalida={suggestion.get('intencion_sugerida', '')!r}")
        return None
    try:
        confidence = float(suggestion.get("confianza", 0) or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "intencion_sugerida": intent_id,
        "confianza": max(0.0, min(confidence, 1.0)),
        "motivo": str(suggestion.get("motivo", "") or ""),
    }


def learn_phrase_for_intent(phrase, selected):
    data = load_intent_dictionary_data()
    learned_phrase = normalize_learned_phrase(phrase)
    selected_in_dictionary = find_or_create_dictionary_intent(data, selected)
    intent_id = canonical_intent_id(selected_in_dictionary.get("id", ""))
    learned_pattern = infer_client_pattern(intent_id, phrase)
    saved_as = "frase"
    saved_value = learned_phrase

    if learned_pattern:
        patterns = selected_in_dictionary.setdefault("patrones", [])
        existing_pattern = next(
            (
                item for item in patterns
                if isinstance(item, dict)
                and normalize_intent_phrase(item.get("patron", "")) == normalize_intent_phrase(learned_pattern)
            ),
            None,
        )
        if existing_pattern is None:
            existing_pattern = {
                "patron": learned_pattern,
                "intencion": intent_id,
                "parametros": ["cliente"],
                "creado": today_iso(),
                "ultimo_uso": today_iso(),
                "usos": 0,
                "alias": [],
            }
            patterns.append(existing_pattern)
        touch_usage(existing_pattern)
        saved_as = "patron"
        saved_value = learned_pattern
    else:
        phrases = list(selected_in_dictionary.get("frases") or [])
        phrase_normalized = normalize_intent_phrase(learned_phrase)
        exists = any(
            normalize_intent_phrase(existing.get("frase", "") if isinstance(existing, dict) else existing) == phrase_normalized
            for existing in phrases
        )
        if not exists:
            phrases.append(learned_phrase)
            selected_in_dictionary["frases"] = phrases
        stats = selected_in_dictionary.setdefault("frases_estadisticas", {})
        usage = stats.setdefault(phrase_normalized, {"creado": today_iso(), "usos": 0})
        touch_usage(usage)

    save_intent_dictionary_data(data)
    message = (
        "Frase agregada correctamente.\n\n"
        f"Guardado como: {saved_as}\n"
        f"Valor: {saved_value}\n"
        f"Intencion seleccionada: {selected_in_dictionary.get('descripcion') or selected_in_dictionary.get('id')}"
    )
    return message, selected_in_dictionary


def unknown_query_prompt(chat_id, phrase):
    suggestion = suggest_intent_with_ai(phrase)
    if not suggestion or suggestion.get("confianza", 0) < 0.75:
        return manual_intent_selection_prompt(chat_id, phrase)

    intent_id = canonical_intent_id(suggestion.get("intencion_sugerida", ""))
    if intent_id not in INTENCIONES_VALIDAS:
        return manual_intent_selection_prompt(chat_id, phrase)
    detected = extraer_parametros(phrase, intent_id)
    PENDING_INTENT_ADDS[int(chat_id)] = {
        "stage": "aprendizaje_confirmar_sugerencia",
        "phrase": phrase,
        "intencion_sugerida": intent_id,
        "confianza": suggestion.get("confianza", 0),
        "parametros": detected,
    }
    return (
        "Creo que esta frase corresponde a:\n"
        f"{readable_intent_label(intent_id)}\n\n"
        "Queres aprenderla asi?\n"
        "1) Si\n"
        "2) Elegir otra intencion\n"
        "0) Cancelar"
    )


def consume_learned_execution_reply(chat_id, reply):
    if not (isinstance(reply, tuple) and reply and reply[0] == "learned_execute"):
        return None
    _, message, selected, phrase = reply
    command = command_from_catalog_intent(selected, phrase)
    if not command:
        return ("text", message)
    kind, params = command
    if kind == "unknown":
        return ("text", message)
    if not isinstance(params, dict):
        params = {"text": str(params)}
    params["chat_id"] = chat_id
    authorized, reason = authorize_command(chat_id, kind, params)
    if not authorized:
        return ("text", message + "\n\n" + reason)
    prepared = prepare_client_query(chat_id, kind, params)
    if prepared[0] == "choices":
        return ("text", message + "\n\n" + prepared[1])
    result = handle_command(prepared[1], prepared[2])
    if result and result[0] == "text":
        return ("text", message + "\n\n" + result[1])
    return result



def format_intent_options():
    intents = available_intentions_for_add()
    lines = []
    for idx, intent in enumerate(intents, start=1):
        label = intent.get("descripcion") or intent.get("id") or f"Intencion {idx}"
        lines.append(f"{idx} - {label}")
    return "\n".join(lines)


def consume_intent_add(chat_id, text):
    pending = PENDING_INTENT_ADDS.get(int(chat_id))
    if not pending:
        return None

    answer = normalize_intent_phrase(text)
    if pending.get("stage") == "aprendizaje_confirmar_sugerencia":
        phrase = pending.get("phrase", "").strip()
        if answer == "1" or answer in {"si", "s"}:
            intent_id = canonical_intent_id(pending.get("intencion_sugerida", ""))
            if intent_id not in INTENCIONES_VALIDAS:
                return manual_intent_selection_prompt(chat_id, phrase)
            selected = {"id": intent_id, **INTENCIONES_VALIDAS[intent_id]}
            message, learned = learn_phrase_for_intent(phrase, selected)
            PENDING_INTENT_ADDS.pop(int(chat_id), None)
            return ("learned_execute", message, learned, phrase)
        if answer == "2":
            return manual_intent_selection_prompt(chat_id, phrase)
        if answer == "0" or answer in {"cancelar", "no", "n"}:
            PENDING_INTENT_ADDS.pop(int(chat_id), None)
            return "Consulta no agregada."
        return "Responda 1 para confirmar, 2 para elegir otra intencion o 0 para cancelar."

    if pending.get("stage") == "confirm":
        if answer in {"si", "sí", "s"}:
            pending["stage"] = "choose"
            pending["options"] = available_intentions_for_add()
            PENDING_INTENT_ADDS[int(chat_id)] = pending
            options = format_intent_options()
            if not options:
                PENDING_INTENT_ADDS.pop(int(chat_id), None)
                return "No hay intenciones disponibles para agregar la frase."
            return "Seleccione la intencion:\n\n" + options
        if answer in {"no", "n"}:
            PENDING_INTENT_ADDS.pop(int(chat_id), None)
            return "Consulta no agregada."
        return "Responda SI o NO."

    if pending.get("stage") == "choose":
        if not answer.isdigit():
            return "Responda con el numero de la intencion."

        intents = pending.get("options") or available_intentions_for_add()
        index = int(answer) - 1
        if index < 0 or index >= len(intents):
            return "Numero invalido. Responda con una opcion del listado."

        phrase = pending.get("phrase", "").strip()
        selected = intents[index]
        message, selected_in_dictionary = learn_phrase_for_intent(phrase, selected)
        PENDING_INTENT_ADDS.pop(int(chat_id), None)
        return message

    PENDING_INTENT_ADDS.pop(int(chat_id), None)
    return "Consulta no agregada."


def clean_script_error(text):
    value = repair_common_text_glitches(str(text or "")).strip()
    first_line = value.splitlines()[0].strip() if value else ""
    if "No encontre cliente:" in value:
        match = re.search(r"No encontre cliente:\s*([^\r\n]+)", value)
        client = (match.group(1).strip() if match else "").split(" En ")[0].strip()
        return f"No encontre el cliente: {client}" if client else "No encontre el cliente."
    return first_line or "No pude ejecutar la consulta."


def useful_output(output, marker):
    if not output:
        return "Consulta ejecutada."
    position = output.find(marker)
    if position >= 0:
        return output[position:].strip()
    return output.strip()


def format_sales_quick_result(data):
    labels = {
        "ARIDOS": "Áridos",
        "GRAVAS": "Gravas",
        "SERVICIOS": "Servicios",
        "OTROS_PRODUCTOS": "Otros productos",
    }
    period_from = data.get("periodo_desde") or "No disponible"
    period_to = data.get("periodo_hasta") or "No disponible"
    period = f"{period_from} a {period_to}" if period_from != "No disponible" else period_from
    categories = data.get("categorias") or []

    lines = [
        "📊 Ventas rápidas",
        "",
        "Período:",
        period,
        "",
        "Total:",
        data.get("total") or "No disponible",
        "",
        "Facturado:",
        data.get("facturado") or "No disponible",
        "",
        "Remitos:",
        data.get("remitos") or "No disponible",
    ]
    if categories:
        lines.append("")
        lines.append("Categorías:")
        for category in categories:
            label = labels.get(category.get("codigo"), category.get("codigo", "No disponible"))
            amount = category.get("importe") or "No disponible"
            pct = category.get("porcentaje") or "No disponible"
            lines.append("")
            lines.append(f"{label}:")
            lines.append(f"{amount} - {pct}")
        lines.append("")
        lines.append(f"Clasificado: {data.get('clasificado') or 'No disponible'}")
        lines.append(f"No clasificado: {data.get('no_clasificado') or 'No disponible'}")
    return "\n".join(lines)


def parse_productos_no_clasificados_period(text):
    lower = fold_accents(text or "").lower()
    today = date.today()
    month_pattern = "|".join(MONTHS_ES)
    month_match = re.search(rf"\b({month_pattern})\b(?:\s+de\s+|\s+)?(\d{{4}})?\b", lower)
    has_explicit_range = bool(
        re.search(r"\b(hoy|ayer|mes|desde|entre|hasta)\b", lower)
        or re.search(r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?", lower)
    )
    if month_match and not has_explicit_range:
        month = MONTHS_ES[month_match.group(1)]
        year = int(month_match.group(2)) if month_match.group(2) else today.year
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        return start.isoformat(), end.isoformat()
    if has_explicit_range:
        return parse_quick_report_period(text)
    start = date(today.year, today.month, 1)
    end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    return start.isoformat(), end.isoformat()


def productos_no_clasificados_requested(text):
    lower = fold_accents(normalize(repair_common_text_glitches(text))).lower()
    return bool(
        re.search(r"\bproductos?\s+no\s+clasificados?\b", lower)
        or re.search(r"\bno\s+clasificados?\b", lower)
        or re.search(r"\bproductos?\s+sin\s+clasificar\b", lower)
    )


def format_productos_no_clasificados_result(data):
    desde = data.get("fecha_desde")
    hasta = data.get("fecha_hasta")
    start = datetime.strptime(desde, "%Y-%m-%d").date()
    end = datetime.strptime(hasta, "%Y-%m-%d").date()
    cantidad_total = int(data.get("cantidad_total") or 0)
    groups = list(data.get("grupos") or [])
    lines = [
        "📦 PRODUCTOS NO CLASIFICADOS",
        "",
        "Período:",
        f"{start.strftime('%d/%m/%Y')} al {end.strftime('%d/%m/%Y')}",
        "",
        "Total no clasificado:",
        format_money_ar(data.get("importe_total")),
        "",
        "Cantidad:",
        f"{cantidad_total} líneas",
    ]
    if not groups:
        lines.extend(["", "━━━━━━━━━━━━━━━━━━", "", "No hay productos no clasificados en el período.", "", "0️⃣ Volver"])
        return "\n".join(lines)

    for index, group in enumerate(groups, start=1):
        product = str(group.get("producto") or "Sin descripción")
        icon = f"{index}️⃣" if index <= 9 else f"{index}."
        lines.extend(
            [
                "",
                "━━━━━━━━━━━━━━━━━━",
                "",
                f"{icon} {product.upper()}",
                f"Total: {format_money_ar(group.get('importe_total'))}",
                f"Líneas: {int(group.get('cantidad_lineas') or 0)}",
                "",
                "Comprobantes:",
            ]
        )
        for row in group.get("registros") or []:
            cantidad = str(row.get("cantidad") or "").strip()
            unidad = str(row.get("unidad") or "").strip()
            quantity = f" — Cant. {cantidad} {unidad}".rstrip() if cantidad else ""
            lines.append(
                f"• {row.get('tipo_comprobante') or '-'} "
                f"{row.get('numero_comprobante') or 's/n'} — "
                f"{row.get('fecha_mostrada') or '-'} — "
                f"{row.get('cliente') or '-'} — "
                f"{format_money_ar(row.get('importe'))}{quantity}"
            )
        hidden_lines = int(group.get("lineas_ocultas") or 0)
        if hidden_lines:
            lines.append(f"• ... {hidden_lines} líneas más en CSV.")

    hidden_products = int(data.get("productos_ocultos") or 0)
    if hidden_products:
        lines.extend(["", f"Hay {hidden_products} productos/conceptos más en el CSV completo."])
    if data.get("truncado"):
        lines.extend(["", f"CSV completo: {data.get('archivo_csv')}"])
    lines.extend(["", "━━━━━━━━━━━━━━━━━━", "", "0️⃣ Volver"])
    return "\n".join(lines)
def multipart_request(url, fields, files, headers=None, timeout=180):
    boundary = "----LaHelenaOpenAIBoundary"
    body = bytearray()
    for key, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    for key, path in files.items():
        path = Path(path)
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            (
                f'Content-Disposition: form-data; name="{key}"; '
                f'filename="{path.name}"\r\n'
            ).encode()
        )
        body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
        body.extend(path.read_bytes())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", **(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def transcribe_audio(path):
    api_key = os.environ.get("OPENAI_API_KEY") or CONFIG.get("openai_api_key", "")
    if not api_key:
        raise RuntimeError("Falta configurar openai_api_key para transcribir audios.")

    text = multipart_request(
        "https://api.openai.com/v1/audio/transcriptions",
        fields={
            "model": CONFIG.get("transcription_model", "gpt-4o-mini-transcribe"),
            "response_format": "text",
            "language": "es",
            "prompt": (
                "Comandos de administracion de Cantera La Helena: saldo de cliente, "
                "deudores, cobros por efectivo cheque echeq transferencia flete, "
                "estado de cuenta PDF desde ultimo pago, materiales, facturas PDF. "
                "Usa nombres de clientes, tipos de comprobantes, fechas o importes. "
                "CLIENTE_A, CLIENTE_B y CLIENTE_C."
            ),
        },
        files={"file": path},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=180,
    )
    return normalize(text)


def convert_voice_to_mp3(source):
    ffmpeg = CONFIG.get("ffmpeg_path", "ffmpeg")
    if not shutil.which(ffmpeg) and not Path(ffmpeg).exists():
        raise RuntimeError("Falta instalar ffmpeg o configurar ffmpeg_path para convertir audios de Telegram.")
    target = source.with_suffix(".mp3")
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(target),
    ]
    completed = run_text_subprocess(command, capture_output=True, timeout=120)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or "No pude convertir el audio.")
    return target


def handle_voice(bot, message):
    VOICE_DIR.mkdir(exist_ok=True)
    voice = message.get("voice") or message.get("audio")
    file_id = voice["file_id"]
    file_info = bot.get_file(file_id)
    file_path = file_info["result"]["file_path"]
    suffix = Path(file_path).suffix or ".oga"
    raw_path = VOICE_DIR / f"{file_id}{suffix}"
    bot.download_file(file_path, raw_path)
    mp3_path = convert_voice_to_mp3(raw_path)
    transcript = transcribe_audio(mp3_path)
    kind, params = parse_command(transcript)
    return transcript, kind, params


def process_text_query(bot, chat_id, text, *, source_object="Mensaje", unknown_description="Texto no interpretado"):
    kind, params = parse_command(text)
    if not isinstance(params, dict):
        params = {"text": str(params)}
    params["chat_id"] = chat_id
    if kind != "unknown":
        PENDING_INTENT_ADDS.pop(int(chat_id), None)
        PENDING_SELECTIONS.pop(int(chat_id), None)
    log_event(f"{chat_id}: texto {text} -> {kind} {params}")
    authorized, reason = authorize_command(chat_id, kind, params)
    if not authorized:
        registrar_actividad(
            chat_id=chat_id,
            modulo=modulo_actividad_para_comando(kind, params),
            accion="Acceso denegado",
            objeto=str(kind or ""),
            descripcion=reason,
            nivel="WARNING",
        )
        bot.send_message(chat_id, reason)
        return
    if kind == "unknown":
        registrar_actividad(
            chat_id=chat_id,
            modulo="Sistema",
            accion="Comando desconocido",
            objeto=source_object,
            descripcion=unknown_description,
            nivel="INFO",
        )
        bot.send_message(chat_id, activate_main_menu(chat_id))
        return
    bot.send_action(chat_id, "typing")
    prepared = prepare_client_query(chat_id, kind, params)
    if prepared[0] == "choices":
        bot.send_message(chat_id, prepared[1])
        return
    try:
        auditar_consulta(chat_id, prepared[1], prepared[2])
        result = handle_command(prepared[1], prepared[2])
        reply_result(bot, chat_id, result)
    except Exception as exc:
        registrar_actividad(
            chat_id=chat_id,
            modulo=modulo_actividad_para_comando(prepared[1], prepared[2]),
            accion="Error de consulta",
            objeto=str(prepared[1] or ""),
            descripcion=f"Error ejecutando consulta: {exc}",
            nivel="ERROR",
        )
        print(f"Error de consulta: {exc}", flush=True)
        bot.send_message(chat_id, friendly_error(exc, input_kind="text"))


def prepare_client_query(chat_id, kind, params):
    client_kinds = {
        "saldo",
        "material",
        "estado_pdf",
        "estado_pdf_abierto",
        "estado_pdf_ultimo_pago",
        "facturas_cliente_pdf",
        "facturas_ultimas_cliente_pdf",
    }
    if kind not in client_kinds:
        return ("ready", kind, params)
    query = params.get("cliente", "")
    if not query or str(query).isdigit():
        return ("ready", kind, params)
    status, value = resolve_client(query)
    if status == "selected":
        updated = dict(params)
        updated["cliente"] = str(value["IdCLIENTE"])
        updated["cliente_nombre"] = value.get("RazonSocial", query)
        return ("ready", kind, updated)
    if status == "choices":
        PENDING_SELECTIONS[int(chat_id)] = {
            "kind": kind,
            "params": dict(params),
            "choices": value,
            "created": time.time(),
        }
        return ("choices", client_choice_text(query, value), None)
    return ("ready", kind, params)


def consume_client_selection(chat_id, text):
    pending = PENDING_SELECTIONS.get(int(chat_id))
    if not pending:
        return None
    if time.time() - pending["created"] > 600:
        PENDING_SELECTIONS.pop(int(chat_id), None)
        return None
    match = re.fullmatch(r"\s*(\d+)\s*", text or "")
    if not match:
        return None
    index = int(match.group(1)) - 1
    choices = pending["choices"]
    if index < 0 or index >= len(choices):
        return ("error", f"Elegi un numero entre 1 y {len(choices)}.")
    selected = choices[index]
    params = dict(pending["params"])
    params["cliente"] = str(selected["IdCLIENTE"])
    params["cliente_nombre"] = selected.get("RazonSocial", "")
    PENDING_SELECTIONS.pop(int(chat_id), None)
    return ("ready", pending["kind"], params)


def friendly_error(exc, *, input_kind="audio"):
    if isinstance(exc, urllib.error.HTTPError):
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:
            detail = ""
        if exc.code == 429 and ("insufficient_quota" in detail or "quota" in detail.lower()):
            return (
                "No queda credito disponible para transcribir audios.\n\n"
                "Carga saldo en OpenAI:\n"
                "https://platform.openai.com/settings/organization/billing/overview\n\n"
                "Mientras tanto podes usar el dictado del teclado y enviar el comando como texto."
            )
        if exc.code == 401:
            return "La API key de OpenAI no es valida o fue revocada."
        return f"OpenAI respondio con error HTTP {exc.code}."
    text = str(exc)
    if "ffmpeg" in text.lower():
        return f"No pude convertir el audio: {text}"
    if "No encontre cliente:" in text:
        return clean_script_error(text)
    if input_kind == "text":
        return f"No pude procesar la consulta: {text}"
    return f"No pude procesar el audio: {text}"


def latest_output(pattern):
    files = sorted(OUTPUTS.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def safe_file_part(text):
    value = fold_accents(str(text or "")).lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "cliente"


def estado_pdf_controlled_error(result):
    code = result.error.code if result.error else ""
    return code in {
        "pdf_no_generado",
        "pdf_no_corresponde_ejecucion",
        "ruta_pdf_no_autorizada",
        "extension_pdf_invalida",
        "pdf_vacio",
        "cliente_no_encontrado",
        "cliente_ambiguo",
        "estado_pdf_timeout",
    }


def parse_factura_pdf_command(text):
    body = re.sub(r"^/factura_pdf\s+", "", text, flags=re.IGNORECASE).strip()
    body = re.sub(
        r"\b(dame|enviame|enviar|mandame|pasame|pasar|buscar|busca|traeme|necesito|quiero|pdf|en pdf|la|el|una|un|por favor)\b",
        "",
        body,
        flags=re.IGNORECASE,
    )
    body = re.sub(r"\s+", " ", body).strip()

    tipo = ""
    type_patterns = [
        (r"\bfta\b", "FTS A"),
        (r"\bftb\b", "FTS B"),
        (r"\bfts?\s*a\b", "FTS A"),
        (r"\bfts?\s*b\b", "FTS B"),
        (r"\bfactura\s*a\b", "FTS A"),
        (r"\bfactura\s*b\b", "FTS B"),
        (r"\bfp\s*a\b", "FP A"),
        (r"\bfp\s*b\b", "FP B"),
        (r"\bncs?\s*a\b", "NCS A"),
        (r"\bncs?\s*b\b", "NCS B"),
        (r"\bnota\s+de\s+credito\s+a\b", "NCS A"),
        (r"\bnota\s+de\s+credito\s+b\b", "NCS B"),
        (r"\bnd\s*a\b", "ND A"),
        (r"\bnd\s*b\b", "ND B"),
    ]
    for pattern, value in type_patterns:
        if re.search(pattern, body, flags=re.IGNORECASE):
            tipo = value
            body = re.sub(pattern, "", body, flags=re.IGNORECASE).strip()
            break

    number_match = re.search(r"(\d[\d\-\s/]*\d|\d+)", body)
    numero = number_match.group(1).strip() if number_match else ""
    return ("factura_pdf", {"tipo": tipo, "numero": numero})


def parse_latest_invoice_count(text):
    lower = fold_accents(text).lower()
    number_words = {
        "una": 1,
        "un": 1,
        "ultima": 1,
        "ultimo": 1,
        "dos": 2,
        "tres": 3,
        "cuatro": 4,
        "cinco": 5,
    }
    digit_match = re.search(r"\b(\d{1,2})\s+(?:ultimas|ultimos)\b", lower)
    if digit_match:
        return max(1, min(int(digit_match.group(1)), 20))
    for word, value in number_words.items():
        if re.search(rf"\b{word}\s+(?:ultimas|ultimos|facturas|comprobantes)\b", lower):
            return value
    return 1


def parse_latest_invoice_client_pattern(text):
    normalized = normalize(repair_common_text_glitches(text))
    match = re.match(
        r"^\s*(?:quiero\s+|dame\s+|enviame\s+|mandame\s+)?(?:la\s+)?(?:ultima|última)\s+factura(?:\s+de)?\s+(.+?)\s*$",
        normalized,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    cliente = clean_client_name(match.group(1).strip())
    if not cliente:
        return None

    return ("facturas_ultimas_cliente_pdf", {"cliente": cliente, "cantidad": 1})


def parse_command(text):
    original = normalize(repair_common_text_glitches(text))
    lower = fold_accents(original).lower()
    if lower == "/start" or lower in {"/menu", "menu", "inicio"}:
        return ("menu_principal", {})
    if lower in {"/ayuda", "ayuda", "help"}:
        return ("help", {})
    if lower in {"/dashboard", "dashboard", "resumen gerencial", "que tengo que saber hoy"}:
        return ("dashboard_gerencial", {})
    if lower == "/usuarios" or lower == "usuarios":
        return ("usuarios_menu", {"accion": "menu"})
    if lower in {"/usuarios listar", "usuarios listar"}:
        return ("usuarios_menu", {"accion": "listar"})
    if lower in {"/usuarios mi", "/usuarios yo", "usuarios mi", "usuarios yo", "mi usuario"}:
        return ("usuarios_menu", {"accion": "mi"})
    if lower in {"/reiniciar", "reiniciar", "reiniciar bot"}:
        return ("bot_restart_hint", {})
    if lower in {"/version", "version", "version bot"}:
        return ("bot_version", {})
    if productos_no_clasificados_requested(original):
        desde, hasta = parse_productos_no_clasificados_period(original)
        return ("productos_no_clasificados", {"desde": desde, "hasta": hasta})

    dictionary_match = match_intent_dictionary(original)
    latest_invoice_match = parse_latest_invoice_client_pattern(original)
    if latest_invoice_match:
        return latest_invoice_match

    if dictionary_match and dictionary_match.get("ambigua"):
        return ("text", "La frase existe en mas de una intencion. Indicar una intencion explicita antes de ejecutarla.")
    if dictionary_match and not dictionary_match.get("sin_coincidencia"):
        return ("diccionario_intencion", dictionary_match)

    if lower.startswith("/saldo "):
        return ("saldo", {"cliente": original[7:].strip()})
    if "saldo de " in lower:
        return ("saldo", {"cliente": original[lower.index("saldo de ") + 9 :].strip()})
    if lower.startswith("saldo "):
        return ("saldo", {"cliente": original[6:].strip()})

    if lower.startswith("/deudores") or lower.startswith("deudores"):
        top_match = re.search(r"\btop\s+(\d+)\b", lower)
        top = top_match.group(1) if top_match else "0"
        return ("deudores", {"top": top})

    if (
        ("ultima factura" in lower or "ultimas facturas" in lower or "ultimos comprobantes" in lower or "ultimas comprobantes" in lower)
        and re.search(r"\b(de|del|para)\b", lower)
    ):
        cantidad = parse_latest_invoice_count(original)
        body = re.sub(
            r"dame\s+|enviame\s+|mandame\s+|pasame\s+|pdf|en pdf|la\s+|las\s+|los\s+",
            "",
            original,
            flags=re.IGNORECASE,
        )
        body = re.sub(r"\b\d{1,2}\s+", "", body, flags=re.IGNORECASE)
        body = re.sub(
            r"\b(ultima|ultimas|ultimo|ultimos|última|últimas|último|últimos|una|un|dos|tres|cuatro|cinco)\s+",
            "",
            body,
            flags=re.IGNORECASE,
        )
        body = re.sub(r"\b(facturas?|comprobantes?)\b", "", body, flags=re.IGNORECASE)
        body = re.sub(r"^(ultima|ultimas|ultimo|ultimos|última|últimas|último|últimos)\s+(de|del|para)\s+", "", body.strip(), flags=re.IGNORECASE)
        cliente = re.sub(r"^(de|del|para)\s+", "", body.strip(), flags=re.IGNORECASE).strip()
        cliente = clean_client_name(cliente)
        return ("facturas_ultimas_cliente_pdf", {"cliente": cliente, "cantidad": cantidad})

    if re.match(r"^(enviame|mandame|pasame|dame)\s+(de|del|para)\s+", lower):
        cliente = clean_client_name(re.sub(r"^(enviame|mandame|pasame|dame)\s+", "", original, flags=re.IGNORECASE))
        return ("facturas_ultimas_cliente_pdf", {"cliente": cliente, "cantidad": 1})

    if (
        "pdf" in lower
        and ("facturas" in lower or "comprobantes" in lower)
        and ("desde" in lower or "entre" in lower)
    ):
        desde, hasta = parse_account_period(original)
        body = re.sub(
            r"dame\s+|enviame\s+|mandame\s+|pasame\s+|pdf|en pdf|todas\s+las|todos\s+los",
            "",
            original,
            flags=re.IGNORECASE,
        )
        body = re.sub(r"\b(facturas|comprobantes)\b(?:\s+en)?", "", body, flags=re.IGNORECASE)
        body = re.sub(
            r"\b(del?\s+)?(resumen|estado)\s+de\s+cuentas?\b",
            "",
            body,
            flags=re.IGNORECASE,
        )
        cliente = clean_client_name(re.sub(r"\bdesde\b.*$", "", body, flags=re.IGNORECASE))
        cliente = clean_client_name(re.sub(r"\bentre\b.*$", "", cliente, flags=re.IGNORECASE))
        cliente = re.sub(r"^(de|del|para)\s+", "", cliente, flags=re.IGNORECASE).strip()
        return ("facturas_cliente_pdf", {"cliente": cliente, "desde": desde, "hasta": hasta})

    single_invoice_words = re.search(
        r"\b(factura|comprobante|ft|fts|fp|nc|ncs|nota de credito|nota credito|nd|nota de debito|nota debito)\b",
        lower,
    )
    has_number = re.search(r"\d", lower)
    if lower.startswith("/factura_pdf ") or (single_invoice_words and has_number):
        return parse_factura_pdf_command(original)

    if (
        lower in {"depositables", "cobrar", "depositar", "cheques depositables"}
        or lower in {"cheques para depositar", "cheques para cobrar"}
        or "puedo depositar" in lower
        or "puedo cobrar" in lower
        or "cobrar o depositar" in lower
        or "depositar hoy" in lower
        or "depositar ya" in lower
        or lower.startswith("/depositables")
    ):
        return ("cheques_depositables", {})

    if (
        lower in {"cheques", "cheque", "echeq", "echeqs", "cartera cheques", "cartera de cheques"}
        or lower.startswith("/cheques")
        or "cuanto tengo en cheques" in lower
        or "cuanto tengo en echeq" in lower
        or "cuanto hay en echeq" in lower
        or "cuanto hay en cheques" in lower
        or "cartera de cheques" in lower
        or "cuanto tengo de cada" in lower
    ):
        tipo = "TODOS"
        mentions_echeq = "echeq" in lower or "e-cheq" in lower
        mentions_physical = "fisic" in lower
        if mentions_echeq and not mentions_physical:
            tipo = "ECHEQ"
        elif mentions_physical and not mentions_echeq:
            tipo = "CHEQUE"
        return ("cheques_resumen", {"tipo": tipo})

    if (
        lower in {"vencimientos", "vencimiento cheques", "vencimientos cheques"}
        or lower.startswith("/vencimientos")
        or "proximos a vencer" in lower
        or "próximos a vencer" in lower
        or "vencen" in lower
    ):
        tipo = "TODOS"
        if "echeq" in lower or "e-cheq" in lower:
            tipo = "ECHEQ"
        elif "cheque" in lower and "echeq" not in lower:
            tipo = "CHEQUE"
        return ("cheques_vencimientos", {"tipo": tipo, "dias": parse_days(original, 7)})

    is_pago_echeq_phrase = "pago" in lower and ("echeq" in lower or "e-cheq" in lower) and "cheque" not in lower
    is_pago_cheque_phrase = re.match(r"^pago\s+con\s+cheques?\b", lower) is not None
    is_pago_mixto_phrase = (
        re.match(r"^pago\s+mixto\b", lower) is not None
        or ("pago" in lower and "cheque" in lower and ("echeq" in lower or "e-cheq" in lower))
    )
    is_pago_optimo_phrase = (
        re.match(r"^pagar\b", lower)
        or re.match(r"^pago\s+optimo\b", lower)
        or re.match(r"^pago\s+óptimo\b", lower)
    )
    if (is_pago_optimo_phrase or is_pago_cheque_phrase or is_pago_mixto_phrase) and not is_pago_echeq_phrase:
        modo = "OPTIMO"
        if is_pago_mixto_phrase:
            modo = "MIXTO"
        elif is_pago_cheque_phrase:
            modo = "CHEQUE"
        importe, plazo = parse_pago_rapido_datos(original)
        if not importe:
            return ("armar_pago_optimo", {"importe": None, "plazo": plazo, "modo": modo})
        if not plazo:
            return ("armar_pago_optimo", {"importe": importe, "plazo": None, "modo": modo})
        return ("armar_pago_optimo", {"importe": importe, "plazo": plazo, "modo": modo})

    if (
        lower.startswith("/armar_pago_echeq")
        or ("arm" in lower and "pago" in lower and ("echeq" in lower or "e-cheq" in lower))
        or ("combin" in lower and ("echeq" in lower or "e-cheq" in lower))
        or ("pago" in lower and ("echeq" in lower or "e-cheq" in lower) and parse_money_amount(original))
    ):
        return (
            "armar_pago_echeq",
            {"importe": parse_money_amount(original), "dias": parse_days(original, 30)},
        )

    if lower.startswith("/cobros") or "se cobro" in lower or "se cobró" in lower or "cobrado" in lower:
        medio = parse_medio_pago(original)
        desde, hasta = parse_period(original)
        return ("cobros", {"medio": medio, "desde": desde, "hasta": hasta})

    if (
        lower.startswith("/iva")
        or lower.startswith("iva ")
        or lower == "iva"
        or "iva mensual" in lower
        or "reporte iva" in lower
    ):
        year, month = parse_iva_month(original)
        return ("iva_mensual", {"anio": year, "mes": month})

    if lower.startswith("/material "):
        return ("material", {"cliente": original[10:].strip()})
    if lower.startswith("material "):
        return ("material", {"cliente": original[9:].strip()})
    if "material que mas compra " in lower:
        pos = lower.index("material que mas compra ") + len("material que mas compra ")
        return ("material", {"cliente": original[pos:].strip()})

    if lower.startswith("/estado_ultimo_pago "):
        return ("estado_pdf_ultimo_pago", {"cliente": original[20:].strip()})

    account_phrase = (
        "estado de cuenta" in lower
        or "estado de cuentas" in lower
        or "resumen de cuenta" in lower
        or "resumen de cuentas" in lower
        or lower.startswith("estado ")
        or lower.startswith("resumen ")
        or lower.startswith("dame estado ")
        or lower.startswith("dame resumen ")
        or lower.startswith("enviame estado ")
        or lower.startswith("enviame resumen ")
        or lower.startswith("mandame estado ")
        or lower.startswith("pasame estado ")
    )

    if account_phrase and ("ultimo pago" in lower or "último pago" in lower):
        return ("estado_pdf_ultimo_pago", {"cliente": strip_client_from_account_text(original)})

    if lower.startswith("/estado_pdf ") or lower.startswith("estado pdf "):
        body = re.sub(r"^/?estado[_ ]pdf\s+", "", original, flags=re.IGNORECASE).strip()
        dates = parse_dates(body)
        desde = dates[0] if dates else None
        hasta = dates[1] if len(dates) > 1 else None
        cliente = clean_client_name(re.sub(r"\bdesde\b.*$", "", body, flags=re.IGNORECASE))
        return ("estado_pdf", {"cliente": cliente, "desde": desde, "hasta": hasta})

    if account_phrase:
        desde, hasta = parse_account_period(original)
        cliente = strip_client_from_account_text(original)
        if not desde:
            return ("estado_pdf_abierto", {"cliente": cliente})
        return ("estado_pdf", {"cliente": cliente, "desde": desde, "hasta": hasta})

    if lower.startswith("/auditoria") or "usuario 3" in lower:
        return ("auditoria_mail_only", {})

    return ("unknown", {"text": original})


def help_text():
    return (
        "Consultas disponibles:\n\n"
        "- Saldo y cuenta corriente de clientes.\n"
        "- Listado de deudores.\n"
        "- Cobros por fecha o medio de pago.\n"
        "- Ventas e IVA por periodo.\n"
        "- Productos no clasificados por periodo.\n"
        "- Materiales entregados a un cliente.\n"
        "- Facturas electronicas y comprobantes.\n"
        "- Estado de cuenta en PDF.\n"
        "- Estado de cuenta desde el ultimo pago.\n"
        "- Busqueda de facturas por numero.\n"
        "- Facturas de un cliente dentro de un periodo.\n"
        "- Ultimas facturas emitidas a un cliente.\n\n"
        "Ejemplos:\n\n"
        "Cual es el saldo de CLIENTE?\n"
        "Mostrar los principales deudores.\n"
        "Cuanto se cobro en efectivo ayer?\n"
        "Productos no clasificados.\n"
        "Generar estado de cuenta de CLIENTE desde FECHA.\n"
        "Generar estado de cuenta de CLIENTE desde el ultimo pago.\n"
        "Buscar FACTURA por numero.\n"
        "Enviar las facturas de CLIENTE de un PERIODO en PDF.\n"
        "Mostrar las ultimas facturas de CLIENTE.\n"
        "Que materiales se entregaron a CLIENTE?\n"
        "Mostrar el IVA de un mes.\n\n"
        "Tambien podes enviar consultas por voz.\n\n"
        "Si el nombre de un cliente es ambiguo, se mostraran opciones para "
        "seleccionar el cliente correcto."
    )


def handle_command(kind, params):
    if PILOT_MODE and kind not in PILOT_READ_ONLY_KINDS:
        return ("text", "Modo piloto: accion deshabilitada; solo se permiten consultas de lectura.")
    if kind == "help":
        return ("text", help_text())

    if kind == "menu_principal":
        chat_id = params.get("chat_id", "")
        if chat_id != "":
            MENU_STATES[int(chat_id)] = {"pantalla": "menu_principal", "anterior": None}
            log_event(f"MENU_NAV set_principal chat_id={chat_id} key={int(chat_id)} estado={MENU_STATES.get(int(chat_id))!r}")
        return ("text", render_menu_principal(chat_id))

    if kind == "bot_restart_request":
        log_event(f"RESTART solicitud_neutralizada chat_id={params.get('chat_id', 0)}")
        return ("text", RESTART_DISABLED_MESSAGE)

    if kind == "bot_restart_hint":
        log_event(f"RESTART comando_deshabilitado chat_id={params.get('chat_id', 0)}")
        return ("text", RESTART_DISABLED_MESSAGE)

    if kind == "bot_version":
        modified = datetime.fromtimestamp(Path(__file__).stat().st_mtime)
        return (
            "text",
            "Version del bot\n\n"
            f"Inicio: {BOT_STARTED_AT.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"PID: {os.getpid()}\n"
            f"Archivo: {modified.strftime('%Y-%m-%d %H:%M:%S')}",
        )

    if kind == "dashboard_gerencial":
        return ("text", handle_dashboard_gerencial())

    if kind == "usuarios_menu":
        accion = params.get("accion", "menu")
        data = load_telegram_users_data()
        if accion == "mi":
            user, _, source = telegram_user_display(params.get("chat_id", ""))
            name = user.get("nombre") or user.get("name") or "Usuario"
            role = user.get("rol") or user.get("role") or "sin_rol"
            active = user.get("activo", True)
            access_user_id = user.get("access_user_id", "")
            return (
                "text",
                "Mi usuario Telegram\n\n"
                f"Nombre: {name}\n"
                f"Rol: {role}\n"
                f"Access UserID: {access_user_id}\n"
                f"Activo: {active}\n"
                f"Origen: {source}",
            )
        if accion == "listar":
            if not data:
                return ("text", "No existe telegram_usuarios.json.")
            return ("text", format_users_list(data))
        PENDING_USER_MANAGEMENT[int(params.get("chat_id", 0))] = {"stage": "menu"}
        return ("text", format_users_menu())

    if kind == "diccionario_intencion":
        intent_id = params.get("id", "")
        base = params.get("parametros_base") or {}
        catalog_command = command_from_catalog_intent(params, params.get("texto_original") or params.get("frase_usuario", ""))
        if catalog_command:
            catalog_kind, catalog_params = catalog_command
            if catalog_kind != "unknown":
                catalog_params["chat_id"] = params.get("chat_id", "")
                return handle_command(catalog_kind, catalog_params)
        if intent_id == "analisis_categorias":
            result = consultar_analisis_categorias(
                Request(
                    capability="ventas.analisis_categorias",
                    parameters={},
                    user_context=UserContext(
                        channel="telegram",
                        channel_user_id=str(params.get("chat_id", "")),
                    ),
                    channel="telegram",
                ),
                adapter=VentasRapidasPowerShellAdapter(settings=SETTINGS),
            )
            if not result.success:
                raise RuntimeError(clean_script_error(result.error.message if result.error else result.message))
            return (
                "text",
                dictionary_header(params, "work/analisis_categorias.ps1")
                + result.data["texto_resumido"],
            )
        if intent_id == "mejores_clientes":
            top = str(base.get("Top", 10))
            output = run_script("ranking_clientes.ps1", ["-Accion", "mejores", "-Top", top], timeout=240)
        return ("text", dictionary_header(params, "work/ranking_clientes.ps1") + useful_output(output, "Ranking de clientes:"))
        if intent_id == "peores_clientes":
            top = str(base.get("Top", 10))
            output = run_script("ranking_clientes.ps1", ["-Accion", "peores", "-Top", top], timeout=240)
        return ("text", dictionary_header(params, "work/ranking_clientes.ps1") + useful_output(output, "Ranking de clientes:"))
        if intent_id == "mayores_deudores":
            top = str(base.get("Top", 10))
            output = run_ps(["deudores", "-Top", top], timeout=240)
        return ("text", dictionary_header(params, "work/consultas_rapidas.ps1") + useful_output(output, "Clientes deudores:"))
        if intent_id == "iva_mensual":
            anio = int(params.get("anio") or date.today().year)
            mes = int(params.get("mes") or date.today().month)
            data = execute_iva_core(anio, mes, chat_id=params.get("chat_id", ""))
            return ("text", format_iva_estimated_output(data, anio, mes))
        if intent_id == "cheques":
            data = execute_cheques_core(
                "cheques.resumen",
                {"tipo": "TODOS", "filtro_fiscal": "TODOS"},
                chat_id=params.get("chat_id", ""),
                timeout_seconds=SETTINGS.timeouts.long_script_seconds,
            )
            return (
                "text",
                dictionary_header(params, "work/gestion_cheques.ps1")
                + format_cheques_resumen_telegram(data),
            )
        return (
            "text",
            "Frase detectada:\n"
            f"{params.get('frase_usuario', '')}\n\n"
            "Intencion:\n"
            f"{intent_id}\n\n"
            "Script:\n"
            f"{Path(params.get('script', '')).name}\n\n"
            "La intencion existe en el diccionario, pero todavia no tiene ejecucion configurada.",
        )

    if kind == "saldo":
        cliente = params.get("cliente", "")
        if not cliente:
            return ("text", "Decime el cliente. Ejemplo: /saldo CLIENTE")
        result = consultar_saldo_cliente(
            Request(
                capability="clientes.saldo",
                parameters={"cliente": cliente},
                user_context=UserContext(
                    channel="telegram",
                    channel_user_id=str(params.get("chat_id", "")),
                ),
                channel="telegram",
            ),
            adapter=ClienteSaldoPowerShellAdapter(settings=SETTINGS),
        )
        if result.error and result.error.code == "cliente_saldo_error":
            raise RuntimeError(clean_script_error(result.error.message))
        return ("text", useful_output(result.message, "Cliente:"))

    if kind == "deudores":
        output = run_ps(["deudores", "-Top", str(params.get("top", "0"))], timeout=240)
        csv_path = latest_output("deudores.csv")
        if csv_path:
            return ("document", csv_path, useful_output(output, "Clientes deudores:")[-1000:])
        return ("text", useful_output(output, "Clientes deudores:"))

    if kind == "ventas_rapidas":
        refresh_access()
        desde = params.get("desde") or date.today().isoformat()
        hasta = params.get("hasta") or desde
        result = consultar_ventas_rapidas(
            Request(
                capability="ventas.rapidas",
                parameters={"fecha_desde": desde, "fecha_hasta": hasta},
                user_context=UserContext(
                    channel="telegram",
                    channel_user_id=str(params.get("chat_id", "")),
                ),
                channel="telegram",
            ),
            adapter=VentasRapidasPowerShellAdapter(settings=SETTINGS),
        )
        if not result.success:
            raise RuntimeError(clean_script_error(result.error.message if result.error else result.message))
        return ("text", format_sales_quick_result(result.data))

    if kind == "productos_no_clasificados":
        refresh_access()
        desde = params.get("desde")
        hasta = params.get("hasta")
        if not desde or not hasta:
            desde, hasta = parse_productos_no_clasificados_period("")
        result = consultar_productos_no_clasificados(
            Request(
                capability="ventas.productos_no_clasificados",
                parameters={"fecha_desde": desde, "fecha_hasta": hasta},
                user_context=UserContext(
                    channel="telegram",
                    channel_user_id=str(params.get("chat_id", "")),
                ),
                channel="telegram",
            ),
            adapter=VentasRapidasPowerShellAdapter(settings=SETTINGS),
        )
        if not result.success:
            raise RuntimeError(clean_script_error(result.error.message if result.error else result.message))
        return ("text", format_productos_no_clasificados_result(result.data))

    if kind == "cobros":
        medio = params.get("medio", "todos")
        desde = params.get("desde")
        hasta = params.get("hasta")
        result = consultar_cobros(
            Request(
                capability="caja.cobros",
                parameters={
                    "medio": medio,
                    "fecha_desde": desde,
                    "fecha_hasta": hasta,
                },
                user_context=UserContext(
                    channel="telegram",
                    channel_user_id=str(params.get("chat_id", "")),
                ),
                channel="telegram",
            ),
            adapter=CajaPowerShellAdapter(settings=SETTINGS),
        )
        if not result.success:
            raise RuntimeError(clean_script_error(result.error.message if result.error else result.message))
        return ("text", result.data["texto_legacy"])

    if kind == "iva_mensual":
        anio = int(params.get("anio") or date.today().year)
        mes = int(params.get("mes") or date.today().month)
        data = execute_iva_core(anio, mes, chat_id=params.get("chat_id", ""))
        return ("text", format_iva_estimated_output(data, anio, mes))

    if kind == "cheques_resumen":
        refresh_access()
        tipo = params.get("tipo", "TODOS")
        filtro_fiscal = normalize_cheques_fiscal_filter(params.get("filtro_fiscal"))
        data = execute_cheques_core(
            "cheques.resumen",
            {"tipo": tipo, "filtro_fiscal": filtro_fiscal},
            chat_id=params.get("chat_id", ""),
            timeout_seconds=SETTINGS.timeouts.default_script_seconds,
        )
        return ("text", format_cheques_resumen_telegram(data))

    if kind == "cheques_depositables":
        refresh_access()
        filtro_fiscal = normalize_cheques_fiscal_filter(params.get("filtro_fiscal"))
        data = execute_cheques_core(
            "cheques.depositables",
            {"tipo": "TODOS", "filtro_fiscal": filtro_fiscal},
            chat_id=params.get("chat_id", ""),
            timeout_seconds=SETTINGS.timeouts.default_script_seconds,
        )
        return ("text", format_cheques_depositables_telegram(data))

    if kind == "cheques_vencimientos":
        refresh_access()
        tipo = params.get("tipo", "TODOS")
        filtro_fiscal = normalize_cheques_fiscal_filter(params.get("filtro_fiscal"))
        dias = max(1, min(int(params.get("dias", 7)), 180))
        data = execute_cheques_core(
            "cheques.vencimientos",
            {
                "tipo": tipo,
                "filtro_fiscal": filtro_fiscal,
                "dias": dias,
            },
            chat_id=params.get("chat_id", ""),
            timeout_seconds=SETTINGS.timeouts.default_script_seconds,
        )
        header = (
            f"Filtro: {CHEQUES_FISCAL_LABELS[filtro_fiscal]}\n"
            f"Período: próximos {dias} días\n\n"
        )
        if not list(data.get("cheques") or []):
            return ("text", header + "No hay valores para ese filtro.")
        return ("text", header + format_cheques_vencimientos_telegram(data))

    if kind == "armar_pago_echeq":
        importe = params.get("importe")
        if not importe or importe <= 0:
            return ("text", "Indica el importe. Ejemplo: armame un pago con eCheq de 5 millones a 30 dias.")
        dias = max(1, min(int(params.get("dias", 30)), 180))
        log_event(f"PAGO_RAPIDO inicio kind=armar_pago_echeq importe={importe} dias={dias}")
        refresh_access()
        try:
            data = execute_pagos_core(
                "pagos.echeq_legacy",
                {
                    "importe": importe,
                    "plazo": {"tipo": "DIAS", "dias": dias},
                    "modo": "ECHEQ",
                    "filtro_fiscal": "TODOS",
                },
                chat_id=params.get("chat_id", ""),
                timeout_seconds=PAYMENT_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            log_event(f"PAGO_RAPIDO timeout kind=armar_pago_echeq importe={importe} dias={dias}")
            return ("text", PAYMENT_TIMEOUT_MESSAGE)
        except Exception as exc:
            if "demor" in str(exc).lower():
                log_event(f"PAGO_RAPIDO timeout_interno kind=armar_pago_echeq importe={importe} dias={dias} error={exc}")
                return ("text", PAYMENT_TIMEOUT_MESSAGE)
            raise
        log_event(f"PAGO_RAPIDO fin kind=armar_pago_echeq importe={importe} dias={dias}")
        return ("text", str(data.get("texto_legacy") or ""))

    if kind == "armar_pago_optimo":
        importe = params.get("importe")
        plazo = params.get("plazo")
        dias = params.get("dias")
        if plazo is None and dias:
            plazo = {"tipo": "DIAS", "dias": dias}
        modo = params.get("modo", "OPTIMO")
        if modo not in {"OPTIMO", "ECHEQ", "CHEQUE", "MIXTO"}:
            modo = "OPTIMO"
        filtro_fiscal = params.get("filtro_fiscal", "TODOS")
        if filtro_fiscal not in {"NN", "BLANCO", "TODOS"}:
            filtro_fiscal = "TODOS"
        if not importe or importe <= 0:
            return ("text", "Pude entender el plazo pero no el importe.")
        if not params.get("fraccionado") and not plazo:
            return ("text", "¿A cuántos días querés realizar el pago?")
        if plazo and plazo.get("tipo") == "DIAS":
            plazo["dias"] = max(1, min(int(plazo.get("dias") or 0), 180))
        log_event(f"PAGO_RAPIDO inicio kind=armar_pago_optimo modo={modo} filtro_fiscal={filtro_fiscal} importe={importe} plazo={plazo} fraccionado={params.get('fraccionado')}")
        refresh_access()
        try:
            data = execute_pagos_core(
                "pagos.propuesta",
                {
                    "importe": importe,
                    "plazo": plazo,
                    "plazos": params.get("plazos"),
                    "fraccionado": bool(params.get("fraccionado")),
                    "modo": modo,
                    "filtro_fiscal": filtro_fiscal,
                },
                chat_id=params.get("chat_id", ""),
                timeout_seconds=PAYMENT_TIMEOUT_SECONDS,
            )
            if data.get("fraccionado"):
                output = format_pago_rapido_fraccionado(data)
                chat_id = params.get("chat_id")
                if chat_id not in (None, ""):
                    MENU_STATES[int(chat_id)] = {
                        "pantalla": "pago_fraccionado_ranking",
                        "anterior": "esperando_datos_pago_rapido_fraccionado",
                        "ranking": payment_ranking_state_data(data),
                    }
            else:
                output = format_pago_rapido_unico(data)
        except TimeoutError:
            log_event(f"PAGO_RAPIDO timeout kind=armar_pago_optimo modo={modo} filtro_fiscal={filtro_fiscal} importe={importe} plazo={plazo}")
            return ("text", PAYMENT_TIMEOUT_MESSAGE)
        except Exception as exc:
            text = str(exc)
            if "demor" in text.lower():
                log_event(f"PAGO_RAPIDO timeout_interno kind=armar_pago_optimo modo={modo} filtro_fiscal={filtro_fiscal} importe={importe} plazo={plazo} error={exc}")
                return ("text", PAYMENT_TIMEOUT_MESSAGE)
            if "bloquear el archivo" in text.lower():
                return ("text", "No pude leer la cartera de cheques porque Access esta bloqueado. Probá de nuevo en unos minutos.")
            raise
        log_event(f"PAGO_RAPIDO fin kind=armar_pago_optimo modo={modo} filtro_fiscal={filtro_fiscal} importe={importe} plazo={plazo} fraccionado={params.get('fraccionado')}")
        return ("text", output)

    if kind == "material":
        cliente = params.get("cliente", "")
        if not cliente:
            return ("text", "Decime el cliente. Ejemplo: /material CLIENTE")
        output = run_ps(["material", cliente, "-Top", "10"], timeout=180)
        return ("text", useful_output(output, "Cliente:"))

    if kind == "estado_pdf":
        cliente = params.get("cliente", "")
        cliente_nombre = params.get("cliente_nombre") or cliente
        desde = params.get("desde")
        hasta = params.get("hasta")
        if not cliente or not desde:
            return ("text", "Ejemplo: /estado_pdf CLIENTE desde FECHA")
        suffix = f"{desde}_a_{hasta}" if hasta else desde
        result = generar_estado_cuenta_pdf(
            Request(
                capability="clientes.estado_pdf",
                parameters={
                    "cliente": cliente,
                    "modo": MODE_RANGE,
                    "desde": desde,
                    "hasta": hasta,
                    "nombre_archivo": f"estado_{safe_file_part(cliente_nombre)}_{suffix}.pdf",
                },
                user_context=UserContext(channel="telegram", channel_user_id=str(params.get("chat_id", ""))),
                channel="telegram",
            ),
            adapter=EstadoCuentaPdfPowerShellAdapter(settings=SETTINGS),
            outputs_directory=OUTPUTS,
        )
        if not result.success:
            if estado_pdf_controlled_error(result):
                return ("text", result.message or result.error.message)
            raise RuntimeError(clean_script_error(result.error.message if result.error else result.message))
        pdf = Path(result.data["file_path"])
        caption = f"Estado de cuenta: {cliente_nombre}"
        if hasta:
            caption += f" | {desde} al {hasta}"
        return ("document", pdf, caption)

    if kind == "estado_pdf_abierto":
        cliente = params.get("cliente", "")
        cliente_nombre = params.get("cliente_nombre") or cliente
        if not cliente:
            return ("text", "Decime el cliente. Ejemplo: estado de cuenta CLIENTE")
        result = generar_estado_cuenta_pdf(
            Request(
                capability="clientes.estado_pdf",
                parameters={
                    "cliente": cliente,
                    "modo": MODE_OPEN_BALANCE,
                    "nombre_archivo": f"estado_{safe_file_part(cliente_nombre)}_abierto.pdf",
                },
                user_context=UserContext(channel="telegram", channel_user_id=str(params.get("chat_id", ""))),
                channel="telegram",
            ),
            adapter=EstadoCuentaPdfPowerShellAdapter(settings=SETTINGS),
            outputs_directory=OUTPUTS,
        )
        if not result.success:
            if estado_pdf_controlled_error(result):
                return ("text", result.message or result.error.message)
            raise RuntimeError(clean_script_error(result.error.message if result.error else result.message))
        return ("document", Path(result.data["file_path"]), f"Estado de cuenta abierto: {cliente_nombre}")

    if kind == "estado_pdf_ultimo_pago":
        cliente = params.get("cliente", "")
        cliente_nombre = params.get("cliente_nombre") or cliente
        if not cliente:
            return ("text", "Ejemplo: /estado_ultimo_pago CLIENTE")
        result = generar_estado_cuenta_pdf(
            Request(
                capability="clientes.estado_pdf",
                parameters={
                    "cliente": cliente,
                    "modo": ESTADO_MODE_SINCE_LAST_PAYMENT,
                    "nombre_archivo": f"estado_{safe_file_part(cliente_nombre)}_desde_ultimo_pago.pdf",
                },
                user_context=UserContext(channel="telegram", channel_user_id=str(params.get("chat_id", ""))),
                channel="telegram",
            ),
            adapter=EstadoCuentaPdfPowerShellAdapter(settings=SETTINGS),
            outputs_directory=OUTPUTS,
        )
        if not result.success:
            if estado_pdf_controlled_error(result):
                return ("text", result.message or result.error.message)
            raise RuntimeError(clean_script_error(result.error.message if result.error else result.message))
        return (
            "document",
            Path(result.data["file_path"]),
            f"Estado de cuenta desde el ultimo pago: {cliente_nombre}",
        )

    if kind == "factura_pdf":
        numero = params.get("numero", "")
        if not numero:
            return ("text", "Ejemplo: /factura_pdf FACTURA NUMERO")
        refresh_access()
        result = generar_facturas_pdf(
            Request(
                capability="clientes.facturas_pdf",
                parameters={
                    "modo": MODE_BY_NUMBER,
                    "tipo": params.get("tipo", ""),
                    "numero": numero,
                },
                user_context=UserContext(channel="telegram", channel_user_id=str(params.get("chat_id", ""))),
                channel="telegram",
            ),
            adapter=FacturasPdfPowerShellAdapter(settings=SETTINGS),
            outputs_directory=OUTPUTS,
        )
        if result.success:
            return (
                "document",
                Path(result.data["file_path"]),
                result.data.get("Caption", "Factura PDF"),
            )
        if not result.error or result.error.code not in {"archivo_no_encontrado", "respuesta_no_exitosa"}:
            raise RuntimeError(clean_script_error(result.error.message if result.error else result.message))
        text = result.data.get("Mensaje", "No encontre el PDF solicitado.")
        if result.data.get("Esperado"):
            text += "\nEsperado: " + result.data["Esperado"]
        if not params.get("tipo"):
            text += "\nProbe factura A/B, nota de credito y nota de debito con ese numero."
        return ("text", text)

    if kind == "facturas_cliente_pdf":
        cliente = params.get("cliente", "")
        desde = params.get("desde")
        hasta = params.get("hasta")
        if not cliente or not desde:
            return ("text", "Ejemplo: facturas CLIENTE_A desde FECHA hasta FECHA en pdf")
        refresh_access()
        if desde == DESDE_ULTIMO_PAGO:
            result = generar_facturas_pdf(
                Request(
                    capability="clientes.facturas_pdf",
                    parameters={
                        "modo": FACTURAS_MODE_SINCE_LAST_PAYMENT,
                        "cliente": cliente,
                        "hasta": hasta or date.today().isoformat(),
                    },
                    user_context=UserContext(channel="telegram", channel_user_id=str(params.get("chat_id", ""))),
                    channel="telegram",
                ),
                adapter=FacturasPdfPowerShellAdapter(settings=SETTINGS),
                outputs_directory=OUTPUTS,
            )
            if result.success:
                if int(result.data.get("Encontrados", 0) or 0) == 0:
                    return (
                        "text",
                        "Encontre el/los comprobantes en Access, pero no encontre el PDF en la carpeta de facturas.\n"
                        f"{result.data.get('Caption', '')}",
                    )
                return (
                    "document",
                    Path(result.data["file_path"]),
                    result.data.get("Caption", "Facturas PDF"),
                )
            legacy_errors = {
                "ultimo_pago_no_encontrado": "No encontré un último pago para ese cliente.",
                "cliente_no_encontrado": "No encontré el cliente indicado.",
                "cliente_ambiguo": "Encontré varios clientes parecidos. Indicá el cliente con más detalle.",
            }
            if result.error and result.error.code in legacy_errors:
                return ("text", legacy_errors[result.error.code])
            if result.error and result.error.code in {"sin_comprobantes", "archivo_no_encontrado", "respuesta_no_exitosa"}:
                return ("text", result.data.get("Mensaje", "No encontre facturas para ese periodo."))
            raise RuntimeError(clean_script_error(result.error.message if result.error else result.message))

        result = generar_facturas_pdf(
            Request(
                capability="clientes.facturas_pdf",
                parameters={
                    "modo": MODE_BY_PERIOD,
                    "cliente": cliente,
                    "desde": desde,
                    "hasta": hasta or date.today().isoformat(),
                },
                user_context=UserContext(channel="telegram", channel_user_id=str(params.get("chat_id", ""))),
                channel="telegram",
            ),
            adapter=FacturasPdfPowerShellAdapter(settings=SETTINGS),
            outputs_directory=OUTPUTS,
        )
        if result.success:
            if int(result.data.get("Encontrados", 0) or 0) == 0:
                return (
                    "text",
                    "Encontre el/los comprobantes en Access, pero no encontre el PDF en la carpeta de facturas.\n"
                    f"{result.data.get('Caption', '')}",
                )
            return (
                "document",
                Path(result.data["file_path"]),
                result.data.get("Caption", "Facturas PDF"),
            )
        if result.error and result.error.code in {"sin_comprobantes", "archivo_no_encontrado", "respuesta_no_exitosa"}:
            return ("text", result.data.get("Mensaje", "No encontre facturas para ese periodo."))
        raise RuntimeError(clean_script_error(result.error.message if result.error else result.message))

    if kind == "facturas_ultimas_cliente_pdf":
        cliente = params.get("cliente", "")
        cantidad = int(params.get("cantidad", 1) or 1)
        if not cliente:
            return ("text", "Ejemplo: ultimas 2 facturas de CLIENTE")
        refresh_access()
        result = generar_facturas_pdf(
            Request(
                capability="clientes.facturas_pdf",
                parameters={
                    "modo": MODE_LATEST,
                    "cliente": cliente,
                    "cantidad": cantidad,
                },
                user_context=UserContext(channel="telegram", channel_user_id=str(params.get("chat_id", ""))),
                channel="telegram",
            ),
            adapter=FacturasPdfPowerShellAdapter(settings=SETTINGS),
            outputs_directory=OUTPUTS,
        )
        if result.success:
            if int(result.data.get("Encontrados", 0) or 0) == 0:
                return (
                    "text",
                    "Encontre la factura en Access, pero no encontre el PDF en la carpeta de facturas.\n"
                    f"{result.data.get('Caption', '')}",
                )
            return (
                "document",
                Path(result.data["file_path"]),
                result.data.get("Caption", "Facturas PDF"),
            )
        if result.error and result.error.code in {"sin_comprobantes", "archivo_no_encontrado", "respuesta_no_exitosa"}:
            return ("text", result.data.get("Mensaje", "No encontre facturas para ese cliente."))
        raise RuntimeError(clean_script_error(result.error.message if result.error else result.message))

    if kind == "auditoria_mail_only":
        return (
            "text",
            "La auditoria del usuario 3 no esta habilitada por Telegram. "
            "Se genera automaticamente y se envia por mail.",
        )

    if kind == "unknown":
        return ("text", render_menu_principal(params.get("chat_id", "")))

    return ("text", "No encontre esta frase en el diccionario de consultas. Desea agregarla?")


def allowed(chat_id):
    user, data = find_telegram_user(chat_id)
    allowed_ids = CONFIG.get("allowed_chat_ids") or []
    if allowed_ids and int(chat_id) in {int(x) for x in allowed_ids}:
        return True
    if has_configured_telegram_users(data):
        return bool(user and user.get("activo", False))
    return not allowed_ids or int(chat_id) in {int(x) for x in allowed_ids}


def telegram_user(chat_id):
    user, data = find_telegram_user(chat_id)
    if user:
        return user
    return legacy_telegram_user(chat_id)


def authorize_command(chat_id, kind, params=None):
    user, data = find_telegram_user(chat_id)
    legacy_user = legacy_telegram_user(chat_id)
    legacy_role = legacy_user.get("role", "query_only")
    if legacy_role == "owner":
        return True, ""
    if has_configured_telegram_users(data):
        if not user or not user.get("activo", False):
            return False, "Usuario Telegram no autorizado o inactivo."
        role = user.get("rol", "")
        permission = command_permission(kind, params)
        if permission is None:
            return True, ""
        if permission == "gerencial":
            return (True, "") if is_gerencial(chat_id) else (False, "No tenes permiso para esta consulta.")
        allowed_permissions, denied_permissions = role_permissions(data, role)
        if permission in denied_permissions:
            return False, "Esta accion no esta permitida para tu rol."
        if permission in allowed_permissions:
            return True, ""
        return False, "No tenes permiso para esta consulta."

    role = legacy_role
    permission = command_permission(kind, params)
    if permission == "gerencial":
        return (True, "") if is_gerencial(chat_id) else (False, "No tenes permiso para esta consulta.")
    if permission in {"cheques", "caja", "auditoria", "usuarios"}:
        if role == "owner":
            return True, ""
        return False, "Esta accion esta reservada para los propietarios de la empresa."
    if kind in QUERY_COMMANDS:
        return True, ""
    if kind in OWNER_COMMANDS and role == "owner":
        return True, ""
    if role != "owner":
        return False, "Esta accion esta reservada para los propietarios de la empresa."
    return False, "Consulta reconocida"


def owner_chat_ids():
    users = CONFIG.get("telegram_users") or {}
    return [
        int(chat_id)
        for chat_id, user in users.items()
        if user.get("role") == "owner"
    ]


def admin_chat_ids():
    recipients = set(owner_chat_ids())
    data = load_telegram_users_data()
    for user in (data or {}).get("usuarios", []):
        chat_id = user.get("chat_id")
        if (
            chat_id is not None
            and user.get("activo", False)
            and user.get("rol") == "administrador"
        ):
            recipients.add(int(chat_id))
    return sorted(recipients)


def gerencial_chat_ids():
    recipients = set(owner_chat_ids())
    data = load_telegram_users_data()
    for user in (data or {}).get("usuarios", []):
        chat_id = user.get("chat_id")
        if (
            chat_id is not None
            and user.get("activo", False)
            and user.get("rol") in {"administrador", "owner"}
        ):
            recipients.add(int(chat_id))
    return sorted(recipients)


def read_cheque_alert_state():
    try:
        if CHEQUE_ALERT_STATE_PATH.exists():
            return json.loads(CHEQUE_ALERT_STATE_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    return {}


def write_cheque_alert_state(state):
    CHEQUE_ALERT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHEQUE_ALERT_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def maybe_send_cheque_alerts(bot):
    global LAST_CHEQUE_ALERT_POLL
    now_monotonic = time.monotonic()
    if now_monotonic - LAST_CHEQUE_ALERT_POLL < 300:
        return
    LAST_CHEQUE_ALERT_POLL = now_monotonic

    settings = CONFIG.get("cheque_alerts") or {}
    if not settings.get("enabled", True):
        return

    now = datetime.now()
    alert_hour = int(settings.get("hour", 8))
    warning_days = max(0, min(int(settings.get("warning_days", 3)), 30))
    if now.hour < alert_hour:
        return

    today = now.date().isoformat()
    state = read_cheque_alert_state()
    if state.get("last_checked_date") == today:
        return

    refresh_access()
    data = execute_cheques_core(
        "cheques.alertas",
        {"tipo": "TODOS", "filtro_fiscal": "TODOS", "dias": warning_days},
        timeout_seconds=SETTINGS.timeouts.default_script_seconds,
    )
    if data.get("hay_alertas"):
        recipients = owner_chat_ids()
        if not recipients:
            raise RuntimeError("No hay propietarios de Telegram configurados para alertas.")
        for chat_id in recipients:
            reply_result(bot, chat_id, ("text", data.get("texto_legacy", "")))

    write_cheque_alert_state(
        {
            "last_checked_date": today,
            "last_checked_at": now.isoformat(timespec="seconds"),
            "warning_days": warning_days,
            "had_alerts": bool(data.get("hay_alertas")),
        }
    )


def read_iva_alert_state():
    try:
        if IVA_ALERT_STATE_PATH.exists():
            return json.loads(IVA_ALERT_STATE_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    return {}


def write_iva_alert_state(state):
    IVA_ALERT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    IVA_ALERT_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def first_business_day_last_week(year, month):
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    start = last_day - timedelta(days=6)
    current = start
    while current <= last_day:
        if current.weekday() < 5:
            return current
        current += timedelta(days=1)
    return last_day


def iva_alert_message(period, data):
    return (
        "🧾 Recordatorio IVA mensual\n\n"
        f"Período: {period}\n\n"
        f"IVA ventas: {data.get('iva_ventas', '-')}\n"
        f"IVA gastos: {data.get('iva_gastos', '-')}\n"
        f"Saldo IVA: {data.get('saldo_iva', '-')}\n\n"
        "Revisar antes del cierre mensual."
    )


def maybe_send_iva_monthly_alert(bot):
    settings = CONFIG.get("iva_alerts") or {}
    if not settings.get("enabled", True):
        return

    now = datetime.now()
    alert_hour = int(settings.get("hour", 10))
    target_day = first_business_day_last_week(now.year, now.month)
    if now.date() != target_day or now.hour < alert_hour:
        return

    period = f"{now.year:04d}-{now.month:02d}"
    state = read_iva_alert_state()
    if state.get("last_period") == period:
        return

    try:
        recipients = admin_chat_ids()
        if not recipients:
            raise RuntimeError("No hay administradores de Telegram configurados para alertas de IVA.")
        data = execute_iva_core(now.year, now.month)
        message = iva_alert_message(period, data)
        for chat_id in recipients:
            reply_result(bot, chat_id, ("text", message))
        write_iva_alert_state(
            {
                "last_period": period,
                "last_sent_date": now.date().isoformat(),
                "last_sent_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                "had_error": False,
            }
        )
    except Exception as exc:
        log_event(f"IVA_ALERT error={exc}")
        print(f"Error alerta IVA: {exc}", flush=True)
        write_iva_alert_state(
            {
                **state,
                "last_period": state.get("last_period", ""),
                "last_sent_date": state.get("last_sent_date", ""),
                "last_sent_at": state.get("last_sent_at", ""),
                "last_error_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                "had_error": True,
                "error": str(exc),
            }
        )


def dashboard_gerencial_week_key(day):
    week_start = day - timedelta(days=day.weekday())
    return week_start.isoformat()


def read_dashboard_gerencial_alert_state():
    try:
        if DASHBOARD_GERENCIAL_ALERT_STATE_PATH.exists():
            return json.loads(DASHBOARD_GERENCIAL_ALERT_STATE_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    return {}


def write_dashboard_gerencial_alert_state(state):
    DASHBOARD_GERENCIAL_ALERT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_GERENCIAL_ALERT_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def maybe_send_dashboard_gerencial_weekly(bot):
    global LAST_DASHBOARD_GERENCIAL_ALERT_POLL
    now_monotonic = time.monotonic()
    if now_monotonic - LAST_DASHBOARD_GERENCIAL_ALERT_POLL < 300:
        return
    LAST_DASHBOARD_GERENCIAL_ALERT_POLL = now_monotonic

    settings = CONFIG.get("dashboard_gerencial_alerts") or {}
    if not settings.get("enabled", True):
        return

    now = datetime.now()
    send_hour = int(settings.get("hour", 10))
    week_start = now.date() - timedelta(days=now.weekday())
    scheduled_at = datetime.combine(week_start, datetime.min.time()).replace(hour=send_hour)
    if now < scheduled_at:
        return

    week_key = dashboard_gerencial_week_key(now.date())
    state = read_dashboard_gerencial_alert_state()
    if state.get("last_sent_week") == week_key:
        return

    recipients = gerencial_chat_ids()
    if not recipients:
        log_event("DASHBOARD_GERENCIAL_WEEKLY sin_destinatarios")
        write_dashboard_gerencial_alert_state(
            {
                **state,
                "week": week_key,
                "last_error_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                "error": "No hay usuarios gerenciales configurados para el envio semanal.",
            }
        )
        return

    sent_chat_ids = set()
    if state.get("week") == week_key:
        sent_chat_ids = {str(chat_id) for chat_id in state.get("sent_chat_ids", [])}
    pending_recipients = [chat_id for chat_id in recipients if str(chat_id) not in sent_chat_ids]
    if not pending_recipients:
        write_dashboard_gerencial_alert_state(
            {
                **state,
                "week": week_key,
                "last_sent_week": week_key,
                "last_sent_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                "recipients": [str(chat_id) for chat_id in recipients],
                "sent_chat_ids": sorted(sent_chat_ids),
                "had_error": False,
            }
        )
        return

    try:
        message = "📊 RESUMEN GERENCIAL SEMANAL\n\n" + handle_dashboard_gerencial()
    except Exception as exc:
        log_event(f"DASHBOARD_GERENCIAL_WEEKLY generar_resumen_error {exc}")
        write_dashboard_gerencial_alert_state(
            {
                **state,
                "week": week_key,
                "last_attempt_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                "last_error_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                "recipients": [str(item) for item in recipients],
                "sent_chat_ids": sorted(sent_chat_ids),
                "had_error": True,
                "error": str(exc),
            }
        )
        return

    for chat_id in pending_recipients:
        try:
            reply_result(bot, chat_id, ("text", message))
            sent_chat_ids.add(str(chat_id))
            write_dashboard_gerencial_alert_state(
                {
                    **state,
                    "week": week_key,
                    "last_attempt_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "recipients": [str(item) for item in recipients],
                    "sent_chat_ids": sorted(sent_chat_ids),
                    "had_error": False,
                }
            )
        except Exception as exc:
            log_event(f"DASHBOARD_GERENCIAL_WEEKLY error chat_id={chat_id} error={exc}")
            write_dashboard_gerencial_alert_state(
                {
                    **state,
                    "week": week_key,
                    "last_attempt_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "last_error_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "recipients": [str(item) for item in recipients],
                    "sent_chat_ids": sorted(sent_chat_ids),
                    "had_error": True,
                    "error": str(exc),
                }
            )

    if all(str(chat_id) in sent_chat_ids for chat_id in recipients):
        write_dashboard_gerencial_alert_state(
            {
                "week": week_key,
                "last_sent_week": week_key,
                "last_sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "recipients": [str(chat_id) for chat_id in recipients],
                "sent_chat_ids": sorted(sent_chat_ids),
                "had_error": False,
            }
        )


def reply_result(bot, chat_id, result):
    max_chars = int(CONFIG.get("max_text_chars", 3500))
    if result[0] == "text":
        text = result[1]
        log_event(f"{chat_id}: respuesta_texto {text[:180]}")
        for i in range(0, len(text), max_chars):
            bot.send_message(chat_id, text[i : i + max_chars])
    elif result[0] == "document":
        _, path, caption = result
        try:
            log_event(f"{chat_id}: respuesta_documento {path} | {caption[:180]}")
            bot.send_document(chat_id, path, caption=caption[:1000])
        except Exception as exc:
            log_event(f"{chat_id}: error_envio_documento {exc}")
            bot.send_message(chat_id, f"No pude enviar el archivo. {friendly_error(exc)}")


def reply_menu_result(bot, chat_id, menu_reply):
    if isinstance(menu_reply, tuple) and menu_reply[0] in {"execute", "parse_text"}:
        if menu_reply[0] == "parse_text":
            menu_text = str(menu_reply[1] or "").strip()
            lower = fold_accents(menu_text).lower()
            if lower.startswith("/saldo "):
                kind, params = "saldo", {"cliente": menu_text[7:].strip()}
            elif lower.startswith("saldo de "):
                kind, params = "saldo", {"cliente": menu_text[9:].strip()}
            elif lower.startswith("saldo "):
                kind, params = "saldo", {"cliente": menu_text[6:].strip()}
            elif (facturas_ultimo_pago_cliente := parse_facturas_desde_ultimo_pago(menu_text)):
                kind, params = (
                    "facturas_cliente_pdf",
                    {
                        "cliente": facturas_ultimo_pago_cliente,
                        "desde": DESDE_ULTIMO_PAGO,
                        "hasta": date.today().isoformat(),
                    },
                )
            elif (facturas_periodo := parse_facturas_periodo_cliente(menu_text)):
                if facturas_periodo.get("error"):
                    bot.send_message(chat_id, facturas_periodo["error"])
                    return
                kind, params = "facturas_cliente_pdf", facturas_periodo
            elif parse_latest_invoice_client_pattern(menu_text):
                kind, params = parse_latest_invoice_client_pattern(menu_text)
            elif re.search(
                r"\b(factura|comprobante|ft|fts|fta|ftb|fp|nc|ncs|nota de credito|nota credito|nd|nota de debito|nota debito)\b",
                lower,
            ) and re.search(r"\d", lower):
                kind, params = parse_factura_pdf_command(menu_text)
            elif (
                "resumen" in lower
                or "estado de cuenta" in lower
                or "estado de cuentas" in lower
                or "cuenta corriente" in lower
            ):
                if "ultimo pago" in lower or "último pago" in lower:
                    kind, params = "estado_pdf_ultimo_pago", {"cliente": strip_client_from_account_text(menu_text)}
                else:
                    desde, hasta = parse_account_period(menu_text)
                    cliente = strip_client_from_account_text(menu_text)
                    if not desde:
                        kind, params = "estado_pdf_abierto", {"cliente": cliente}
                    else:
                        kind, params = "estado_pdf", {"cliente": cliente, "desde": desde, "hasta": hasta}
            else:
                kind, params = parse_command(menu_text)
                if not isinstance(params, dict):
                    params = {"text": str(params)}
            params["chat_id"] = chat_id
        else:
            _, kind, params = menu_reply
            if isinstance(params, dict):
                params["chat_id"] = chat_id
        authorized, reason = authorize_command(chat_id, kind, params)
        if not authorized:
            registrar_actividad(
                chat_id=chat_id,
                modulo=modulo_actividad_para_comando(kind, params),
                accion="Acceso denegado",
                objeto=str(kind or ""),
                descripcion=reason,
                nivel="WARNING",
            )
            bot.send_message(chat_id, reason)
            return
        if kind == "unknown":
            registrar_actividad(
                chat_id=chat_id,
                modulo="Sistema",
                accion="Comando desconocido",
                objeto="Mensaje",
                descripcion="Comando desconocido desde menú",
                nivel="INFO",
            )
            bot.send_message(chat_id, activate_main_menu(chat_id))
            return
        bot.send_action(chat_id, "typing")
        prepared = prepare_client_query(chat_id, kind, params)
        if prepared[0] == "choices":
            bot.send_message(chat_id, prepared[1])
            return
        try:
            auditar_consulta(chat_id, prepared[1], prepared[2])
            result = handle_command(prepared[1], prepared[2])
            reply_result(bot, chat_id, result)
        except Exception as exc:
            registrar_actividad(
                chat_id=chat_id,
                modulo=modulo_actividad_para_comando(prepared[1], prepared[2]),
                accion="Error de consulta",
                objeto=str(prepared[1] or ""),
                descripcion=f"Error ejecutando consulta: {exc}",
                nivel="ERROR",
            )
            print(f"Error de consulta: {exc}", flush=True)
            bot.send_message(chat_id, friendly_error(exc, input_kind="text"))
        return
    reply_result(bot, chat_id, ("text", menu_reply))


def main():
    log_event("MAIN inicio")
    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock_socket.bind(("127.0.0.1", LOCK_PORT))
        lock_socket.listen(1)
        log_event(f"MAIN lock_adquirido port={LOCK_PORT}")
        if PILOT_MODE:
            BOT_PID_PATH.parent.mkdir(parents=True, exist_ok=True)
            BOT_PID_PATH.write_text(str(os.getpid()), encoding="ascii")
            atexit.register(lambda: BOT_PID_PATH.unlink(missing_ok=True))
        registrar_actividad(
            modulo="Sistema",
            accion="Inicio",
            objeto="Bot",
            descripcion="Inicio del bot",
            nivel="INFO",
            extra={"pid": os.getpid()},
        )
    except OSError:
        log_event(f"MAIN lock_ocupado port={LOCK_PORT}; salgo")
        print("El bot ya esta corriendo. Salgo para evitar instancia duplicada.")
        return

    bot = Telegram(CONFIG["telegram_bot_token"])
    try:
        me = bot.call("getMe", timeout=20)
        print(f"Bot conectado: @{me['result']['username']}")
        log_event(f"TELEGRAM getMe ok username=@{me['result']['username']}")
    except Exception as exc:
        print(f"No pude verificar getMe al iniciar; sigo intentando getUpdates: {exc}", flush=True)
        log_event(f"TELEGRAM getMe_error inicial={exc}")
    offset = None
    loop_iteration = 0
    log_event("MAIN antes_while")
    while True:
        try:
            loop_iteration += 1
            if loop_iteration == 1:
                log_event("MAIN primera_iteracion")
            if SETTINGS.environment.automatic_alerts_enabled:
                maybe_send_cheque_alerts(bot)
                maybe_send_iva_monthly_alert(bot)
                maybe_send_dashboard_gerencial_weekly(bot)
            log_event(f"TELEGRAM getUpdates_inicio offset={offset}")
            updates = bot.get_updates(offset=offset, timeout=30)
            log_event(f"TELEGRAM getUpdates_fin cantidad={len(updates.get('result', []))}")
            for update in updates.get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message") or update.get("edited_message")
                if not message:
                    continue
                chat_id = message["chat"]["id"]
                text = message.get("text") or message.get("caption") or ""
                from_user = message.get("from") or {}
                is_allowed = allowed(chat_id)
                log_event(
                    "TELEGRAM update_recibido "
                    f"update_id={update.get('update_id')} chat_id={chat_id} "
                    f"username={from_user.get('username', '')!r} autorizado={is_allowed} texto={text[:80]!r}"
                )
                if not is_allowed:
                    pending_registered = False
                    message_sent = False
                    try:
                        register_pending_telegram_user(message)
                        pending_registered = True
                    except Exception as exc:
                        log_event(f"TELEGRAM_PENDING error_registro chat_id={chat_id} error={exc}")
                        print(f"Error registrando pendiente {chat_id}: {exc}", flush=True)
                    try:
                        bot.send_message(
                            chat_id,
                            "Tu solicitud fue registrada.\n"
                            "Esperá que un administrador autorice el acceso.",
                        )
                        message_sent = True
                    except Exception as exc:
                        log_event(f"TELEGRAM_PENDING error_envio chat_id={chat_id} error={exc}")
                        print(f"Error enviando respuesta a pendiente {chat_id}: {exc}", flush=True)
                    log_event(
                        f"TELEGRAM_PENDING flujo chat_id={chat_id} "
                        f"autorizado=False pendiente_registrado={pending_registered} mensaje_enviado={message_sent}"
                    )
                    print(f"Solicitud de acceso registrada: {chat_id} enviado={message_sent}", flush=True)
                    continue
                text = message.get("text") or message.get("caption") or ""
                reset_inactive_chat_state(chat_id)
                if message.get("voice") or message.get("audio"):
                    try:
                        bot.send_action(chat_id, "typing")
                        transcript, kind, params = handle_voice(bot, message)
                        log_event(f"{chat_id}: audio_transcripto {transcript} -> {kind} {params}")
                        global_reply = consume_global_navigation(chat_id, transcript)
                        if global_reply:
                            bot.send_message(chat_id, global_reply)
                            continue
                        if int(chat_id) in MENU_STATES:
                            menu_reply = consume_menu_navigation(chat_id, transcript)
                            if menu_reply:
                                reply_menu_result(bot, chat_id, menu_reply)
                                continue
                        process_text_query(
                            bot,
                            chat_id,
                            transcript,
                            source_object="Audio",
                            unknown_description="Audio no interpretado",
                        )
                    except Exception as exc:
                        registrar_actividad(
                            chat_id=chat_id,
                            modulo="Sistema",
                            accion="Error de consulta",
                            objeto="Audio",
                            descripcion=f"Error procesando audio: {exc}",
                            nivel="ERROR",
                        )
                        error_text = friendly_error(exc)
                        print(f"Error de audio: {exc}", flush=True)
                        bot.send_message(chat_id, error_text)
                    continue
                if int(chat_id) in PENDING_RESTARTS:
                    restart_reply = consume_restart_confirmation(chat_id, text)
                    bot.send_message(chat_id, restart_reply["message"])
                    continue
                global_reply = consume_global_navigation(chat_id, text)
                if global_reply:
                    bot.send_message(chat_id, global_reply)
                    continue
                user_management_reply = consume_user_management(chat_id, text)
                if user_management_reply:
                    bot.send_message(chat_id, user_management_reply)
                    continue
                menu_reply = consume_menu_navigation(chat_id, text)
                if menu_reply:
                    reply_menu_result(bot, chat_id, menu_reply)
                    continue
                intent_add_reply = consume_intent_add(chat_id, text)
                if intent_add_reply:
                    learned_result = consume_learned_execution_reply(chat_id, intent_add_reply)
                    if learned_result:
                        reply_result(bot, chat_id, learned_result)
                    else:
                        bot.send_message(chat_id, intent_add_reply)
                    continue
                selection = consume_client_selection(chat_id, text)
                if selection:
                    if selection[0] == "error":
                        bot.send_message(chat_id, selection[1])
                        continue
                    authorized, reason = authorize_command(chat_id, selection[1], selection[2])
                    if not authorized:
                        registrar_actividad(
                            chat_id=chat_id,
                            modulo=modulo_actividad_para_comando(selection[1], selection[2]),
                            accion="Acceso denegado",
                            objeto=str(selection[1] or ""),
                            descripcion=reason,
                            nivel="WARNING",
                        )
                        bot.send_message(chat_id, reason)
                        continue
                    bot.send_action(chat_id, "typing")
                    try:
                        auditar_consulta(chat_id, selection[1], selection[2])
                        result = handle_command(selection[1], selection[2])
                        reply_result(bot, chat_id, result)
                    except Exception as exc:
                        registrar_actividad(
                            chat_id=chat_id,
                            modulo=modulo_actividad_para_comando(selection[1], selection[2]),
                            accion="Error de consulta",
                            objeto=str(selection[1] or ""),
                            descripcion=f"Error ejecutando consulta: {exc}",
                            nivel="ERROR",
                        )
                        print(f"Error de consulta: {exc}", flush=True)
                        bot.send_message(chat_id, friendly_error(exc, input_kind="text"))
                    continue
                process_text_query(bot, chat_id, text)
        except urllib.error.URLError as exc:
            print(f"Error de red Telegram: {exc}")
            log_event(f"LOOP urlerror {exc}\n{traceback.format_exc()}")
            time.sleep(5)
        except Exception as exc:
            print(f"Error: {exc}")
            log_event(f"LOOP exception {exc}\n{traceback.format_exc()}")
            time.sleep(2)


if __name__ == "__main__":
    BOT_ENVIRONMENT = SETTINGS.environment
    if not BOT_ENVIRONMENT.telegram_enabled:
        print(
            "Telegram deshabilitado por entorno de desarrollo. "
            "Bot finalizado sin iniciar polling.",
            flush=True,
        )
        raise SystemExit(0)
    if BOT_ENVIRONMENT.pilot_mode:
        pilot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        pilot_config = SETTINGS.private_config.telegram_bot_config.resolve()
        production_config = (ROOT / "telegram_bot_config.json").resolve()
        if not pilot_token:
            raise SystemExit("Modo piloto: falta TELEGRAM_BOT_TOKEN de prueba.")
        if pilot_config == production_config:
            raise SystemExit("Modo piloto: se requiere HELENA_PRIVATE_CONFIG separado de produccion.")
        try:
            production_data = json.loads(production_config.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            production_data = {}
        if pilot_token == str(production_data.get("telegram_bot_token", "")).strip():
            raise SystemExit("Modo piloto: el token de prueba no puede coincidir con produccion.")
    CONFIG = load_config()
    main()

