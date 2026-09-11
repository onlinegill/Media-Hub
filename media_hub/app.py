from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import re
import secrets
import socket
import sys
import tempfile
import urllib.parse
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from aiohttp import ClientSession, ClientTimeout, web

APP_VERSION = "1.0.0"
UI_PORT = 8099
PUBLIC_PORT = 8100
MEDIA_ROOT = Path("/media")
LIBRARY_ROOT = Path("/data/library")
DATA_FILE = Path("/data/media_hub.json")
WEB_ROOT = Path("/app/web")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")

HA_API = "http://supervisor/core/api"
SUPERVISOR_API = "http://supervisor"

AUDIO_EXTENSIONS = {
    ".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".oga", ".opus",
}
PLAYLIST_MIMES = {
    "audio/x-mpegurl",
    "audio/mpegurl",
    "application/x-mpegurl",
    "application/vnd.apple.mpegurl",
    "application/mpegurl",
    "audio/x-scpls",
}
DIRECT_HLS_MIMES = {
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/mpegurl",
    "audio/x-mpegurl",
}
WEEKDAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

KNOWN_AUDIO_MIMES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/aac",
    "audio/aacp",
    "audio/ogg",
    "audio/opus",
    "audio/flac",
    "audio/x-flac",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "application/ogg",
}

mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("audio/aac", ".aac")
mimetypes.add_type("audio/flac", ".flac")
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("audio/opus", ".opus")
mimetypes.add_type("audio/mp4", ".m4a")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
LOGGER = logging.getLogger("media_hub")


class HubError(Exception):
    pass


def json_response(data: Any, status: int = 200) -> web.Response:
    return web.json_response(data, status=status)


def safe_error(exc: Exception) -> str:
    text = str(exc).strip()
    return text or exc.__class__.__name__


def normalise_content_type(value: str | None) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def sniff_audio_mime(data: bytes, current: str = "") -> str:
    if current in KNOWN_AUDIO_MIMES or current in DIRECT_HLS_MIMES:
        return current

    if data.startswith(b"ID3"):
        return "audio/mpeg"
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        # MP3 and AAC ADTS both begin with a syncword. AAC commonly has F1/F9.
        if data[1] in (0xF1, 0xF9):
            return "audio/aac"
        return "audio/mpeg"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if data.startswith(b"fLaC"):
        return "audio/flac"
    if data.startswith(b"RIFF") and b"WAVE" in data[:16]:
        return "audio/wav"
    if len(data) > 12 and data[4:8] == b"ftyp":
        return "audio/mp4"
    return current


def looks_like_playlist(content_type: str, data: bytes, url: str) -> bool:
    ctype = normalise_content_type(content_type)
    lower = data.lstrip().lower()
    path = urllib.parse.urlparse(url).path.lower()
    return (
        ctype in PLAYLIST_MIMES
        or path.endswith((".m3u", ".m3u8", ".pls"))
        or lower.startswith(b"#extm3u")
        or lower.startswith(b"[playlist]")
    )


def extract_playlist_url(data: bytes, base_url: str) -> str | None:
    text = data.decode("utf-8", errors="ignore").strip()
    # PLS
    for line in text.splitlines():
        line = line.strip()
        if re.match(r"(?i)^file\d+\s*=", line):
            value = line.split("=", 1)[1].strip()
            if value:
                return urllib.parse.urljoin(base_url, value)

    # M3U / M3U8
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith(("http://", "https://")):
            return line
        return urllib.parse.urljoin(base_url, line)
    return None


class Store:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.data: dict[str, Any] = {
            "version": 2,
            "media_token": secrets.token_urlsafe(28),
            "default_output": "",
            "host_override": "",
            "radios": [],
            "schedules": [],
            "last_runs": {},
        }

    async def load(self) -> None:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)
        if DATA_FILE.exists():
            try:
                loaded = json.loads(DATA_FILE.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except Exception as exc:
                LOGGER.warning("Could not read persistent settings: %s", safe_error(exc))

        if not self.data.get("media_token"):
            self.data["media_token"] = secrets.token_urlsafe(28)
        if not isinstance(self.data.get("radios"), list):
            self.data["radios"] = []
        if not isinstance(self.data.get("schedules"), list):
            self.data["schedules"] = []
        if not isinstance(self.data.get("last_runs"), dict):
            self.data["last_runs"] = {}
        self.data["version"] = 2
        await self.save()

    async def save(self) -> None:
        async with self._lock:
            DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = DATA_FILE.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self.data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(DATA_FILE)

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "default_output": self.data.get("default_output", ""),
            "host_override": self.data.get("host_override", ""),
            "radios": [
                {
                    "id": item.get("id", ""),
                    "name": item.get("name", ""),
                    "url": item.get("url", ""),
                    "last_mime": item.get("last_mime", ""),
                }
                for item in self.data.get("radios", [])
            ],
            "schedules": self.data.get("schedules", []),
        }


class HAClient:
    def __init__(self, session: ClientSession) -> None:
        self.session = session

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
            "Content-Type": "application/json",
        }

    async def _json(self, method: str, url: str, **kwargs: Any) -> Any:
        headers = dict(self.headers)
        headers.update(kwargs.pop("headers", {}))
        async with self.session.request(method, url, headers=headers, **kwargs) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise HubError(f"Home Assistant API returned {resp.status}: {text[:240]}")
            if not text:
                return None
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text

    async def states(self) -> list[dict[str, Any]]:
        data = await self._json("GET", f"{HA_API}/states")
        return data if isinstance(data, list) else []

    async def core_config(self) -> dict[str, Any]:
        data = await self._json("GET", f"{HA_API}/config")
        return data if isinstance(data, dict) else {}

    async def call_service(self, service: str, payload: dict[str, Any]) -> Any:
        return await self._json(
            "POST",
            f"{HA_API}/services/media_player/{service}",
            json=payload,
        )

    async def supervisor_network(self) -> dict[str, Any]:
        data = await self._json("GET", f"{SUPERVISOR_API}/network/info")
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            return data["data"]
        return data if isinstance(data, dict) else {}


