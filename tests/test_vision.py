#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Локальная проверка зрения/ПИД/локализации без Windows: подменяем CAP кадрами из скриншотов.

Запуск из корня проекта:  python tests/test_vision.py   (нужны opencv-python и numpy; Windows не требуется.)
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import math          # noqa: E402
import cv2           # noqa: E402
import numpy as np   # noqa: E402

import eternal_fishmod as ef  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []


class FakeCap:
    streaming = False

    def __init__(self, img):
        self.img = img
        self.backend = "test"
        self.is_fallback = False
        self.mon = {"left": 0, "top": 0, "width": 1920, "height": 1080}
        self.sx = self.sy = 1.0
        self.fps = 144.0
        self.avg_ms = 6.9
        self.grabs = 0
        self.errors = 0
        self.last_grab_ms = 0.001
        self.stream_rect = None
        self.frame = None
        self.frames = 0
        self.streaming = False

    def grab_region(self, l, t, w, h):
        self.grabs += 1
        l, t, w, h = int(l), int(t), int(w), int(h)
        H, W = self.img.shape[:2]
        x0, y0 = max(0, l), max(0, t)
        x1, y1 = min(W, l + w), min(H, t + h)
        if y1 <= y0 or x1 <= x0:
            return np.zeros((1, 1, 3), np.uint8)
        return np.ascontiguousarray(self.img[y0:y1, x0:x1])

    def grab_ref(self, rect):
        x, y, w, h = rect
        return self.grab_region(x * self.sx, y * self.sy, w * self.sx, h * self.sy)

    def grab_full(self):
        return self.img

    def stop_stream(self):
        self.streaming = False


def shot(name):
    import cv2
    img = cv2.imread(os.path.join(ROOT, name), cv2.IMREAD_COLOR)
    assert img is not None, name
    return img


def set_screen(img):
    ef.CAP = FakeCap(img)
    ef._tpl_cache.clear()


def check(label, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + label + ("  " + extra if extra else ""))
    if not cond:
        fails.append(label)


print("== 1. analyze(): зона / рыба / срыв на реальных скриншотах ==")
for fn, expect_slip, want_zone in (("1791751386010-image.png", False, (720, 819)),
                                   ("1791751386672-image.png", False, (756, 1000)),
                                   ("1791751387184-image.png", True, (769, 1000))):
    set_screen(shot(fn))
    rect, inner = ef.bar_rects()
    r = ef.analyze(ef.grab(rect), inner)
    z, f_ = r["zone"], r["fish"]
    print(f"  {fn}: zone={z} fish={f_} slip={r['slip']:.2f} area={r['area']}")
    check(f"{fn}: зона найдена", z is not None)
    check(f"{fn}: рыба найдена", f_ is not None)
    check(f"{fn}: срыв = {expect_slip}", (r["slip"] >= ef.CFG["slip_thr"]) == expect_slip, f"score={r['slip']:.2f}")
    if z and f_ is not None:
        check(f"{fn}: координаты внутри шкалы", 0 <= f_ <= r["ih"] and 0 <= z[0] <= z[1] <= r["ih"], f"ih={r['ih']}")

print("== 2. Шаблоны (find/find_all) по инвентарю и HUD ==")
set_screen(shot("1791751387911-image.png"))
m = ef.find("rod")
check("rod найден", m is not None, str(m))
check("rod: позиция = слот (0,0)", m is not None and abs(m[1] - 126) < 40 and abs(m[2] - 256) < 40, str(m))
check("bait: >=1 стак", len(ef.find_all("bait")) >= 1, f"{len(ef.find_all('bait'))} шт")
check("inv_header виден", ef.find("inv_header") is not None)
set_screen(shot("27033efd-f8b1-489a-97b3-64f476efafbf.png"))
for n in ("hud_fish", "hud_bait", "hud_shield"):
    check(f"{n} виден в HUD", ef.find(n) is not None, f"score={ef.best_score(n)}")
check("inv_header НЕ виден вне инвентаря", ef.find("inv_header") is None)
set_screen(shot("1791751385077-image.png"))
check("rod не ложно-срабатывает на игровом экране", ef.best_score("rod") < ef.THR["rod"], f"{ef.best_score('rod'):.2f}")

