import json
import logging
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("api_client")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BUFFER_DB = Path(os.getenv("OAMP_BUFFER_DB", "local_buffer.db"))
_SYNC_INTERVAL = 15  # seconds between sync attempts
_MAX_UID_LEN = 64
_UID_PATTERN = re.compile(r"^[A-Za-z0-9\-_:]+$")
_VALID_BUFFER_TABLES = frozenset(("pending_sessions",))

_REQUIRED_SESSION_FIELDS = (
    "participant_id", "game_score", "blocks_hit",
    "hand_tracking_status", "play_duration", "timestamp",
)


def _init_db(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_sessions (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            payload   TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    db.commit()


def _sanitize_uid(uid: str) -> Optional[str]:
    """Strip + validate RFID UID. Reject path traversal / injection."""
    uid = uid.strip()[:_MAX_UID_LEN]
    if not uid or not _UID_PATTERN.match(uid):
        logger.warning("Rejected invalid UID: %r", uid)
        return None
    return uid


def _validate_session_data(session: dict) -> list[str]:
    """Return list of missing required fields (empty = valid)."""
    return [f for f in _REQUIRED_SESSION_FIELDS if f not in session]


# ---------------------------------------------------------------------------
# ServerClient
# ---------------------------------------------------------------------------

class ServerClient:
    """
    HTTP client for the OAMP Go backend server.

    Offline-first: failed submissions buffered to SQLite.
    Background sync daemon retries every 15 s.

    Usage:
        client = ServerClient()
        child = client.authenticate("RFID-ABC123")
        payload = client.build_session_payload(
            participant_id=child["id"],
            game_data={...},
        )
        session_id = client.submit_game_session(payload)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 5.0,
    ):
        self.base_url = (
            base_url
            or os.getenv("BACKEND_API_URL", "http://localhost:8080/api/v1")
        ).rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.mount(
            "https://",
            requests.adapters.HTTPAdapter(pool_maxsize=4, pool_block=True),
        )
        self._session.mount(
            "http://",
            requests.adapters.HTTPAdapter(pool_maxsize=4, pool_block=True),
        )
        self._online = False
        self._stop_sync = threading.Event()
        self._db_lock = threading.Lock()

        # Offline buffer
        self._db = sqlite3.connect(str(_BUFFER_DB), check_same_thread=False)
        _init_db(self._db)

        # Background sync thread
        self._sync_thread = threading.Thread(
            target=self._sync_loop, daemon=True
        )
        self._sync_thread.start()

        logger.info("ServerClient initialized — server: %s", self.base_url)

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> Optional[dict]:
        """Shared request handler with retry + proper online tracking."""
        kwargs.setdefault("timeout", self.timeout)
        url = f"{self.base_url}{path}"

        for attempt in range(3):
            try:
                r = self._session.request(method, url, **kwargs)
                self._online = True

                if r.status_code >= 500:
                    logger.warning(
                        "%s %s → %d (attempt %d)",
                        method, path, r.status_code, attempt + 1,
                    )
                    if attempt < 2:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    return None  # retries exhausted

                r.raise_for_status()

                # Guard: non-JSON body
                try:
                    return r.json()
                except (ValueError, TypeError) as e:
                    logger.error("Non-JSON response from %s: %s", path, e)
                    return None

            except requests.ConnectionError:
                self._online = False
                logger.error("Server unreachable: %s %s", method, path)
                break
            except requests.Timeout:
                self._online = False
                logger.error("Timeout: %s %s", method, path)
                break
            except requests.HTTPError:
                self._online = True
                raise
            except requests.RequestException as e:
                self._online = False
                logger.error("%s %s error: %s", method, path, e)
                break

        return None

    def _get(self, path: str) -> Optional[dict]:
        try:
            return self._request("GET", path)
        except requests.HTTPError:
            return None

    def _post(self, path: str, data: dict) -> Optional[dict]:
        try:
            return self._request("POST", path, json=data)
        except requests.HTTPError:
            return None

    # ------------------------------------------------------------------
    # Online status
    # ------------------------------------------------------------------

    @property
    def is_online(self) -> bool:
        return self._online

    def health_check(self) -> bool:
        """GET /health — returns True if server + DB healthy."""
        try:
            body = self._request("GET", "/health")
            return body is not None and body.get("status") == "success"
        except requests.HTTPError:
            return False

    # ------------------------------------------------------------------
    # Robot endpoints
    # ------------------------------------------------------------------

    def authenticate(self, uid: str) -> Optional[dict]:
        """
        GET /api/v1/robot/auth/{uid}
        Returns participant dict or None.

        UID sanitized: alphanumeric, dash, underscore, colon only.
        Max 64 chars.
        """
        safe_uid = _sanitize_uid(uid)
        if not safe_uid:
            return None

        body = self._get(f"/app/auth/{safe_uid}")
        if body and body.get("status") == "success" and body.get("data"):
            data = body["data"]
            if not isinstance(data, dict):
                logger.error("auth response data not dict: %r", type(data))
                return None
            # /app/auth returns {"participant": {...}, "sessions": [...]}
            participant = data.get("participant") or data
            logger.info(
                "Authenticated: %s (id=%s, height=%.1f cm)",
                participant.get("name"),
                participant.get("id"),
                participant.get("height", 0),
            )
            return participant

        logger.warning("Authentication failed for UID %s", safe_uid)
        return None

    def build_session_payload(
        self,
        participant_id: int,
        game_data: dict,
    ) -> Optional[dict]:
        """
        Build session payload. Validates required fields:
        participant_id, game_score, blocks_hit,
        hand_tracking_status, play_duration, timestamp.
        Returns None if validation fails.
        """
        session = {"participant_id": participant_id, **game_data}
        missing = _validate_session_data(session)
        if missing:
            logger.error("build_session_payload missing: %s", missing)
            return None

        return session

    def submit_game_session(self, data: dict) -> Optional[int]:
        """
        POST /api/v1/game/submit
        Returns session_id or None. Buffers offline.
        """
        body = self._post("/game/submit", data)
        if body and body.get("status") == "success" and body.get("data"):
            session_id = body["data"].get("session_id")
            logger.info("Session submitted — id=%s", session_id)
            return session_id

        if not self._online:
            self._buffer("pending_sessions", data)
            logger.info("Session buffered for offline sync")

        logger.error("submit_game_session failed")
        return None

    # ------------------------------------------------------------------
    # Offline buffer
    # ------------------------------------------------------------------

    def _buffer(self, table: str, payload: dict) -> None:
        """Store failed payload in SQLite. Table name whitelisted."""
        if table not in _VALID_BUFFER_TABLES:
            logger.error("Invalid buffer table: %r", table)
            return
        try:
            with self._db_lock:
                self._db.execute(
                    f"INSERT INTO {table} (payload, created_at) VALUES (?, ?)",
                    (json.dumps(payload), datetime.now(timezone.utc).isoformat()),
                )
                self._db.commit()
        except sqlite3.Error as e:
            logger.error("Buffer write failed: %s", e)

    def _sync_loop(self) -> None:
        """Background: retry buffered payloads when online."""
        while not self._stop_sync.is_set():
            self._stop_sync.wait(_SYNC_INTERVAL)
            if not self._online:
                continue
            self._flush_table("pending_sessions", "/game/submit")

    def _flush_table(self, table: str, endpoint: str) -> None:
        """Send buffered rows to endpoint. Table name whitelisted."""
        if table not in _VALID_BUFFER_TABLES:
            return
        try:
            with self._db_lock:
                rows = self._db.execute(
                    f"SELECT id, payload FROM {table} ORDER BY id"
                ).fetchall()
        except sqlite3.Error:
            return

        for row_id, payload_json in rows:
            if not self._online or self._stop_sync.is_set():
                break
            try:
                payload = json.loads(payload_json)
                body = self._request("POST", endpoint, json=payload)
                if body and body.get("status") == "success":
                    with self._db_lock:
                        self._db.execute(
                            f"DELETE FROM {table} WHERE id = ?", (row_id,)
                        )
                        self._db.commit()
                    logger.info("Synced buffered %s row %d", table, row_id)
                else:
                    break
            except requests.HTTPError:
                break
            except Exception as e:
                logger.error("Sync error (%s row %d): %s", table, row_id, e)
                break

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Stop sync thread + close DB."""
        self._stop_sync.set()
        if self._sync_thread.is_alive():
            self._sync_thread.join(timeout=2.0)
        try:
            with self._db_lock:
                self._db.close()
        except Exception:
            pass

    def __del__(self):
        self.stop()
