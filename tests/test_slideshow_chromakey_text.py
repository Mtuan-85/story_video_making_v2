import numpy as np

from slideshow.renderer import _extract_sticker


def test_extract_sticker_preserves_thin_text_strokes_on_light_background():
    source = np.full((40, 80, 3), 255, dtype=np.uint8)
    # A 1px anti-aliased text-like stroke. Old morph-open erased this.
    source[20, 10:70] = [90, 90, 90]
    polygon = [(0, 0), (79, 0), (79, 39), (0, 39)]

    sticker = _extract_sticker(source, polygon, zone_id=1, bg_color=(255, 255, 255))
    alpha = np.array(sticker.image.split()[3])

    assert alpha[20, 20] > 0
    assert alpha[20, 60] > 0


def test_extract_sticker_preserves_low_contrast_text_near_background():
    source = np.full((40, 80, 3), 255, dtype=np.uint8)
    # Difference from white is only 8 per channel. Old threshold=15 dropped it.
    source[18:22, 10:70] = [247, 247, 247]
    polygon = [(0, 0), (79, 0), (79, 39), (0, 39)]

    sticker = _extract_sticker(source, polygon, zone_id=1, bg_color=(255, 255, 255))
    alpha = np.array(sticker.image.split()[3])

    assert alpha[19, 20] > 0
    assert alpha[19, 60] > 0
