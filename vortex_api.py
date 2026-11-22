"""Rate-limit aware Discord REST client used by VORTEX CLONER."""
from __future__ import annotations

import base64
import json
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from vortex_config import Settings


class DiscordError(Exception):
    """A Discord API failure with the status/code preserved."""

    def __init__(self, status: int, message: str, code: Optional[int] = None) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message
        self.code = code


class DiscordAPI:
    """Small REST wrapper: bounded retries, bucket-aware waits, no token echo."""

    def __init__(self, token: str, settings: Settings) -> None:
        self.settings = settings
        self.token = token.strip()
        self.base = settings.api_base.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": self.token,
            "User-Agent": "VortexCloner/2.0 (+https://discord.com)",
            "Accept": "application/json",
        })
        self.request_count = 0
        self.retry_count = 0

    def close(self) -> None:
        self.session.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        reason: Optional[str] = None,
    ) -> Any:
        url = self.base + path
        headers = {"Content-Type": "application/json"} if json_body is not None and files is None else {}
        if reason:
            headers["X-Audit-Log-Reason"] = reason[:512]
        attempt = 0
        while True:
            attempt += 1
            self.request_count += 1
            if self.settings.request_delay > 0:
                time.sleep(self.settings.request_delay)
            try:
                response = self.session.request(
                    method.upper(), url, json=json_body, params=params,
                    files=files, headers=headers or None,
                    timeout=self.settings.timeout,
                )
            except requests.RequestException as exc:
                if attempt >= self.settings.max_retries:
                    raise DiscordError(0, f"network failure: {type(exc).__name__}") from exc
                time.sleep(min(2 ** (attempt - 1), 8))
                continue

            if response.status_code == 429:
                self.retry_count += 1
                if attempt >= self.settings.max_retries:
                    raise DiscordError(429, "rate limit retries exhausted")
                payload = self._safe_json(response)
                if isinstance(payload, dict):
                    wait = float(payload.get("retry_after", 1.0))
                else:
                    wait = float(response.headers.get("Retry-After", "1000")) / 1000.0
                time.sleep(max(0.1, min(wait, 60.0)))
                continue

            if response.status_code >= 500 and attempt < self.settings.max_retries:
                self.retry_count += 1
                time.sleep(min(2 ** (attempt - 1), 8))
                continue

            if response.status_code == 204 or not response.content:
                return None

            payload = self._safe_json(response)
            if 200 <= response.status_code < 300:
                return payload
            if isinstance(payload, dict):
                message = str(payload.get("message", response.reason or "request failed"))
                code = payload.get("code")
                raise DiscordError(response.status_code, message, code if isinstance(code, int) else None)
            raise DiscordError(response.status_code, response.reason or "request failed")

    @staticmethod
    def _safe_json(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return None

    # ------------------------------------------------------------------ account
    def validate_token(self) -> Dict[str, Any]:
        result = self._request("GET", "/users/@me")
        if not isinstance(result, dict):
            raise DiscordError(0, "invalid account response")
        return result

    def list_guilds(self) -> List[Dict[str, Any]]:
        result = self._request("GET", "/users/@me/guilds", params={"limit": 200})
        return result if isinstance(result, list) else []

    # ------------------------------------------------------------------- reads
    def get_guild(self, guild_id: str, with_counts: bool = True) -> Dict[str, Any]:
        result = self._request(
            "GET", f"/guilds/{guild_id}",
            params={"with_counts": "true"} if with_counts else None,
        )
        return result if isinstance(result, dict) else {}

    def get_roles(self, guild_id: str) -> List[Dict[str, Any]]:
        result = self._request("GET", f"/guilds/{guild_id}/roles")
        return result if isinstance(result, list) else []

    def get_channels(self, guild_id: str) -> List[Dict[str, Any]]:
        result = self._request("GET", f"/guilds/{guild_id}/channels")
        return result if isinstance(result, list) else []

    def get_emojis(self, guild_id: str) -> List[Dict[str, Any]]:
        result = self._request("GET", f"/guilds/{guild_id}/emojis")
        return result if isinstance(result, list) else []

    def get_stickers(self, guild_id: str) -> List[Dict[str, Any]]:
        result = self._request("GET", f"/guilds/{guild_id}/stickers")
        return result if isinstance(result, list) else []

    def get_invites(self, guild_id: str) -> List[Dict[str, Any]]:
        result = self._request("GET", f"/guilds/{guild_id}/invites")
        return result if isinstance(result, list) else []

    def get_webhooks(self, guild_id: str) -> List[Dict[str, Any]]:
        result = self._request("GET", f"/guilds/{guild_id}/webhooks")
        return result if isinstance(result, list) else []

    # ------------------------------------------------------------------ writes
    def create_role(self, guild_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = self._request("POST", f"/guilds/{guild_id}/roles", json_body=payload)
        return result if isinstance(result, dict) else {}

    def edit_role_position(self, guild_id: str, role_id: str, position: int) -> None:
        self._request("PATCH", f"/guilds/{guild_id}/roles/{role_id}", json_body={"position": position})

    def delete_role(self, guild_id: str, role_id: str) -> None:
        self._request("DELETE", f"/guilds/{guild_id}/roles/{role_id}")

    def create_channel(self, guild_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = self._request("POST", f"/guilds/{guild_id}/channels", json_body=payload)
        return result if isinstance(result, dict) else {}

    def edit_channel(self, channel_id: str, payload: Dict[str, Any]) -> None:
        self._request("PATCH", f"/channels/{channel_id}", json_body=payload)

    def delete_channel(self, channel_id: str) -> None:
        self._request("DELETE", f"/channels/{channel_id}")

    def create_emoji(self, guild_id: str, name: str, image: str) -> Dict[str, Any]:
        result = self._request("POST", f"/guilds/{guild_id}/emojis", json_body={"name": name, "image": image})
        return result if isinstance(result, dict) else {}

    def delete_emoji(self, guild_id: str, emoji_id: str) -> None:
        self._request("DELETE", f"/guilds/{guild_id}/emojis/{emoji_id}")

    def create_sticker(self, guild_id: str, name: str, description: str, tags: str,
                       image: bytes, filename: str, content_type: str) -> Dict[str, Any]:
        fields = {
            "payload_json": (None, json.dumps({
                "name": name,
                "description": description[:100],
                "tags": tags[:200],
            })),
            "file": (filename, image, content_type),
        }
        result = self._request("POST", f"/guilds/{guild_id}/stickers", files=fields)
        return result if isinstance(result, dict) else {}

    def delete_sticker(self, guild_id: str, sticker_id: str) -> None:
        self._request("DELETE", f"/guilds/{guild_id}/stickers/{sticker_id}")

    def edit_guild(self, guild_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = self._request("PATCH", f"/guilds/{guild_id}", json_body=payload)
        return result if isinstance(result, dict) else {}

    def create_invite(self, channel_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        body = {"max_age": 0, "max_uses": 0, "temporary": False, "unique": True}
        if payload:
            body.update(payload)
        result = self._request("POST", f"/channels/{channel_id}/invites", json_body=body)
        return result if isinstance(result, dict) else {}

    def create_webhook(self, channel_id: str, name: str, avatar: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"name": name[:80]}
        if avatar:
            body["avatar"] = avatar
        result = self._request("POST", f"/channels/{channel_id}/webhooks", json_body=body)
        return result if isinstance(result, dict) else {}

    def delete_webhook(self, webhook_id: str) -> None:
        self._request("DELETE", f"/webhooks/{webhook_id}")

    # ------------------------------------------------------------------ assets
    def fetch_asset(self, url: str) -> Optional[Tuple[bytes, str, str]]:
        """Download a Discord asset with a hard byte ceiling.

        Returns (bytes, extension, data_uri).
        """
        if not url.startswith("https://"):
            return None
        try:
            response = self.session.get(url, timeout=self.settings.timeout, stream=True)
        except requests.RequestException:
            return None
        if response.status_code != 200:
            response.close()
            return None
        chunks: List[bytes] = []
        total = 0
        for chunk in response.iter_content(64 * 1024):
            total += len(chunk)
            if total > self.settings.max_image_bytes:
                response.close()
                return None
            chunks.append(chunk)
        response.close()
        image = b"".join(chunks)
        if not image:
            return None
        content_type = response.headers.get("Content-Type", "image/png").split(";")[0].strip().lower()
        extension = {
            "image/gif": "gif", "image/jpeg": "jpg", "image/webp": "webp",
            "image/png": "png", "application/json": "json",
        }.get(content_type, "png")
        if image[:3] == b"\x89PN":
            extension, content_type = "png", "image/png"
        elif image[:3] == b"GIF":
            extension, content_type = "gif", "image/gif"
        uri = f"data:{content_type};base64,{base64.b64encode(image).decode('ascii')}"
        return image, extension, uri