print("== 3. Макро-закид (v1.12) + сканер наживки: конфиг, миграция, NMS ==")


class _Cap3:
    """Полный «экран» = img; координаты 1:1."""
    def __init__(self, img):
        self.img = img
        self.mon = {"left": 0, "top": 0, "width": img.shape[1], "height": img.shape[0]}
        self.sx = self.sy = 1.0
        self.backend, self.is_fallback, self.fps, self.avg_ms = "test", False, 0.0, 0.0
        self.streaming, self.stream_rect, self.frames = False, None, 0

    def grab_region(self, l, t, w, h):
        H, W = self.img.shape[:2]
        x0, y0 = max(0, int(l)), max(0, int(t))
        x1, y1 = min(W, int(l) + int(w)), min(H, int(t) + int(h))
        if y1 <= y0 or x1 <= x0:
            return None
        return self.img[y0:y1, x0:x1]

    def grab_ref(self, rect):
        x, y, w, h = rect
        return self.grab_region(x, y, w, h)

    def grab_full(self):
        return self.img


check("жёстких координат закида больше нет в DEFAULT_CFG",
      not [k for k in ("rod_click_pos", "use_click_pos", "rod_match_min", "move_time",
                       "use_menu_delay", "rod_retry_delay") if k in ef.DEFAULT_CFG])
check("макро по умолчанию не записано", ef.DEFAULT_CFG["cast_macro"] is None)
check("устаревшие ключи закида в REMOVED_CFG_KEYS",
      all(k in ef.REMOVED_CFG_KEYS for k in ("rod_click_pos", "use_click_pos", "rod_match_min",
                                             "move_time", "use_menu_delay", "rod_retry_delay")))

INV3 = cv2.imread(os.path.join(ROOT, "1791751387911-image.png"))
GAME3 = cv2.imread(os.path.join(ROOT, "27033efd-f8b1-489a-97b3-64f476efafbf.png"))
assert all(x is not None for x in (INV3, GAME3))

_tmp3 = os.path.join(ROOT, "tests", "vision_tpl")
os.makedirs(_tmp3, exist_ok=True)
import shutil as _shutil
for _n in ("rod", "bait", "inv_header", "hud_fish", "hud_bait", "hud_shield"):
    _src = os.path.join(ROOT, "templates", _n + ".png")
    if os.path.exists(_src):
        _shutil.copy(_src, os.path.join(_tmp3, _n + ".png"))
ef.TPL_DIR = _tmp3
ef.CFG["tpl_selflearn"] = False
ef.CAP = _Cap3(INV3)
ef.scale = lambda: (1.0, 1.0)
ef.monitor = lambda: ef.CAP.mon

# --- наживка: сканер всего экрана, стеки через NMS ---
_hits = ef._match_scales(cv2.cvtColor(INV3, cv2.COLOR_BGR2GRAY), ef._tpl_trimmed("bait"),
                         max_n=24, thr=0.93, with_f=True)
check("наживка: >= 5 стеков на инвентаре (порог 0.93, весь экран)", len(_hits) >= 5, f"{len(_hits)} стеков")
_hits_g = ef._match_scales(cv2.cvtColor(GAME3, cv2.COLOR_BGR2GRAY), ef._tpl_trimmed("bait"),
                           max_n=24, thr=0.93, with_f=True)
check("наживка: в игровом кадре ложных стеков нет", len(_hits_g) == 0, f"{len(_hits_g)}")

# --- конфиг: миграция на v9 и санитизация макро ---
import json as _json
tmp3 = os.path.join(ROOT, "tests", "vision_cfg.json")
ef.CFG_PATH = tmp3
with open(tmp3, "w", encoding="utf-8") as f:
    _json.dump({"cfg_version": 8, "rod_click_pos": [126, 256], "use_menu_delay": 1.0,
                "move_time": 0.3, "lang": "ru"}, f)
ef.CFG_DROPPED.clear()
ef.CFG_MIGRATED.clear()
ef.CFG.clear()
ef.CFG.update(ef.DEFAULT_CFG)
ef.load_cfg()
check("конфиг v8 мигрирует: старые ключи закида удалены",
      all(k not in ef.CFG for k in ("rod_click_pos", "use_click_pos", "use_menu_delay",
                                    "move_time", "rod_match_min")),
      str(sorted(ef.CFG_DROPPED)[:6]))
