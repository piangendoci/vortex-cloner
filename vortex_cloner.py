"""Clone orchestration: cleanup, roles, channels, assets and metadata."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from vortex_api import DiscordAPI, DiscordError
from vortex_config import Settings
from vortex_i18n import t

SUPPORTED_CHANNEL_TYPES = {0, 2, 4, 5, 13, 15}
TYPE_NAMES = {0: "text", 2: "voice", 4: "category", 5: "announcement", 13: "stage", 15: "forum"}


@dataclass
class CloneOptions:
    sections: Dict[str, bool] = field(default_factory=lambda: {
        "roles": True, "categories": True, "channels": True, "emojis": True,
        "stickers": True, "settings": True, "invites": True, "webhooks": True,
    })
    dry_run: bool = False
    delete_first: bool = False

    def enabled(self, name: str) -> bool:
        return bool(self.sections.get(name, False))


@dataclass
class CloneReport:
    created: Dict[str, int] = field(default_factory=dict)
    failed: List[str] = field(default_factory=list)
    invites: List[str] = field(default_factory=list)
    dry_run: bool = False
    api_requests: int = 0

    def bump(self, section: str) -> None:
        self.created[section] = self.created.get(section, 0) + 1


class Cloner:
    """Applies a snapshot to a target guild through the REST client."""

    def __init__(self, api: DiscordAPI, settings: Settings,
                 log: Optional[Callable[[str], None]] = None,
                 progress: Optional[Callable[[int, int, str], None]] = None,
                 progress_done: Optional[Callable[[], None]] = None) -> None:
        self.api = api
        self.settings = settings
        self.log = log or (lambda _message: None)
        self.progress = progress or (lambda _done, _total, _label: None)
        self.progress_done = progress_done or (lambda: None)
        self.report = CloneReport()
        self.options = CloneOptions()

    # --------------------------------------------------------------- internals
    def _run(self, label: str, func: Callable[[], Any]) -> Any:
        if self.report.dry_run:
            return None
        try:
            return func()
        except DiscordError as exc:
            self.report.failed.append(f"{label}: HTTP {exc.status} {exc.message}")
            return None
        except Exception as exc:  # one bad item must not kill the whole clone
            self.report.failed.append(f"{label}: {type(exc).__name__}: {exc}")
            return None

    def _each(self, items: List[Dict[str, Any]], label: str,
              action: Callable[[Dict[str, Any], int], None]) -> None:
        total = len(items)
        for index, item in enumerate(items, 1):
            name = str(item.get("name", item.get("id", "?")))
            action(item, index)
            self.progress(index, total, f"{label}: {name[:20]}")
        if total:
            self.progress_done()

    # ------------------------------------------------------------------ deletion
    def _delete_all(self, target_id: str, options: CloneOptions) -> None:
        channels = self.api.get_channels(target_id)[:self.settings.cap_channels]
        self._each(channels, "clearing channels", lambda item, _i: self._run(
            f"delete channel {item.get('name')}", lambda c=str(item.get("id", "")): self.api.delete_channel(c)))

        if options.enabled("emojis"):
            emojis = self.api.get_emojis(target_id)[:self.settings.cap_emojis]
            self._each(emojis, "clearing emojis", lambda item, _i: self._run(
                f"delete emoji {item.get('name')}", lambda e=str(item.get("id", "")): self.api.delete_emoji(target_id, e)))

        if options.enabled("stickers"):
            stickers = self.api.get_stickers(target_id)[:self.settings.cap_stickers]
            self._each(stickers, "clearing stickers", lambda item, _i: self._run(
                f"delete sticker {item.get('name')}", lambda s=str(item.get("id", "")): self.api.delete_sticker(target_id, s)))

        if options.enabled("webhooks"):
            webhooks = self.api.get_webhooks(target_id)[:self.settings.cap_webhooks]
            self._each(webhooks, "clearing webhooks", lambda item, _i: self._run(
                f"delete webhook {item.get('name')}", lambda w=str(item.get("id", "")): self.api.delete_webhook(w)))

        roles = [r for r in self.api.get_roles(target_id) if str(r.get("name")) != "@everyone"]
        roles = roles[:self.settings.cap_roles]
        self._each(roles, "clearing roles", lambda item, _i: self._run(
            f"delete role {item.get('name')}", lambda r=str(item.get("id", "")): self.api.delete_role(target_id, r)))

    # -------------------------------------------------------------------- roles
    def _clone_roles(self, snapshot: Dict[str, Any], target_id: str,
                     everyone_id: str, role_map: Dict[str, str]) -> None:
        roles = [r for r in snapshot.get("roles", [])[:self.settings.cap_roles]
                 if str(r.get("name")) != "@everyone"]
        roles.sort(key=lambda r: int(r.get("position", 0) or 0))
        self.log(t("log.roles", count=len(roles)))

        def create(role: Dict[str, Any], _index: int) -> None:
            payload = {
                "name": str(role.get("name", "role"))[:100],
                "permissions": str(role.get("permissions", "0")),
                "color": int(role.get("color", 0) or 0),
                "hoist": bool(role.get("hoist", False)),
                "mentionable": bool(role.get("mentionable", False)),
            }
            created = self._run(f"create role {payload['name']}",
                                lambda: self.api.create_role(target_id, payload))
            if created and created.get("id"):
                role_map[str(role.get("id"))] = str(created["id"])
                self.report.bump("roles")

        self._each(roles, "roles", create)

        positions = sorted(roles, key=lambda r: int(r.get("position", 0) or 0), reverse=True)
        for role in positions:
            new_id = role_map.get(str(role.get("id")))
            if new_id:
                self._run(f"position role {role.get('name')}", lambda i=new_id, p=int(role.get("position", 0)):
                          self.api.edit_role_position(target_id, i, p))

    # -------------------------------------------------------------- permissions
    @staticmethod
    def _translate_overwrites(overwrites: Any, role_map: Dict[str, str],
                              everyone_id: str, source_everyone_id: str) -> List[Dict[str, str]]:
        result: List[Dict[str, str]] = []
        if not isinstance(overwrites, list):
            return result
        for overwrite in overwrites[:100]:
            if not isinstance(overwrite, dict):
                continue
            if int(overwrite.get("type", 0)) != 0:
                continue  # member-specific overwrites cannot be moved across guilds
            old_id = str(overwrite.get("id", ""))
            new_id = everyone_id if old_id == source_everyone_id else role_map.get(old_id)
            if not new_id:
                continue
            result.append({
                "id": new_id,
                "type": "0",
                "allow": str(overwrite.get("allow", "0")),
                "deny": str(overwrite.get("deny", "0")),
            })
        return result

    # ----------------------------------------------------------------- channels
    def _channel_payload(self, channel: Dict[str, Any], category_map: Dict[str, str],
                         role_map: Dict[str, str], everyone_id: str,
                         source_everyone_id: str) -> Optional[Dict[str, Any]]:
        kind = int(channel.get("type", 0) or 0)
        if kind not in SUPPORTED_CHANNEL_TYPES:
            self.report.failed.append(
                f"channel {channel.get('name')}: type {kind} not supported, made as text")
            kind = 0
        payload: Dict[str, Any] = {
            "name": str(channel.get("name", "channel"))[:100],
            "type": kind,
        }
        parent = str(channel.get("parent_id") or "")
        if parent and parent in category_map:
            payload["parent_id"] = category_map[parent]
        payload["permission_overwrites"] = self._translate_overwrites(
            channel.get("permission_overwrites"), role_map, everyone_id, source_everyone_id)
        if kind in (0, 5, 13, 15):
            topic = channel.get("topic")
            if topic:
                payload["topic"] = str(topic)[:1024]
        if kind in (0, 5, 15):
            payload["nsfw"] = bool(channel.get("nsfw", False))
            delay = int(channel.get("rate_limit_per_user", 0) or 0)
            payload["rate_limit_per_user"] = max(0, min(21600, delay))
        if kind in (2, 13):
            payload["bitrate"] = max(8000, min(256000, int(channel.get("bitrate", 64000) or 64000)))
            payload["user_limit"] = max(0, min(99, int(channel.get("user_limit", 0) or 0)))
        return payload

    def _clone_channels(self, snapshot: Dict[str, Any], target_id: str,
                        role_map: Dict[str, str], everyone_id: str,
                        source_everyone_id: str, category_map: Dict[str, str],
                        channel_map: Dict[str, str]) -> None:
        channels = [c for c in snapshot.get("channels", [])[:self.settings.cap_channels]
                    if isinstance(c, dict)]
        categories = sorted([c for c in channels if int(c.get("type", 0)) == 4],
                            key=lambda c: int(c.get("position", 0) or 0))
        others = [c for c in channels if int(c.get("type", 0)) != 4]
        others.sort(key=lambda c: (int(c.get("position", 0) or 0), str(c.get("name", ""))))

        if self.options.enabled("categories"):
            self.log(t("log.categories", count=len(categories)))
            for category in categories:
                payload = self._channel_payload(category, category_map, role_map,
                                                everyone_id, source_everyone_id)
                created = self._run(f"create category {category.get('name')}",
                                    lambda p=payload: self.api.create_channel(target_id, p))
                if created and created.get("id"):
                    category_map[str(category.get("id"))] = str(created["id"])
                    channel_map[str(category.get("id"))] = str(created["id"])
                    self.report.bump("categories")

        if self.options.enabled("channels"):
            self.log(t("log.channels", count=len(others)))

            def create(channel: Dict[str, Any], _index: int) -> None:
                payload = self._channel_payload(channel, category_map, role_map,
                                                everyone_id, source_everyone_id)
                created = self._run(f"create channel {channel.get('name')}",
                                    lambda p=payload: self.api.create_channel(target_id, p))
                if created and created.get("id"):
                    channel_map[str(channel.get("id"))] = str(created["id"])
                    self.report.bump("channels")

            self._each(others, "channels", create)

    # -------------------------------------------------------------------- emojis
    @staticmethod
    def _clean_emoji_name(name: str) -> str:
        clean = re.sub(r"[^a-zA-Z0-9_]", "_", name or "emoji")
        clean = clean[:32]
        return clean if len(clean) >= 2 else "emoji_" + clean

    def _clone_emojis(self, snapshot: Dict[str, Any], target_id: str) -> None:
        emojis = snapshot.get("emojis", [])[:self.settings.cap_emojis]
        self.log(t("log.emojis", count=len(emojis)))

        def create(emoji: Dict[str, Any], _index: int) -> None:
            url = emoji.get("asset_url")
            asset = self.api.fetch_asset(url) if url else None
            if not asset or not asset[2]:
                self.report.failed.append(f"emoji {emoji.get('name')}: asset download failed")
                return
            self._run(f"create emoji {emoji.get('name')}",
                      lambda: self.api.create_emoji(target_id, self._clean_emoji_name(str(emoji.get("name"))), asset[2]))
            self.report.bump("emojis")

        self._each(emojis, "emojis", create)

    # ------------------------------------------------------------------ stickers
    def _clone_stickers(self, snapshot: Dict[str, Any], target_id: str) -> None:
        stickers = snapshot.get("stickers", [])[:self.settings.cap_stickers]
        self.log(t("log.stickers", count=len(stickers)))

        def create(sticker: Dict[str, Any], _index: int) -> None:
            asset = self.api.fetch_asset(sticker.get("asset_url", "")) if sticker.get("asset_url") else None
            if not asset:
                self.report.failed.append(f"sticker {sticker.get('name')}: asset download failed")
                return
            image, extension, _uri = asset
            mime = {"png": "image/png", "gif": "image/gif", "json": "application/json"}.get(extension, "image/png")
            name = (re.sub(r"[^a-zA-Z0-9_]", "_", str(sticker.get("name", "sticker"))) or "sticker")[:30]
            if len(name) < 2:
                name = "sticker_" + name
            self._run(f"create sticker {name}", lambda: self.api.create_sticker(
                target_id, name, str(sticker.get("description", "")),
                str(sticker.get("tags", "")), image, f"{name}.{extension}", mime))
            self.report.bump("stickers")

        self._each(stickers, "stickers", create)

    # ------------------------------------------------------------------ metadata
    def _clone_settings(self, snapshot: Dict[str, Any], target_id: str) -> None:
        guild = snapshot.get("guild", {})
        payload: Dict[str, Any] = {}
        name = str(guild.get("name", ""))
        if 2 <= len(name) <= 100:
            payload["name"] = name
        features = guild.get("features", []) or []
        if "COMMUNITY" in features and guild.get("description"):
            payload["description"] = str(guild["description"])[:1000]
        if guild.get("icon_url"):
            icon = self.api.fetch_asset(guild["icon_url"])
            if icon:
                payload["icon"] = icon[2]
        if guild.get("banner_url"):
            banner = self.api.fetch_asset(guild["banner_url"])
            if banner:
                payload["banner"] = banner[2]
        if payload:
            self._run("edit guild settings", lambda: self.api.edit_guild(target_id, payload))
            self.report.bump("settings")

    def _clone_invites(self, snapshot: Dict[str, Any], channel_map: Dict[str, str]) -> None:
        invites = snapshot.get("invites", [])[:self.settings.cap_invites]
        self.log(t("log.invites", count=len(invites)))

        def create(invite: Dict[str, Any], _index: int) -> None:
            new_channel = channel_map.get(str(invite.get("channel_id", "")))
            if not new_channel:
                self.report.failed.append(f"invite {invite.get('code')}: source channel not cloned")
                return
            payload = {
                "max_age": int(invite.get("max_age", 0) or 0),
                "max_uses": int(invite.get("max_uses", 0) or 0),
                "temporary": bool(invite.get("temporary", False)),
                "unique": True,
            }
            result = self._run(f"create invite {invite.get('code')}",
                               lambda: self.api.create_invite(new_channel, payload))
            if result and result.get("code"):
                code = str(result["code"])
                self.report.invites.append(f"https://discord.gg/{code}")
                self.report.bump("invites")

        self._each(invites, "invites", create)

    def _clone_webhooks(self, snapshot: Dict[str, Any], channel_map: Dict[str, str]) -> None:
        webhooks = snapshot.get("webhooks", [])[:self.settings.cap_webhooks]
        self.log(t("log.webhooks", count=len(webhooks)))

        def create(webhook: Dict[str, Any], _index: int) -> None:
            new_channel = channel_map.get(str(webhook.get("channel_id", "")))
            if not new_channel:
                self.report.failed.append(f"webhook {webhook.get('name')}: source channel not cloned")
                return
            avatar = None
            if webhook.get("avatar"):
                url = f"https://cdn.discordapp.com/avatars/{webhook.get('id')}/{webhook['avatar']}.png?size=128"
                asset = self.api.fetch_asset(url)
                avatar = asset[2] if asset else None
            self._run(f"create webhook {webhook.get('name')}",
                      lambda: self.api.create_webhook(new_channel, str(webhook.get("name", "webhook")), avatar))
            self.report.bump("webhooks")

        self._each(webhooks, "webhooks", create)

    # -------------------------------------------------------------------- public
    def plan(self, snapshot: Dict[str, Any], target_id: str) -> Dict[str, Any]:
        guild = self.api.get_guild(target_id)
        return {
            "source": str(snapshot.get("guild", {}).get("name", "?")),
            "target": str(guild.get("name", target_id)),
            "target_id": target_id,
            "roles": len([r for r in snapshot.get("roles", []) if str(r.get("name")) != "@everyone"]),
            "categories": sum(1 for c in snapshot.get("channels", []) if int(c.get("type", 0)) == 4),
            "channels": sum(1 for c in snapshot.get("channels", []) if int(c.get("type", 0)) != 4),
            "emojis": len(snapshot.get("emojis", [])),
            "stickers": len(snapshot.get("stickers", [])),
            "invites": len(snapshot.get("invites", [])),
            "webhooks": len(snapshot.get("webhooks", [])),
        }

    def execute(self, snapshot: Dict[str, Any], target_id: str, options: CloneOptions) -> CloneReport:
        self.report = CloneReport(dry_run=options.dry_run)
        self.options = options
        role_map: Dict[str, str] = {}
        category_map: Dict[str, str] = {}
        channel_map: Dict[str, str] = {}
        roles = self.api.get_roles(target_id)
        everyone = next((str(r.get("id")) for r in roles if str(r.get("name")) == "@everyone"
                         or str(r.get("id")) == target_id), target_id)
        source_roles = snapshot.get("roles", [])
        source_everyone = next((str(r.get("id")) for r in source_roles
                                if str(r.get("name")) == "@everyone"),
                               str(snapshot.get("guild", {}).get("id", "")))

        if options.delete_first and not options.dry_run:
            self.log(t("log.cleaning"))
            self._delete_all(target_id, options)

        if options.enabled("roles"):
            self._clone_roles(snapshot, target_id, everyone, role_map)
        if options.enabled("categories") or options.enabled("channels"):
            self._clone_channels(snapshot, target_id, role_map, everyone, source_everyone,
                                 category_map, channel_map)
        if options.enabled("emojis") and not options.dry_run:
            self._clone_emojis(snapshot, target_id)
        if options.enabled("stickers") and not options.dry_run and self.settings.copy_stickers:
            self._clone_stickers(snapshot, target_id)
        if options.enabled("settings") and not options.dry_run and self.settings.copy_guild_settings:
            self._clone_settings(snapshot, target_id)
        if options.enabled("invites") and not options.dry_run and self.settings.copy_invites:
            self._clone_invites(snapshot, channel_map)
        if options.enabled("webhooks") and not options.dry_run and self.settings.copy_webhooks:
            self._clone_webhooks(snapshot, channel_map)

        self.report.api_requests = self.api.request_count
        return self.report
