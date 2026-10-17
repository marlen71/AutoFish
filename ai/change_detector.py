# -*- coding: utf-8 -*-
"""Детектор визуальных изменений (v1.24): лёгкий OpenCV, между инференсами.

Это ГЕНЕРАТОР СИГНАЛОВ, а не доказательство семантики: он говорит «здесь и
настолько что-то изменилось», но не «что именно произошло». Устойчивость к
анимации воды/камеры/частиц: гауссово сглаживание, сетка 16x16 клеток, порог с
гистерезисом (клетка должна измениться дважды подряд), вычитание среднего сдвига
яркости (ровная засветка экрана не считается изменением).

Экранная перестановка (loading/переходы) — почти весь экран изменился: отдельный
флаг transition.
"""
import cv2
import numpy as np

GRID = 16                    # клеток по меньшей стороне нормализованной сетки


class ChangeInfo(object):
    __slots__ = ("fraction", "transition", "cells", "motion", "first")

    def __init__(self, fraction=0.0, transition=False, cells=None, motion=(0.0, 0.0), first=False):
        self.fraction = float(fraction)          # доля изменившихся клеток 0..1
        self.transition = bool(transition)
        self.cells = cells or []                 # [(x, y, w, h, score)] в координатах кадра
        self.motion = (float(motion[0]), float(motion[1]))
        self.first = bool(first)


class ChangeDetector(object):
    def __init__(self, cell_px=48, diff_thr=13.0, frac_thr=0.03,
                 transition_frac=0.45, persistence=2, max_cells=6):
        self.cell = int(cell_px)
        self.diff_thr = float(diff_thr)
        self.frac_thr = float(frac_thr)
        self.transition_frac = float(transition_frac)
        self.persistence = max(1, int(persistence))
        self.max_cells = int(max_cells)
        self._prev = None
        self._hot = None                          # клетки, изменённые на прошлом кадре
        self._prev_cells = None                   # центры горячих клеток для оценки смещения

    def _grid(self, bgr):
        g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        g = cv2.GaussianBlur(g, (5, 5), 0)
        H, W = g.shape
        cw = max(8, W // GRID)
        ch = max(8, H // GRID)
        gg = cv2.resize(g, (cw * GRID, ch * GRID), interpolation=cv2.INTER_AREA)
        return gg, cw, ch

    def update(self, bgr):
        """Сравнить с предыдущим кадром -> ChangeInfo (первый кадр — без событий)."""
        if bgr is None or bgr.size == 0:
            return ChangeInfo(first=self._prev is None)
        gg, cw, ch = self._grid(bgr)
        if self._prev is not None and self._prev.shape != gg.shape:
            self._prev = None
        if self._prev is None:
            self._prev = gg
            return ChangeInfo(first=True)
        d = cv2.absdiff(gg, self._prev).astype(np.float32)
        self._prev = gg
        # «Ровная засветка» (гамма/экспозиция): сдвиг большой, но ОДИНАКОВЫЙ везде
        # (низкий разброс) — игнорируем. Смена сцены/оверлей меняют пиксели ПО-
        # РАЗНОМУ (разброс высокий) — это событие/переход.
        d_mean, d_std = float(d.mean()), float(d.std())
        if d_std < 7.0 and d_mean > self.diff_thr:
            return ChangeInfo()
        frac_raw = float((d > self.diff_thr).mean())
        if frac_raw >= self.transition_frac and d_std >= 7.0:
            self._hot = None
            self._prev_cells = None
            return ChangeInfo(fraction=frac_raw, transition=True)
        d -= d.mean()                              # остаток ровного сдвига — долой
        np.clip(d, 0, None, out=d)
        # усреднение по клеткам (GRID x GRID)
        gsum = d.reshape(GRID, d.shape[0] // GRID, GRID, d.shape[1] // GRID).mean(axis=(1, 3))
        hot = gsum > self.diff_thr
        # гистерезис: клетка подтверждена, если горячая и в прошлый раз
        # (persistence=1 — без гистерезиса: сигнал уже на первом кадре)
        confirmed = hot if self.persistence <= 1 else \
            (hot & (self._hot if self._hot is not None else False))
        self._hot = hot
        frac = float(hot.mean())
        # центры подтверждённых клеток -> прямоугольники в координатах кадра
        ys, xs = np.where(confirmed)
        out, motion = [], (0.0, 0.0)
        if len(ys):
            order = np.argsort(-gsum[ys, xs])[:self.max_cells]
            cents = []
            for o in order:
                gy, gx = int(ys[o]), int(xs[o])
                out.append((int(gx * cw), int(gy * ch), int(cw), int(ch),
                            float(gsum[gy, gx])))
                cents.append((gx + 0.5, gy + 0.5))
            if self._prev_cells:
                dx = np.mean([c[0] for c in cents]) - np.mean([p[0] for p in self._prev_cells])
                dy = np.mean([c[1] for c in cents]) - np.mean([p[1] for p in self._prev_cells])
                motion = (float(dx) * cw, float(dy) * ch)
            self._prev_cells = cents
        else:
            self._prev_cells = None
        return ChangeInfo(fraction=frac, transition=False, cells=out, motion=motion)
