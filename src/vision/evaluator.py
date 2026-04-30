import math
import cv2
import numpy as np
from typing import List, Optional, Tuple


LEVEL_ANSWERS_NORMAL = {
    '1a': [2,1,1,1], '1b': [2,1,1,2], '1c': [1,1,1,2], '1d': [1,2,2,1],
    '2a': [2,1,6,1], '2b': [3,2,1,2], '2c': [2,2,5,6], '2d': [6,2,2,6],
    '3a': [3,5,1,1], '3b': [1,5,1,6], '3c': [2,3,4,1], '3d': [6,5,3,4],
    '4a': [6,2,1,6], '4b': [3,2,2,5], '4c': [1,5,3,1], '4d': [4,2,2,6],
    '5a': [6,3,5,4], '5b': [5,4,6,3], '5c': [3,5,6,4], '5d': [4,4,6,6],
    '6a': [1,4,3,1], '6b': [6,1,5,5], '6c': [5,1,1,4], '6d': [5,4,4,5],
    '7a': [4,5,5,5], '7b': [4,5,5,6], '7c': [2,5,1,5], '7d': [1,2,3,6],
    '8a': [6,5,6,3], '8b': [6,3,4,2], '8c': [5,6,3,5], '8d': [3,6,5,4],
}

LEVEL_ANSWERS_OTAK_ATIK = {
    '1a': [1,2,1,2], '1b': [2,1,2,1], '1c': [2,1,1,2], '1d': [1,2,2,1],
    '2a': [2,4,1,1], '2b': [1,6,2,2], '2c': [1,2,2,4], '2d': [2,1,1,6],
    '3a': [4,1,5,1], '3b': [6,2,3,2], '3c': [5,1,4,1], '3d': [3,2,6,2],
    '4a': [4,1,1,6], '4b': [6,2,2,4], '4c': [1,5,3,1], '4d': [2,3,5,2],
    '5a': [4,3,5,6], '5b': [6,5,3,4], '5c': [6,6,6,6], '5d': [4,4,4,4],
    '6a': [5,3,4,6], '6b': [3,5,6,4], '6c': [6,6,4,4], '6d': [4,4,6,6],
    '7a': [3,4,6,5], '7b': [5,6,4,3], '7c': [3,6,4,5], '7d': [5,4,6,3],
    '8a': [5,4,4,5], '8b': [3,6,6,3], '8c': [4,5,3,6], '8d': [6,3,5,4],
}

def sort_blocks_by_position(
    pos_x: List[float],
    pos_y: List[float],
    designs: List[int],
) -> Optional[List[int]]:

    if len(pos_x) != 4 or len(pos_y) != 4 or len(designs) != 4:
        return None

    distances = []
    for i in range(4):
        for j in range(i + 1, 4):
            d = math.sqrt((pos_x[i]-pos_x[j])**2 + (pos_y[i]-pos_y[j])**2)
            distances.append(d)
    distances.sort()

    if not all(abs(distances[k] - distances[k+1]) < 100 for k in range(3)):
        return None

    sorted_x = sorted(pos_x)
    mid = (sorted_x[1] + sorted_x[2]) / 2

    indexed = [(pos_x[i], pos_y[i], i) for i in range(4)]
    indexed.sort(key=lambda p: (p[0] >= mid, p[1]))

    return [designs[idx] for _, _, idx in indexed]


def classify_block_face(img_thres: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> int:
    if y2 <= y1 or x2 <= x1:
        return 0
    if y1 < 0 or y2 > img_thres.shape[0] or x1 < 0 or x2 > img_thres.shape[1]:
        return 0

    dim = (100, 100)
    roi = cv2.resize(img_thres[y1:y2, x1:x2], dim, interpolation=cv2.INTER_AREA)

    top    = roi[25, 50]
    right  = roi[50, 75]
    bottom = roi[75, 50]
    left   = roi[50, 25]
    pattern = [top, right, bottom, left]

    face_map = {
        (0,   0,   0,   0  ): 1,  # all black
        (255, 255, 255, 255): 2,  # all white
        (255, 255, 0,   0  ): 3,  # top-right white
        (255, 0,   0,   255): 4,  # top-left white
        (0,   0,   255, 255): 5,  # bottom-left white
        (0,   255, 255, 0  ): 6,  # bottom-right white
    }
    return face_map.get(tuple(pattern), 0)


class BlockEvaluator:

    def __init__(self, normal_pattern: bool = True):
        self._answers = LEVEL_ANSWERS_NORMAL if normal_pattern else LEVEL_ANSWERS_OTAK_ATIK
        self._attempt_count: int = 0
        self._current_variant: Optional[str] = None

    def set_variant(self, variant: str):
        self._current_variant = variant
        self._attempt_count = 0

    def check(
        self,
        pos_x: List[float],
        pos_y: List[float],
        designs: List[int],
    ) -> Tuple[bool, Optional[List[int]]]:
        if self._current_variant is None:
            return False, None

        expected = self._answers.get(self._current_variant)
        if expected is None:
            return False, None

        sorted_designs = sort_blocks_by_position(pos_x, pos_y, designs)
        if sorted_designs is None:
            return False, None

        self._attempt_count += 1
        return sorted_designs == expected, sorted_designs

    @property
    def attempt_count(self) -> int:
        return self._attempt_count

    def get_expected(self, variant: Optional[str] = None) -> Optional[List[int]]:
        v = variant or self._current_variant
        return self._answers.get(v)