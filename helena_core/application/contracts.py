from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class UserContext:
    user_id: str = ""
    display_name: str = ""
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    channel: str = ""
    channel_user_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Request:
    capability: str
    parameters: dict[str, Any] = field(default_factory=dict)
    user_context: UserContext = field(default_factory=UserContext)
    channel: str = ""
    request_id: str = field(default_factory=lambda: str(uuid4()))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ErrorInfo:
    code: str
    message: str
    technical_detail: str = ""
    recoverable: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Result:
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    error: ErrorInfo | None = None
