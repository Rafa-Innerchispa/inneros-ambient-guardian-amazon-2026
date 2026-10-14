from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from .home_assistant import HomeAssistantBridge


@dataclass(slots=True)
class MusicAssistantStatus:
    configured: bool
    reachable: bool
    integration_available: bool
    youtube_music_ready: bool
    control_enabled: bool
    players: dict[str, str]
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class MusicAssistantBridge:
    """Bounded YouTube Music playback through Home Assistant Music Assistant.

    Ambient Guardian never receives a Google password or cookie. Music Assistant
    owns the provider session; this bridge can target only explicitly allowlisted
    Music Assistant player entities.
    """

    def __init__(self, home_assistant: HomeAssistantBridge) -> None:
        self.home_assistant = home_assistant
        self.control_enabled = (
            os.getenv("AMBIENT_GUARDIAN_MUSIC_CONTROL_ENABLED", "0") == "1"
        )
        self.youtube_music_ready = (
            os.getenv("AMBIENT_GUARDIAN_YOUTUBE_MUSIC_READY", "0") == "1"
        )
        self.default_player = os.getenv(
            "AMBIENT_GUARDIAN_MUSIC_DEFAULT_PLAYER", ""
        ).strip().lower()
        self.players = self._parse_players(
            os.getenv("AMBIENT_GUARDIAN_MUSIC_PLAYERS", "")
        )

    @staticmethod
    def _parse_players(raw: str) -> dict[str, str]:
        if not raw.strip():
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("AMBIENT_GUARDIAN_MUSIC_PLAYERS must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("AMBIENT_GUARDIAN_MUSIC_PLAYERS must be an object")
        players: dict[str, str] = {}
        for alias, entity_id in payload.items():
            clean_alias = " ".join(str(alias).lower().split())
            clean_entity = str(entity_id).strip()
            if not clean_alias or not clean_entity.startswith("media_player."):
                raise ValueError("Music players must map an alias to a media_player entity")
            players[clean_alias] = clean_entity
        return players

    def _resolve_player(self, requested: str) -> tuple[str, str]:
        requested = " ".join(requested.lower().split())
        if requested in self.players:
            return requested, self.players[requested]
        for alias in sorted(self.players, key=len, reverse=True):
            if alias in requested:
                return alias, self.players[alias]
        if not requested and self.default_player in self.players:
            return self.default_player, self.players[self.default_player]
        raise ValueError("The requested music player is outside the allowlist")

    def status(self) -> MusicAssistantStatus:
        if not self.home_assistant.configured:
            return MusicAssistantStatus(
                configured=False,
                reachable=False,
                integration_available=False,
                youtube_music_ready=self.youtube_music_ready,
                control_enabled=self.control_enabled,
                players=dict(self.players),
                detail="Home Assistant is not configured.",
            )
        try:
            response = httpx.get(
                f"{self.home_assistant.url}/api/services",
                headers=self.home_assistant._headers(),
                timeout=max(self.home_assistant.timeout, 4.0),
            )
            response.raise_for_status()
            services = response.json()
            integration_available = any(
                item.get("domain") == "music_assistant" for item in services
            )
        except Exception as exc:
            return MusicAssistantStatus(
                configured=True,
                reachable=False,
                integration_available=False,
                youtube_music_ready=self.youtube_music_ready,
                control_enabled=self.control_enabled,
                players=dict(self.players),
                detail=f"Home Assistant service discovery failed: {type(exc).__name__}",
            )
        if not integration_available:
            detail = "Music Assistant is not installed in Home Assistant."
        elif not self.youtube_music_ready:
            detail = "Music Assistant is present; YouTube Music provider setup is pending."
        elif not self.players:
            detail = "YouTube Music is ready; no Music Assistant players are allowlisted."
        elif not self.control_enabled:
            detail = "YouTube Music is ready; voice playback is disabled."
        else:
            detail = "YouTube Music voice playback is ready."
        return MusicAssistantStatus(
            configured=True,
            reachable=True,
            integration_available=integration_available,
            youtube_music_ready=self.youtube_music_ready,
            control_enabled=self.control_enabled,
            players=dict(self.players),
            detail=detail,
        )

    def play(self, query: str, requested_player: str = "", *, dry_run: bool = False) -> dict[str, Any]:
        query = " ".join(query.split())
        if not query or len(query) > 200:
            raise ValueError("Music query must contain between 1 and 200 characters")
        alias, entity_id = self._resolve_player(requested_player)
        status = self.status()
        if not status.integration_available:
            raise RuntimeError("Music Assistant is not available")
        if not status.youtube_music_ready:
            raise RuntimeError("YouTube Music provider is not ready")
        if not status.control_enabled:
            raise PermissionError("Music playback is disabled")
        payload = {
            "entity_id": entity_id,
            "media_content_id": query,
            "media_content_type": "music",
        }
        if dry_run:
            return {
                "accepted": True,
                "executed": False,
                "dry_run": True,
                "query": query,
                "player_alias": alias,
                "entity_id": entity_id,
                "provider": "youtube_music_via_music_assistant",
            }
        response = httpx.post(
            f"{self.home_assistant.url}/api/services/media_player/play_media",
            headers=self.home_assistant._headers(),
            json=payload,
            timeout=max(self.home_assistant.timeout, 8.0),
        )
        response.raise_for_status()
        return {
            "accepted": True,
            "executed": True,
            "dry_run": False,
            "query": query,
            "player_alias": alias,
            "entity_id": entity_id,
            "provider": "youtube_music_via_music_assistant",
        }
