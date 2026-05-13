"""
Camera Settings Panel — real-time OpenCV capture property control.

Exposes: camera index, resolution, flip H/V, exposure, brightness.
Persists to config.json. Live-update existing VideoCapture without restart.
"""
import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

import cv2
import customtkinter as ctk
from PIL import Image as PILImage

logger = logging.getLogger("settings_panel")

RESOLUTION_PRESETS = [
    ("640x480",  640, 480),
    ("800x600",  800, 600),
    ("1280x720", 1280, 720),
    ("1920x1080", 1920, 1080),
]

DEFAULT_CONFIG = {
    "camera_index": 0,
    "resolution": "640x480",
    "flip_horizontal": True,
    "flip_vertical": False,
    "exposure": -4,      # default; range varies by webcam
    "brightness": 128,   # 0-255
    "stream_url": "",    # rtsp/http ip camera url, empty = use local cv2
}


# ──────────────────────────────────────────────────────────────────────────────
# Config persistence
# ──────────────────────────────────────────────────────────────────────────────

def _config_path() -> Path:
    base = os.getenv("OAMP_BASE_DIR", os.getcwd())
    return Path(base) / "config.json"


def load_camera_config() -> dict:
    p = _config_path()
    if p.exists():
        try:
            with open(p) as f:
                cfg = json.load(f)
                # merge with defaults for missing keys
                return {**DEFAULT_CONFIG, **cfg}
        except Exception as e:
            logger.warning("config.json corrupt: %s — using defaults", e)
    return {**DEFAULT_CONFIG}


