#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка бэкендов захвата на подставных dxcam / bettercam / mss.

Зачем: на Windows-машине пользователя бот молча уехал в резервный mss (~20 к/с), и
это же утащило за собой мини-игру (ШИМ при 20 к/с превращался в «держать ЛКМ всегда»).
Причины были три, и все три проверяются здесь:
  1) dxcam 0.3.x поменял API (нет output_idxs()/output_dims()/set_region(), у
     start() появился region=, а get_latest_frame() не принимает timeout) — код
     обязан работать с ОБАМИ поколениями;
  2) ошибка импорта/создания камеры обязана быть ВИДНА (иначе «dxcam is not
     installed» вместо настоящих comtypes/DXGI_ERROR_*);
  3) mss больше не подключается сам — только явно (capture_backend="mss").

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
print("== 4. сломанный DXGI: причину видно, mss сам не подключается ==")
mss_calls = []


class NoMss(ef._MssBackend):
    def __init__(self):
        mss_calls.append(1)
        raise AssertionError("mss нельзя подключать автоматически")


real_mss_cls, ef._MssBackend = ef._MssBackend, NoMss

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

# 4c. create() кидает DXGI_ERROR -> текст ошибки доходит до пользователя
boom = make_module("modern", None, [], fail=RuntimeError("DXGI_ERROR_ACCESS_LOST"))
ef._DxcamBackend.module = boom
ef._BettercamBackend.module = make_module("bettercam", None, [], fail=RuntimeError("no output"))
try:
    cap = ef.ScreenCapture("auto", 0)
    check("без DXGI захват НЕ создаётся", False, str(getattr(cap, "backend", "?")))
except ef.Fail as e:
    msg = str(e)
    check("Fail содержит обе причины", "DXGI_ERROR_ACCESS_LOST" in msg and "no output" in msg, msg[:150])
    check("Fail содержит подсказку по починке", "pip install" in msg, msg[-120:])
    check("mss автоматически НЕ подключался", not mss_calls)

# 4d. dxcam сломан, bettercam жив -> auto выбирает bettercam, а не mss
ef._DxcamBackend.module = boom
good = CamBettercam(1920, 1080)
ef._BettercamBackend.module = make_module("bettercam", good, [])
cap = ef.ScreenCapture("auto", 0)
check("auto переключается на второй DXGI-бэкенд", cap.backend == "bettercam", cap.backend)
check("это не считается резервным режимом", cap.is_fallback is False)
check("в fallback_reason осталась причина отказа dxcam", "DXGI_ERROR_ACCESS_LOST" in cap.fallback_reason,
      cap.fallback_reason[:100])
cap.close()

# ------------------------------------------------------------------ 5. явный mss
print("== 5. mss — только явно, и без DeprecationWarning в консоли ==")


class FakeMSS:
    ctor = None
    monitors = [{}, {"left": 0, "top": 0, "width": 1920, "height": 1080}]

    def __init__(self):
        FakeMSS.ctor = "MSS"

    def close(self):
        pass


class OldMss(FakeMSS):
    def __init__(self):
        warnings.warn("mss.mss is deprecated and will be removed in a future release; "
                      "use mss.MSS instead", DeprecationWarning, stacklevel=2)
        FakeMSS.ctor = "mss()"


def make_mss_mod(new_api=True):
    m = types.ModuleType("fake_mss")
    m.monitors = FakeMSS.monitors
    if new_api:
        m.MSS = FakeMSS
    else:
        m.MSS = None

        def legacy():
            return OldMss()
        m.mss = legacy
    return m


ef.mss = make_mss_mod(new_api=True)
ef._MssBackend = real_mss_cls
cap = ef.ScreenCapture("mss", 0)
check("capture_backend=\"mss\" по-прежнему работает (RDP/VM)", cap.backend == "mss" and cap.is_fallback,
      cap.backend)
check("используется новый API mss.MSS()", FakeMSS.ctor == "MSS", str(FakeMSS.ctor))
cap.close()

FakeMSS.ctor = None
ef.mss = make_mss_mod(new_api=False)
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    bg = ef._MssBackend()
    dep = [x for x in w if issubclass(x.category, DeprecationWarning)]
    check("на старом mss DeprecationWarning в консоль не лезет", not dep,
          "; ".join(str(x.message)[:60] for x in dep))
    bg.close()
check("mss-бэкенд умеет хватать монитор", bg.mon["width"] == 1920, str(bg.mon))

# ------------------------------------------------------------------ 6. порядок кандидатов
print("== 6. политика выбора: auto = только DXGI ==")
src = open(os.path.join(ROOT, "eternal_fishmod.py"), encoding="utf-8").read()
i0 = src.index("order = {")
i1 = src.index("\n", src.index("}", i0))
block = src[i0:i1]
check("auto = (dxcam, bettercam) — без mss", '"auto": ("dxcam", "bettercam")' in block, block.strip()[:120])
check("mss доступен только явным значением", '"mss": ("mss",)' in block)
check("никакого «тихого» mss в конце очереди нет", '"dxcam", "mss"' not in src and '"bettercam", "mss"' not in src)
bad_calls = [l.strip() for l in src.splitlines()
             if re.search(r"(?<!return )mss\.mss\(\)", l) and not l.strip().startswith(("#", '"'))]
check("deprecation-шума нет: прямой mss.mss() остался лишь в хелпере _mss_new()",
      not bad_calls, str(bad_calls[:2]))

ef._MssBackend = real_mss_cls
print()
if fails:
    print("FAILED:", len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CAPTURE BACKEND CHECKS PASSED")
