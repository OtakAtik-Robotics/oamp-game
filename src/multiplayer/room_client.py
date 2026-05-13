"""
Room client — HTTP room management + WS game state for multiplayer.

HTTP: create / join / leave / ready rooms via Go backend REST API.
WS: connect to /ws/match/{room_id} as spectator to receive
    join/score/GAME_OVER broadcasts and detect "playing" status.
"""
import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional, Callable

import websockets

from src.api_client import ServerClient

logger = logging.getLogger("room_client")

ROOM_HTTP_TIMEOUT = 5.0


class RoomClient:
    """
    Manages multiplayer room lifecycle + WS state broadcasting.

    Usage:
        rc = RoomClient(server_client, player_name)
        rc.create_room()          # → room_id or None
        rc.join_room("ABCD")       # → room_id or None
        rc.mark_ready()           # → None
        rc.leave_room()           # → None
        rc.get_rooms()            # → list[dict] or []

        rc.start_wsspectator(room_id, callback)
        rc.stop_ws()
    """

    def __init__(self, server: Optional[ServerClient], player_name: str):
        self._server = server
        self._player_name = player_name
        self._room_id: Optional[str] = None
        self._player_num: Optional[int] = None  # 1 or 2

        # WS spectator for room broadcasts
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_stop = threading.Event()
        self._ws_cb: Optional[Callable[[dict], None]] = None
        self._last_room_state: dict = {}

    # ── HTTP room management ──────────────────────────────────────────────────

    def get_rooms(self) -> list:
        """GET /api/v1/rooms — list available rooms."""
        if not self._server:
            return []
        body = self._server._get("/rooms")
        if body and body.get("status") == "success":
            return body.get("data", [])
        return []

    def create_room(self) -> Optional[str]:
        """POST /api/v1/rooms → returns room_id or None."""
        if not self._server:
            return None
        body = self._server._post(
            "/rooms",
            {"player_name": self._player_name},
        )
        if body and body.get("status") == "success":
            data = body.get("data", {})
            self._room_id = data.get("id")
            self._player_num = 1
            return self._room_id
        return None

    def join_room(self, code: str) -> Optional[str]:
        """POST /api/v1/rooms/{code}/join → returns room_id or None."""
        if not self._server:
            return None
        body = self._server._post(
            f"/rooms/{code}/join",
            {"player_name": self._player_name},
        )
        if body and body.get("status") == "success":
            data = body.get("data", {})
            self._room_id = data.get("id")
            # Determine player number from response
            p1 = data.get("player1_name", "")
            self._player_num = 1 if p1 == self._player_name else 2
            return self._room_id
        return None

    def mark_ready(self) -> bool:
        """POST /api/v1/rooms/{code}/ready → True on success."""
        if not self._server or not self._room_id:
            return False
        body = self._server._post(
            f"/rooms/{self._room_id}/ready",
            {"player_name": self._player_name},
        )
        return body is not None and body.get("status") == "success"

    def leave_room(self):
        """POST /api/v1/rooms/{code}/leave."""
        if not self._server or not self._room_id:
            return
        self._server._post(
            f"/rooms/{self._room_id}/leave",
            {"player_name": self._player_name},
        )
        self._room_id = None
        self._player_num = None

    # ── WS spectator — receive broadcast from Go backend ────────────────────

    def start_ws_spectator(self, room_id: str, callback: Callable[[dict], None]):
        """
        Connect as spectator to /ws/match/{room_id}?role=spectator.
        Calls callback(room_state_dict) on each broadcast message.
        """
        self._ws_cb = callback
        self._ws_stop = threading.Event()
        base = os.getenv("BACKEND_WS_URL", "ws://localhost:8080").rstrip("/")
        url = f"{base}/ws/match/{room_id}?role=spectator&player_id={self._player_name}"
        self._ws_url = url
        t = threading.Thread(target=self._ws_run, daemon=True, name="WS-Room")
        t.start()
        self._ws_thread = t

    def stop_ws(self):
        if self._ws_thread:
            self._ws_stop.set()
            self._ws_thread.join(timeout=3.0)
            self._ws_thread = None

    @property
    def room_id(self) -> Optional[str]:
        return self._room_id

    @property
    def player_num(self) -> Optional[int]:
        return self._player_num

    # ── internals ────────────────────────────────────────────────────────────

    def _ws_run(self):
        asyncio.new_event_loop().run_until_complete(self._ws_dispatch())

    async def _ws_dispatch(self):
        while not self._ws_stop.is_set():
            try:
                async with websockets.connect(self._ws_url) as ws:
                    logger.info("RoomClient WS connected: %s", self._ws_url)
                    while not self._ws_stop.is_set():
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            data = json.loads(msg)
                            self._last_room_state = data
                            if self._ws_cb:
                                try:
                                    self._ws_cb(data)
                                except Exception as e:
                                    logger.warning("WS callback error: %s", e)
                        except asyncio.TimeoutError:
                            pass
                        except websockets.ConnectionClosed:
                            break
            except Exception as e:
                logger.warning("RoomClient WS error: %s — retrying 3s", e)
                try:
                    await asyncio.wait_for(asyncio.sleep(3), timeout=3.0)
                except asyncio.TimeoutError:
                    pass
