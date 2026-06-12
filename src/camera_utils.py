from __future__ import annotations

from typing import Iterable, Optional, Tuple

import cv2


def open_camera(
    preferred_index: Optional[int] = None,
    fallback_indexes: Iterable[int] = (0, 1, 2),
) -> Tuple[cv2.VideoCapture, int]:
    tried = []
    indexes = []

    if preferred_index is not None:
        indexes.append(int(preferred_index))

    for idx in fallback_indexes:
        idx = int(idx)
        if idx not in indexes:
            indexes.append(idx)

    for idx in indexes:
        tried.append(idx)
        cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            return cap, idx
        cap.release()

    raise RuntimeError(
        f"Failed to open camera. Tried indexes: {', '.join(map(str, tried))}"
    )
