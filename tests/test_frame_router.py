#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты FrameRouter (v1.24): стратегия «последний кадр», отбраковка устаревших,
дедупликация одинаковых кадров, быстрый путь, метаданные и координаты.
Запуск: python tests/test_frame_router.py"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

from ai.frame_router import Frame, FrameRouter

fails = []


def check(label, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + label + ("  " + extra if extra else ""))
    if not cond:
        fails.append(label)


def mkframe(i, seed=0):
    img = np.full((120, 160, 3), 30 + seed, np.uint8)
    return Frame(i, time.time(), img, {"left": 0, "top": 0, "width": 160, "height": 120},
                 1.0, 1.0, backend="test", fps=8.0)


print("== 1. Метаданные кадра ==")
f = mkframe(1, 5)
check("id/ts/геометрия/полнота", f.frame_id == 1 and f.mon["width"] == 160 and
      f.sx == 1.0 and f.backend == "test" and abs(f.fps - 8.0) < 1e-9)
check("свежесть (age) растёт от метки времени", 0.0 <= f.age < 5.0, "%.3f" % f.age)
crop = f.region((10, 10, 50, 40))
check("кроп региона", crop is not None and crop.shape == (40, 50, 3))
check("кроп за границей кадра обрезается/None", f.region((150, 100, 500, 500)) is not None
      and f.region((200, 0, 10, 10)) is None)

print("== 2. Стратегия «последний кадр» (backpressure без очереди) ==")
r = FrameRouter(dedup_thr=0.0)                 # дедуп выключен: важен только вытеснитель
r.submit(mkframe(10, 1))
r.submit(mkframe(11, 2))
r.submit(mkframe(12, 3))
g = r.next_slow(0.1)
check("потребитель получил САМЫЙ СВЕЖИЙ кадр", g is not None and g.frame_id == 12)
check("вытесненные кадры посчитаны (не копились в очереди)", r.dropped_stale == 2,
      str(r.stats()))
check("после разбора слот пуст", r.next_slow(0.05) is None)

print("== 3. Дедупликация одинаковых кадров ==")
r2 = FrameRouter(dedup_thr=0.6)
a = r2.submit(mkframe(20, 0))
b = r2.submit(mkframe(21, 0))                  # тот же фон — дубль
c = r2.submit(mkframe(22, 90))                 # яркая засветка — не дубль
check("одинаковый кадр отброшен как дубль", a is True and b is False and
      r2.dropped_dup == 1)
check("изменившийся кадр прошёл", c is True)
g2 = r2.next_slow(0.1)
check("в слоте именно новый кадр", g2.frame_id == 22)

print("== 4. Быстрый путь (мини-игра) не трогает медленный слот ==")
r3 = FrameRouter(dedup_thr=0.0)
fast = []
r3.set_fast_callback(lambda fr: fast.append(fr.frame_id))
r3.submit(mkframe(30, 0), fast=True)
check("колбэк быстрого пути вызван сразу", fast == [30], str(fast))
check("быстрый кадр не попал в медленный слот", r3.next_slow(0.05) is None)

print("== 5. Таймаут потребителя (пусто, не блокируется навсегда) ==")
t0 = time.time()
g3 = r3.next_slow(0.2)
check("next_slow вернулся по таймауту с None", g3 is None and time.time() - t0 < 1.0)

print()
if fails:
    print("FAILED:", len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL FRAME-ROUTER CHECKS PASSED")
