from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

# Same aspect ratio as the reference images (5:7 card).
CARD_WIDTH = 600
CARD_HEIGHT = 838

# Detection runs on a downscaled copy: full-resolution phone photos fragment the
# Canny edges badly enough that no card contour survives.
DETECTION_MAX_SIZE = 1600
CARD_ASPECT = (1.15, 2.0)


@dataclass(frozen=True)
class Rectified:
    image: np.ndarray
    found: bool
    corners: np.ndarray | None = None
    source_size: tuple[int, int] = (0, 0)
    rotated: bool = False
    rotation: int = 0


def rectify_file(path: Path) -> Rectified:
    from PIL import Image, ImageOps

    with Image.open(path) as opened:
        rgb = np.array(ImageOps.exif_transpose(opened).convert("RGB"))
    return rectify(rgb[:, :, ::-1].copy())


def rectify(image: np.ndarray) -> Rectified:
    source_size = (image.shape[1], image.shape[0])
    corners = _find_card(image)
    if corners is None:
        return Rectified(image=image, found=False, source_size=source_size)

    top_vector = corners[1] - corners[0]
    top = float(np.linalg.norm(top_vector))
    left = float(np.linalg.norm(corners[3] - corners[0]))
    rotated = top > left
    rotation = 0
    if rotated:
        # The card is sideways in the frame; map its long edge to the height.
        # Clockwise degrees to apply to the original so it stands like a reference.
        rotation = 270 if top_vector[0] >= 0 else 90
        corners = corners[[1, 2, 3, 0]]

    destination = np.array(
        [[0, 0], [CARD_WIDTH - 1, 0], [CARD_WIDTH - 1, CARD_HEIGHT - 1], [0, CARD_HEIGHT - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(corners, destination)
    warped = cv2.warpPerspective(image, matrix, (CARD_WIDTH, CARD_HEIGHT))
    return Rectified(
        image=_normalize(warped),
        found=True,
        corners=corners,
        source_size=source_size,
        rotated=rotated,
        rotation=rotation,
    )


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise OSError(f"could not write image: {path}")


def _find_card(image: np.ndarray) -> np.ndarray | None:
    largest = max(image.shape[0], image.shape[1])
    scale = min(1.0, DETECTION_MAX_SIZE / largest)
    small = (
        cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if scale < 1.0
        else image
    )
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    frame_area = gray.shape[0] * gray.shape[1]

    edges = cv2.Canny(gray, 20, 60)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best: np.ndarray | None = None
    best_area = 0.0
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 0.05 * frame_area or area <= best_area:
            continue
        quad = _quad_from_contour(contour)
        if quad is None or not _plausible_card(quad):
            continue
        best = quad
        best_area = area

    if best is None:
        return None
    corners = _order_corners(best)
    return corners / scale


def _quad_from_contour(contour: np.ndarray) -> np.ndarray | None:
    perimeter = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
    if len(approx) == 4:
        return approx.reshape(4, 2).astype(np.float32)
    hull = cv2.convexHull(contour).reshape(-1, 2).astype(np.float32)
    if len(hull) < 3:
        return None
    # Rounded corners and JPEG blur turn the card into 5+ vertices.
    return _quad_from_hull(hull)


def _plausible_card(quad: np.ndarray) -> bool:
    ordered = _order_corners(quad)
    top = float(np.linalg.norm(ordered[1] - ordered[0]))
    left = float(np.linalg.norm(ordered[3] - ordered[0]))
    ratio = max(top, left) / max(min(top, left), 1e-6)
    return CARD_ASPECT[0] <= ratio <= CARD_ASPECT[1]


def _quad_from_hull(hull: np.ndarray) -> np.ndarray:
    total = hull.sum(axis=1)
    difference = hull[:, 0] - hull[:, 1]
    return np.array(
        [
            hull[np.argmin(total)],
            hull[np.argmax(difference)],
            hull[np.argmax(total)],
            hull[np.argmin(difference)],
        ],
        dtype=np.float32,
    )


def _order_corners(points: np.ndarray) -> np.ndarray:
    ordered = np.zeros((4, 2), dtype=np.float32)
    total = points.sum(axis=1)
    difference = np.diff(points, axis=1).ravel()
    ordered[0] = points[np.argmin(total)]
    ordered[2] = points[np.argmax(total)]
    ordered[1] = points[np.argmin(difference)]
    ordered[3] = points[np.argmax(difference)]
    return ordered


def _normalize(image: np.ndarray) -> np.ndarray:
    """Stretch exposure per channel, then neutralize the color cast of the lamp."""
    values = image.astype(np.float32)
    low = np.percentile(values, 2, axis=(0, 1))
    high = np.percentile(values, 98, axis=(0, 1))
    values = np.clip((values - low) * (255.0 / np.maximum(high - low, 1e-6)), 0, 255)

    means = np.maximum(values.mean(axis=(0, 1)), 1e-6)
    values *= means.mean() / means
    return np.clip(values, 0, 255).astype(np.uint8)
