import os
import time
import random
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

import cv2
import torch
import numpy as np

from src.api_client import ServerClient
from src.vision.hand_tracker import HandTracker
from src.vision.block_detector import BlockDetector, DetectionResult
from src.vision.evaluator import BlockEvaluator

logger = logging.getLogger("game_engine")


# ─── Preloader ────────────────────────────────────────────────────────────────

_PRELOAD_DONE = False
_PRELOAD_ERR  = None
_preload_lock = threading.Lock()


def _background_preload():
    global _PRELOAD_DONE, _PRELOAD_ERR
    try:
        from src.vision.hand_tracker import HandTracker
        base_dir = os.path.join(os.path.dirname(__file__), "..", "..")
        device   = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        use_bantal = os.getenv("MODEL_BANTAL", "false").lower() == "true"

        if use_bantal:
            p = os.path.join(base_dir, "models", "weights", "bantal.pt")
            from ultralytics import YOLO
            YOLO(p).to(device)
        else:
            p = os.path.join(base_dir, "models", "weights", "best.pt")
            torch.hub.load(
                os.path.join(base_dir, "models", "yolov5"),
                "custom", path=p, force_reload=True, source="local",
            ).to(device)
    except Exception as e:
        _PRELOAD_ERR = e
    finally:
        with _preload_lock:
            _PRELOAD_DONE = True


def _start_preload():
    with _preload_lock:
        if not _PRELOAD_DONE:
            t = threading.Thread(target=_background_preload, daemon=True, name="ModelPreload")
            t.start()


# ─── Game Engine ───────────────────────────────────────────────────────────────

