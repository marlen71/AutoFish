#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка бэкендов захвата на подставных dxcam / bettercam / GDI.

Зачем: на машине пользователя бот молча уезжал в медленный путь (~12 мс/кадр), и
это ломало мини-игру (ШИМ превращался в «держать ЛКМ всегда»). Здесь проверяется:
  1) dxcam 0.3.x и 0.0.x (два поколения API) и bettercam работают;
  2) ошибка импорта/создания камеры ВИДНА в тексте Fail (настоящие
     comtypes/DXGI_ERROR_* вместо «dxcam is not installed»);
  3) mss в проекте ВЫРЕЗАН: ни авто-подключений, ни явного режима, ни импорта;
     резерв теперь — собственный GDI-бэкенд (ctypes), тоже с явной причиной
     отказа и подписью в журнале/интерфейсе.

Запуск: python tests/test_capture_backends.py
"""
import os
import re
import sys
import time
import types
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np          # noqa: E402
import eternal_fishmod as ef  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + label + ("  " + extra if extra else ""))
    if not cond:
        fails.append(label)


def good_frame(h, w):
    return np.full((max(1, h), max(1, w), 3), 199, np.uint8)


# ------------------------------------------------------------------ подставные камеры
class CamModern:
    """dxcam 0.3.x: start(region=...), get_latest_frame() БЕЗ timeout,
    grab(region=) запрещён во время потока, set_region/clear_queue нет."""

    def __init__(self, w=1920, h=1080, black=False):
        self.width, self.height = w, h
        self.region = (0, 0, w, h)
        self.log = []
        self.capturing = False
        self.black = black
        self.n_frames = 0

    def _frame(self, region):
        l, t, r, b = region
        h, w = int(b - t), int(r - l)
        if self.black:
            return np.zeros((max(1, h), max(1, w), 3), np.uint8)
        return good_frame(h, w)

    def grab(self, region=None, copy=True, new_frame_only=True):
        self.log.append(("grab", tuple(region) if region else None, new_frame_only))
        if self.capturing and region is not None and tuple(region) != tuple(self.region):
            raise ValueError("grab(region=...) is not supported while capture is running")
        return self._frame(region if region is not None else self.region)

    def start(self, region=None, target_fps=60, video_mode=False, delay=0):
        self.log.append(("start", tuple(region) if region else None, target_fps, video_mode))
        if region:
            self.region = region
        self.capturing = True

    def get_latest_frame(self, copy=True, with_timestamp=False):
        self.n_frames += 1
        time.sleep(0.002)
        f = self._frame(self.region)
        return (f, 1.0) if with_timestamp else f

    def stop(self):
        self.log.append(("stop",))
        self.capturing = False

    def release(self):
        self.log.append(("release",))


class CamLegacy(CamModern):
    """dxcam 0.0.x: set_region(), clear_queue(), get_latest_frame(timeout=)."""

    def set_region(self, region):
        self.log.append(("set_region", tuple(region)))
        self.region = region

    def start(self, target_fps=60, video_mode=False):
        self.log.append(("start", None, target_fps, video_mode))
        self.capturing = True

    def get_latest_frame(self, timeout=None):
        self.n_frames += 1
        time.sleep(0.002)
        return self._frame(self.region)

    def clear_queue(self):
        self.log.append(("clear_queue",))


class CamBettercam(CamModern):
    """bettercam 1.0.0: start(region=...), get_latest_frame() без аргументов."""

    def get_latest_frame(self):
        self.n_frames += 1
        time.sleep(0.002)
        return self._frame(self.region)


ALLOWED = {
    "modern": {"device_idx", "output_idx", "region", "output_color", "max_buffer_len",
               "backend", "processor_backend"},
    "legacy": {"device_idx", "output_idx", "region", "output_color", "max_buffer_len"},
    "bettercam": {"device_idx", "output_idx", "region", "output_color", "nvidia_gpu",
                  "max_buffer_len"},
}


def make_module(kind, cam, calls, fail=None, no_idxs=False):
    """Возвращает поддельный модуль dxcam/bettercam с проверкой допустимых kwargs."""
    m = types.ModuleType("fake_" + kind)

    def create(**kw):
        calls.append(tuple(sorted(kw)))
        bad = [k for k in kw if k not in ALLOWED[kind]]
        if bad:
            raise TypeError("create() got an unexpected keyword argument %r" % bad[0])
        if fail:
            raise fail
        return cam

    m.create = create
    if kind == "legacy" and not no_idxs:
        m.output_idxs = lambda: [0, 1]           # в 0.0.x этот хелпер был
    return m


# ------------------------------------------------------------------ 1. dxcam 0.3.x
print("== 1. dxcam 0.3.x (текущий API на PyPI) ==")
cam = CamModern()
calls = []
mod = make_module("modern", cam, calls)
ef.dxcam = ef._DxcamBackend.module = mod
b = ef._DxcamBackend(0)
check("бэкенд создан на реальном наборе аргументов 0.3.x", b.cam is cam, str(calls[:2]))
check("геометрия взята с выхода камеры", (b.mon["width"], b.mon["height"]) == (1920, 1080), str(b.mon))
img = b.grab(100, 50, 64, 40)
check("region-захват: размер кадра = размеру региона", img.shape == (40, 64, 3), str(img.shape))
check("grab звался с region (не «весь экран + кроп»)", any(g[1] for g in cam.log if g[0] == "grab"))
frames = []
b.start(0, 0, 200, 120, 120, lambda f, ts: frames.append(f))
st = [x for x in cam.log if x[0] == "start"][0]
check("start() получил region= (экономия на захвате только шкалы)", st[1] == (0, 0, 200, 120), str(st[1]))
check("start(video_mode=True)", st[3] is True)
deadline = time.time() + 1.0
while len(frames) < 3 and time.time() < deadline:
    time.sleep(0.01)
check("поток пригоняет кадры в on_frame", len(frames) >= 3, "%d шт." % len(frames))
check("отсутствие timeout у get_latest_frame переживается", b._lkf_kw == {}, str(b._lkf_kw))
b.stop()
check("stop() остановил поток камеры", any(x[0] == "stop" for x in cam.log) and not b.streaming)
b.close()
check("close() освободил дупликацию (release)", any(x[0] == "release" for x in cam.log))

# ------------------------------------------------------------------ 2. dxcam 0.0.x
print("== 2. dxcam 0.0.x (старый API: set_region + timeout) ==")
cam2 = CamLegacy()
calls2 = []
ef.dxcam = ef._DxcamBackend.module = make_module("legacy", cam2, calls2)
b2 = ef._DxcamBackend(0)
check("старый create() подошёл", b2.cam is cam2, str(calls2[:2]))
frames2 = []
b2.start(10, 20, 300, 150, 90, lambda f, ts: frames2.append(f))
check("регион выставлен через set_region (в 0.0.x start его не принимает)",
      ("set_region", (10, 20, 310, 170)) in cam2.log, str([x for x in cam2.log if x[0] == "set_region"]))
deadline = time.time() + 1.0
while len(frames2) < 2 and time.time() < deadline:
    time.sleep(0.01)
check("поток на старом API тоже работает", len(frames2) >= 2, "%d шт." % len(frames2))
check("timeout=1.0 используется, когда он поддерживается", b2._lkf_kw == {"timeout": 1.0}, str(b2._lkf_kw))
b2.close()
check("close() зовёт stop+release и на старом API", any(x[0] == "release" for x in cam2.log))

# ------------------------------------------------------------------ 3. bettercam
print("== 3. bettercam (второй DXGI-бэкенд) ==")
cam3 = CamBettercam(2560, 1440)
calls3 = []
ef.bettercam = ef._BettercamBackend.module = make_module("bettercam", cam3, calls3)
b3 = ef._BettercamBackend(0)
check("bettercam.create() вызван с output_idx+output_color", b3.cam is cam3
      and "output_idx" in calls3[0] and "output_color" in calls3[0], str(calls3[0]))
check("монитор взят с выхода (2560x1440)", (b3.mon["width"], b3.mon["height"]) == (2560, 1440), str(b3.mon))
fr3 = []
b3.start(0, 0, 120, 80, 60, lambda f, ts: fr3.append(f))
starts3 = [x for x in cam3.log if x[0] == "start"]
check("bettercam.start(region=, target_fps=, video_mode=) без callback",
      starts3 and starts3[0][1] == (0, 0, 120, 80) and starts3[0][2] == 60 and starts3[0][3] is True,
      str(starts3[:1]))
deadline = time.time() + 1.0
while len(fr3) < 2 and time.time() < deadline:
    time.sleep(0.01)
check("поток bettercam даёт кадры (callback в 1.0.0 нет)", len(fr3) >= 2, "%d шт." % len(fr3))
b3.close()

# ------------------------------------------------------------------ 4. причины отказа
print("== 4. сломанный DXGI: причину видно, GDI вызывается, mss не существует ==")
gdi_calls = []


class NoGdi(ef._GdiBackend):
    def __init__(self, *a):
        gdi_calls.append(1)
        raise RuntimeError("gdi: нет экрана (подстава в тесте)")


real_gdi_cls, ef._GdiBackend = ef._GdiBackend, NoGdi

# 4a. dxcam не импортирован — в тексте должна быть НАСТОЯЩАЯ причина
ef._DxcamBackend.module = None
ef._CAP_IMPORT_ERR["dxcam"] = "ModuleNotFoundError: No module named 'comtypes'"
try:
    ef._DxcamBackend(0)
    check("без dxcam бэкенд падает", False)
except Exception as e:
    check("причина отказа импорта сохранена в тексте ошибки", "comtypes" in str(e), str(e)[:90])

# 4b. камера создаётся, но кадры чёрные -> отказ с внятной формулировкой
ef._DxcamBackend.module = make_module("modern", CamModern(black=True), [])
try:
    ef._DxcamBackend(0)
    check("чёрный экран считается нерабочим", False)
except Exception as e:
    check("чёрный кадр отбракован и объяснён", "чёрн" in str(e).lower(), str(e)[:120])

# 4c. create() кидает DXGI_ERROR -> текст ошибки доходит до пользователя;
# GDI-кандидат при этом ОБЯЗАН быть попробован (он третий в очереди)
boom = make_module("modern", None, [], fail=RuntimeError("DXGI_ERROR_ACCESS_LOST"))
ef._DxcamBackend.module = boom
ef._BettercamBackend.module = make_module("bettercam", None, [], fail=RuntimeError("no output"))
try:
    cap = ef.ScreenCapture("auto", 0)
    check("без DXGI и GDI захват НЕ создаётся", False, str(getattr(cap, "backend", "?")))
except ef.Fail as e:
    msg = str(e)
    check("Fail содержит обе DXGI-причины", "DXGI_ERROR_ACCESS_LOST" in msg and "no output" in msg, msg[:150])
    check("Fail содержит причину GDI-кандидата", "нет экрана" in msg, msg[:200])
    check("Fail содержит подсказку по починке", "pip install" in msg, msg[-120:])
check("GDI-кандидат был опрошен автоматически (он часть очереди auto)", len(gdi_calls) == 1)

# 4d. dxcam сломан, bettercam жив -> auto выбирает bettercam, а не резерв
ef._DxcamBackend.module = boom
good = CamBettercam(1920, 1080)
ef._BettercamBackend.module = make_module("bettercam", good, [])
cap = ef.ScreenCapture("auto", 0)
check("auto переключается на второй DXGI-бэкенд", cap.backend == "bettercam", cap.backend)
check("это не считается резервным режимом", cap.is_fallback is False)
check("в fallback_reason осталась причина отказа dxcam", "DXGI_ERROR_ACCESS_LOST" in cap.fallback_reason,
      cap.fallback_reason[:100])
cap.close()

# ------------------------------------------------------------------ 5. явный gdi + деградация в полёте
print("== 5. capture_backend=gdi работает; при поломке DXGI в полёте — деградация на GDI ==")


class FakeGdi:
    """Подстава вместо ctypes-реализации: интерфейс тот же."""

    def __init__(self, monitor_idx=0):
        self.mon = {"left": 0, "top": 0, "width": 1920, "height": 1080}
        self.note = "кадр 320x240 (GDI)"
        self.started = []
        self.streaming = False

    def grab(self, left, top, width, height):
        return good_frame(height, width)

    def can_stream(self):
        return True

    def start(self, left, top, width, height, fps, on_frame):
        self.started.append((left, top, width, height, fps))
        self.streaming = True

    def stop(self):
        self.streaming = False

    def close(self):
        self.streaming = False


class BoomGdi(FakeGdi):
    def __init__(self, *a):
        raise RuntimeError("gdi сломан в тесте")


ef._GdiBackend = FakeGdi
cap = ef.ScreenCapture("gdi", 0)
check("capture_backend=\"gdi\" работает", cap.backend == "gdi" and cap.is_fallback, cap.backend)
fr = []
cap.start_stream([900, 400, 120, 200], 30)
cap.wait_frame(0.3)
check("GDI-поток запускается по региону шкалы", cap.streaming and len(cap._bg.started) == 1,
      str(cap._bg.started[:1]))
cap.close()

# деградация в полёте: DXGI-бэкенд умирает на grab() -> ScreenCapture переходит на GDI
class DyingCam(CamModern):
    def grab(self, region=None, **k):
        raise RuntimeError("device removed")


ef._GdiBackend = FakeGdi
ef._DxcamBackend.module = make_module("modern", None, [], fail=RuntimeError("x"))
ef._BettercamBackend.module = make_module("bettercam", DyingCam(1920, 1080), [])
cap = ef.ScreenCapture("auto", 0)
check("стартуем на bettercam", cap.backend == "bettercam" and not cap.is_fallback, cap.backend)
cap.start_stream([900, 400, 120, 200], 60)
cap.grab_region(900, 400, 60, 60)            # DyingCam.grab кидает -> должна сработать деградация
check("поломка DXGI в полёте -> GDI, и это ПОДПИСАНО", cap.backend == "gdi" and cap.is_fallback,
      "%s / %s" % (cap.backend, cap.fallback_reason[:60]))
check("поток поднят заново на GDI", cap.streaming and cap._bg.started, str(cap._bg.started[-1:]))
cap.close()

# на не-Windows настоящий ctypes-GDI обязан отказываться с внятной формулировкой
ef._GdiBackend = real_gdi_cls
if os.name != "nt":
    try:
        ef._GdiBackend(0)
        check("GDI на не-Windows не создаётся", False)
    except Exception as e:
        check("GDI на не-Windows отказывается внятно", "Windows" in str(e), str(e)[:80])

# ------------------------------------------------------------------ 6. политика выбора
print("== 6. политика выбора: auto = dxcam -> bettercam -> gdi, mss вырезан полностью ==")
src = open(os.path.join(ROOT, "eternal_fishmod.py"), encoding="utf-8").read()
i0 = src.index("CANDIDATES = {")
i1 = src.index("}", i0)
block = src[i0:i1]
check("auto = (dxcam, bettercam, gdi)", '"auto": ("dxcam", "bettercam", "gdi")' in block, block.strip()[:120])
check("явный \"gdi\" = только GDI", '"gdi": ("gdi",)' in block)
check("из кода захвата mss исчез целиком (осталась только миграция старого конфига)",
      all(t not in src for t in ("import mss", "_MssBackend", "_mss_new", "mss.mss()", "_degrade_to_mss"))
      and src.count("mss") <= 12, "упоминаний: %d" % src.count("mss"))
check("старое значение capture_backend=\"mss\" мигрирует на auto", '"mss", "no", "dxgpu-dxs"' in src)
check("import mss удалён", "import mss" not in src)
req = open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
check("в requirements.txt нет упоминаний mss", "mss" not in req.lower())
check("в requirements.txt нет dxcam-дублей у bettercam",
      req.count("dxcam>=") == 1 and req.count("bettercam>=") == 1)
launch = open(os.path.join(ROOT, "launch.py"), encoding="utf-8").read()
check("в launch.py mss больше не обязателен", '("mss", "mss", True)' not in launch)

ef._GdiBackend = real_gdi_cls
print()
if fails:
    print("FAILED:", len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CAPTURE BACKEND CHECKS PASSED")
