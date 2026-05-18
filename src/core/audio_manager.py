"""
Arcade SFX engine — pure wav playback, no TTS/voice.

Preloads .wav files into memory for zero-latency triggering.
All playback is non-blocking (queued channel play).
"""
import logging
import os
import threading
from pathlib import Path
from typing import Optional

import pygame

logger = logging.getLogger("audio_manager")

# ---------------------------------------------------------------------------
# SFX list — add new .wav filenames here as they are added to assets/sfx/
# ---------------------------------------------------------------------------
_SFX_FILES = (
    "hit",
    "combo",
    "gameover",
    "levelup",
    "countdown",
    "selesai",
    "tick",
)


class AudioManager:
    """
    Thread-safe arcade SFX player.

    Usage:
        audio = AudioManager(base_dir="/path/to/oamp-game")
        audio.play_hit()
        audio.play_gameover()
        audio.shutdown()
    """

    def __init__(self, base_dir: Optional[str] = None):
        base = base_dir or os.getenv("OAMP_BASE_DIR", os.getcwd())
        self._sfx_dir = Path(base) / "assets" / "sfx"

        self._sounds: dict[str, pygame.mixer.Sound] = {}
        self._lock = threading.Lock()
        self._started = False

        # tick cooldown — 1 per second max
        self._last_tick_ts = 0.0
        self._tick_cooldown = 1.0  # seconds

        # Lazy init — pygame + preload on first play, not at construction

    # ── public API ──────────────────────────────────────────────────────────

    def play_hit(self):
        self._play("hit")

    def play_combo(self):
        self._play("combo")

    def play_gameover(self):
        self._play("gameover")

    def play_levelup(self):
        self._play("levelup")

    def play_countdown(self):
        self._play("countdown")

    def play_selesai(self):
        self._play("selesai")

    def play_tick(self):
        """Tick SFX — max 1 per second (cooldown guard)."""
        import time
        now = time.monotonic()
        if now - self._last_tick_ts < self._tick_cooldown:
            return
        self._last_tick_ts = now
        self._play("tick")

    def shutdown(self):
        with self._lock:
            if self._started:
                pygame.mixer.quit()
                self._started = False
        self._sounds.clear()

    # ── internals ────────────────────────────────────────────────────────────

    def _ensure_started(self):
        if self._started:
            return
        with self._lock:
            if self._started:
                return
            self._init_pygame()

    def _init_pygame(self):
        try:
            # SDL init must happen in same thread that uses mixer
            import warnings as _warnings
            with _warnings.catch_warnings():
                _warnings.simplefilter("ignore")
                pygame.mixer.init(frequency=44100, buffer=512)
            self._preload()
            self._started = True
        except Exception:
            self._started = False

    def _preload(self):
        """Load all declared SFX files into memory."""
        for name in _SFX_FILES:
            path = self._sfx_dir / f"{name}.wav"
            if path.exists():
                try:
                    self._sounds[name] = pygame.mixer.Sound(str(path))
                    logger.debug("Loaded sfx: %s", name)
                except Exception as e:
                    logger.warning("Failed to load %s.wav: %s", name, e)
            # else: silently skip — sfx dir may be empty during dev

    def _play(self, name: str):
        """Non-blocking play on mixer channel. Thread-safe."""
        if not self._started:
            self._ensure_started()
        if not self._started:
            return  # pygame not available
        with self._lock:
            sound = self._sounds.get(name)
        if sound:
            try:
                sound.play()
            except Exception as e:
                logger.warning("_play(%s) failed: %s", name, e)
