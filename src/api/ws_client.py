"""
WebSocket client for real-time 1v1 match telemetry.

Runs a background thread hosting an async event loop.
Sends score updates at a fixed rate without blocking OpenCV.
"""
import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional

import websockets

logger = logging.getLogger("ws_client")


class MatchWSClient:
    """
    Background-thread WebSocket client.

    Usage:
        ws = MatchWSClient(room_id="room42", player_id="P001")
        ws.start()           # connects in background
        ws.update(score=3)   # thread-safe state update
        ws.stop()            # graceful close
    """

    def __init__(
        self,
        room_id: str,
        player_id: str,
        base_url: Optional[str] = None,
        tick_interval: float = 0.2,  # ~5 sends/sec
    ):
        base = base_url or os.getenv("BACKEND_WS_URL", "ws://localhost:8080")
        self._url = (
            f"{base.rstrip('/')}/ws/match/{room_id}"
            f"?role=player&player_id={player_id}"
        )
        self._player_id = player_id
        self._tick_interval = tick_interval

        # shared state (guarded by lock)
        self._lock = threading.Lock()
        self._latest: dict = {}
        self._dirty = False

        # async primitives (created in _run)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_evt: Optional[asyncio.Event] = None

        self._game_over_sent = False
        self._game_over_evt: Optional[asyncio.Event] = None

        self._thread: Optional[threading.Thread] = None

    # ── public API ────────────────────────────────────────────────────────

    def start(self):
        t = threading.Thread(target=self._run, daemon=True, name="WS-Match")
        t.start()
        self._thread = t

    def stop(self):
        if self._loop and self._stop_evt:
            self._loop.call_soon_threadsafe(self._stop_evt.set)
        if self._thread:
            self._thread.join(timeout=3.0)

    def update(self, score: int = 0, blocks_hit: int = 0):
        """Thread-safe telemetry state update. Sent on next tick."""
        with self._lock:
            self._latest = {
                "player_id": self._player_id,
                "score": score,
                "blocks_hit": blocks_hit,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._dirty = True

    @property
    def connected(self) -> bool:
        return self._loop is not None and not self._stop_evt.is_set()

    def send_game_over(self, final_score: int, blocks_hit: int):
        """Send GAME_OVER payload exactly once, then signal stop."""
        if self._game_over_sent:
            return
        self._game_over_sent = True
        with self._lock:
            self._latest = {
                "type": "GAME_OVER",
                "data": {
                    "player_id": self._player_id,
                    "final_score": final_score,
                    "blocks_hit": blocks_hit,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            }
            self._dirty = True
        # tick_loop will send the payload, then _game_over_evt breaks it
        if self._loop and self._game_over_evt:
            self._loop.call_soon_threadsafe(self._game_over_evt.set)

    # ── internals ─────────────────────────────────────────────────────────

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_evt = asyncio.Event()
        self._game_over_evt = asyncio.Event()
        try:
            self._loop.run_until_complete(self._ws_loop())
        except Exception as e:
            logger.error("WS thread crashed: %s", e)
        finally:
            self._loop.close()

    async def _ws_loop(self):
        while not self._stop_evt.is_set():
            try:
                async with websockets.connect(self._url) as ws:
                    logger.info("WS connected: %s", self._url)
                    await self._tick_loop(ws)
            except (
                websockets.ConnectionClosed,
                websockets.InvalidStatusCode,
                OSError,
            ) as e:
                logger.warning("WS disconnected (%s), retrying in 3s", e)
                try:
                    await asyncio.wait_for(
                        self._stop_evt.wait(), timeout=3.0
                    )
                except asyncio.TimeoutError:
                    pass

    async def _tick_loop(self, ws):
        while not self._stop_evt.is_set():
            payload = None
            is_game_over = False
            with self._lock:
                if self._dirty:
                    payload = self._latest.copy()
                    self._dirty = False
                    is_game_over = payload.get("type") == "GAME_OVER"

            if payload:
                try:
                    await ws.send(json.dumps(payload))
                except websockets.ConnectionClosed:
                    return

            if is_game_over:
                logger.info("GAME_OVER sent, closing WS")
                return

            try:
                await asyncio.wait_for(
                    self._stop_evt.wait(), timeout=self._tick_interval
                )
                return  # stop requested
            except asyncio.TimeoutError:
                pass  # normal tick
