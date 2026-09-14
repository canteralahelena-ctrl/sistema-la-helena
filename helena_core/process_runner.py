from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


PS_UTF8_SETUP = "$OutputEncoding = New-Object System.Text.UTF8Encoding $false; [Console]::OutputEncoding = $OutputEncoding"


def subprocess_utf8_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    if extra:
        env.update(extra)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_text_subprocess(command: list[str], **run_options: Any) -> subprocess.CompletedProcess[str]:
    run_options.setdefault("text", True)
    run_options.setdefault("encoding", "utf-8")
    run_options.setdefault("errors", "replace")
    run_options["env"] = subprocess_utf8_env(run_options.get("env"))
    return subprocess.run(command, **run_options)


def ps_quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def powershell_file_command(
    script_path: str | Path,
    args: list[object] | tuple[object, ...] | None = None,
    *,
    powershell_executable: str = "powershell",
) -> list[str]:
    return [
        powershell_executable,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        os.fspath(script_path),
    ] + [str(arg) for arg in list(args or [])]


def powershell_inline_command(
    script: str,
    *,
    powershell_executable: str = "powershell",
) -> list[str]:
    return [
        powershell_executable,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        f"{PS_UTF8_SETUP}; {script}",
    ]
