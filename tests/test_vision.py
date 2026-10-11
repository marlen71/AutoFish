import copy
from pathlib import Path

import cv2
import numpy as np

from vision import analyze_bar, analyze_progress, analyze_warning, bounds_from_samples, hsv_mask
from eternal_fishmod import DEFAULT_CFG


CFG = copy.deepcopy(DEFAULT_CFG)


def frame(zone=(230, 340), fish=210):
    bar = np.full((530, 58, 3), (190, 126, 74), np.uint8)  # BGR синий фон
    cv2.rectangle(bar, (1, zone[0]), (56, zone[1]), (20, 210, 135), -1)
    cv2.ellipse(bar, (27, fish), (11, 8), 0, 0, 360, (20, 210, 230), -1)
    return bar


def test_bar_zone_and_multiple_fish_colors():
    for fish in (210, 290, 420):
        b = frame(fish=fish)
        o = analyze_bar(b, CFG)
        assert o.present
        assert o.zone[0] == 230 and o.zone[1] == 340
        assert abs(o.fish_y - fish) < 5


def test_cyan_fish_inside_background_hue_range():
    b = frame(fish=210)
    cv2.ellipse(b, (27, 210), (11, 8), 0, 0, 360, (225, 180, 75), -1)
    o = analyze_bar(b, CFG)
    assert o.present and o.fish_y is not None
    assert abs(o.fish_y - 210) < 5


def test_not_present_without_green():
    b = frame()
    b[:] = (190, 126, 74)
    assert not analyze_bar(b, CFG).present


def test_progress_bottom_up_and_black_outline():
    p = np.zeros((530, 13, 3), np.uint8)
    for height in (0, 130, 260, 520):
        p[:] = 0
        p[526-height:526, 1:12] = 255
        fraction = analyze_progress(p, CFG)
        assert abs(fraction - height / 524) < 0.02


def test_red_warning_not_regular_frame():
    w = np.zeros((115, 345, 3), np.uint8)
    assert not analyze_warning(w, CFG)[0]
    cv2.rectangle(w, (20, 30), (270, 70), (15, 15, 220), -1)
    assert analyze_warning(w, CFG)[0]


def test_hue_wraparound():
    bounds = bounds_from_samples([[178, 220, 210], [2, 220, 215]], [7, 20, 20])
    h = np.uint8([[[179, 220, 210], [1, 220, 210], [80, 220, 210]]])
    assert hsv_mask(h, bounds).tolist() == [[255, 255, 0]]


def test_supplied_rp_screenshots_when_available():
    root = Path(__file__).resolve().parents[1]
    waiting = root / '1791751385077-image.png'
    playing = root / '1791751386672-image.png'
    warning = root / '1791751387184-image.png'
    if not all(p.exists() for p in (waiting, playing, warning)):
        return  # Test still works when screenshots are distributed separately.
    a, b, c = [cv2.imread(str(p)) for p in (waiting, playing, warning)]
    assert not analyze_bar(a[470:1000, 913:971], CFG).present
    o = analyze_bar(b[470:1000, 913:971], CFG)
    assert o.present and 270 < o.fish_y < 325 and o.fish_y < o.zone[0]
    assert 0.4 < analyze_progress(b[470:1000, 984:997], CFG) < 0.6
    assert not analyze_warning(b[640:755, 1035:1380], CFG)[0]
    assert analyze_warning(c[640:755, 1035:1380], CFG)[0]