class GameEngine:
    """Core game loop manager. Handles frame capture, detection, and UI updates."""

    def __init__(
        self,
        user_data: dict,
        server_client: Optional[ServerClient] = None,
    ):
        self.user_data     = user_data
        self.server_client = server_client
        self.session_id: Optional[str] = None

        self._setup_env()
        self._setup_ai()
        self._setup_game_state()

    def _setup_env(self):
        self.display_half  = os.getenv("DISPLAY_HALF", "true").lower() == "true"
        self.hide_camera    = os.getenv("HIDE_CAMERA",  "false").lower() == "true"
        self.debug_mode     = os.getenv("DEBUG_MODE",   "false").lower() == "true"
        self.max_level      = min(max(int(os.getenv("MAX_LEVEL", "8")), 1), 8)
        self.yolo_skip      = int(os.getenv("YOLO_SKIP_FRAMES",      "2"))
        self.mp_skip        = int(os.getenv("MEDIAPIPE_SKIP_FRAMES",  "2"))
        self.cam_game_idx   = int(os.getenv("CAMERA_GAME_INDEX", os.getenv("CAMERA_INDEX", "0")))
        self.base_dir       = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )

    def _setup_ai(self):
        # Game camera
        self._cap_game = cv2.VideoCapture(self.cam_game_idx)
        self._cap_game.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
        self._cap_game.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self._game_cam_ok = self._cam_probe("Kamera game", self.cam_game_idx)
        if not self._game_cam_ok:
            self._cap_game = None

        # Hand tracker
        self._hand_tracker = HandTracker(draw_style="rich")

        # YOLO block detector
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        use_bantal = os.getenv("MODEL_BANTAL","false").lower() == "true"
        model_yolo = None

        if use_bantal:
            p = os.path.join(self.base_dir,"models","weights","bantal.pt")
            try:
                from ultralytics import YOLO
                model_yolo = YOLO(p); model_yolo.to(device)
            except Exception: use_bantal = False

        if not use_bantal:
            p = os.path.join(self.base_dir,"models","weights","best.pt")
            try:
                model_yolo = torch.hub.load(
                    os.path.join(self.base_dir,"models","yolov5"),
                    "custom", path=p, force_reload=True, source="local",
                ); model_yolo.to(device)
            except Exception as e:
                print(f"[YOLO] Gagal load: {e}")

        if model_yolo:
            self._yolo = BlockDetector(model_yolo, use_bantal, confidence=0.7)
            self._yolo.start()
        else:
            self._yolo = None

    @staticmethod
    def _cam_probe(label: str, idx: int) -> bool:
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            print(f">>> {label} (index {idx}) tidak tersedia.")
            cap.release()
            return False
        ret, _ = cap.read()
        if not ret:
            print(f">>> {label} (index {idx}) terbuka tapi gagal baca frame.")
            cap.release()
            return False
        return True

    def _setup_game_state(self):
        self._start_time    = 0.0
        self._start_task    = 0.0
        self._frame_count   = 0
        self._fps_counter   = 0
        self._fps_ts        = time.time()
        self._latest_boxes  = []
        self._task_flags    = {i: True for i in range(1, self.max_level+1)}
        self._timer_all     = []
        self._current_q     = 1
        self._current_variant = ""
        self._image_show_ts   = 0.0
        self._image_duration  = 5.0
        self._evaluator     = BlockEvaluator()
        self._timer_running = False

    # ─── Game Loop Hooks ─────────────────────────────────────────────────────

    def start_timer(self):
        if not self._timer_running:
            self._start_time = time.time()
            self._timer_running = True

    def stop_timer(self):
        self._timer_running = False

    def reset_timer(self):
        self._timer_running = False

    def get_elapsed(self) -> float:
        return time.time() - self._start_time if self._timer_running else 0.0

    def next_level(self):
        variant = f"{self._current_q}{random.choice('abcd')}"
        self._current_variant = variant
        self._evaluator.set_variant(variant)
        self._start_task = time.time()
        self.reset_timer()
        self.start_timer()
        self._hand_tracker.reset_session()
        self._hand_tracker.reset_gesture()
        return variant

    def complete_level(self) -> float:
        if not self._task_flags.get(self._current_q, False):
            return 0.0
        elapsed = time.time() - self._start_task
        self._task_flags[self._current_q] = False
        self._timer_all.append(round(elapsed, 2))
        return elapsed

    @property
    def current_level(self) -> int:
        return self._current_q

    @property
    def attempts(self) -> int:
        return self._evaluator.attempt_count

    def set_level(self, level: int):
        self._current_q = level
        self._task_flags[level] = True

    def advance_level(self) -> bool:
        """Advance to next level. Returns False if game complete."""
        if self._current_q >= self.max_level:
            return False
        self._current_q += 1
        self._task_flags[self._current_q] = True
        return True

    def is_game_complete(self) -> bool:
        return self._current_q >= self.max_level and not any(self._task_flags.values())

    def get_session_summary(self) -> dict:
        avg = sum(self._timer_all) / len(self._timer_all) if self._timer_all else 0
        cog = int(sum(self._estimate_cognitive_age(t) for t in self._timer_all) / len(self._timer_all)) if self._timer_all else 0
        age = self.user_data.get("age", 0)
        fit = 100 if cog <= age else max(0, 100 - (cog - age))
        return {
            "avg_time": round(avg, 2),
            "cognitive_age": cog,
            "visuo_spatial_fit": fit,
            "level_reached": self._current_q,
            "timer_all": self._timer_all,
        }

    @staticmethod
    def _estimate_cognitive_age(elapsed: float) -> int:
        if elapsed < 10:   return 6
        elif elapsed < 14: return 7
        elif elapsed < 18: return 8
        elif elapsed < 22: return 9
        elif elapsed < 26: return 10
        elif elapsed < 32: return 11
        elif elapsed < 40: return 12
        return 13

    # ─── Frame Processing ────────────────────────────────────────────────────

    def process_frame(self, frame):
        """Process a frame through hand tracking and YOLO detection."""
        if not self._game_cam_ok or self._cap_game is None:
            return frame, []

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        if self._frame_count % (self.mp_skip + 1) == 0:
            self._hand_tracker.detect(frame_rgb)

        frame_rgb = self._hand_tracker.draw_cached(frame_rgb)

        if self._yolo:
            if self._frame_count % (self.yolo_skip + 1) == 0:
                self._yolo.submit_frame(frame)
            result = self._yolo.get_result()
            if result:
                self._latest_boxes = result.boxes

            for box in self._latest_boxes:
                x1, y1, x2, y2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])
                cv2.rectangle(frame_rgb, (x1, y1), (x2, y2), (0, 0, 255), 2)

        self._frame_count += 1
        return frame_rgb, self._latest_boxes

    def check_blocks(self) -> bool:
        """Check if 4 blocks detected match expected pattern."""
        if len(self._latest_boxes) != 4:
            return False
        boxes = self._latest_boxes
        pos_x = [(b[0] + b[2]) / 2 for b in boxes]
        pos_y = [(b[1] + b[3]) / 2 for b in boxes]
        is_ok, _ = self._evaluator.check(pos_x=pos_x, pos_y=pos_y, designs=[])
        return is_ok

    def get_latest_boxes(self):
        return self._latest_boxes

    def get_hand_tracker(self) -> HandTracker:
        return self._hand_tracker

    def get_evaluator(self) -> BlockEvaluator:
        return self._evaluator

    # ─── Cleanup ─────────────────────────────────────────────────────────────

    def cleanup(self):
        if self._cap_game and self._cap_game.isOpened():
            self._cap_game.release()
        if self._yolo:
            self._yolo.stop()
        if self._hand_tracker:
            self._hand_tracker.close()
        if self.server_client:
            self.server_client.stop()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()