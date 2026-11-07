import cv2
import numpy as np

from tcg_scanner.imaging.rectify import CARD_HEIGHT, CARD_WIDTH, rectify


def _card_image() -> np.ndarray:
    card = np.zeros((CARD_HEIGHT, CARD_WIDTH, 3), np.uint8)
    card[:] = (200, 180, 160)
    cv2.rectangle(card, (10, 10), (CARD_WIDTH - 10, CARD_HEIGHT - 10), (255, 255, 255), 6)
    cv2.putText(card, "CARD", (150, 450), cv2.FONT_HERSHEY_SIMPLEX, 4, (30, 30, 30), 8)
    return card


def _card_photo() -> np.ndarray:
    card = _card_image()

    canvas = np.full((1200, 900, 3), 40, np.uint8)
    source = np.float32(
        [[0, 0], [CARD_WIDTH - 1, 0], [CARD_WIDTH - 1, CARD_HEIGHT - 1], [0, CARD_HEIGHT - 1]]
    )
    target = np.float32([[220, 120], [690, 180], [640, 1060], [150, 990]])
    matrix = cv2.getPerspectiveTransform(source, target)
    warped = cv2.warpPerspective(card, matrix, (900, 1200))
    mask = cv2.warpPerspective(
        np.full((CARD_HEIGHT, CARD_WIDTH), 255, np.uint8), matrix, (900, 1200)
    )
    canvas[mask > 0] = warped[mask > 0]
    return canvas


def test_rectify_finds_a_card_and_returns_the_canonical_size():
    result = rectify(_card_photo())

    assert result.found
    assert result.image.shape == (CARD_HEIGHT, CARD_WIDTH, 3)


def test_rectify_returns_the_original_when_no_card_is_found():
    blank = np.full((300, 300, 3), 128, np.uint8)

    result = rectify(blank)

    assert not result.found
    assert result.image.shape == blank.shape


def test_rectify_handles_a_contour_with_more_than_four_vertices():
    canvas = np.full((900, 700, 3), 30, np.uint8)
    hexagon = np.array(
        [[350, 80], [620, 220], [620, 660], [350, 800], [80, 660], [80, 220]], np.int32
    )
    cv2.fillPoly(canvas, [hexagon], (220, 210, 200))
    cv2.putText(canvas, "CARD", (170, 450), cv2.FONT_HERSHEY_SIMPLEX, 3, (10, 10, 10), 6)

    result = rectify(canvas)

    assert result.found
    assert result.image.shape == (CARD_HEIGHT, CARD_WIDTH, 3)


def test_rectify_rotates_a_sideways_card():
    sideways = cv2.rotate(_card_image(), cv2.ROTATE_90_CLOCKWISE)
    canvas = np.full((900, 1200, 3), 40, np.uint8)
    canvas[150 : 150 + sideways.shape[0], 180 : 180 + sideways.shape[1]] = sideways

    result = rectify(canvas)

    assert result.found
    assert result.rotated
    assert result.rotation in (90, 270)
    assert result.image.shape == (CARD_HEIGHT, CARD_WIDTH, 3)
