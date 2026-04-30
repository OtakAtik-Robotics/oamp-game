import os
import time
import threading
from dataclasses import dataclass
from typing import List, Optional

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None

try:
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import (
        HandLandmarker,
        HandLandmarkerOptions,
        HandLandmarksConnections,
        RunningMode,
    )
    _HAS_MP = True
except Exception as e:
    print(f">>> [DEBUG] Gagal load MediaPipe: {e}")
    _HAS_MP = False


_MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "models", "weights")
_HAND_MODEL = os.path.normpath(os.path.join(_MODEL_DIR, "hand_landmarker.task"))


FINGER_COLORS = {
    "thumb":  (0,   165, 255),
    "index":  (0,   255, 0),
    "middle": (255, 255, 0),
    "ring":   (255, 0,   200),
    "pinky":  (80,  80,  255),
    "palm":   (180, 180, 180),
}

FINGER_LANDMARKS = {
    "thumb":  [1, 2, 3, 4],
    "index":  [5, 6, 7, 8],
    "middle": [9, 10, 11, 12],
    "ring":   [13, 14, 15, 16],
    "pinky":  [17, 18, 19, 20],
}

PALM_CONNECTIONS = [
    (0,1),(0,5),(0,9),(0,13),(0,17),
    (5,9),(9,13),(13,17),
]

TIP_LABELS = {4:"T", 8:"I", 12:"M", 16:"R", 20:"P"}


@dataclass
class HandMovementSample:
    timestamp_ms: int
    koordinat_x:  float
    koordinat_y:  float
    kecepatan:    float


