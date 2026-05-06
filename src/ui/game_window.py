import os
import time
import random
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import cv2
import torch
import customtkinter
from PIL import Image, ImageTk

from src.api_client import ServerClient
from src.api.ws_client import MatchWSClient
from src.ui.components import (
    TextFrame, ImageFrame,
    TimerDisplay, LevelBadge, StatusBar, CameraPanel,
)
from src.vision.hand_tracker import HandTracker
from src.vision.block_detector import BlockDetector
from src.vision.evaluator import BlockEvaluator

logger = logging.getLogger("game_window")


# ─── Neon Arcade Palette ──────────────────────────────────────────────────────

RED       = "#FF1744"
RED_DARK  = "#B71C1C"
BG_DARK   = "#f5f5f5"
BG_CARD   = "#ffffff"
BORDER    = "#e0e0e0"
WHITE     = "#1a1a1a"
MUTED     = "#757575"
GREEN     = "#00897B"
CYAN      = "#0097A7"
ORANGE    = "#E65100"
YELLOW    = "#F9A825"

LEVEL_COLORS = {
    1: "#D32F2F", 2: "#E65100", 3: "#F9A825", 4: "#00897B",
    5: "#0097A7", 6: "#2979FF", 7: "#7B1FA2", 8: "#C2185B",
}


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


# ─── Camera Panel (single camera — game only) ──────────────────────────────────

class CameraPanel(customtkinter.CTkFrame):
    def __init__(self, master, **kw):
        super().__init__(master, fg_color=BG_CARD, corner_radius=12,
                         border_width=1, border_color=BORDER, **kw)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        customtkinter.CTkLabel(
            self, text="◉ CAMERA — GAME",
            font=("Courier", 9, "bold"), text_color=RED,
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(8, 2))

        self._cam_label = customtkinter.CTkLabel(self, text="", anchor="center")
        self._cam_label.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

    def update_frame(self, pil_image: Image.Image):
        w = self._cam_label.winfo_width()
        h = self._cam_label.winfo_height()
        if w > 10 and h > 10:
            fw, fh = pil_image.size
            scale = min(w / fw, h / fh)
            if scale != 1.0:
                pil_image = pil_image.resize(
                    (int(fw * scale), int(fh * scale)), Image.Resampling.LANCZOS
                )
        tk_img = ImageTk.PhotoImage(image=pil_image)
        self._cam_label.imgtk = tk_img
        self._cam_label.configure(image=tk_img)


# ─── Game Window ──────────────────────────────────────────────────────────────