check("...а cast_macro добавлен дефолтом (None)", ef.CFG["cast_macro"] is None)
with open(tmp3, "w", encoding="utf-8") as f:
    _json.dump({"cfg_version": 9, "cast_macro": "мусор", "lang": "ru"}, f)
ef.CFG.clear()
ef.CFG.update(ef.DEFAULT_CFG)
ef.load_cfg()
check("битое макро -> None, без падений", ef.CFG["cast_macro"] is None)
_good = [[0.0, "move", 10, 20], [0.5, "down", "r"], [0.7, "up", "r"]]
with open(tmp3, "w", encoding="utf-8") as f:
    _json.dump({"cfg_version": 9, "cast_macro": _good, "lang": "ru"}, f)
ef.CFG.clear()
ef.CFG.update(ef.DEFAULT_CFG)
ef.load_cfg()
check("корректное макро переживает загрузку конфига", ef.CFG["cast_macro"] == _good)
os.remove(tmp3)
_shutil.rmtree(_tmp3, ignore_errors=True)

print("== 4. relay_decide: реле с предсказанием останова, гистерезис ==")
A_UP, G_DN, VMAX, LOOK, HYST = 1750.0, 800.0, 850.0, 0.17, 12.0
d = ef.relay_decide
check("рыба НИЖЕ зоны -> не держим (зона должна падать)",
      not d(100.0, 0.0, 400.0, False, A_UP, G_DN, VMAX, LOOK, HYST))
check("рыба ВЫШЕ зоны -> держим",
      d(400.0, 0.0, 100.0, False, A_UP, G_DN, VMAX, LOOK, HYST))
check("зону несёт вверх МИМО цели при зажатой ЛКМ -> отпустить",
      not d(300.0, -500.0, 340.0, True, A_UP, G_DN, VMAX, LOOK, HYST))
check("зона падает на цель с большой скоростью -> зажать ЗАРАНЕЕ (тормозим у цели)",
      d(340.0, 500.0, 400.0, False, A_UP, G_DN, VMAX, LOOK, HYST))
check("на цели и будущее равно: состояние сохраняется (гистерезис, нет дребезга)",
      d(400.0, 0.0, 400.0, True, 800.0, 800.0, VMAX, LOOK, HYST)
      and not d(400.0, 0.0, 400.0, False, 800.0, 800.0, VMAX, LOOK, HYST))
check("на цели при асимметричной физике (a_up > g): ЛКМ отпускается — падать выгоднее",
      not d(400.0, 0.0, 400.0, True, A_UP, G_DN, VMAX, LOOK, HYST))
check("предел скорости учитывается в предсказании",
      d(100.0, 0.0, 529.0, False, A_UP, G_DN, 300.0, LOOK, HYST)
      == d(100.0, 0.0, 529.0, False, A_UP, G_DN, 300.0, LOOK, HYST + 0.01))

print("== 5. Замкнутый цикл: инерционная модель «ЛКМ = ускорение зоны» ==")
H = 529
V_UP, V_DN = 1750.0, 640.0                  # ускорение зоны: зажали / отпустили (px/с^2)
VMAX_UP, VMAX_DN = 660.0, 540.0
FRAME_DT = 1.0 / 144.0
rng = np.random.RandomState(7)
st = {"t": 0.0, "y": 430.0, "vy": 0.0, "fish": 260.0, "fv": 60.0, "held": False, "worst": 0.0, "sum": 0.0,
      "n": 0, "in_zone": 0, "errs": [], "toggles": 0, "slip": False}