class HandTracker:
    def __init__(
        self,
        max_num_hands: int = 2,
        draw_style: str = "rich",
        session_start: Optional[float] = None,
    ):
        self.draw_style  = draw_style
        self._session_start = session_start or time.time()
        self._movement_buffer: List[HandMovementSample] = []
        self._last_pos: Optional[tuple] = None
        self._last_ts:  Optional[float] = None
        self._cached_hands: list = []
        self._gesture_start_ts: Optional[float] = None
        self._peace_triggered: bool = False

        if not _HAS_MP or not os.path.isfile(_HAND_MODEL):
            print(f">>> MediaPipe tidak tersedia atau model tidak ditemukan: {_HAND_MODEL}")
            self.available = False
            self._landmarker = None
            return

        try:
            options = HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=_HAND_MODEL),
                running_mode=RunningMode.IMAGE,
                min_hand_detection_confidence=0.6,
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5,
                num_hands=max_num_hands,
            )
            self._landmarker = HandLandmarker.create_from_options(options)
            self.available = True
        except Exception as e:
            print(f">>> [DEBUG] Gagal inisialisasi HandLandmarker: {e}")
            self.available = False
            self._landmarker = None

    def _px(self, lmk, w, h):
        return int(lmk.x * w), int(lmk.y * h)

    def _draw_rich(self, frame, landmarks):
        if cv2 is None:
            return
        h, w = frame.shape[:2]

        for a, b in PALM_CONNECTIONS:
            cv2.line(frame, self._px(landmarks[a],w,h), self._px(landmarks[b],w,h),
                    FINGER_COLORS["palm"], 2, cv2.LINE_AA)

        for finger, indices in FINGER_LANDMARKS.items():
            color = FINGER_COLORS[finger]
            cv2.line(frame, self._px(landmarks[0],w,h), self._px(landmarks[indices[0]],w,h),
                    color, 2, cv2.LINE_AA)
            for i in range(len(indices)-1):
                cv2.line(frame,
                        self._px(landmarks[indices[i]],  w,h),
                        self._px(landmarks[indices[i+1]],w,h),
                        color, 2, cv2.LINE_AA)

        for i, lmk in enumerate(landmarks):
            px = self._px(lmk, w, h)
            r  = 7 if i in TIP_LABELS else 4
            cv2.circle(frame, px, r+2, (255,255,255), -1, cv2.LINE_AA)
            cv2.circle(frame, px, r,   (0, 180, 0),   -1, cv2.LINE_AA)

        for tip_idx, lbl in TIP_LABELS.items():
            px = self._px(landmarks[tip_idx], w, h)
            cv2.putText(frame, lbl, (px[0]+6, px[1]-6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        (255,255,255), 1, cv2.LINE_AA)

    def detect(self, frame):
        if not self.available or self._landmarker is None or cv2 is None:
            self._cached_hands = []
            return []

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        results = self._landmarker.detect(mp_image)
        samples: List[HandMovementSample] = []

        if not results.hand_landmarks:
            self._cached_hands = []
            self._last_pos = None
            self._last_ts  = None
            return []

        self._cached_hands = results.hand_landmarks

        now   = time.time()
        ts_ms = int((now - self._session_start) * 1000)

        for hand_landmarks in results.hand_landmarks:
            wrist = hand_landmarks[0]
            cx, cy = wrist.x, wrist.y
            kecepatan = 0.0
            if self._last_pos is not None and self._last_ts is not None:
                dt_ms = (now - self._last_ts) * 1000
                if dt_ms > 0:
                    dx = (cx - self._last_pos[0]) * 1000
                    dy = (cy - self._last_pos[1]) * 1000
                    import math
                    kecepatan = round(math.sqrt(dx*dx+dy*dy)/dt_ms, 4)

            self._last_pos = (cx, cy)
            self._last_ts  = now
            s = HandMovementSample(ts_ms, round(cx,4), round(cy,4), kecepatan)
            samples.append(s)
            self._movement_buffer.append(s)

        return samples

    def draw_cached(self, frame):
        if not self._cached_hands or cv2 is None:
            return frame

        for hand_landmarks in self._cached_hands:
            if self.draw_style == "rich":
                self._draw_rich(frame, hand_landmarks)
            else:
                connections = HandLandmarksConnections.HAND_CONNECTIONS
                for conn in connections:
                    start = hand_landmarks[conn.start]
                    end   = hand_landmarks[conn.end]
                    h_img, w_img = frame.shape[:2]
                    cv2.line(frame,
                             self._px(start, w_img, h_img),
                             self._px(end, w_img, h_img),
                             (0, 200, 0), 2, cv2.LINE_AA)
                for lmk in hand_landmarks:
                    h_img, w_img = frame.shape[:2]
                    cv2.circle(frame, self._px(lmk, w_img, h_img),
                               3, (0, 255, 0), -1, cv2.LINE_AA)

        return frame

    @staticmethod
    def _is_peace_sign(landmarks) -> bool:
        if landmarks[8].y >= landmarks[6].y:
            return False
        if landmarks[12].y >= landmarks[10].y:
            return False
        if landmarks[16].y < landmarks[14].y:
            return False
        if landmarks[20].y < landmarks[18].y:
            return False
        return True

    def check_peace_gesture(self) -> bool:
        if not self._cached_hands:
            self._gesture_start_ts = None
            return False

        peace_now = any(self._is_peace_sign(h) for h in self._cached_hands)

        if peace_now:
            now = time.time()
            if self._gesture_start_ts is None:
                self._gesture_start_ts = now
            elif now - self._gesture_start_ts >= 1.5 and not self._peace_triggered:
                self._peace_triggered = True
                return True
        else:
            self._gesture_start_ts = None
            self._peace_triggered = False
        return False

    def reset_gesture(self):
        self._gesture_start_ts = None
        self._peace_triggered = False

    def reset_session(self, session_start: Optional[float] = None):
        self._session_start = session_start or time.time()
        self._movement_buffer.clear()
        self._cached_hands = []
        self._last_pos = None
        self._last_ts  = None

    def flush_buffer(self):
        data = [asdict(s) for s in self._movement_buffer]
        self._movement_buffer.clear()
        return data

    def close(self):
        if self._landmarker is not None:
            self._landmarker.close()


def asdict(s):
    return {"timestamp_ms": s.timestamp_ms, "koordinat_x": s.koordinat_x,
            "koordinat_y": s.koordinat_y, "kecepatan": s.kecepatan}