from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

# Same aspect ratio as the reference images (5:7 card).
CARD_WIDTH = 600
CARD_HEIGHT = 838


@dataclass(frozen=True)
class Rectified:
    image: np.ndarray
    found: bool
    corners: np.ndarray | None = None
    source_size: tuple[int, int] = (0, 0)


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
    )


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise OSError(f"could not write image: {path}")


def _find_card(image: np.ndarray) -> np.ndarray | None:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    frame_area = gray.shape[0] * gray.shape[1]

    edges = cv2.Canny(gray, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best: np.ndarray | None = None
    best_area = 0.0
    fallback: np.ndarray | None = None
    fallback_area = 0.0
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 0.1 * frame_area:
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) == 4 and area > best_area:
            best = approx.reshape(4, 2).astype(np.float32)
            best_area = area
        elif area > fallback_area:
            # Rounded corners and JPEG blur turn the card into 5+ vertices.
            fallback = cv2.convexHull(contour).reshape(-1, 2).astype(np.float32)
            fallback_area = area

    if best is not None:
        return _order_corners(best)
    if fallback is not None:
        return _order_corners(_quad_from_hull(fallback))
    return None


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