def step(dt):
    st["vy"] = min(max(st["vy"] + (-V_UP if st["held"] else V_DN) * dt, -VMAX_UP), VMAX_DN)
    st["y"] += st["vy"] * dt                               # зона разгоняется: ЛКМ = усилие
    if st["y"] < 55.0:
        st["y"], st["vy"] = 55.0, max(0.0, st["vy"]) * 0.2
    if st["y"] > H - 55.0:
        st["y"], st["vy"] = H - 55.0, min(0.0, st["vy"]) * 0.2
    # рыба плавно рыскает (как в игре): сумма двух синусоид + лёгкий шум
    t_ = st["t"]
    st["fv"] = float(min(360.0, max(-360.0,
              230.0 * np.sin(0.55 * t_ + 1.0) + 150.0 * np.sin(1.35 * t_ + 4.0) + rng.normal(0, 22))))
    st["fish"] += st["fv"] * dt
    if st["fish"] < 70.0 or st["fish"] > H - 70.0:
        st["fish"] = min(H - 70.0, max(70.0, st["fish"]))
    e = abs(st["y"] - st["fish"])
    if st["t"] >= 0.6:                      # метрики УДЕРЖАНИЯ: после выхода на режим
        st["worst"] = max(st["worst"], e)
        st["sum"] += e
        st["n"] += 1
        st["in_zone"] += 1 if e < 55 else 0
        st["errs"].append(e)


def phys_frame():
    img = np.full((H + 44, 94, 3), (200, 150, 60), np.uint8)
    if st.get("slip"):
        img[:, 0:21] = (30, 30, 210)
        img[:, 73:94] = (30, 30, 210)
    top, bot = int(st["y"] - 55), int(st["y"] + 55)
    img[max(0, 22 + top):min(H + 44, 22 + bot), 22:72] = (60, 200, 60)
    fy = int(st["fish"])
    for dy in range(-13, 14):
        yy = 22 + fy + dy
        if 0 <= yy < img.shape[0]:
            wd = int(20 - abs(dy) * 1.2)
            img[yy, max(22, 47 - wd):min(72, 47 + wd)] = (30, 180, 240) if abs(dy) < 11 else (18, 60, 90)
    return img


class VT:
    def perf_counter(self):
        return st["t"]

    def sleep(self, sec):
        st["t"] += max(0.0, sec or 0.0)

    def time(self):
        return st["t"]

    def strftime(self, fmt, *a):
        return "00:00:00"


class PhysCap(FakeCap):
    streaming = True

    def grab_region(self, l, t, w, h):
        return phys_frame()

    def grab_ref(self, rect):
        return phys_frame()

    def start_stream(self, *a, **k):
        return True

    def stop_stream(self):
        pass

    def wait_frame(self, timeout=0.25):
        st["t"] += FRAME_DT
        step(FRAME_DT)
        return phys_frame(), st["t"]


ef.time = VT()
ef.LOG_PATH = os.path.join(ROOT, "tests", "test.log")
ef.CAP = PhysCap(np.zeros((1080, 1920, 3), np.uint8))
ef.CAP.fps = 144.0
ef._send_mouse = lambda flags, dx=0, dy=0: (st.__setitem__("held", flags == ef.MOUSEEVENTF_LEFTDOWN),
                                            st.__setitem__("toggles", st["toggles"] + 1))
ef.check_stop = lambda: None
real_analyze = ef.analyze
counter = [0]


def counting_analyze(bgr, inner=None):
    counter[0] += 1
    if counter[0] > 1400:
        raise ef.Stopped()
    return real_analyze(bgr, inner)


ef.analyze = counting_analyze


def run(label):
    st.update({"t": 0.0, "y": 430.0, "vy": 0.0, "fish": 260.0, "fv": 60.0, "worst": 0.0, "sum": 0.0, "n": 0,
               "in_zone": 0, "errs": [], "toggles": 0})
    ef.RELAY_PHYS.update({"up": None, "dn": None, "n": 0, "logged": False})
    ef.CAP.streaming = True
    counter[0] = 0
    try:
        ef.play_minigame()
    except ef.Stopped:
        pass
    n = max(1, st["n"])
    avg = st["sum"] / n
    p95 = float(np.percentile(st["errs"], 95)) if st["errs"] else 0.0
    inz = 100.0 * st["in_zone"] / n
    dur = max(0.01, st["t"])
    print(f"  {label}: avg={avg:5.1f}px p95={p95:5.1f} worst={st['worst']:5.1f} в_зоне={inz:5.1f}% "
          f"перекл/с={st['toggles'] / dur:5.1f}")
    return avg, p95, inz, st["toggles"] / dur


avg, p95, inz, tps = run("реле (дефолтные параметры)")
check("РЕЛЕ: средняя ошибка < 40 px", avg < 40.0, f"avg={avg:.1f}")
check("РЕЛЕ: в зоне >= 60% времени", inz >= 60.0, f"{inz:.1f}%")
check("РЕЛЕ: p95 < 140 px", p95 < 140.0, f"p95={p95:.1f}")
check("ЛКМ: <= 130 событий/с", tps <= 130.0, f"{tps:.1f}/с")

