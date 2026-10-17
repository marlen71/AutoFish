#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты совместимости AI-слоя с легаси (v1.24):
* старый конфиг без ai_* ключей мигрирует аддитивно, значения не теряются;
* vision_equip в режимах ai/hybrid БЕЗ модели честно падает в шаблонный каскад;
* VisionPipeline без модели работает (degraded), события изменений публикуются,
  стопается чисто; detect_once возвращает пусто;
* архитектурный инвариант: в ai/ НЕТ ни одного вызова ввода (мышь/клавиатура).
Запуск: python tests/test_legacy_compatibility.py"""
import io
import json
import os
import sys
import tempfile
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cv2
import numpy as np

import eternal_fishmod as ef

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []


def check(label, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + label + ("  " + extra if extra else ""))
    if not cond:
        fails.append(label)


class FakeCap:
    def __init__(self, img):
        self.img = img
        self.backend = "test"
        self.is_fallback = False
        self.mon = {"left": 0, "top": 0, "width": 1920, "height": 1080}
        self.sx = self.sy = 1.0
        self.fps = 8.0
        self.avg_ms = 6.9
        self.grabs = self.errors = 0
        self.last_grab_ms = 0.001
        self.streaming = False
        self.stream_rect = None
        self.frame = None
        self.frames = 0

    def grab_region(self, l, t, w, h):
        self.grabs += 1
        l, t, w, h = int(l), int(t), int(w), int(h)
        H, W = self.img.shape[:2]
        x0, y0 = max(0, l), max(0, t)
        x1, y1 = min(W, l + w), min(H, t + h)
        if y1 <= y0 or x1 <= y0:
            return np.zeros((1, 1, 3), np.uint8)
        return np.ascontiguousarray(self.img[y0:y1, x0:x1])

    def grab_ref(self, rect):
        x, y, w, h = rect
        return self.grab_region(x, y, w, h)

    def grab_full(self):
        return self.img

    def start_stream(self, rect, fps=None):
        self.streaming = True
        return True

    def stop_stream(self):
        self.streaming = False

    def wait_frame(self, timeout=0.25):
        return self.grab_full(), time.perf_counter()

    def close(self):
        pass


INV = cv2.imread(os.path.join(ROOT, "1791751387911-image.png"))
MENU = cv2.imread(os.path.join(ROOT, "1791751384528-image.png"))
assert INV is not None and MENU is not None

screens = {}
ef.CAP = FakeCap(INV)
ef.P = lambda x, y: (int(x), int(y))
ef.scale = lambda: (1.0, 1.0)
ef.monitor = lambda: ef.CAP.mon
_real_grab = ef.grab


def grab(rect=None):
    ef.CAP.img = screens.get("cur", INV)
    return _real_grab(rect)


ef.grab = grab
ef.grab_px = lambda l, t, w, h: grab((l, t, w, h))
ef.grab_ref = lambda r: grab(r)
ef.LOG_PATH = os.path.join(ROOT, "tests", "legacy.log")
ef.CFG_PATH = os.path.join(ROOT, "tests", "legacy_config.json")
ef.STATS_PATH = os.path.join(ROOT, "tests", "legacy_stats.json")
for p in (ef.LOG_PATH, ef.CFG_PATH):
    if os.path.exists(p):
        os.remove(p)
ef.CFG.clear()
ef.CFG.update(ef.DEFAULT_CFG)
_real_imw = ef.cv2.imwrite
ef.cv2.imwrite = lambda path, img: True
_real_nap = ef.nap
ef.nap = lambda sec: None

print("== 1. Конфиг старой версии (без ai_*): аддитивная миграция ==")
old = {"cfg_version": 10, "lang": "en", "rod_thr": 0.85, "bar": [900, 460, 60, 520],
       "sound_start": True, "ui_scale": 0.8, "cast_macro": "obsolete"}
with open(ef.CFG_PATH, "w", encoding="utf-8") as f:
    json.dump(old, f)
ef.CFG.clear()
ef.CFG.update(ef.DEFAULT_CFG)
ok_load = ef.load_cfg()
check("старый конфиг загрузился", ok_load is True)
check("значения пользователя НЕ потеряны (lang/rod_thr/bar/sound_start)",
      ef.CFG["lang"] == "en" and ef.CFG["rod_thr"] == 0.85 and
      ef.CFG["bar"] == [900, 460, 60, 520] and ef.CFG["sound_start"] is True)
check("ai-ключи получили дефолты v1.26 (наблюдение ON, гибрид)",
      ef.CFG["ai_enabled"] is True and ef.CFG["ai_mode"] == "hybrid" and
      ef.CFG["ai_conf"] == 0.45)
check("устаревший ключ cast_macro чистится", "cast_macro" not in ef.CFG and
      "cast_macro" in ef.CFG_DROPPED)
ef.save_cfg()
saved = json.load(open(ef.CFG_PATH, encoding="utf-8"))
check("save_cfg записал ai-ключи (следующий старт их увидит)", "ai_enabled" in saved and
      "ai_mode" in saved)

print("== 1c. Конфиг РАВНОЙ версии без ai_* (сценарий поля 1.24.1: KeyError ai_mode) ==")
old11 = {"cfg_version": ef.CFG_VERSION, "lang": "ua", "rod_thr": 0.82}
with open(ef.CFG_PATH, "w", encoding="utf-8") as f:
    json.dump(old11, f)
ef.CFG.clear()
ef.CFG.update(ef.DEFAULT_CFG)
ef.CFG_DROPPED.clear()
ok11 = ef.load_cfg()
check("конфиг v11 (версия совпадает) загрузился", ok11 is True)
check("ai-ключи добавлены БЕЗ миграции версии (фикс load_cfg)",
      "ai_mode" in ef.CFG and "ai_enabled" in ef.CFG and
      ef.CFG["ai_mode"] == "hybrid" and ef.CFG["ai_enabled"] is True,
      str(ef.CFG.get("ai_mode")))
check("пользовательские значения не тронуты", ef.CFG["lang"] == "ua" and
      ef.CFG["rod_thr"] == 0.82)

print("== 2. vision_equip: режим ai БЕЗ модели -> честный фолбэк в шаблоны ==")
ef.CFG["lang"] = "ru"
ef.CFG["ai_mode"] = "ai"
ef._AI["det"], ef._AI["det_status"], ef._AI["det_tried"] = None, "", False
screens["cur"] = INV
sent3 = []
_real_hwnd, _real_uiclk = ef._cef_render_hwnd, ef._cef_click_at
ef._cef_render_hwnd = lambda: 7777
ef._cef_click_at = lambda *a: sent3.append(a) or True
screens["cur"] = MENU                                    # после ПКМ откроется меню
ok2 = ef.vision_equip()
check("экипировка ДОшла до конца и без модели", ok2 is True, str(len(sent3)))
check("в журнале честная строка про недоступную модель",
      "шаблонами" in io.open(ef.LOG_PATH, encoding="utf-8").read())
check("фолбэк дал те же координаты (шаблонный каскад)",
      len(sent3) >= 2 and abs(sent3[0][1] - 125) <= 12 and abs(sent3[0][2] - 257) <= 12,
      str(sent3[:1]))

print("== 3. vision_equip: режим hybrid без модели -> тоже работает ==")
ef.CFG["ai_mode"] = "hybrid"
screens["cur"] = MENU                                    # кадр с открытым меню: ПКМ уже «сработал»
sent3.clear()
ef._AI["det_tried"] = True                               # детектор уже «пробовали»
ok3 = ef.vision_equip()
check("гибрид без модели экипирует шаблонами", ok3 is True and len(sent3) >= 2)
ef.CFG["ai_mode"] = "legacy"
ef._cef_render_hwnd, ef._cef_click_at = _real_hwnd, _real_uiclk

print("== 4. VisionPipeline без модели: degraded, события идут, стоп чистый ==")
from ai.pipeline import VisionPipeline
from ai.frame_router import Frame

tmpd = tempfile.mkdtemp()
fid = [0]


def push(img):
    fid[0] += 1
    return Frame(fid[0], time.time(), img, {"left": 0, "top": 0, "width": 1920,
                                            "height": 1080}, 1.0, 1.0, "test", 8.0)


ai_def = dict(ef.DEFAULT_CFG)
ai_def.update({"ai_change_detect": True, "ai_detect_fps": 10.0, "ai_ocr_enabled": False})
pipe = VisionPipeline(lambda: None, lambda: {}, base_dir=tmpd,
                      cfg_getter=lambda: ai_def)
pipe.start()
pipe.submit(push(np.full((1080, 1920, 3), 40, np.uint8)))
img2 = np.full((1080, 1920, 3), 40, np.uint8)
img2[100:500, 100:700] = (200, 90, 160)                  # большое структурное изменение
pipe.submit(push(img2))
t_end = time.time() + 3.0
while time.time() < t_end and pipe.get_status()["frames"] < 2:
    time.sleep(0.05)
st = pipe.get_status()
check("конвейер жив БЕЗ модели (degraded, не упал)", st["state"] == "degraded"
      and st["det_rt"] in ("no_model",), "%s %s" % (st["state"], st["det_rt"]))
check("кадры разобраны, деградация не блокирует цикл", st["frames"] >= 2, str(st["frames"]))
check("изменение кадра опубликовано событием (неизвестным — честно)",
      st["events"] >= 1 and any(e.type == "game.unknown_visual_change"
                                for e in pipe.bus.history(20)),
      str(st["events"]))
check("классификатор не выдумывает состояние без оснований",
      st["state_screen"] == "unknown", str(st["state_screen"]))
check("detect_once без модели возвращает пусто (легаси уйдёт в шаблоны)",
      pipe.detect_once(np.zeros((64, 64, 3), np.uint8)) == [])
pipe.stop()
check("стоп: статус stopped, поток завершён", pipe.state == "stopped" and
      (pipe._thr is None or not pipe._thr.is_alive()))
import shutil
shutil.rmtree(tmpd, ignore_errors=True)

print("== 5. Архитектурный инвариант: ai/ НЕ содержит ввода ==")
bad = []
for name in sorted(os.listdir(os.path.join(ROOT, "ai"))):
    if not name.endswith(".py"):
        continue
    src = io.open(os.path.join(ROOT, "ai", name), encoding="utf-8").read()
    for token in ("SetCursorPos", "SendInput", "keybd_event", "_send_mouse",
                  "mouse_event", "PostMessage", "SendMessage"):
        if token in src:
            bad.append((name, token))
check("в ai/ нет ни мыши, ни клавиатуры, ни сообщений окну", not bad, str(bad))

print("== 6. Встроенный payload ai/ синхронен с каталогом ai/ ==")
import subprocess
r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "embed_ai.py"), "--check"],
                   capture_output=True, text=True, cwd=ROOT)
check("scripts/embed_ai.py --check: payload == ai/ на диске", r.returncode == 0,
      (r.stdout + r.stderr).strip()[:120])

print("== 7. ОДИН файл eternal_fishmod.py самодостаточен (сценарий поля 1.24) ==")
tmpf = tempfile.mkdtemp()
try:
    shutil.copy(os.path.join(ROOT, "eternal_fishmod.py"),
                os.path.join(tmpf, "eternal_fishmod.py"))
    code = (
        "import sys\n"
        "sys.path.insert(0, r'%s')\n"
        "import eternal_fishmod as ef\n"
        "import ai.config, ai.pipeline, ai.detector\n"
        "print('AI_KEYS', len([k for k in ef.DEFAULT_CFG if k.startswith('ai_')]))\n"
        "print('EMBED', len(ef._AI_EMBED_SRC))\n"
        "print('NO_DISK_AI', __import__('os').path.isdir(r'%s/ai'))\n"
        "print('CFG_AI', 'ai_mode' in ef.CFG and 'ai_enabled' in ef.CFG)\n"
    ) % (tmpf, tmpf)
    r2 = subprocess.run([sys.executable, "-c", code], capture_output=True,
                        text=True, cwd=tmpf, timeout=120)
    check("импорт одним файлом БЕЗ каталога ai/ проходит", r2.returncode == 0,
          (r2.stderr or "").strip()[-160:])
    check("из payload поднялись ai-ключи (19) и 16 модулей",
          "AI_KEYS 19" in r2.stdout and "EMBED 16" in r2.stdout and
          "NO_DISK_AI False" in r2.stdout, r2.stdout.strip())
    check("ai-ключи в CFG СРАЗУ после импорта (копия после пополнения дефолтов)",
          "CFG_AI True" in r2.stdout, r2.stdout.strip())
finally:
    shutil.rmtree(tmpf, ignore_errors=True)

print()
if fails:
    print("FAILED:", len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL LEGACY-COMPATIBILITY CHECKS PASSED")
