"""Configuration and metadata for VORTEX CLONER."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Dict

APP_NAME = "VORTEX CLONER"
MADE_BY = "@piangendoci on discord"
VERSION = "1.0.0"
DEFAULT_API_BASE = "https://discord.com/api/v10"


def app_dir() -> str:
    """Directory used for settings, backups and logs."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def settings_path() -> str:
    return os.path.join(app_dir(), "vortex_settings.json")


@dataclass
class Settings:
    api_base: str = DEFAULT_API_BASE
    request_delay: float = 0.15
    timeout: float = 20.0
    max_retries: int = 5
    cap_roles: int = 250
    cap_channels: int = 500
    cap_emojis: int = 200
    cap_stickers: int = 200
    cap_webhooks: int = 100
    cap_invites: int = 100
    max_image_bytes: int = 8 * 1024 * 1024
    max_backup_bytes: int = 64 * 1024 * 1024
    confirm_destructive: bool = True
    delete_first_default: bool = False
    copy_invites: bool = True
    copy_webhooks: bool = False
    copy_stickers: bool = True
    copy_guild_settings: bool = True
    log_file: str = "vortex.log"
    theme: str = "violet"
    language: str = "auto"
    recent_sources: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Settings":
        path = settings_path()
        if not os.path.isfile(path):
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw: Dict[str, Any] = json.load(handle)
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        known = {key: field.default for key, field in cls.__dataclass_fields__.items()}
        clean = {key: value for key, value in raw.items() if key in known}
        for key in ("cap_roles", "cap_channels", "cap_emojis", "cap_stickers",
                    "cap_webhooks", "cap_invites", "max_retries"):
            try:
                clean[key] = max(1, min(10000, int(clean.get(key, known[key]))))
            except (TypeError, ValueError):
                clean[key] = known[key]
        for key in ("request_delay", "timeout"):
            try:
                clean[key] = max(0.0, min(120.0, float(clean.get(key, known[key]))))
            except (TypeError, ValueError):
                clean[key] = known[key]
        clean["api_base"] = str(clean.get("api_base", DEFAULT_API_BASE)).rstrip("/")
        return cls(**clean)

    def save(self) -> bool:
        try:
            tmp = settings_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(asdict(self), handle, indent=2, ensure_ascii=False)
            os.replace(tmp, settings_path())
            return True
        except OSError:
            return False
