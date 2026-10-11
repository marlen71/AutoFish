"""Чистый OpenCV-анализ UI рыбалки (без Windows API и GUI).

Все координаты ROI задаются в базовом разрешении 1920x1080; в функцию
передаются уже вырезанные физические пиксели. Никакого OCR.
"""
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Observation:
    zone: tuple | None = None  # top, bottom, center, пиксели относительно bar ROI
    fish_y: float | None = None
    progress: float | None = None  # None = недостаточно данных; 0..1
    warning: bool = False
    warning_score: float = 0.0
    zone_area: int = 0
    fish_area: int = 0
    green_mask: np.ndarray | None = None
    fish_mask: np.ndarray | None = None

    @property
    def present(self):
        return self.zone is not None


def hsv_mask(hsv, bounds):
    """Интервал HSV, в т.ч. циклический диапазон оттенка через 0/179."""
    lo, hi = np.array(bounds[0], np.uint8), np.array(bounds[1], np.uint8)
    if lo[0] <= hi[0]:
        return cv2.inRange(hsv, lo, hi)
    a, b = lo.copy(), hi.copy()
    a[0], b[0] = 0, 179
    return cv2.bitwise_or(cv2.inRange(hsv, lo, b), cv2.inRange(hsv, a, hi))


def bounds_from_samples(samples, tolerance):
    """Пипетка: несколько HSV-точек + запас. Hue учитывает переход 179→0."""
    if not samples:
        raise ValueError('Нет образцов')
    h = np.asarray(samples, dtype=int)
    th, ts, tv = [int(v) for v in tolerance]
    angles = h[:, 0] * 2 * np.pi / 180
    mean = np.arctan2(np.sin(angles).mean(), np.cos(angles).mean()) * 180 / (2 * np.pi)
    unwrapped = ((h[:, 0] - mean + 90) % 180) - 90 + mean
    lo_h, hi_h = int(np.floor(unwrapped.min())) - th, int(np.ceil(unwrapped.max())) + th
    lo = [lo_h % 180, max(0, int(h[:, 1].min()) - ts), max(0, int(h[:, 2].min()) - tv)]
    hi = [hi_h % 180, min(255, int(h[:, 1].max()) + ts), min(255, int(h[:, 2].max()) + tv)]
    if hi_h - lo_h >= 179:
        lo[0], hi[0] = 0, 179
    return [lo, hi]


def _components(mask):
    count, labels, stats, centers = cv2.connectedComponentsWithStats(mask, 8)
    return ((stats[i], centers[i]) for i in range(1, count))


