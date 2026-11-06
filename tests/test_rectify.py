import cv2
import numpy as np

from tcg_scanner.imaging.rectify import CARD_HEIGHT, CARD_WIDTH, rectify


def _card_photo() -> np.ndarray:
    card = np.zeros((CARD_HEIGHT, CARD_WIDTH, 3), np.uint8)
    card[:] = (200, 180, 160)
    cv2.rectangle(card, (10, 10), (CARD_WIDTH - 10, CARD_HEIGHT - 10), (255, 255, 255), 6)
    cv2.putText(card, "CARD", (150, 450), cv2.FONT_HERSHEY_SIMPLEX, 4, (30, 30, 30), 8)

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
