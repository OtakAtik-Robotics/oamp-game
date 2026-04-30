import time
import threading
from queue import Queue, Empty
from dataclasses import dataclass
from typing import List, Optional

import numpy as np


@dataclass
class DetectionResult:
    __slots__ = ("boxes", "timestamp")
    boxes: List
    timestamp: float

    def __len__(self):
        return len(self.boxes)


class BlockDetector:
    """YOLO-based block detection thread."""

    def __init__(
        self,
        model,
        use_bantal_model: bool = False,
        confidence: float = 0.7,
        skip_frames: int = 2,
        on_error: Optional[callable] = None,
    ):
        self.model = model
        self.use_bantal_model = use_bantal_model
        self.confidence = confidence
        self.skip_frames = skip_frames
        self.on_error = on_error

        self.frame_queue: Queue = Queue(maxsize=1)
        self.result_queue: Queue = Queue(maxsize=1)
        self.running = True

        self.inference_count = 0
        self.last_inference_ms = 0.0
        self._inference_times: List[float] = []
        self._max_history = 30

    def _infer(self, frame) -> List:
        if self.use_bantal_model:
            results = self.model(frame, verbose=False)
            if not results or not hasattr(results[0], "boxes"):
                return []
            data = results[0].boxes.data.cpu().numpy()
            mask = data[:, 4] >= self.confidence
            return [row.tolist() + [""] for row in data[mask]]
        else:
            results = self.model(frame)
            pred = results.xyxy[0]
            data = pred.cpu().numpy() if pred.is_cuda else pred.numpy()
            mask = data[:, 4] >= self.confidence
            return [row[:6].tolist() + [row[6] if len(row) > 6 else ""]
                    for row in data[mask]]

    def _update_metrics(self, elapsed_ms: float):
        self.last_inference_ms = elapsed_ms
        self._inference_times.append(elapsed_ms)
        if len(self._inference_times) > self._max_history:
            self._inference_times.pop(0)
        self.inference_count += 1

    @property
    def avg_inference_ms(self) -> float:
        if not self._inference_times:
            return 0.0
        return sum(self._inference_times) / len(self._inference_times)

    def submit_frame(self, frame) -> bool:
        if self.frame_queue.full():
            return False
        try:
            self.frame_queue.put_nowait(np.array(frame, copy=True))
            return True
        except Exception:
            return False

    def get_result(self) -> Optional[DetectionResult]:
        try:
            return self.result_queue.get_nowait()
        except Empty:
            return None

    def run(self):
        while self.running:
            try:
                frame = self.frame_queue.get(timeout=0.05)
            except Empty:
                continue

            try:
                t0 = time.perf_counter()
                boxes = self._infer(frame)
                elapsed = (time.perf_counter() - t0) * 1000
                self._update_metrics(elapsed)

                result = DetectionResult(boxes=boxes, timestamp=time.time())

                if self.result_queue.full():
                    try:
                        self.result_queue.get_nowait()
                    except Empty:
                        pass
                self.result_queue.put(result)

            except Exception as e:
                if self.on_error:
                    self.on_error(e)
                time.sleep(0.01)

    def stop(self):
        self.running = False


class YOLODetectionThread(BlockDetector):
    """Alias for backwards compatibility."""
    pass