print("  сетка параметров (дефолты не должны быть хуже разумных):")
best = [1e9, None]
for look in (240, 300, 360):
    for hyst in (8.0, 12.0, 18.0):
        ef.CFG.update(relay_look_ms=look, relay_hyst=hyst)
        a3, _p3, _i3, _t3 = run("cfg look=%s hyst=%s" % (look, hyst))
        if a3 < best[0]:
            best[0], best[1] = a3, (look, hyst)
ef.CFG.update(relay_look_ms=300, relay_hyst=12.0)
print(f"  лучший в сетке: look={best[1][0]} hyst={best[1][1]} -> avg={best[0]:.1f} px")
check("дефолтные параметры в пределах 1.5x от лучших в сетке", avg <= 1.5 * best[0] + 2.0,
      f"default avg={avg:.1f} vs best={best[0]:.1f}")

print("  аварийный режим (красная рамка = «РЫБА СРЫВАЕТСЯ»)")
st["slip"] = True


def phys_frame_slip():
    img = phys_frame()
    img[:, 0:21] = (30, 30, 210)          # красная рамка с двух сторон (BGR: R=210)
    img[:, 73:94] = (30, 30, 210)
    return img


ef.CAP.grab_region = lambda l, t, w, h: phys_frame_slip()
ef.CAP.grab_ref = lambda rect: phys_frame_slip()
def wf_slip(timeout=0.25):
    st["t"] += FRAME_DT
    step(FRAME_DT)
    return phys_frame_slip(), st["t"]


ef.CAP.wait_frame = wf_slip
ef.CAP.streaming = True
st.update({"t": 0.0, "y": 470.0, "fish": 150.0, "fv": 0.0, "worst": 0.0, "sum": 0.0, "n": 0,
           "in_zone": 0, "errs": [], "toggles": 0})
counter[0] = 0
seen_emerg = [False]
ever_pressed = [False]
real_play_frame = ef.analyze


def spy(bgr, inner=None):
    r = real_play_frame(bgr, inner)
    if r["slip"] >= ef.CFG["slip_thr"]:
        seen_emerg[0] = True
    ever_pressed[0] = ever_pressed[0] or bool(ef.CTL_VIEW.get("press", False))
    return r


ef.analyze = spy
try:
    ef.play_minigame()
except ef.Stopped:
    pass
ef.analyze = counting_analyze
check("красная рамка распознаётся как срыв", seen_emerg[0], f"mode={ef.CTL_VIEW.get('mode')}")
check("в аварийном режиме ЛКМ зажимается (догоняем рыбу)", ever_pressed[0])
check("аварийный режим выводит зону к рыбе", st["sum"] / max(1, st["n"]) < 60.0,
      f"avg={st['sum'] / max(1, st['n']):.1f}")
st["slip"] = False
ef.CAP.grab_region = lambda l, t, w, h: phys_frame()
ef.CAP.grab_ref = lambda rect: phys_frame()
def wf_norm(timeout=0.25):
    st["t"] += FRAME_DT
    step(FRAME_DT)
    return phys_frame(), st["t"]


ef.CAP.wait_frame = wf_norm

# ---------------------------------------------------------------- 5B. низкий FPS и «полка»
print("== 5B. Низкий FPS захвата (20 к/с) и зона, упершаяся в верх шкалы ==")
# Это ровно та комбинация, из-за которой бот «тупо зажимал ЛКМ»: при ШИМ-окне 22 мс
# и шаге цикла 50 мс решение всегда принималось в начале окна, и любое duty>0
# превращалось в бессрочное удержание. Плюс зона, прижатая к верху, продолжала
# «держаться», хотя опускать её былоединственный способ вернуться к рыбе.
held_samples = []
ceiling_log = []
iter_limit = [0]
real_mouse = ef._send_mouse


def spy_hold(bgr, inner=None):
    iter_limit[0] += 1
    if iter_limit[0] > 120:
        raise ef.Stopped()
    return real_analyze(bgr, inner)


