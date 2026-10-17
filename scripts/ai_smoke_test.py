#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Офлайн smoke-тест AI-зрения Eternal FishMod (v1.24).

Проверяет окружение и конвейер БЕЗ игры и БЕЗ сети:
  python scripts/ai_smoke_test.py

Что делает:
  1. проверяет зависимости (numpy/opencv обязательны; onnxruntime/rapidocr — опция);
  2. ищет модель в ai/models/manifest.json и проверяет sha256;
  3. гоняет детектор изменений на синтетических кадрах 1920x1080 и меряет время;
  4. если модель есть — меряет инференс детектора на полном экране;
  5. прогоняет VisionPipeline 20 циклов и печатает статус/счётчики.
Никогда не скачивает модели и не выходит в сеть.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def have(mod):
    try:
        __import__(mod)
        return True
    except Exception:
        return False


print("== 1. Зависимости ==")
for m, need in (("numpy", True), ("cv2", True), ("onnxruntime", False), ("rapidocr_onnxruntime", False)):
    ok = have(m)
    print("  %-22s %s" % (m, ("OK" if ok else "НЕТ") + ("" if need or ok else "  (опционально)")))
    if need and not ok:
        print("ОШИБКА: обязательная зависимость отсутствует.")
        sys.exit(1)
if not have("onnxruntime"):
    print("  подсказка: pip install onnxruntime   # включит локальный детектор/OCR")

print("== 2. Модель (ai/models/manifest.json) ==")
from ai.model_manager import ModelManager          # noqa: E402
from ai import config as aicfg                     # noqa: E402
mm = ModelManager(aicfg.ai_models_dir(None))
entry = mm.entry("detector")
if entry is None:
    print("  модели не установлены — это ШТАТНО: бот работает на легаси-зрении.")
    print("  Как подключить модель: docs/AI_VISION.md и datasets/README.md")
else:
    print("  найдено: %s -> %s" % (entry.describe(), mm.validate(entry)))

print("== 3. Детектор изменений на синтетике 1920x1080 ==")
import numpy as np                                  # noqa: E402
import cv2                                          # noqa: E402
from ai.change_detector import ChangeDetector       # noqa: E402
base = np.full((1080, 1920, 3), 40, np.uint8)
noise = (np.arange(1080 * 1920).reshape(1080, 1920) % 90).astype(np.uint8)
base[::7, ::11, 0] = 30 + noise[::7, ::11]            # «текстура» вместо ровной заливки
cd = ChangeDetector()
t0 = time.perf_counter()
n = 0
for i in range(30):
    fr = base.copy()
    if i % 2:
        fr[200 + i * 3:400, 300:800] = (i * 5 % 200, 120, 200)   # «движение»
    cd.update(fr)
    n += 1
dt = (time.perf_counter() - t0) / n * 1000.0
print("  %d кадров 1920x1080 -> %.1f мс/кадр (лёгкий путь, живёт между инференсами)" % (n, dt))

print("== 4. Детектор ONNX (если модель установлена) ==")
if entry is not None and mm.validate(entry) == "ok":
    from ai.detector import make_detector           # noqa: E402
    det, _st = make_detector(mm, conf=0.45)
    if det.ensure_loaded():
        fr = np.full((1080, 1920, 3), 50, np.uint8)
        det.detect(fr, 1)                           # прогрев
        t0 = time.perf_counter()
        k = 0
        while time.perf_counter() - t0 < 1.5:
            det.detect(fr, k)
            k += 1
        wall = time.perf_counter() - t0
        print("  %s: %.1f мс/инференс полного экрана -> %.1f к/с (CPU этой машины)"
              % (entry.file, det.rt.ema_ms, k / wall))
    else:
        print("  модель не загрузилась: %s" % det.status)
else:
    print("  пропущено (модели нет)")

print("== 5. VisionPipeline: 20 циклов наблюдения ==")
from ai.pipeline import VisionPipeline              # noqa: E402
from ai.frame_router import Frame                   # noqa: E402
import tempfile, shutil                             # noqa: E402
tmp = tempfile.mkdtemp()
fid = [0]


def push(img):
    fid[0] += 1
    return Frame(fid[0], time.time(), img, {"left": 0, "top": 0, "width": 1920,
                                            "height": 1080}, 1.0, 1.0, "smoke", 2.0)


ai = dict(aicfg.AI_DEFAULTS)
ai.update({"ai_change_detect": True, "ai_detect_fps": 5.0})
pipe = VisionPipeline(lambda: None, lambda: {}, base_dir=tmp, cfg_getter=lambda: ai)
pipe.start()
for i in range(20):
    img = np.full((1080, 1920, 3), 40, np.uint8)
    if i % 3 == 1:
        img[100:900, 200:1600] = (i * 7 % 200, 80, 160)
    pipe.submit(push(img))
    time.sleep(0.05)
time.sleep(0.8)
st = pipe.get_status()
pipe.stop()
print("  статус: %s | кадров: %s | событий: %s | неизвестных: %s | ошибок модулей: %s"
      % (st["state"], st["frames"], st["events"], st["unknown"], st["errors"]))
print("  диагностика: %s" % st["diag"])
shutil.rmtree(tmp, ignore_errors=True)
ok = st["state"] in ("running", "degraded", "stopped") and st["errors"] == 0
print()
print("SMOKE %s" % ("PASSED" if ok else "FAILED"))
sys.exit(0 if ok else 1)