class GameWindow(customtkinter.CTk):

    def __init__(
        self,
        user_data: dict,
        server_client: Optional[ServerClient] = None,
        room_id: Optional[str] = None,
    ):
        super().__init__()
        self.user_data     = user_data
        self.server_client = server_client
        self.session_id: Optional[str] = None

        # WebSocket telemetry for 1v1 match mode
        self._ws_client: Optional[MatchWSClient] = None
        if room_id:
            pid = user_data.get("participant_id", "unknown")
            self._ws_client = MatchWSClient(
                room_id=room_id, player_id=str(pid)
            )

        self._setup_env()
        self._setup_window()
        self._setup_layout()
        self._setup_game_state()
        self._setup_ai()
        self._preload_images()

        self.bind("<Return>", lambda _: self._on_skip())
        self.bind("<s>",     lambda _: self._on_skip())

    def _setup_env(self):
        self.display_half = os.getenv("DISPLAY_HALF", "true").lower() == "true"
        self.hide_camera  = os.getenv("HIDE_CAMERA",  "false").lower() == "true"
        self.debug_mode   = os.getenv("DEBUG_MODE",   "false").lower() == "true"
        self.max_level    = min(max(int(os.getenv("MAX_LEVEL", "8")), 1), 8)
        self.yolo_skip    = int(os.getenv("YOLO_SKIP_FRAMES",      "2"))
        self.mp_skip      = int(os.getenv("MEDIAPIPE_SKIP_FRAMES",  "2"))
        self.cam_game_idx = int(os.getenv("CAMERA_GAME_INDEX", os.getenv("CAMERA_INDEX", "0")))
        self.base_dir     = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )

    def _setup_window(self):
        self.title("Otak Atik Merah Putih")
        w, h = (1200, 620) if self.display_half else (1400, 820)
        self.geometry(f"{w}x{h}")
        self.configure(fg_color=BG_DARK)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_columnconfigure(0, weight=1)

    def _setup_layout(self):
        self._main = customtkinter.CTkFrame(self, fg_color=BG_DARK, corner_radius=0)
        self._main.grid(row=0, column=0, sticky="nsew")
        self._main.grid_columnconfigure(0, weight=2)
        self._main.grid_columnconfigure(1, weight=3)
        self._main.grid_rowconfigure(0, weight=1)

        self._left = customtkinter.CTkFrame(self._main, fg_color=BG_CARD, corner_radius=12,
                                            border_width=1, border_color=BORDER)
        self._left.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        self._left.grid_columnconfigure(1, weight=1)
        self._left.grid_rowconfigure(1, weight=1)

        self._level_badge = LevelBadge(self._left, width=100, max_level=self.max_level)
        self._level_badge.grid(row=0, column=0, rowspan=2, padx=(12, 8), pady=12, sticky="n")

        customtkinter.CTkLabel(
            self._left, text="BLOCK DESIGN",
            font=("Courier", 10, "bold"), text_color=RED,
        ).grid(row=0, column=1, sticky="w", padx=(0, 12), pady=(12, 0))

        self._img_frame = customtkinter.CTkFrame(self._left, fg_color="#e8e8e8", corner_radius=8,
                                                  border_width=1, border_color=BORDER)
        self._img_frame.grid(row=1, column=1, sticky="nsew", padx=(0, 12), pady=(4, 12))
        self._img_frame.grid_propagate(False)

        self.frame_w = 340 if self.display_half else 480
        self.frame_h = 340 if self.display_half else 480

        self._img_label = customtkinter.CTkLabel(self._img_frame, text="")
        self._img_label.pack(expand=True, fill="both")

        self._timer = TimerDisplay(self._left, width=100, font_size=22)
        self._timer.grid(row=2, column=0, padx=(12, 8), pady=(0, 8), sticky="ew")

        self._start_btn = customtkinter.CTkButton(
            self._left, text="▶  MULAI",
            font=("Helvetica", 14, "bold"), height=44,
            corner_radius=8, fg_color=RED, hover_color="#B71C1C",
            text_color="#ffffff", command=self._on_start,
        )
        self._start_btn.grid(row=2, column=1, padx=(0, 12), pady=(0, 8), sticky="ew")

        if not self.hide_camera:
            self._cam_panel = CameraPanel(self._main)
            self._cam_panel.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)
        else:
            self._cam_panel = None

        self._status_bar = StatusBar(self)
        self._status_bar.grid(row=1, column=0, sticky="ew")

    def _setup_game_state(self):
        self._timer_running = False
        self._start_time    = 0.0
        self._start_task    = 0.0
        self._frame_count   = 0
        self._fps_counter   = 0
        self._fps_ts        = time.time()
        self._latest_boxes  = []
        self._cached_images = {}
        self._task_flags    = {i: True for i in range(1, self.max_level + 1)}
        self._timer_all     = []
        self._cog_ages      = []
        self._current_q     = 1
        self._current_variant = ""
        self._image_visible = False
        self._image_show_ts = 0.0
        self._image_duration = 5.0
        self._level_btn: Optional[customtkinter.CTkButton] = None
        self._evaluator    = BlockEvaluator()

    @staticmethod
    def _cam_probe(cap, label, idx):
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

    def _setup_ai(self):
        self._cap_game = cv2.VideoCapture(self.cam_game_idx)
        self._cap_game.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
        self._cap_game.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self._game_cam_ok = self._cam_probe(
            self._cap_game, "Kamera game", self.cam_game_idx
        )
        if not self._game_cam_ok:
            self._cap_game = None

        self._hand_tracker = HandTracker(draw_style="rich")

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        use_bantal = os.getenv("MODEL_BANTAL", "false").lower() == "true"
        model_yolo = None

        if use_bantal:
            p = os.path.join(self.base_dir, "models", "weights", "bantal.pt")
            try:
                from ultralytics import YOLO
                model_yolo = YOLO(p); model_yolo.to(device)
            except Exception:
                use_bantal = False

        if not use_bantal:
            p = os.path.join(self.base_dir, "models", "weights", "best.pt")
            try:
                model_yolo = torch.hub.load(
                    os.path.join(self.base_dir, "models", "yolov5"),
                    "custom", path=p, force_reload=True, source="local",
                ); model_yolo.to(device)
            except Exception as e:
                print(f"[YOLO] Gagal load: {e}")

        if model_yolo:
            self._yolo = BlockDetector(model_yolo, use_bantal, confidence=0.7)
            self._yolo.start()
        else:
            self._yolo = None

    def _preload_images(self):
        base = os.path.join(self.base_dir, "assets", "images", "FILES", "TEST_RANDOM_1500x1500")
        for lvl in range(1, 9):
            for var in "abcd":
                key  = f"{lvl}{var}"
                path = os.path.join(base, f"Lvl {key}.png")
                if os.path.exists(path):
                    img = Image.open(path).resize(
                        (self.frame_w, self.frame_h), Image.Resampling.LANCZOS
                    )
                    self._cached_images[key] = img

    # ─── Timer ─────────────────────────────────────────────────────────────

    def _tick(self):
        if self._timer_running:
            self._timer.set_time(time.time() - self._start_time)
            self.after(50, self._tick)

    def _start_timer(self):
        if not self._timer_running:
            self._start_time = time.time()
            self._timer_running = True
            self._tick()

    def _stop_timer(self):
        self._timer_running = False

    def _reset_timer(self):
        self._timer_running = False
        self._timer.reset()

    # ─── Game Flow ─────────────────────────────────────────────────────────

    def _on_start(self):
        self._start_btn.grid_remove()
        self._hand_tracker.reset_session()
        self._show_level_btn()
        self._next_level()
        if self._ws_client:
            self._ws_client.start()
        self._stream()

    def _show_level_btn(self):
        if self._level_btn:
            self._level_btn.grid_remove()
        self._level_btn = customtkinter.CTkButton(
            self._left, text=f"Level {self._current_q}",
            font=("Courier", 12, "bold"), height=34,
            corner_radius=6, fg_color=BG_CARD,
            hover_color="#e0e0e0", border_width=2,
            border_color=RED, text_color=RED, state="disabled",
        )
        self._level_btn.grid(row=3, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="ew")

    def _next_level(self):
        variant = f"{self._current_q}{random.choice('abcd')}"
        self._current_variant = variant
        self._evaluator.set_variant(variant)
        self._level_badge.set_level(self._current_q)
        if self._level_btn:
            self._level_btn.configure(text=f"Level {self._current_q}")
        self._load_image(variant)
        self._hand_tracker.reset_session()
        self._hand_tracker.reset_gesture()
        self._start_task = time.time()
        self._reset_timer()
        self._start_timer()
        self._status_bar.set_attempts(0)

    def _load_image(self, variant: str):
        img = self._cached_images.get(variant)
        if not img:
            return
        self._img = customtkinter.CTkImage(light_image=img, size=(self.frame_w, self.frame_h))
        self._img_label.configure(image=self._img)
        self._image_visible = True
        self._image_show_ts = time.time()

    def _complete_level(self, elapsed: float):
        if not self._task_flags.get(self._current_q, False):
            return
        self._task_flags[self._current_q] = False
        self._timer_all.append(round(elapsed, 2))
        self._cog_ages.append(self._estimate_cog_age(elapsed))
        self._status_bar.set_attempts(self._evaluator.attempt_count)
        self._show_score_flash(elapsed)
        self._shake()
        self._level_badge.set_completed(self._current_q)

        if self._current_q >= self.max_level:
            self._end_game()
            return

        nxt = self._current_q + 1
        self._current_q = nxt
        self._task_flags[self._current_q] = True
        self._next_level()

    @staticmethod
    def _estimate_cog_age(elapsed: float) -> int:
        if elapsed < 10:   return 6
        elif elapsed < 14: return 7
        elif elapsed < 18: return 8
        elif elapsed < 22: return 9
        elif elapsed < 26: return 10
        elif elapsed < 32: return 11
        elif elapsed < 40: return 12
        return 13

    def _on_skip(self):
        if self._timer_running:
            self._complete_level(time.time() - self._start_task)

    def _show_score_flash(self, elapsed: float):
        flash = customtkinter.CTkFrame(
            self._left, fg_color=GREEN, corner_radius=8, height=56,
        )
        flash.grid(row=1, column=0, columnspan=2, padx=16, pady=16, sticky="ew")
        flash.grid_propagate(False)
        customtkinter.CTkLabel(
            flash, text=f"✓  {elapsed:.1f}s",
            font=("Courier", 20, "bold"), text_color="#ffffff",
        ).pack(expand=True)
        self.after(1200, flash.destroy)

    def _shake(self):
        self._left.grid_configure(padx=(18, 0))
        self.after(50,  lambda: self._left.grid_configure(padx=(6, 12)))
        self.after(100, lambda: self._left.grid_configure(padx=(15, 3)))
        self.after(150, lambda: self._left.grid_configure(padx=(12, 6)))

    def _end_game(self):
        self._stop_timer()
        if self._level_btn:
            self._level_btn.grid_remove()

        avg = sum(self._timer_all) / len(self._timer_all) if self._timer_all else 0
        age = self.user_data.get("age", 0)
        cog = int(sum(self._cog_ages) / len(self._cog_ages)) if self._cog_ages else age
        fit = 100 if cog <= age else max(0, 100 - (cog - age))
        hand = self._hand_tracker.flush_buffer()

        print(f"=== HASIL === Avg: {avg:.2f}s | CogAge: {cog} | Fitness: {fit}%")

        # WS: send GAME_OVER exactly once, before cleanup
        if self._ws_client:
            self._ws_client.send_game_over(
                final_score=fit, blocks_hit=self._current_q,
            )

        if self.server_client:
            participant_id = self.user_data.get("participant_id")
            if participant_id:
                from datetime import datetime, timezone
                payload = self.server_client.build_session_payload(
                    participant_id=participant_id,
                    game_data={
                        "game_score": fit,
                        "blocks_hit": self._current_q,
                        "hand_tracking_status": "active" if hand else "none",
                        "play_duration": round(avg, 2),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
                session_id = self.server_client.submit_game_session(payload)
                if session_id:
                    logger.info("Session %d recorded", session_id)
            else:
                logger.warning("No participant_id, skip submit")

        end_img = os.path.join(self.base_dir, "assets", "images", "FILES", "TEST_1000x1000", "09.jpg")
        if os.path.exists(end_img):
            img = Image.open(end_img).resize((self.frame_w, self.frame_h), Image.Resampling.LANCZOS)
            self._img = customtkinter.CTkImage(light_image=img, size=(self.frame_w, self.frame_h))
            self._img_label.configure(image=self._img)

        customtkinter.CTkButton(
            self._left, text="↺  MAIN LAGI",
            font=("Helvetica", 13, "bold"), height=44,
            corner_radius=8, fg_color=RED,
            hover_color="#B71C1C", text_color="#ffffff",
            command=self.destroy,
        ).grid(row=3, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="ew")

    # ─── Stream ────────────────────────────────────────────────────────────

    def _stream(self):
        try:
            if self._game_cam_ok and self._cap_game and self._cap_game.isOpened():
                ret, frame = self._cap_game.read()
                if ret:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                    if self._frame_count % (self.mp_skip + 1) == 0:
                        self._hand_tracker.detect(frame_rgb)

                    frame_rgb = self._hand_tracker.draw_cached(frame_rgb)

                    if self._hand_tracker.check_peace_gesture():
                        self.after(0, self._on_skip)

                    if self._yolo:
                        if self._frame_count % (self.yolo_skip + 1) == 0:
                            self._yolo.submit_frame(frame)
                        result = self._yolo.get_result()
                        if result:
                            self._latest_boxes = result.boxes

                        for box in self._latest_boxes:
                            x1, y1, x2, y2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])
                            cv2.rectangle(frame_rgb, (x1, y1), (x2, y2), (0, 0, 255), 2)

                        if len(self._latest_boxes) == 4:
                            boxes = self._latest_boxes
                            pos_x = [(b[0] + b[2]) / 2 for b in boxes]
                            pos_y = [(b[1] + b[3]) / 2 for b in boxes]
                            is_ok, _ = self._evaluator.check(pos_x=pos_x, pos_y=pos_y, designs=[])
                            if is_ok:
                                self._complete_level(time.time() - self._start_task)

                    if self._cam_panel:
                        self._cam_panel.update_frame(Image.fromarray(frame_rgb))

        except Exception as e:
            print(f">>> [DEBUG] _stream error: {e}")
            import traceback
            traceback.print_exc()

        self._frame_count += 1
        self._fps_counter += 1
        if time.time() - self._fps_ts >= 1.0:
            self._status_bar.set_fps(self._fps_counter)
            self._fps_counter = 0
            self._fps_ts = time.time()
            if self.server_client:
                self._status_bar.set_server_online(self.server_client.is_online)

        # WS telemetry — push on every frame (~100Hz is fine, ws_client throttles internally)
        if self._ws_client:
            self._ws_client.update(
                score=self._current_q,
                blocks_hit=len(self._latest_boxes),
            )

        self.after(10, self._stream)

    # ─── Cleanup ──────────────────────────────────────────────────────────

    def cleanup(self):
        if getattr(self, "_ws_client", None):
            self._ws_client.stop()
        for cap in (self._cap_game,):
            if cap and cap.isOpened():
                cap.release()
        if getattr(self, "_yolo", None):
            self._yolo.stop()
        if getattr(self, "_hand_tracker", None):
            self._hand_tracker.close()
        if getattr(self, "server_client", None):
            self.server_client.stop()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def destroy(self):
        self.cleanup()
        super().destroy()