def analyze_bar(bgr, cfg, last_fish=None):
    """Зона по горизонтальному заполнению; рыба — насыщенный чужеродный blob.

    Маска рыбы оставляет пиксели, не относящиеся к фону, зелени и бело-чёрной
    рамке. Малые разрозненные цвета спрайта объединяются close; последнее
    положение помогает не перескакивать на другие анимации.
    """
    o = Observation()
    if bgr is None or min(bgr.shape[:2]) < 8:
        return o
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, w = hsv.shape[:2]
    green = hsv_mask(hsv, cfg['green_hsv'])
    green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    o.green_mask = green
    for st, _ in _components(green):
        x, y, cw, ch, area = map(int, st)
        if (area >= cfg['min_zone_area'] * (w * h / (50 * 529))
                and cw >= w * cfg['zone_width_ratio'] and ch >= cfg['min_zone_height_ratio'] * h
                and area > o.zone_area):
            o.zone = (y, y + ch - 1, y + (ch - 1) / 2)
            o.zone_area = area
    mode = cfg['fish_mode']
    if mode == 'samples':
        fish = hsv_mask(hsv, cfg['fish_hsv'])
    else:
        blue = hsv_mask(hsv, cfg['blue_hsv'])
        # Даже синяя рыба может лежать ВНУТРИ цветового диапазона фона.
        # Сравнение с медианой той же строки отсекает ровный градиент, но
        # сохраняет локально отличающийся спрайт.
        baseline = np.median(bgr[:, w // 5:4 * w // 5], axis=1)[:, None, :]
        different = np.max(np.abs(bgr.astype(np.int16) - baseline), axis=2) >= cfg['fish_row_diff']
        eligible = (hsv[:, :, 1] >= cfg['fish_min_s']) & (hsv[:, :, 2] >= cfg['fish_min_v'])
        fish = np.where(eligible & (green == 0) & ((blue == 0) | different), 255, 0).astype(np.uint8)
    margin = max(1, int(w * cfg['fish_side_margin']))
    fish[:, :margin] = 0
    fish[:, w - margin:] = 0
    # Не объединять рыбу с целым рядом зоны: close только после исключения зелени.
    fish = cv2.morphologyEx(fish, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    o.fish_mask = fish
    candidates = []
    for st, center in _components(fish):
        x, y, cw, ch, area = map(int, st)
        if (cfg['min_fish_area'] * w * h / (50 * 529) <= area <= cfg['max_fish_area_ratio'] * w * h
                and ch >= cfg['min_fish_height_ratio'] * h
                and cw >= cfg['min_fish_width_ratio'] * w):
            score = area if last_fish is None else area / (1 + abs(center[1] - last_fish) / cfg['fish_tracking_radius'])
            candidates.append((score, area, float(center[1])))
    if candidates and o.present:
        _, o.fish_area, o.fish_y = max(candidates)
    return o


def analyze_progress(bgr, cfg):
    """Доля заполненных снизу строк внутри ROI (без чёрной обводки).

    Если нет видимого заполненного столбца, возвращаем 0, но только при
    достаточно тёмном фоне; светлый шум сверху не считается успехом.
    """
    if bgr is None or min(bgr.shape[:2]) < 5:
        return None
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, w = hsv.shape[:2]
    x0 = max(0, int(w * cfg['progress_crop_side']))
    x1 = max(x0 + 1, w - x0)
    # Тёмная нижняя обводка/поле в ROI не должна обнулять заполнение.
    trim = min(h // 8, int(h * cfg['progress_bottom_trim']))
    inner = hsv[:h - trim if trim else h, x0:x1]
    h = inner.shape[0]
    v, s = inner[:, :, 2], inner[:, :, 1]
    bright = (v >= cfg['progress_min_v']) & (s <= cfg['progress_max_s'])
    rows = bright.mean(axis=1) >= cfg['progress_row_ratio']
    # Сплошная последовательность вверх, допускается немного рваных строк.
    count, gap = 0, 0
    for filled in rows[::-1]:
        if filled:
            count += 1
            gap = 0
        elif count and gap < cfg['progress_gap_rows']:
            count += 1
            gap += 1
        else:
            break
    return float(np.clip(count / h, 0, 1))


def analyze_warning(bgr, cfg, template=None):
    if bgr is None or min(bgr.shape[:2]) < 5:
        return False, 0.0
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    red = hsv_mask(hsv, cfg['red_hsv'])
    score = float((red > 0).mean())
    # Текст-шаблон: опционально, не заменяет цветовую проверку.
    matched = 0.0
    if template is not None and all(a >= b for a, b in zip(bgr.shape[:2], template.shape[:2])):
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        matched = float(cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED).max())
    return score >= cfg['warning_red_ratio'] or matched >= cfg['warning_template_threshold'], max(score, matched)


def annotate(bar, progress, obs):
    """Превью без Pillow: две ROI рядом, рамка зоны и отметка рыбы."""
    a = bar.copy()
    if obs.zone:
        cv2.rectangle(a, (1, obs.zone[0]), (a.shape[1] - 2, obs.zone[1]), (0, 255, 0), 2)
    if obs.fish_y is not None:
        cv2.line(a, (0, round(obs.fish_y)), (a.shape[1] - 1, round(obs.fish_y)), (0, 120, 255), 2)
    if obs.warning:
        cv2.rectangle(a, (0, 0), (a.shape[1] - 1, a.shape[0] - 1), (0, 0, 255), 2)
    p = cv2.resize(progress, (max(6, a.shape[1] // 3), a.shape[0]))
    return np.hstack((a, np.zeros((a.shape[0], 4, 3), np.uint8), p))