def save_camera_config(cfg: dict):
    p = _config_path()
    try:
        with open(p, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        logger.error("save config.json failed: %s", e)


# ──────────────────────────────────────────────────────────────────────────────
# CameraPropertyStore — thread-safe, shared state between UI and capture loop
# ──────────────────────────────────────────────────────────────────────────────

class CameraPropertyStore:
    """
    Shared mutable config. UI writes here; capture loop reads here.
    All cv2 prop writes go through _set_prop() with try/except fallback.
    """

    def __init__(self):
        self._cfg = load_camera_config()
        self._lock = threading.Lock()
        self._subscribers: list = []
        self._capture_callbacks: dict = {}

    # ── read from anywhere ─────────────────────────────────────────────────────

    @property
    def camera_index(self) -> int:
        return self._cfg["camera_index"]

    @property
    def resolution(self) -> tuple[int, int]:
        return next(
            (w, h) for label, w, h in RESOLUTION_PRESETS
            if label == self._cfg["resolution"]
        )

    @property
    def flip_h(self) -> bool:
        return self._cfg["flip_horizontal"]

    @property
    def flip_v(self) -> bool:
        return self._cfg["flip_vertical"]

    @property
    def exposure(self) -> int:
        return self._cfg["exposure"]

    @property
    def brightness(self) -> int:
        return self._cfg["brightness"]

    @property
    def stream_url(self) -> str:
        return self._cfg.get("stream_url", "")

    # ── UI writes these ────────────────────────────────────────────────────────

    def set_camera_index(self, idx: int):
        with self._lock:
            self._cfg["camera_index"] = idx
            save_camera_config(self._cfg)
        self._notify()
        self._notify_capture_reopen()

    def set_resolution(self, label: str):
        with self._lock:
            self._cfg["resolution"] = label
            save_camera_config(self._cfg)
        self._notify()
        self._notify_capture_reconfig()

    def set_flip_h(self, val: bool):
        with self._lock:
            self._cfg["flip_horizontal"] = val
            save_camera_config(self._cfg)
        self._notify()

    def set_flip_v(self, val: bool):
        with self._lock:
            self._cfg["flip_vertical"] = val
            save_camera_config(self._cfg)
        self._notify()

    def set_exposure(self, val: int):
        with self._lock:
            self._cfg["exposure"] = val
            save_camera_config(self._cfg)
        self._notify()

    def set_brightness(self, val: int):
        with self._lock:
            self._cfg["brightness"] = val
            save_camera_config(self._cfg)
        self._notify()

    def set_stream_url(self, url: str):
        with self._lock:
            self._cfg["stream_url"] = url.strip()
            save_camera_config(self._cfg)
        self._notify()
        self._notify_capture_reopen()

    # ── capture loop reads raw frame → applies transforms ──────────────────────

    def apply_capture_properties(self, cap: cv2.VideoCapture):
        """Write current config to open VideoCapture. Call after open + on change."""
        def _set(prop, val):
            try:
                cap.set(prop, val)
            except Exception as e:
                logger.debug("cap.set(%s, %s) unavailable: %s", prop, val, e)

        _set(cv2.CAP_PROP_FRAME_WIDTH,  self.resolution[0])
        _set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
        _set(cv2.CAP_PROP_EXPOSURE,     self.exposure)
        _set(cv2.CAP_PROP_BRIGHTNESS,   self.brightness)

    def apply_flip(self, frame) -> cv2.Mat:
        if self.flip_h and self.flip_v:
            return cv2.flip(cv2.flip(frame, 0), 1)
        if self.flip_h:
            return cv2.flip(frame, 1)
        if self.flip_v:
            return cv2.flip(frame, 0)
        return frame

    def _notify(self):
        for cb in self._subscribers:
            try:
                cb(self._cfg)
            except Exception:
                pass

    def _notify_capture_reopen(self):
        # Pass stream_url if set, otherwise camera index — game_window decides
        url = self._cfg.get("stream_url", "").strip()
        for name, cb in self._capture_callbacks.items():
            try:
                cb("reopen", url if url else self._cfg["camera_index"])
            except Exception as e:
                logger.warning("capture_reopen callback(%s) failed: %s", name, e)

    def _notify_capture_reconfig(self):
        for name, cb in self._capture_callbacks.items():
            try:
                cb("reconfig", self.resolution)
            except Exception as e:
                logger.warning("capture_reconfig callback(%s) failed: %s", name, e)

    def get(self, key, default=None):
        return self._cfg.get(key, default)

    def subscribe_capture(self, name: str, cb):
        self._capture_callbacks[name] = cb

    def subscribe(self, fn):
        self._subscribers.append(fn)


# ──────────────────────────────────────────────────────────────────────────────
# Settings Panel Widget — CustomTkinter
# ──────────────────────────────────────────────────────────────────────────────

class CameraSettingsPanel(ctk.CTkToplevel):
    """
    Modal window. Write changes to CameraPropertyStore immediately.
    """

    def __init__(self, store: CameraPropertyStore, **kwargs):
        super().__init__(**kwargs)
        self._store = store
        self._preview_cap = None
        self._preview_running = False
        self.title("Pengaturan Kamera")
        self.geometry("460x640")
        self.resizable(True, True)
        self._build_ui()
        self._populate()
        self._store.subscribe(self._on_store_change)
        self._bind_close()

    def _bind_close(self):
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        self._stop_preview()
        self.destroy()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        frame = ctk.CTkScrollableFrame(self, fg_color="#f5f5f5")
        frame.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        frame.grid_columnconfigure(0, weight=1)

        # ── Camera Index ────────────────────────────────────────────────────
        ctk.CTkLabel(frame, text="INDEKS KAMERA",
                     font=("Helvetica", 11, "bold")
        ).grid(row=0, column=0, sticky="w", pady=(12, 2))

        self._cam_idx_var = ctk.StringVar(value="0")
        idx_menu = ctk.CTkOptionMenu(
            frame, variable=self._cam_idx_var,
            values=["0", "1", "2", "3"],
            command=self._on_idx_change,
        )
        idx_menu.grid(row=1, column=0, sticky="ew", pady=(0, 12))

        # ── Resolution ─────────────────────────────────────────────────────
        ctk.CTkLabel(frame, text="RESOLUSI",
                     font=("Helvetica", 11, "bold")
        ).grid(row=2, column=0, sticky="w", pady=(12, 2))

        res_labels = [r for r, _, _ in RESOLUTION_PRESETS]
        self._res_var = ctk.StringVar(value="640x480")
        res_menu = ctk.CTkOptionMenu(
            frame, variable=self._res_var,
            values=res_labels,
            command=self._on_res_change,
        )
        res_menu.grid(row=3, column=0, sticky="ew", pady=(0, 12))

        # ── Flip ────────────────────────────────────────────────────────────
        ctk.CTkLabel(frame, text="ORIENTASI",
                     font=("Helvetica", 11, "bold")
        ).grid(row=4, column=0, sticky="w", pady=(12, 2))

        flip_frame = ctk.CTkFrame(frame, fg_color="transparent")
        flip_frame.grid(row=5, column=0, sticky="ew", pady=(0, 12))
        flip_frame.grid_columnconfigure(0, weight=1)

        self._flip_h_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            flip_frame, text="Balik Horizontal (Mirror)",
            variable=self._flip_h_var, command=self._on_flip_h_change,
        ).grid(row=0, column=0, sticky="w", pady=4)

        self._flip_v_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            flip_frame, text="Balik Vertical",
            variable=self._flip_v_var, command=self._on_flip_v_change,
        ).grid(row=1, column=0, sticky="w", pady=4)

        # ── Exposure ─────────────────────────────────────────────────────────
        ctk.CTkLabel(frame, text="EXPOSURE",
                     font=("Helvetica", 11, "bold")
        ).grid(row=6, column=0, sticky="w", pady=(12, 2))

        self._exp_var = ctk.IntVar(value=self._store.exposure)
        ctk.CTkSlider(
            frame, variable=self._exp_var,
            from_=-7, to=-1, number_of_steps=6,
            command=self._on_exp_change,
        ).grid(row=7, column=0, sticky="ew", pady=(0, 4))

        self._exp_label = ctk.CTkLabel(
            frame, text=f"Current: {self._store.exposure}",
            font=("Helvetica", 10),
        )
        self._exp_label.grid(row=8, column=0, sticky="w", pady=(0, 12))

        # ── Brightness ─────────────────────────────────────────────────────
        ctk.CTkLabel(frame, text="BRIGHTNESS",
                     font=("Helvetica", 11, "bold")
        ).grid(row=9, column=0, sticky="w", pady=(12, 2))

        self._br_var = ctk.IntVar(value=self._store.brightness)
        ctk.CTkSlider(
            frame, variable=self._br_var,
            from_=0, to=255, number_of_steps=255,
            command=self._on_br_change,
        ).grid(row=10, column=0, sticky="ew", pady=(0, 4))

        self._br_label = ctk.CTkLabel(
            frame, text=f"Current: {self._store.brightness}",
            font=("Helvetica", 10),
        )
        self._br_label.grid(row=11, column=0, sticky="w", pady=(0, 16))

        self._preview_hint = ctk.CTkLabel(
            frame, text="Preview aktif saat settings terbuka",
            font=("Helvetica", 9), text_color="#757575",
        )
        self._preview_hint.grid(row=12, column=0, sticky="w", pady=(0, 8))

        # ── Live Preview toggle ─────────────────────────────────────────────
        self._preview_running = False
        self._preview_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            frame, text="Tampilkan Preview Kamera",
            variable=self._preview_var,
            command=self._on_preview_toggle,
        ).grid(row=13, column=0, sticky="w", pady=(0, 4))

        # ── Stream URL (IP camera / remote) ───────────────────────────────────
        ctk.CTkLabel(frame, text="STREAM URL (opsional)",
                     font=("Helvetica", 11, "bold")
        ).grid(row=14, column=0, sticky="w", pady=(12, 2))

        url_frame = ctk.CTkFrame(frame, fg_color="transparent")
        url_frame.grid(row=15, column=0, sticky="ew", pady=(0, 8))
        url_frame.grid_columnconfigure(0, weight=1)

        self._stream_url_var = ctk.StringVar(value=self._store.get("stream_url", ""))
        url_entry = ctk.CTkEntry(
            url_frame, textvariable=self._stream_url_var,
            placeholder_text="rtsp://192.168.1.100/stream",
            font=("Helvetica", 11),
        )
        url_entry.grid(row=0, column=0, sticky="ew")

        ctk.CTkButton(
            url_frame, text="Apply",
            width=70, height=30,
            font=("Helvetica", 10),
            command=self._on_url_apply,
        ).grid(row=0, column=1, padx=(6, 0))

        # ── Live Camera Preview ────────────────────────────────────────────────
        ctk.CTkLabel(frame, text="LIVE PREVIEW",
                     font=("Helvetica", 11, "bold")
        ).grid(row=16, column=0, sticky="w", pady=(16, 4))

        preview_frame = ctk.CTkFrame(frame, fg_color="#1a1a1a", corner_radius=8)
        preview_frame.grid(row=17, column=0, sticky="ew", pady=(0, 8))
        preview_frame.grid_propagate(False)

        self._preview_label = ctk.CTkLabel(preview_frame, text="")
        self._preview_label.pack(fill="both", expand=True, padx=4, pady=4)

        self._cam_idx = self._store._cfg.get("camera_index", 0)

        # Try configured index, then 0, then scan /dev/video* for first working
        cap = None
        for dev in [self._cam_idx, 0, 1]:
            cap = cv2.VideoCapture(dev)
            if cap.isOpened():
                print(f"[SettingsPreview] Opened camera index {dev}")
                break
            cap.release()
            cap = None

        self._preview_cap = cap
        if self._preview_cap and self._preview_cap.isOpened():
            self._preview_running = True
            self._update_preview()
        else:
            self._preview_label.configure(text="Camera unavailable\nCheck index or URL")

    def _start_preview(self):
        url = self._store.get("stream_url", "").strip()
        cap = None
        if url:
            cap = cv2.VideoCapture(url)
        else:
            # Try configured index first, fall back to first working /dev/video*
            idx = self._cam_idx
            cap = cv2.VideoCapture(idx)
            if not cap.isOpened():
                cap.release()
                cap = None
                for dev in range(8):
                    if dev == idx:
                        continue
                    tmp = cv2.VideoCapture(dev)
                    if tmp.isOpened():
                        cap = tmp
                        break
        self._preview_cap = cap
        if self._preview_cap and self._preview_cap.isOpened():
            self._preview_running = True
            self._update_preview()
        else:
            self._preview_label.configure(text="Camera unavailable\nCheck index or URL")

        # Test: read one frame immediately and update UI
        self.after(200, self._preview_first_frame)

    def _preview_first_frame(self):
        if not self._preview_cap or not self._preview_running:
            return
        try:
            ret, frame = self._preview_cap.read()
            if ret:
                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil = PILImage.fromarray(rgb).resize((380, 220), PILImage.Resampling.LANCZOS)
                tk_img = PILImage.ImageTk.PhotoImage(image=pil)
                self._preview_label.imgtk = tk_img
                self._preview_label.configure(image=tk_img)
                print(f"[SettingsPreview] First frame OK — shape={frame.shape}")
            else:
                print("[SettingsPreview] Read returned False")
        except Exception as e:
            print(f"[SettingsPreview] First frame error: {e}")

    def _update_preview(self):
        if not self._preview_running or not self._preview_cap:
            return
        try:
            ret, frame = self._preview_cap.read()
            if ret:
                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil = PILImage.fromarray(rgb).resize((380, 220), PILImage.Resampling.LANCZOS)
                tk_img = PILImage.ImageTk.PhotoImage(image=pil)
                self._preview_label.imgtk = tk_img
                self._preview_label.configure(image=tk_img)
        except Exception:
            pass
        if self._preview_running:
            self.after(66, self._update_preview)

    def _stop_preview(self):
        self._preview_running = False
        if self._preview_cap:
            self._preview_cap.release()
            self._preview_cap = None

    def _populate(self):
        cfg = self._store._cfg
        self._cam_idx_var.set(str(cfg["camera_index"]))
        self._res_var.set(cfg["resolution"])
        self._flip_h_var.set(cfg["flip_horizontal"])
        self._flip_v_var.set(cfg["flip_vertical"])
        self._exp_var.set(cfg["exposure"])
        self._br_var.set(cfg["brightness"])

    # ── change handlers — write to store → store persists → notifies ─────────

    def _on_idx_change(self, val: str):
        self._store.set_camera_index(int(val))

    def _on_res_change(self, val: str):
        self._store.set_resolution(val)

    def _on_flip_h_change(self):
        self._store.set_flip_h(self._flip_h_var.get())

    def _on_flip_v_change(self):
        self._store.set_flip_v(self._flip_v_var.get())

    def _on_exp_change(self, val: float):
        ival = int(val)
        self._store.set_exposure(ival)
        self._exp_label.configure(text=f"Current: {ival}")

    def _on_br_change(self, val: float):
        ival = int(val)
        self._store.set_brightness(ival)
        self._br_label.configure(text=f"Current: {ival}")

    def _on_preview_toggle(self):
        # preview lifecycle managed by game_window — just signal intent
        pass

    def _on_url_apply(self):
        url = self._stream_url_var.get().strip()
        self._store.set_stream_url(url)
        self._stop_preview()
        self._start_preview()

    def _on_store_change(self, cfg: dict):
        """Sync UI if config changed externally (e.g., loaded from file)."""
        try:
            self._cam_idx_var.set(str(cfg["camera_index"]))
            self._res_var.set(cfg["resolution"])
            self._flip_h_var.set(cfg["flip_horizontal"])
            self._flip_v_var.set(cfg["flip_vertical"])
            self._exp_var.set(cfg["exposure"])
            self._br_var.set(cfg["brightness"])
        except Exception:
            pass
