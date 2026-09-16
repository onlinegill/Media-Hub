"""Saved playlists and runtime queues. No browser is needed for advancement."""
from __future__ import annotations

import asyncio
import copy
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger("media_hub")


class PlaylistMixin:
    def init_playlists(self):
        self.playback_lock = asyncio.Lock()
        self.queues = {}
        self.playlist_task = None

    def cancel_queue(self, entity_id, target):
        for key, queue in list(self.queues.items()):
            if key in (entity_id, target) or queue["entity_id"] in (entity_id, target):
                del self.queues[key]

    async def play_local(self, entity_id, source, relative_path, browser_host="", announce=False, volume=None):
        async with self.playback_lock:
            target = await self.resolve_play_target(entity_id)
            self.cancel_queue(entity_id, target)
            return await self._play_local(target, source, relative_path, browser_host, announce, volume)

    async def play_radio(self, station_id, entity_id, browser_host):
        async with self.playback_lock:
            target = await self.resolve_play_target(entity_id)
            self.cancel_queue(entity_id, target)
            return await self._play_radio(station_id, entity_id, browser_host)

    async def start_playlist(self, playlist, entity_id, browser_host="", volume=None, stop_at=None):
        async with self.playback_lock:
            target = await self.resolve_play_target(entity_id)
            self.cancel_queue(entity_id, target)
            queue = {
                "playlist_id": playlist["id"], "name": playlist["name"],
                "tracks": copy.deepcopy(playlist["tracks"]), "index": 0,
                "repeat": playlist.get("repeat", False), "entity_id": entity_id,
                "target": target, "browser_host": browser_host,
                "stop_at": stop_at, "paused": False,
            }
            await self.play_queue_track(queue, volume)
            self.queues[target] = queue

    async def play_queue_track(self, queue, volume=None):
        track = queue["tracks"][queue["index"]]
        queue["url"] = await self._play_local(
            queue["target"], track["source"], track["path"],
            queue["browser_host"], False, volume,
        )
        queue.update(seen_playing=False, idle_count=0,
                     started=asyncio.get_running_loop().time())

    async def advance_queue(self, queue):
        queue["index"] += 1
        if queue["index"] >= len(queue["tracks"]):
            if not queue["repeat"]:
                self.queues.pop(queue["target"], None)
                return
            queue["index"] = 0
        await self.play_queue_track(queue)

    async def playlist_tick(self):
        async with self.playback_lock:
            if not self.queues:
                return
            states = {s["entity_id"]: s for s in await self.ha.states()}
            now = datetime.now(ZoneInfo(self.time_zone))
            for target, queue in list(self.queues.items()):
                try:
                    state = states.get(target, {})
                    status = state.get("state", "unavailable")
                    content = str((state.get("attributes") or {}).get("media_content_id") or "")
                    # A new source started outside Media Hub. Relinquish ownership.
                    if queue["seen_playing"] and status in ("playing", "paused") and content and content != queue["url"]:
                        self.queues.pop(target, None)
                        continue
                    if queue["stop_at"] and now >= queue["stop_at"]:
                        try:
                            await self.ha.call_service("media_stop", {"entity_id": target})
                        except Exception:
                            # Keep the deadline and retry; never advance after it.
                            LOGGER.exception("Could not stop playlist %s; retrying", queue["name"])
                            continue
                        self.queues.pop(target, None)
                        continue
                    if status in ("off", "unavailable", "unknown"):
                        self.queues.pop(target, None)
                        continue
                    if queue["paused"] or status == "paused":
                        queue["idle_count"] = 0
                        continue
                    if status == "playing" and (not content or content == queue["url"]):
                        queue["seen_playing"] = True
                        queue["idle_count"] = 0
                    elif status == "idle" and queue["seen_playing"]:
                        queue["idle_count"] += 1
                        if queue["idle_count"] >= 2:
                            await self.advance_queue(queue)
                    else:
                        queue["idle_count"] = 0
                    if not queue["seen_playing"] and asyncio.get_running_loop().time() - queue["started"] > 60:
                        LOGGER.warning("Playlist %s stopped: playback was not confirmed", queue["name"])
                        self.queues.pop(target, None)
                except Exception:
                    self.queues.pop(target, None)
                    LOGGER.exception("Playlist %s stopped after a playback error", queue["name"])

    async def playlist_loop(self):
        while True:
            try:
                await self.playlist_tick()
            except Exception:
                LOGGER.exception("Playlist monitor failed")
            await asyncio.sleep(1)

    async def playlist_control(self, entity_id, action):
        """Called with playback_lock held. Return whether the queue handled it."""
        target = await self.resolve_play_target(entity_id)
        queue = self.queues.get(target)
        if queue is None:
            queue = next((q for q in self.queues.values() if q["entity_id"] == entity_id), None)
        if queue is None:
            return False
        target = queue["target"]
        if action == "stop":
            self.queues.pop(target, None)
            await self.ha.call_service("media_stop", {"entity_id": target})
        elif action == "next":
            if queue["index"] == len(queue["tracks"]) - 1 and not queue["repeat"]:
                await self.ha.call_service("media_stop", {"entity_id": target})
            queue["paused"] = False
            try:
                await self.advance_queue(queue)
            except Exception:
                self.queues.pop(target, None)
                raise
        elif action in ("pause", "play"):
            await self.ha.call_service("media_pause" if action == "pause" else "media_play", {"entity_id": target})
            queue["paused"] = action == "pause"
        else:
            return False
        return True

    def queue_snapshot(self):
        return [{"entity_id": q["entity_id"], "target": q["target"],
                 "playlist_id": q["playlist_id"], "name": q["name"],
                 "track": q["index"] + 1, "total": len(q["tracks"]),
                 "paused": q["paused"],
                 "stop_at": q["stop_at"].isoformat() if q["stop_at"] else None}
                for q in self.queues.values()]