def mouse_rec(flags, dx=0, dy=0):
    """Логируем САМО РЕШЕНИЕ, пока зона прижата к верху: это и есть различие «отпустить»
    против «бессрочно держать» (на старом коде зона с полки не уходила вообще)."""
    st["held"] = (flags == ef.MOUSEEVENTF_LEFTDOWN)
    st["toggles"] += 1
    st["ymax"] = max(st.get("ymax", 0.0), st["y"])
    if st["y"] <= 56.0:
        ceiling_log.append(1.0 if flags == ef.MOUSEEVENTF_LEFTDOWN else 0.0)
    else:
        held_samples.append(1.0 if st["held"] else 0.0)


FRAME_DT = 1.0 / 20.0                       # «резервный» захват / тяжёлая машина
ef.CAP.fps = 20.0
ef.analyze = spy_hold
st.update({"t": 0.0, "y": 300.0, "fish": 300.0, "fv": 0.0, "worst": 0.0, "sum": 0.0, "n": 0,
           "in_zone": 0, "errs": [], "toggles": 0})
counter[0] = 0
held_samples.clear()
iter_limit[0] = 0
ef._send_mouse = mouse_rec
try:
    ef.play_minigame()
except ef.Stopped:
    pass
ef._send_mouse = real_mouse
frac = sum(held_samples) / max(1, len(held_samples))
check("20 к/с: регулятор переключает ЛКМ, а не «держит всегда»", 0.10 < frac < 0.85,
      f"доля удержания={frac:.2f}, avg={st['sum'] / max(1, st['n']):.1f}px")
check("20 к/с: зона всё-таки следует за рыбой (avg < 90 px)", st["sum"] / max(1, st["n"]) < 90.0,
      f"avg={st['sum'] / max(1, st['n']):.1f}")

# зона упёрта в верх, рыба чуть ниже -> удерживать бессмысленно, надо отпускать
st["slip"] = True
st.update({"t": 0.0, "y": 55.0, "vy": 0.0, "fish": 150.0, "fv": 0.0, "worst": 0.0, "sum": 0.0, "n": 0,
           "in_zone": 0, "errs": [], "toggles": 0})
counter[0] = 0
held_samples.clear()
ceiling_log.clear()
iter_limit[0] = 0
ef._send_mouse = mouse_rec
try:
    ef.play_minigame()
except ef.Stopped:
    pass
ef._send_mouse = real_mouse
frac2 = sum(ceiling_log) / max(1, len(ceiling_log))
check("полка сверху + рыба ниже: на полке ЛКМ НЕ держим", len(ceiling_log) >= 2 and frac2 < 0.2,
      f"решений на полке={len(ceiling_log)}, доля удержания={frac2:.2f}")
# главное — зона НЕ прилипает к полке и едет к рыбе (на 20 к/с она может
# и перелететь по инерции — проверяем сам факт движения вниз, а не конечную точку)
check("полка сверху: зона опускается к рыбе", st.get("ymax", 0.0) > 110.0,
      f"макс спуск={st.get('ymax', 0.0):.0f}, y в конце={st['y']:.0f}")
st["slip"] = False
FRAME_DT = 1.0 / 144.0
ef.CAP.fps = 144.0
ef.analyze = counting_analyze

print("== 6. Локализация: полнота набора и форматирование ==")
for lang in ef.STRINGS:
    ef.CFG["lang"] = lang
    miss = [k for k in ef.STRINGS["ru"] if k not in ef.STRINGS[lang]]
    check(f"{lang}: все ключи на месте", not miss, str(miss[:5]))
    empty = [k for k, v in ef.STRINGS[lang].items() if not str(v).strip()]
    check(f"{lang}: нет пустых строк", not empty, str(empty[:5]))
    badfmt = [k for k, v in ef.STRINGS[lang].items()
              if ("{" in v) != ("{" in ef.STRINGS["ru"].get(k, "")) or
              (v.count("{") != ef.STRINGS["ru"].get(k, "").count("{"))]
    check(f"{lang}: набор полей формата совпадает с ru", not badfmt, str(badfmt[:5]))
