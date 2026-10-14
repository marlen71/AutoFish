# -*- coding: utf-8 -*-
"""FrameRouter (v1.24): маршрутизация кадров между быстрым и медленным контурами.

Кадр для AI — это НЕ только картинка: с ним идут id, монотонная метка времени,
геометрия монитора и коэффициенты пересчёта (те же mon/sx/sy, что использует
легаси-захват и ввод — система координат кликов НЕ меняется).

Медленный путь (AI/OCR) — стратегия «последний кадр»: слот на 1 кадр, новый кадр
ВЫТЕСНЯЕТ не разобранный предыдущий (backpressure без неограниченной очереди).
Счётчик dropped показывает, что AI не успевает — и это штатная ситуация.

Быстрый путь (легаси-мини-игра) НЕ проходит через роутер вообще: он живёт в
основном приложении на своём потоке захвата. Роутер лишь даёт ему колбэк.
"""
import threading
import time


class Frame(object):
    """Кадр + метаданные. Владелец изображения явный: image не мутируется."""

    __slots__ = ("frame_id", "ts", "image", "mon", "sx", "sy", "backend", "fps")

    def __init__(self, frame_id, ts, image, mon, sx, sy, backend="", fps=0.0):
        self.frame_id = int(frame_id)
        self.ts = float(ts)
        self.image = image
        self.mon = dict(mon or {})
        self.sx = float(sx)
        self.sy = float(sy)
        self.backend = str(backend)
        self.fps = float(fps)

    @property
    def age(self):
        return time.time() - self.ts

    def region(self, rect):
        """Кроп (x, y, w, h) с ограничением по кадру — для регионального OCR."""
        x, y, w, h = (int(v) for v in rect)
        H, W = self.image.shape[:2]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(W, x + max(1, w)), min(H, y + max(1, h))
        if x1 <= x0 or y1 <= y0:
            return None
        return self.image[y0:y1, x0:x1]


def _tiny_hash(bgr):
    """Дешёвый отпечаток кадра 8x8 (средняя яркость) — для отбраковки дублей."""
    import cv2
    small = cv2.resize(bgr, (8, 8), interpolation=cv2.INTER_AREA)
    return small.mean(axis=2)


class FrameRouter(object):
    def __init__(self, dedup_thr=0.6):
        self._slot = None
        self._evt = threading.Event()
        self._lock = threading.Lock()
        self._last_hash = None
        self.dedup_thr = float(dedup_thr)
        self.submitted = 0
        self.dropped_stale = 0
        self.dropped_dup = 0
        self.fast_count = 0
        self._fast_cb = None

    # ------------------------------------------------------------------ приём
    def set_fast_callback(self, fn):
        """Быстрый путь: fn(Frame) зовётся сразу, в потоке источника кадра."""
        self._fast_cb = fn

    def submit(self, frame, fast=False):
        """Принять кадр. Медленный путь: последний кадр вытесняет неразобранный."""
        self.submitted += 1
        if fast:
            self.fast_count += 1
            if self._fast_cb:
                try:
                    self._fast_cb(frame)
                except Exception:
                    pass
            return True
        h = _tiny_hash(frame.image)
        with self._lock:
            if self._last_hash is not None and self.dedup_thr > 0:
                import numpy as np
                if float(np.abs(h - self._last_hash).mean()) < self.dedup_thr:
                    self.dropped_dup += 1
                    return False                      # кадр не изменился — AI не нужен
            self._last_hash = h
            if self._slot is not None:
                self.dropped_stale += 1               # AI не успел — старый кадр выкинут
            self._slot = frame
        self._evt.set()
        return True

    # --------------------------------------------------------------- потребление
    def next_slow(self, timeout=0.5):
        """Блокирующе взять САМЫЙ СВЕЖИЙ кадр (или None по таймауту)."""
        self._evt.wait(timeout)
        with self._lock:
            fr, self._slot = self._slot, None
        self._evt.clear()
        return fr

    def stats(self):
        with self._lock:
            return {"submitted": self.submitted, "dropped_stale": self.dropped_stale,
                    "dropped_dup": self.dropped_dup, "fast": self.fast_count}
