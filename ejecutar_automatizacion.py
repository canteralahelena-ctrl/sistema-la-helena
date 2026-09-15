"""Punto de entrada de una sola ejecucion para alertas automaticas.

No contiene reglas comerciales: delega en las mismas funciones que usa el bot.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import telegram_access_bot as telegram_bot


ROOT = Path(__file__).resolve().parent


def _environment_config() -> Path:
    value = os.environ.get("HELENA_ENV_CONFIG", "").strip()
    return Path(value) if value else ROOT / "config" / "environment.json"


def validate_automation_environment(path: Path | None = None) -> dict:
    config_path = path or _environment_config()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise RuntimeError("Falta config/environment.json; automatizacion cancelada.") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("config/environment.json no es JSON valido; automatizacion cancelada.") from exc

    if os.environ.get("HELENA_PILOT_MODE", "").strip() == "1":
        raise RuntimeError("Modo piloto: las automatizaciones estan deshabilitadas.")
    if data.get("environment") != "production":
        raise RuntimeError("Entorno no productivo: las automatizaciones estan deshabilitadas.")
    required = ("telegram_enabled", "automatic_alerts_enabled", "scheduled_tasks_enabled")
    disabled = [key for key in required if data.get(key) is not True]
    if disabled:
        raise RuntimeError("Automatizacion deshabilitada por configuracion: " + ", ".join(disabled))
    return data


def run(automation: str) -> None:
    validate_automation_environment()
    telegram_bot.CONFIG = telegram_bot.load_config()
    client = telegram_bot.Telegram(telegram_bot.CONFIG["telegram_bot_token"])
    if automation == "cheques":
        telegram_bot.maybe_send_cheque_alerts(client)
    elif automation == "resumen-gerencial":
        telegram_bot.maybe_send_dashboard_gerencial_weekly(client)
    else:  # argparse evita este caso; queda defensivo para uso como modulo.
        raise ValueError(f"Automatizacion desconocida: {automation}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Ejecuta una automatizacion de Sistema La Helena una sola vez.")
    parser.add_argument("automation", choices=("cheques", "resumen-gerencial"))
    args = parser.parse_args()
    try:
        run(args.automation)
    except Exception as exc:
        print(f"Automatizacion cancelada: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