ef.CFG["lang"] = "en"
check("t(): данные подставляются (en)", "Caught #7" in ef.t("log_caught", n=7, dur=1.23), ef.t("log_caught", n=7, dur=1.23))
ef.CFG["lang"] = "ua"
check("t(): данные подставляются (ua)", "Спіймано #7" in ef.t("log_caught", n=7, dur=1.23), ef.t("log_caught", n=7, dur=1.23))
ef.CFG["lang"] = "ru"
check("t(): неизвестный ключ возвращает сам ключ", ef.t("nope_not_here") == "nope_not_here")
ef.set_state("st_stopped", "st_idle_d", "idle")
check("set_state/состояния переводятся при отображении (ru)", ef.state_text()[0] == "ОСТАНОВЛЕНО")
ef.CFG["lang"] = "en"
check("то же состояние переводится на лету (en)", ef.state_text()[0] == "STOPPED", ef.state_text()[0])
ef.CFG["lang"] = "ua"
check("то же состояние переводится на лету (ua)", ef.state_text()[0] == "ЗУПИНЕНО", ef.state_text()[0])
ef.CFG["lang"] = "ru"
ef.CFG["lang"] = "de"           # несуществующий язык -> не падаем
check("t(): неизвестный язык -> откат на ru", ef.t("st_stopped") == "ОСТАНОВЛЕНО")
ef.CFG["lang"] = "ru"
check("все PAGE_KEYS существуют", all(k in ef.STRINGS["ru"] for pr in ef.PAGE_KEYS for k in pr))
check("все TEMPLATE_LABEL_KEYS существуют", all(v in ef.STRINGS["ru"] for v in ef.TEMPLATE_LABEL_KEYS.values()))
used = set()
src = open(os.path.join(ROOT, "eternal_fishmod.py"), encoding="utf-8").read()
import re as _re
used = set(_re.findall(r'\bt\("([a-z0-9_]+)"', src)) | set(_re.findall(r'set_state\("([a-z0-9_]+)"', src)) \
    | set(_re.findall(r'set_state\("[a-z_0-9]+",\s*"([a-z_0-9]+)"', src)) | set(_re.findall(r'notify\("([a-z_0-9]+)"', src))
used.discard("reason_")
missing = sorted(k for k in used if k not in ef.STRINGS["ru"])
check("нет обращений к несуществующим ключам", not missing, str(missing))

print("== 7. Конфиг: миграция старого файла, сохранение версии ==")
tmp = os.path.join(ROOT, "tests", "fishmod_config.json")
ef.CFG_PATH = tmp
with open(tmp, "w", encoding="utf-8") as f:
    json.dump({"bar": [1, 2, 3, 4], "lang": "ru", "cfg_version": 1, "volume": 33, "junk": 1,
               "pid_kp": 1.8, "pwm_hz": 45.0, "vel_gain": 5.0}, f)
ef.reset_cfg()
ef.CFG_DROPPED.clear()
check("старый конфиг читается", ef.load_cfg() is True)
check("ключи ПИД v1.3-1.5 удалены с пометкой", "pid_kp" not in ef.CFG and "pid_kp" in ef.CFG_DROPPED
      and "pwm_hz" in ef.CFG_DROPPED and "vel_gain" in ef.CFG_DROPPED)
check("значения пользователя сохранены", ef.CFG["bar"] == [1, 2, 3, 4] and ef.CFG["volume"] == 33)
check("новые ключи добавлены дефолтами", ef.CFG["relay_look_ms"] == ef.DEFAULT_CFG["relay_look_ms"] and "junk" not in ef.CFG)
check("save_cfg() пишет cfg_version/app_version", ef.save_cfg() and
      json.load(open(tmp, encoding="utf-8"))["cfg_version"] == ef.CFG_VERSION)
ef.reset_cfg()
check("reset_cfg возвращает дефолты", ef.CFG["bar"] == ef.DEFAULT_CFG["bar"])
saved = json.load(open(tmp, encoding="utf-8"))
check("relay-ключи сериализуются в JSON", all(k in saved for k in ("relay_look_ms", "relay_a_up", "relay_g", "lang", "capture_backend")))
check("устаревшие ключи в файл не возвращаются", "pid_kp" not in saved and "pwm_hz" not in saved)
os.remove(tmp)
check("APP_VERSION совпадает с файлом VERSION", ef.read_version() == open(os.path.join(ROOT, "VERSION")).read().strip())
print()
if fails:
    print("FAILED:", len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED")