class MediaHub:
    def __init__(self) -> None:
        timeout = ClientTimeout(total=None, connect=10, sock_connect=10, sock_read=None)
        self.session = ClientSession(timeout=timeout)
        self.store = Store()
        self.ha = HAClient(self.session)
        self.detected_host = ""
        self.time_zone = "UTC"
        self.scheduler_task: asyncio.Task | None = None
        # Runtime-only radio playback state, keyed by the output selected in the UI.
        self.active_radio_sessions: dict[str, dict[str, str]] = {}

    async def start(self) -> None:
        await self.store.load()
        try:
            cfg = await self.ha.core_config()
            tz = str(cfg.get("time_zone") or "UTC")
            try:
                ZoneInfo(tz)
                self.time_zone = tz
            except Exception:
                self.time_zone = "UTC"
        except Exception as exc:
            LOGGER.debug("Time zone detection unavailable: %s", safe_error(exc))
        await self.refresh_host()
        self.scheduler_task = asyncio.create_task(self.scheduler_loop())

    async def close(self) -> None:
        if self.scheduler_task:
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                pass
        await self.session.close()

    async def refresh_host(self) -> str:
        # Supervisor network info is the most reliable source on HA OS/Supervised.
        try:
            info = await self.ha.supervisor_network()
            interfaces = info.get("interfaces", [])
            primary_candidates = [
                item for item in interfaces
                if item.get("primary") and item.get("enabled", True) and item.get("connected", True)
            ]
            candidates = primary_candidates or interfaces
            for item in candidates:
                ipv4 = item.get("ipv4") or {}
                raw = (
                    ipv4.get("ip_address")
                    or (ipv4.get("address") or [None])[0]
                )
                if raw:
                    self.detected_host = str(raw).split("/", 1)[0]
                    return self.detected_host
        except Exception as exc:
            LOGGER.debug("Supervisor network detection unavailable: %s", safe_error(exc))

        # Fall back to Home Assistant's configured internal URL.
        try:
            cfg = await self.ha.core_config()
            tz = str(cfg.get("time_zone") or "UTC")
            try:
                ZoneInfo(tz)
                self.time_zone = tz
            except Exception:
                self.time_zone = "UTC"
            internal = cfg.get("internal_url") or ""
            if internal:
                parsed = urllib.parse.urlparse(internal)
                if parsed.hostname:
                    self.detected_host = parsed.hostname
                    return self.detected_host
        except Exception as exc:
            LOGGER.debug("Internal URL detection unavailable: %s", safe_error(exc))

        return self.detected_host

    async def public_host(self, browser_host: str = "") -> str:
        override = str(self.store.data.get("host_override", "")).strip()
        if override:
            parsed = urllib.parse.urlparse(
                override if "://" in override else f"http://{override}"
            )
            if parsed.hostname:
                return parsed.hostname

        if not self.detected_host:
            await self.refresh_host()
        if self.detected_host:
            return self.detected_host

        # Browser hostname is a final fallback and is never persisted automatically.
        browser_host = browser_host.strip().strip("[]")
        if browser_host:
            return browser_host
        raise HubError(
            "Could not determine the local Home Assistant address. "
            "Open Media Hub settings and set the local host/IP."
        )

    async def public_base(self, browser_host: str = "") -> str:
        host = await self.public_host(browser_host)
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"http://{host}:{PUBLIC_PORT}/m/{self.store.data['media_token']}"

    async def outputs(self) -> list[dict[str, Any]]:
        states = await self.ha.states()
        state_map = {
            str(item.get("entity_id", "")): item
            for item in states
        }
        result: list[dict[str, Any]] = []
        stale_sessions: list[str] = []

        for state in states:
            entity_id = str(state.get("entity_id", ""))
            if not entity_id.startswith("media_player."):
                continue

            attrs = state.get("attributes") or {}
            name = str(attrs.get("friendly_name") or entity_id)
            device_class = str(attrs.get("device_class") or "")

            group_members = attrs.get("group_members")
            if not isinstance(group_members, list):
                group_members = []

            helper_members = attrs.get("entity_id")
            if not isinstance(helper_members, list):
                helper_members = []
            helper_members = [
                str(item)
                for item in helper_members
                if str(item).startswith("media_player.")
            ]

            speaker_like = (
                device_class == "speaker"
                or bool(group_members)
                or bool(helper_members)
                or "sonos" in entity_id.lower()
                or "sonos" in name.lower()
            )
            if not speaker_like:
                continue

            display_state = str(state.get("state", "unknown"))
            media_title = attrs.get("media_title")
            media_artist = attrs.get("media_artist")
            media_album_name = attrs.get("media_album_name")
            entity_picture = attrs.get("entity_picture")
            active_radio_id = ""

            session = self.active_radio_sessions.get(entity_id)
            if session:
                effective_id = session.get("effective_entity_id", "")
                effective_state = state_map.get(effective_id) or {}
                effective_attrs = effective_state.get("attributes") or {}

                if effective_state.get("state") == "playing":
                    display_state = "playing"
                    active_radio_id = session.get("station_id", "")
                    try:
                        radio = self.radio_by_id(active_radio_id)
                        media_title = (
                            effective_attrs.get("media_title")
                            or radio.get("name")
                            or media_title
                        )
                    except HubError:
                        media_title = (
                            effective_attrs.get("media_title")
                            or media_title
                        )

                    media_artist = (
                        effective_attrs.get("media_artist")
                        or media_artist
                    )
                    media_album_name = (
                        effective_attrs.get("media_album_name")
                        or media_album_name
                    )
                    entity_picture = (
                        effective_attrs.get("entity_picture")
                        or entity_picture
                    )
                else:
                    stale_sessions.append(entity_id)

            result.append(
                {
                    "entity_id": entity_id,
                    "name": name,
                    "state": display_state,
                    "volume": attrs.get("volume_level"),
                    "muted": attrs.get("is_volume_muted"),
                    "media_title": media_title,
                    "media_artist": media_artist,
                    "media_album_name": media_album_name,
                    "entity_picture": entity_picture,
                    "group_members": group_members,
                    "helper_members": helper_members,
                    "active_radio_id": active_radio_id,
                }
            )

        for entity_id in stale_sessions:
            self.active_radio_sessions.pop(entity_id, None)

        default_output = str(self.store.data.get("default_output", ""))
        result.sort(
            key=lambda item: (
                0 if item["entity_id"] == default_output else 1,
                0
                if (
                    len(item["group_members"]) > 1
                    or len(item["helper_members"]) > 1
                )
                else 1,
                item["name"].lower(),
            )
        )
        return result

    async def resolve_play_target(self, requested_entity_id: str) -> str:
        """Resolve helper groups to a real media_player when possible."""
        states = await self.ha.states()
        state_map = {
            str(item.get("entity_id", "")): item
            for item in states
        }

        requested = state_map.get(requested_entity_id) or {}
        attrs = requested.get("attributes") or {}
        helper_members = attrs.get("entity_id")

        if isinstance(helper_members, list):
            candidates = [
                str(item)
                for item in helper_members
                if str(item).startswith("media_player.")
                and str(item) in state_map
            ]

            if candidates:
                # Prefer an existing Sonos coordinator.
                for candidate in candidates:
                    candidate_attrs = (
                        state_map[candidate].get("attributes") or {}
                    )
                    group_members = candidate_attrs.get("group_members")
                    if (
                        isinstance(group_members, list)
                        and group_members
                        and group_members[0] == candidate
                    ):
                        return candidate

                return candidates[0]

        return requested_entity_id

    async def wait_for_playing(
        self,
        entity_id: str,
        timeout_seconds: float = 4.5,
    ) -> bool:
        """Wait for an asynchronous HA media service to really start playback."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds

        while loop.time() < deadline:
            await asyncio.sleep(0.6)
            states = await self.ha.states()

            for item in states:
                if (
                    item.get("entity_id") == entity_id
                    and item.get("state") == "playing"
                ):
                    return True

        return False

    def radio_by_id(self, station_id: str) -> dict[str, Any]:
        for item in self.store.data.get("radios", []):
            if item.get("id") == station_id:
                return item
        raise HubError("Radio station was not found.")

    async def probe_stream(self, source_url: str, max_depth: int = 4) -> dict[str, str]:
        current_url = source_url
        headers = {
            "User-Agent": "MediaHub/1.0.0",
                        "Accept": "*/*",
        }

        for _ in range(max_depth):
            timeout = ClientTimeout(total=12, connect=7, sock_read=7)
            try:
                async with self.session.get(
                    current_url,
                    headers=headers,
                    allow_redirects=True,
                    timeout=timeout,
                ) as resp:
                    if resp.status >= 400:
                        raise HubError(f"Stream server returned HTTP {resp.status}.")
                    first = await resp.content.read(32768)
                    ctype = normalise_content_type(resp.headers.get("Content-Type"))
                    final_url = str(resp.url)

                    if looks_like_playlist(ctype, first, final_url):
                        body = first + await resp.content.read(32768)
                        next_url = extract_playlist_url(body, final_url)
                        if not next_url:
                            # HLS media playlists are directly playable by many Sonos
                            # products; preserve the final URL rather than mis-parsing.
                            if ctype in DIRECT_HLS_MIMES or final_url.lower().endswith(".m3u8"):
                                return {
                                    "url": final_url,
                                    "mime": "application/vnd.apple.mpegurl",
                                    "mode": "direct_hls",
                                }
                            raise HubError("Playlist did not contain a playable stream URL.")
                        if next_url == current_url:
                            raise HubError("Stream playlist points back to itself.")
                        current_url = next_url
                        continue

                    detected = sniff_audio_mime(first, ctype)
                    if detected in KNOWN_AUDIO_MIMES:
                        return {
                            "url": final_url,
                            "mime": normalize_sonos_mime(detected),
                            "mode": "proxy",
                            "direct_ok": ctype.startswith("audio/") and ctype != "audio/aacp",
                        }

                    if ctype.startswith("audio/"):
                        return {
                            "url": final_url,
                            "mime": normalize_sonos_mime(ctype),
                            "mode": "proxy",
                            "direct_ok": ctype != "audio/aacp",
                        }

                    if ctype.startswith("text/html") or first.lstrip().startswith(b"<"):
                        raise HubError(
                            "This URL appears to be a web page, not a direct audio stream."
                        )

                    # Many internet radio servers incorrectly use application/octet-stream.
                    if ctype in ("", "application/octet-stream", "binary/octet-stream"):
                        guessed = sniff_audio_mime(first, "")
                        if guessed:
                            return {
                                "url": final_url,
                                "mime": normalize_sonos_mime(guessed),
                                "mode": "proxy",
                                "direct_ok": False,
                            }

                    raise HubError(
                        f"The stream returned an unsupported content type: "
                        f"{ctype or 'unknown'}."
                    )
            except asyncio.TimeoutError as exc:
                raise HubError("Timed out while checking the radio stream.") from exc

        raise HubError("Too many nested playlist redirects.")

    async def play_local(
        self,
        entity_id: str,
        source: str,
        relative_path: str,
        browser_host: str = "",
        announce: bool = False,
        volume: float | None = None,
    ) -> None:
        root = MEDIA_ROOT if source == "ha" else LIBRARY_ROOT
        file_path = resolve_path(root, relative_path)
        if not file_path.is_file():
            raise HubError("The selected media file no longer exists.")

        if volume is not None:
            await self.ha.call_service(
                "volume_set",
                {
                    "entity_id": entity_id,
                    "volume_level": min(1.0, max(0.0, float(volume))),
                },
            )
            await asyncio.sleep(0.35)

        base = await self.public_base(browser_host)
        quoted = urllib.parse.quote(relative_path.replace("\\", "/"), safe="/")
        media_url = f"{base}/media/{source}/{quoted}"
        data: dict[str, Any] = {
            "entity_id": entity_id,
            "media_content_id": media_url,
            "media_content_type": "music",
        }
        if announce:
            data["announce"] = True
        await self.ha.call_service("play_media", data)

    async def play_radio(
        self,
        station_id: str,
        entity_id: str,
        browser_host: str,
    ) -> dict[str, str]:
        station = self.radio_by_id(station_id)
        probe = await self.probe_stream(str(station.get("url", "")))
        mime = normalize_sonos_mime(probe["mime"])
        station["last_mime"] = mime
        await self.store.save()

        effective_entity_id = await self.resolve_play_target(entity_id)

        if probe["mode"] == "direct_hls":
            candidates = [(probe["url"], "direct")]
        else:
            base = await self.public_base(browser_host)
            extension = stream_extension(mime)
            proxy_url = (
                f"{base}/stream/"
                f"{urllib.parse.quote(station_id)}.{extension}"
            )

            if probe.get("direct_ok"):
                candidates = [
                    (probe["url"], "direct"),
                    (proxy_url, "proxy"),
                ]
            else:
                candidates = [
                    (proxy_url, "proxy"),
                    (probe["url"], "direct-fallback"),
                ]

        errors: list[str] = []

        for media_url, mode in candidates:
            try:
                old_session = self.active_radio_sessions.pop(entity_id, None)
                if old_session:
                    old_effective = old_session.get(
                        "effective_entity_id",
                        effective_entity_id,
                    )
                    try:
                        await self.ha.call_service(
                            "media_stop",
                            {"entity_id": old_effective},
                        )
                    except HubError:
                        pass

                await self.ha.call_service(
                    "play_media",
                    {
                        "entity_id": effective_entity_id,
                        "media_content_id": media_url,
                        "media_content_type": "music",
                    },
                )

                if await self.wait_for_playing(effective_entity_id):
                    self.active_radio_sessions[entity_id] = {
                        "station_id": station_id,
                        "effective_entity_id": effective_entity_id,
                        "mode": mode,
                    }
                    return {
                        "mime": mime,
                        "mode": mode,
                        "effective_entity_id": effective_entity_id,
                    }

                errors.append(
                    f"{mode}: Home Assistant accepted the request but "
                    f"{effective_entity_id} stayed idle"
                )

                try:
                    await self.ha.call_service(
                        "media_stop",
                        {"entity_id": effective_entity_id},
                    )
                except HubError:
                    pass

            except HubError as exc:
                errors.append(f"{mode}: {safe_error(exc)}")

        raise HubError(
            "The stream was detected as playable, but the speaker did not "
            "actually start playback. "
            + " | ".join(errors)
            + ". If proxy mode is mentioned, confirm TCP port 8100 on the "
            "Home Assistant host is reachable from the speaker network."
        )

    async def scheduler_loop(self) -> None:
        await asyncio.sleep(2)
        while True:
            try:
                await self.run_due_schedules()
            except Exception:
                LOGGER.exception("Scheduler check failed")
            await asyncio.sleep(10)

    async def run_due_schedules(self) -> None:
        zone = ZoneInfo(self.time_zone)
        now = datetime.now(zone)
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        current_time = now.strftime("%H:%M")
        weekday = WEEKDAY_CODES[now.weekday()]
        changed = False

        for schedule in list(self.store.data.get("schedules", [])):
            if not schedule.get("enabled", True):
                continue

            schedule_id = str(schedule.get("id", ""))
            if not schedule_id:
                continue

            if self.store.data.get("last_runs", {}).get(schedule_id) == minute_key:
                continue

            mode = schedule.get("mode", "weekly")
            due = False

            if mode == "once":
                due = (
                    schedule.get("date") == now.strftime("%Y-%m-%d")
                    and current_time in parse_time_list(schedule.get("times", []))
                )
            else:
                week = schedule.get("week") or {}
                due = current_time in parse_time_list(week.get(weekday, []))

            if not due:
                continue

            self.store.data.setdefault("last_runs", {})[schedule_id] = minute_key
            changed = True
            LOGGER.info("Running schedule: %s", schedule.get("name", schedule_id))
            asyncio.create_task(self.execute_schedule(schedule))

        if changed:
            await self.store.save()

    async def execute_schedule(self, schedule: dict[str, Any]) -> None:
        try:
            await self.play_local(
                str(schedule["entity_id"]),
                str(schedule.get("source") or "ha"),
                str(schedule["path"]),
                "",
                bool(schedule.get("announce", False)),
                float(schedule["volume"]) if schedule.get("volume") is not None else None,
            )
            LOGGER.info("Schedule completed: %s", schedule.get("name", schedule.get("id")))
        except Exception as exc:
            LOGGER.error(
                "Schedule failed (%s): %s",
                schedule.get("name", schedule.get("id")),
                safe_error(exc),
            )


HUB: MediaHub | None = None


def require_hub() -> MediaHub:
    assert HUB is not None
    return HUB


def normalize_sonos_mime(value: str) -> str:
    value = normalise_content_type(value)
    mapping = {
        "audio/mp3": "audio/mpeg",
        "audio/aacp": "audio/aac",
        "application/ogg": "audio/ogg",
        "audio/x-flac": "audio/flac",
        "audio/x-wav": "audio/wav",
    }
    return mapping.get(value, value or "audio/mpeg")


def stream_extension(mime: str) -> str:
    mime = normalize_sonos_mime(mime)
    return {
        "audio/mpeg": "mp3",
        "audio/aac": "aac",
        "audio/ogg": "ogg",
        "audio/opus": "opus",
        "audio/flac": "flac",
        "audio/wav": "wav",
        "audio/mp4": "m4a",
    }.get(mime, "mp3")


def parse_time_list(value: Any) -> list[str]:
    """Parse schedule times into normalized HH:MM values.

    Accepted examples:
    09:05, 9:05, 0905, 905, 17:58, 1758.
    Items can be separated by commas, semicolons, spaces, or new lines.
    """
    if isinstance(value, list):
        text = " ".join(str(item) for item in value)
    else:
        text = str(value or "")

    tokens = re.findall(
        r"(?<!\d)(?:\d{1,2}:\d{2}|\d{3,4})(?!\d)",
        text,
    )

    result: list[str] = []

    for token in tokens:
        if ":" in token:
            hour_text, minute_text = token.split(":", 1)
        elif len(token) == 3:
            hour_text, minute_text = token[0], token[1:]
        elif len(token) == 4:
            hour_text, minute_text = token[:2], token[2:]
        else:
            continue

        try:
            hour = int(hour_text)
            minute = int(minute_text)
        except ValueError:
            continue

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            continue

        normalized = f"{hour:02d}:{minute:02d}"
        if normalized not in result:
            result.append(normalized)

    return sorted(result)


def safe_filename(name: str) -> str:
    name = Path(name).name.strip()
    name = re.sub(r"[^A-Za-z0-9._()\- +\[\]]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:180]


def resolve_path(root: Path, relative: str) -> Path:
    resolved_root = root.resolve()
    relative = relative.strip().replace("\\", "/").lstrip("/")
    candidate = (resolved_root / relative).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise HubError("Invalid media path.") from exc
    return candidate


def list_media(root: Path, relative: str) -> list[dict[str, Any]]:
    path = resolve_path(root, relative)
    if not path.exists() or not path.is_dir():
        raise HubError("Folder not found.")

    items: list[dict[str, Any]] = []
    for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if child.name.startswith("."):
            continue
        rel = child.relative_to(root).as_posix()
        if child.is_dir():
            items.append({"name": child.name, "path": rel, "type": "folder"})
            continue
        if child.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        try:
            size = child.stat().st_size
        except OSError:
            size = 0
        items.append({
            "name": child.name,
            "path": rel,
            "type": "audio",
            "size": size,
            "size_text": friendly_size(size),
            "mime": mimetypes.guess_type(child.name)[0] or "audio/mpeg",
        })
    return items


def walk_audio(root: Path, source: str, limit: int = 3000) -> list[dict[str, str]]:
    root.mkdir(parents=True, exist_ok=True)
    result: list[dict[str, str]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if len(result) >= limit:
            break
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        rel = path.relative_to(root).as_posix()
        result.append({
            "source": source,
            "path": rel,
            "name": path.name,
            "label": "Home Assistant" if source == "ha" else "Media Hub Library",
        })
    return result


def friendly_size(size: int) -> str:
    value = float(size)
    units = ["B", "KB", "MB", "GB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


@web.middleware
async def api_error_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except HubError as exc:
        return json_response({"ok": False, "error": safe_error(exc)}, status=400)
    except web.HTTPException:
        raise
    except Exception as exc:
        LOGGER.exception("Unhandled request error")
        return json_response(
            {"ok": False, "error": f"Unexpected error: {safe_error(exc)}"},
            status=500,
        )


async def ui_index(request: web.Request) -> web.Response:
    return web.FileResponse(WEB_ROOT / "index.html")


async def ui_logo(request: web.Request) -> web.Response:
    return web.FileResponse("/app/logo.png")


async def ui_icon(request: web.Request) -> web.Response:
    return web.FileResponse("/app/icon.png")


async def health(request: web.Request) -> web.Response:
    return json_response({"status": "ok", "version": APP_VERSION})


async def api_bootstrap(request: web.Request) -> web.Response:
    hub = require_hub()
    outputs = await hub.outputs()
    snapshot = hub.store.public_snapshot()
    return json_response(
        {
            "ok": True,
            "version": APP_VERSION,
            "outputs": outputs,
            "settings": {
                "default_output": snapshot["default_output"],
                "host_override": snapshot["host_override"],
                "detected_host": hub.detected_host,
                "public_port": PUBLIC_PORT,
                "time_zone": hub.time_zone,
            },
            "radios": snapshot["radios"],
            "schedules": snapshot["schedules"],
        }
    )


async def api_outputs(request: web.Request) -> web.Response:
    return json_response({"ok": True, "outputs": await require_hub().outputs()})


async def api_media(request: web.Request) -> web.Response:
    source = request.query.get("source", "ha")
    relative = request.query.get("path", "")
    if source not in ("ha", "library"):
        raise HubError("Unknown media source.")
    root = MEDIA_ROOT if source == "ha" else LIBRARY_ROOT
    return json_response({
        "ok": True,
        "source": source,
        "path": relative,
        "items": list_media(root, relative),
    })


async def api_media_all(request: web.Request) -> web.Response:
    return json_response({
        "ok": True,
        "items": walk_audio(MEDIA_ROOT, "ha") + walk_audio(LIBRARY_ROOT, "library"),
    })


async def api_library_upload(request: web.Request) -> web.Response:
    LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)
    reader = await request.multipart()
    saved: list[dict[str, Any]] = []

    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name != "file" or not part.filename:
            continue

        name = safe_filename(part.filename)
        extension = Path(name).suffix.lower()
        if extension not in AUDIO_EXTENSIONS:
            raise HubError(f"Unsupported audio file type: {extension or 'unknown'}")

        target = LIBRARY_ROOT / name
        if target.exists():
            stem, suffix = target.stem, target.suffix
            counter = 2
            while target.exists():
                target = LIBRARY_ROOT / f"{stem} ({counter}){suffix}"
                counter += 1

        size = 0
        with target.open("wb") as handle:
            while True:
                chunk = await part.read_chunk(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > 512 * 1024 * 1024:
                    handle.close()
                    target.unlink(missing_ok=True)
                    raise HubError("Upload exceeds the 512 MB per-file limit.")
                handle.write(chunk)

        saved.append({
            "name": target.name,
            "path": target.name,
            "size": size,
            "size_text": friendly_size(size),
        })

    if not saved:
        raise HubError("No audio file was uploaded.")

    return json_response({"ok": True, "files": saved})


async def api_library_delete(request: web.Request) -> web.Response:
    path = resolve_path(LIBRARY_ROOT, request.match_info["tail"])
    if not path.is_file():
        raise HubError("Library file not found.")
    path.unlink()
    return json_response({"ok": True})


async def api_save_settings(request: web.Request) -> web.Response:
    hub = require_hub()
    payload = await request.json()
    if "default_output" in payload:
        value = str(payload.get("default_output") or "").strip()
        hub.store.data["default_output"] = value
    if "host_override" in payload:
        value = str(payload.get("host_override") or "").strip()
        # Only allow a hostname/IP, optionally entered as a URL.
        if value:
            parsed = urllib.parse.urlparse(
                value if "://" in value else f"http://{value}"
            )
            if not parsed.hostname:
                raise HubError("Enter a valid local hostname or IP address.")
            value = parsed.hostname
        hub.store.data["host_override"] = value
    await hub.store.save()
    await hub.refresh_host()
    return json_response({"ok": True, "settings": hub.store.public_snapshot()})


async def api_add_radio(request: web.Request) -> web.Response:
    hub = require_hub()
    payload = await request.json()
    name = str(payload.get("name") or "").strip()
    url = str(payload.get("url") or "").strip()
    if not name:
        raise HubError("Enter a station name.")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HubError("Enter a valid HTTP or HTTPS stream URL.")

    # Test before saving so broken web-page URLs do not become mysterious entries.
    probe = await hub.probe_stream(url)
    station = {
        "id": uuid.uuid4().hex,
        "name": name[:120],
        "url": url,
        "last_mime": probe["mime"],
    }
    hub.store.data.setdefault("radios", []).append(station)
    await hub.store.save()
    return json_response(
        {
            "ok": True,
            "station": {
                "id": station["id"],
                "name": station["name"],
                "url": station["url"],
                "last_mime": station["last_mime"],
            },
            "test": {"mime": probe["mime"], "mode": probe["mode"]},
        }
    )


async def api_update_radio(request: web.Request) -> web.Response:
    hub = require_hub()
    station_key = request.match_info["station_id"]
    station_id = station_key.split(".", 1)[0]
    station = hub.radio_by_id(station_id)
    payload = await request.json()
    name = str(payload.get("name") or "").strip()
    url = str(payload.get("url") or "").strip()
    if not name:
        raise HubError("Enter a station name.")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HubError("Enter a valid HTTP or HTTPS stream URL.")
    probe = await hub.probe_stream(url)
    station.update(
        {
            "name": name[:120],
            "url": url,
            "last_mime": probe["mime"],
        }
    )
    await hub.store.save()
    return json_response(
        {
            "ok": True,
            "station": station,
            "test": {"mime": probe["mime"], "mode": probe["mode"]},
        }
    )


async def api_delete_radio(request: web.Request) -> web.Response:
    hub = require_hub()
    station_id = request.match_info["station_id"]
    before = len(hub.store.data.get("radios", []))
    hub.store.data["radios"] = [
        item for item in hub.store.data.get("radios", [])
        if item.get("id") != station_id
    ]
    if len(hub.store.data["radios"]) == before:
        raise HubError("Radio station was not found.")
    await hub.store.save()
    return json_response({"ok": True})


async def api_test_radio(request: web.Request) -> web.Response:
    hub = require_hub()
    station_key = request.match_info["station_id"]
    station_id = station_key.split(".", 1)[0]
    station = hub.radio_by_id(station_id)
    probe = await hub.probe_stream(str(station.get("url", "")))
    station["last_mime"] = probe["mime"]
    await hub.store.save()
    return json_response(
        {
            "ok": True,
            "mime": probe["mime"],
            "mode": probe["mode"],
            "message": "Playable audio stream detected.",
        }
    )


async def api_test_url(request: web.Request) -> web.Response:
    payload = await request.json()
    url = str(payload.get("url") or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HubError("Enter a valid HTTP or HTTPS stream URL.")
    probe = await require_hub().probe_stream(url)
    return json_response(
        {
            "ok": True,
            "mime": probe["mime"],
            "mode": probe["mode"],
            "message": "Playable audio stream detected.",
        }
    )


async def api_play_local(request: web.Request) -> web.Response:
    hub = require_hub()
    payload = await request.json()
    entity_id = str(payload.get("entity_id") or "")
    source = str(payload.get("source") or "ha")
    relative_path = str(payload.get("path") or "")
    browser_host = str(payload.get("browser_host") or "")
    announce = bool(payload.get("announce", False))
    if not entity_id.startswith("media_player."):
        raise HubError("Choose a media player.")
    if source not in ("ha", "library"):
        raise HubError("Unknown media source.")
    hub.active_radio_sessions.pop(entity_id, None)
    await hub.play_local(entity_id, source, relative_path, browser_host, announce)
    return json_response({"ok": True})


async def api_play_radio(request: web.Request) -> web.Response:
    hub = require_hub()
    payload = await request.json()
    entity_id = str(payload.get("entity_id") or "")
    browser_host = str(payload.get("browser_host") or "")
    if not entity_id.startswith("media_player."):
        raise HubError("Choose a media player.")
    details = await hub.play_radio(
        request.match_info["station_id"],
        entity_id,
        browser_host,
    )
    return json_response({"ok": True, **details})


async def api_control(request: web.Request) -> web.Response:
    hub = require_hub()
    payload = await request.json()
    entity_id = str(payload.get("entity_id") or "")
    action = str(payload.get("action") or "")

    if not entity_id.startswith("media_player."):
        raise HubError("Choose a media player.")

    mapping = {
        "play": "media_play",
        "pause": "media_pause",
        "stop": "media_stop",
        "mute": "volume_mute",
    }
    if action not in mapping:
        raise HubError("Unknown playback command.")

    session = hub.active_radio_sessions.get(entity_id)
    target_entity_id = (
        session.get("effective_entity_id", entity_id)
        if session
        else entity_id
    )

    data: dict[str, Any] = {"entity_id": target_entity_id}
    if action == "mute":
        data["is_volume_muted"] = bool(payload.get("muted", True))

    await hub.ha.call_service(mapping[action], data)

    if action == "stop":
        hub.active_radio_sessions.pop(entity_id, None)

    return json_response({"ok": True})


async def api_volume(request: web.Request) -> web.Response:
    payload = await request.json()
    entity_id = str(payload.get("entity_id") or "")
    try:
        volume = float(payload.get("volume"))
    except (TypeError, ValueError) as exc:
        raise HubError("Invalid volume.") from exc
    if not entity_id.startswith("media_player."):
        raise HubError("Choose a media player.")
    volume = min(1.0, max(0.0, volume))
    await require_hub().ha.call_service(
        "volume_set",
        {"entity_id": entity_id, "volume_level": volume},
    )
    return json_response({"ok": True})


def sanitize_schedule(payload: dict[str, Any], existing_id: str | None = None) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()[:120]
    entity_id = str(payload.get("entity_id") or "").strip()
    source = str(payload.get("source") or "ha")
    path = str(payload.get("path") or "").strip()
    mode = str(payload.get("mode") or "weekly")

    if not name:
        raise HubError("Enter a schedule name.")
    if not entity_id.startswith("media_player."):
        raise HubError("Choose an output.")
    if source not in ("ha", "library"):
        raise HubError("Unknown media source.")

    root = MEDIA_ROOT if source == "ha" else LIBRARY_ROOT
    if not resolve_path(root, path).is_file():
        raise HubError("Choose a valid media file.")

    try:
        raw_volume = payload.get("volume")
        volume = None if raw_volume in (None, "", False) else min(1.0, max(0.0, float(raw_volume)))
    except (TypeError, ValueError) as exc:
        raise HubError("Invalid schedule volume.") from exc

    schedule: dict[str, Any] = {
        "id": existing_id or uuid.uuid4().hex,
        "name": name,
        "enabled": bool(payload.get("enabled", True)),
        "entity_id": entity_id,
        "source": source,
        "path": path,
        "media_name": str(payload.get("media_name") or Path(path).name)[:180],
        "announce": bool(payload.get("announce", False)),
        "volume": volume,
        "mode": mode if mode in ("weekly", "once") else "weekly",
    }

    if schedule["mode"] == "once":
        date_value = str(payload.get("date") or "")
        try:
            datetime.strptime(date_value, "%Y-%m-%d")
        except ValueError as exc:
            raise HubError("Choose a valid date.") from exc
        times = parse_time_list(payload.get("times", []))
        if not times:
            raise HubError("Add at least one time.")
        schedule["date"] = date_value
        schedule["times"] = times
    else:
        incoming = payload.get("week") or {}
        week: dict[str, list[str]] = {}
        for code in WEEKDAY_CODES:
            times = parse_time_list(incoming.get(code, []))
            if times:
                week[code] = times
        if not week:
            raise HubError("Add at least one weekday and time.")
        schedule["week"] = week

    return schedule


async def api_schedule_add(request: web.Request) -> web.Response:
    hub = require_hub()
    schedule = sanitize_schedule(await request.json())
    hub.store.data.setdefault("schedules", []).append(schedule)
    await hub.store.save()
    return json_response({"ok": True, "schedule": schedule})


async def api_schedule_update(request: web.Request) -> web.Response:
    hub = require_hub()
    schedule_id = request.match_info["schedule_id"]
    schedules = hub.store.data.setdefault("schedules", [])
    index = next((idx for idx, item in enumerate(schedules) if item.get("id") == schedule_id), None)
    if index is None:
        raise HubError("Schedule not found.")
    schedule = sanitize_schedule(await request.json(), schedule_id)
    schedules[index] = schedule
    await hub.store.save()
    return json_response({"ok": True, "schedule": schedule})


async def api_schedule_delete(request: web.Request) -> web.Response:
    hub = require_hub()
    schedule_id = request.match_info["schedule_id"]
    before = len(hub.store.data.get("schedules", []))
    hub.store.data["schedules"] = [
        item for item in hub.store.data.get("schedules", []) if item.get("id") != schedule_id
    ]
    hub.store.data.get("last_runs", {}).pop(schedule_id, None)
    if len(hub.store.data["schedules"]) == before:
        raise HubError("Schedule not found.")
    await hub.store.save()
    return json_response({"ok": True})


async def api_schedule_toggle(request: web.Request) -> web.Response:
    hub = require_hub()
    schedule_id = request.match_info["schedule_id"]
    payload = await request.json()
    for item in hub.store.data.get("schedules", []):
        if item.get("id") == schedule_id:
            item["enabled"] = bool(payload.get("enabled", True))
            await hub.store.save()
            return json_response({"ok": True, "schedule": item})
    raise HubError("Schedule not found.")


async def api_schedule_run(request: web.Request) -> web.Response:
    hub = require_hub()
    schedule_id = request.match_info["schedule_id"]
    for item in hub.store.data.get("schedules", []):
        if item.get("id") == schedule_id:
            asyncio.create_task(hub.execute_schedule(item))
            return json_response({"ok": True})
    raise HubError("Schedule not found.")


def valid_public_token(token: str) -> bool:
    hub = require_hub()
    return secrets.compare_digest(
        token,
        str(hub.store.data.get("media_token", "")),
    )


async def public_media(request: web.Request) -> web.StreamResponse:
    if not valid_public_token(request.match_info["token"]):
        raise web.HTTPNotFound()
    source = request.match_info["source"]
    if source not in ("ha", "library"):
        raise web.HTTPNotFound()
    root = MEDIA_ROOT if source == "ha" else LIBRARY_ROOT
    relative = request.match_info.get("tail", "")
    path = resolve_path(root, relative)
    if not path.is_file():
        raise web.HTTPNotFound()
    if path.suffix.lower() not in AUDIO_EXTENSIONS:
        raise web.HTTPForbidden()
    return web.FileResponse(path)


async def open_radio_upstream(
    hub: MediaHub,
    station: dict[str, Any],
    request: web.Request,
) -> tuple[Any, bytes, str]:
    current_url = str(station.get("url") or "")
    headers = {
        "User-Agent": "MediaHub/1.0.0",
                "Accept": "*/*",
    }
    if request.headers.get("Range"):
        headers["Range"] = request.headers["Range"]

    for _ in range(4):
        upstream = await hub.session.get(
            current_url,
            headers=headers,
            allow_redirects=True,
            timeout=ClientTimeout(total=None, connect=10, sock_connect=10, sock_read=None),
        )
        if upstream.status >= 400:
            status = upstream.status
            upstream.release()
            raise HubError(f"Stream server returned HTTP {status}.")
        initial = await upstream.content.read(32768)
        ctype = normalise_content_type(upstream.headers.get("Content-Type"))
        final_url = str(upstream.url)

        if looks_like_playlist(ctype, initial, final_url):
            body = initial + await upstream.content.read(32768)
            next_url = extract_playlist_url(body, final_url)
            upstream.release()
            if not next_url:
                raise HubError(
                    "This stream uses an HLS playlist that should be played directly."
                )
            current_url = next_url
            continue

        mime = sniff_audio_mime(initial, ctype)
        if not mime and ctype.startswith("audio/"):
            mime = ctype
        mime = normalize_sonos_mime(mime) if mime else mime
        if not mime:
            upstream.release()
            raise HubError(
                f"Unable to determine a playable audio type "
                f"({ctype or 'unknown'})."
            )
        return upstream, initial, mime

    raise HubError("Too many nested playlist redirects.")


async def public_stream(request: web.Request) -> web.StreamResponse:
    hub = require_hub()
    if not valid_public_token(request.match_info["token"]):
        raise web.HTTPNotFound()

    station_key = request.match_info["station_id"]
    station_id = station_key.split(".", 1)[0]
    station = hub.radio_by_id(station_id)
    upstream = None
    try:
        upstream, initial, mime = await open_radio_upstream(hub, station, request)

        out_headers = {
            "Content-Type": mime,
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Access-Control-Allow-Origin": "*",
        }
        for key in (
            "Accept-Ranges",
            "Content-Range",
            "icy-name",
            "icy-br",
        ):
            value = upstream.headers.get(key)
            if value:
                out_headers[key] = value

        # Preserve content length only if it represents the complete upstream
        # response (we will also write the bytes already read into `initial`).
        length = upstream.headers.get("Content-Length")
        if length:
            out_headers["Content-Length"] = length

        response = web.StreamResponse(status=upstream.status, headers=out_headers)
        await response.prepare(request)

        if request.method == "HEAD":
            upstream.release()
            await response.write_eof()
            return response

        if initial:
            await response.write(initial)

        try:
            async for chunk in upstream.content.iter_chunked(65536):
                await response.write(chunk)
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        finally:
            upstream.release()

        try:
            await response.write_eof()
        except (ConnectionResetError, RuntimeError):
            pass
        return response
    finally:
        if upstream is not None and not upstream.closed:
            upstream.release()


def create_ui_app() -> web.Application:
    app = web.Application(
        middlewares=[api_error_middleware],
        client_max_size=520 * 1024 * 1024,
    )
    app.router.add_get("/", ui_index)
    app.router.add_get("/logo.png", ui_logo)
    app.router.add_get("/icon.png", ui_icon)
    app.router.add_get("/health", health)

    app.router.add_get("/api/bootstrap", api_bootstrap)
    app.router.add_get("/api/outputs", api_outputs)
    app.router.add_get("/api/media", api_media)
    app.router.add_get("/api/media/all", api_media_all)
    app.router.add_post("/api/library/upload", api_library_upload)
    app.router.add_delete("/api/library/{tail:.*}", api_library_delete)
    app.router.add_post("/api/settings", api_save_settings)

    app.router.add_post("/api/radios/test-url", api_test_url)
    app.router.add_post("/api/radios", api_add_radio)
    app.router.add_put("/api/radios/{station_id}", api_update_radio)
    app.router.add_delete("/api/radios/{station_id}", api_delete_radio)
    app.router.add_post("/api/radios/{station_id}/test", api_test_radio)
    app.router.add_post("/api/radios/{station_id}/play", api_play_radio)

    app.router.add_post("/api/play/local", api_play_local)
    app.router.add_post("/api/control", api_control)
    app.router.add_post("/api/volume", api_volume)

    app.router.add_post("/api/schedules", api_schedule_add)
    app.router.add_put("/api/schedules/{schedule_id}", api_schedule_update)
    app.router.add_delete("/api/schedules/{schedule_id}", api_schedule_delete)
    app.router.add_post("/api/schedules/{schedule_id}/toggle", api_schedule_toggle)
    app.router.add_post("/api/schedules/{schedule_id}/run", api_schedule_run)
    return app


def create_public_app() -> web.Application:
    app = web.Application(middlewares=[api_error_middleware])
    app.router.add_route(
        "*",
        "/m/{token}/media/{source}/{tail:.*}",
        public_media,
    )
    app.router.add_route(
        "*",
        "/m/{token}/stream/{station_id}.{ext}",
        public_stream,
    )
    app.router.add_route(
        "*",
        "/m/{token}/stream/{station_id}",
        public_stream,
    )
    return app


async def main() -> None:
    global HUB
    HUB = MediaHub()
    await HUB.start()

    ui_runner = web.AppRunner(create_ui_app(), access_log=None)
    public_runner = web.AppRunner(create_public_app(), access_log=None)
    await ui_runner.setup()
    await public_runner.setup()

    ui_site = web.TCPSite(ui_runner, "0.0.0.0", UI_PORT)
    public_site = web.TCPSite(public_runner, "0.0.0.0", PUBLIC_PORT)

    await ui_site.start()
    await public_site.start()

    LOGGER.info("Media Hub %s is running", APP_VERSION)
    LOGGER.info("Ingress UI listening on port %s", UI_PORT)
    LOGGER.info("LAN media proxy listening on port %s", PUBLIC_PORT)
    LOGGER.info("Scheduler time zone: %s", HUB.time_zone)

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    finally:
        await ui_runner.cleanup()
        await public_runner.cleanup()
        await HUB.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
