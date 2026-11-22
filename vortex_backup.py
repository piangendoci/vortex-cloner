"""Snapshot capture, storage and comparison."""
from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any, Dict, List, Optional, Sequence

from vortex_api import DiscordAPI, DiscordError
from vortex_config import APP_NAME, MADE_BY, VERSION
from vortex_i18n import t

FORMAT = "vortex-backup"
SNAPSHOT_VERSION = 2

SECTIONS: Sequence[str] = (
    "roles", "categories", "channels", "emojis", "stickers",
    "settings", "invites", "webhooks",
)


def _bounded(items: Any, limit: int) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    return [item for item in items[:limit] if isinstance(item, dict)]


def _icon_url(guild_id: str, icon_hash: Optional[str], kind: str = "icons") -> Optional[str]:
    if not icon_hash:
        return None
    ext = "gif" if icon_hash.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/{kind}/{guild_id}/{icon_hash}.{ext}?size=4096"


def _emoji_url(emoji: Dict[str, Any]) -> Optional[str]:
    emoji_id = emoji.get("id")
    if not emoji_id:
        return None
    ext = "gif" if emoji.get("animated") else "png"
    return f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}?size=128"


def _sticker_url(sticker: Dict[str, Any]) -> Optional[str]:
    sticker_id = sticker.get("id")
    if not sticker_id:
        return None
    ext = {1: "png", 2: "png", 3: "json", 4: "gif"}.get(int(sticker.get("format_type", 1) or 1), "png")
    return f"https://media.discordapp.net/stickers/{sticker_id}.{ext}"


def capture(api: DiscordAPI, guild_id: str, settings: Any,
            include: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    """Read one guild into a portable snapshot. Read failures become warnings."""
    chosen = {name: True for name in SECTIONS}
    if include:
        chosen.update({key: bool(value) for key, value in include.items() if key in chosen})

    warnings: List[str] = []

    def read(label: str, func: Any, default: Any) -> Any:
        if not chosen.get(label, True):
            return default
        try:
            return func()
        except DiscordError as exc:
            warnings.append(f"{label}: HTTP {exc.status} {exc.message}")
            return default

    guild = read("settings", lambda: api.get_guild(guild_id), {}) or {}
    roles = _bounded(read("roles", lambda: api.get_roles(guild_id), []), settings.cap_roles)
    channels = _bounded(read("categories", lambda: api.get_channels(guild_id), []), settings.cap_channels)
    emojis = _bounded(read("emojis", lambda: api.get_emojis(guild_id), []), settings.cap_emojis)
    stickers = _bounded(read("stickers", lambda: api.get_stickers(guild_id), []), settings.cap_stickers)
    invites = _bounded(read("invites", lambda: api.get_invites(guild_id), []), settings.cap_invites)
    webhooks = _bounded(read("webhooks", lambda: api.get_webhooks(guild_id), []), settings.cap_webhooks)

    if not chosen.get("categories", True):
        channels = [chan for chan in channels if int(chan.get("type", 0)) != 4]
    if not chosen.get("channels", True):
        channels = [chan for chan in channels if int(chan.get("type", 0)) == 4]

    for emoji in emojis:
        emoji["asset_url"] = _emoji_url(emoji)
    for sticker in stickers:
        sticker["asset_url"] = _sticker_url(sticker)

    return {
        "format": FORMAT,
        "version": SNAPSHOT_VERSION,
        "app": APP_NAME,
        "made_by": MADE_BY,
        "generator_version": VERSION,
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "guild": {
            "id": str(guild.get("id", guild_id)),
            "name": guild.get("name", ""),
            "description": guild.get("description") or "",
            "icon_url": _icon_url(guild_id, guild.get("icon")),
            "banner_url": _icon_url(guild_id, guild.get("banner"), "banners"),
            "verification_level": guild.get("verification_level", 0),
            "features": guild.get("features", []) or [],
            "preferred_locale": guild.get("preferred_locale", ""),
            "approximate_member_count": guild.get("approximate_member_count"),
        },
        "roles": roles,
        "channels": channels,
        "emojis": emojis,
        "stickers": stickers,
        "invites": invites,
        "webhooks": webhooks,
        "warnings": warnings,
    }


def section_counts(snapshot: Dict[str, Any]) -> Dict[str, int]:
    channels = snapshot.get("channels", [])
    return {
        "roles": len(snapshot.get("roles", [])),
        "categories": sum(1 for c in channels if int(c.get("type", 0)) == 4),
        "channels": sum(1 for c in channels if int(c.get("type", 0)) != 4),
        "emojis": len(snapshot.get("emojis", [])),
        "stickers": len(snapshot.get("stickers", [])),
        "invites": len(snapshot.get("invites", [])),
        "webhooks": len(snapshot.get("webhooks", [])),
    }


def save_snapshot(snapshot: Dict[str, Any], path: str) -> bool:
    try:
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def load_snapshot(path: str, settings: Any) -> Dict[str, Any]:
    if not os.path.isfile(path):
        raise ValueError(t("backup.not_found"))
    if os.path.getsize(path) > settings.max_backup_bytes:
        raise ValueError(t("backup.too_big"))
    with open(path, "r", encoding="utf-8") as handle:
        data: Any = json.load(handle)
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError(t("backup.not_vortex"))
    if int(data.get("version", 0)) > SNAPSHOT_VERSION:
        raise ValueError(t("backup.newer"))
    for key in ("guild", "roles", "channels", "emojis", "stickers", "invites", "webhooks"):
        if key not in data:
            raise ValueError(t("backup.missing", key=key))
    return data


def diff_snapshots(left: Dict[str, Any], right: Dict[str, Any]) -> List[str]:
    """Report names present in left but absent in right."""
    lines: List[str] = []

    def missing(section: str, key: str = "name") -> None:
        source = {str(item.get(key, "")) for item in left.get(section, []) if isinstance(item, dict)}
        target = {str(item.get(key, "")) for item in right.get(section, []) if isinstance(item, dict)}
        for name in sorted(source - target):
            lines.append(f"{section[:-1] if section.endswith('s') else section}: {name}")

    for section in ("roles", "channels", "emojis", "stickers"):
        missing(section)
    left_name = str(left.get("guild", {}).get("name", ""))
    right_name = str(right.get("guild", {}).get("name", ""))
    if left_name and left_name != right_name:
        lines.append(f"name: {left_name} -> {right_name}")
    return lines
