# -*- coding: utf-8 -*-
"""
Eternal FishMod — полуавтомат рыбалки.

RP-цикл: инвентарь → верхнее «Использовать» → ожидание шкалы → мини-игра.
Проверка наживки опциональна; есть альтернативный заброс ЛКМ с удочкой в руках.
Никакой ходьбы, торговли и маршрутов — это делаешь ты (полуавтомат).

Установка:  pip install opencv-python numpy mss pydirectinput keyboard
Запуск:     python eternal_fishmod.py        (от администратора, если игра запущена от админа)

Клавиши:    F8 — старт/стоп, F10 — аварийный стоп, Insert — показать/скрыть окно, F9 — диагностика.
Рядом:      templates/ (картинки-шаблоны), sounds/ (можно положить свои start.wav / end.wav / alert.wav / catch.wav)
"""
import os
import sys
import json
import math
import time
import wave
import queue
import base64
import ctypes
import datetime
import threading
import itertools
import traceback
import collections
import re

import cv2
from vision import analyze_bar, analyze_progress, analyze_warning, annotate, bounds_from_samples, hsv_mask
import numpy as np

try:
    import tkinter as tk
except ImportError:
    tk = None
try:
    import mss
except ImportError:
    mss = None
try:
    import pydirectinput
except ImportError:
    pydirectinput = None
try:
    import keyboard
except ImportError:
    keyboard = None
try:
    import winsound
except ImportError:
    winsound = None

APP_NAME = "Eternal FishMod"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TPL_DIR = os.path.join(BASE_DIR, "templates")
SND_DIR = os.path.join(BASE_DIR, "sounds")
CFG_PATH = os.path.join(BASE_DIR, "fishmod_config.json")
STATS_PATH = os.path.join(BASE_DIR, "fishmod_stats.json")
LOG_PATH = os.path.join(BASE_DIR, "fishmod.log")
REF_W, REF_H = 1920, 1080

# ==========================================================================
# 1. НАСТРОЙКИ
# ==========================================================================
DEFAULT_CFG = {
    "game_title_hint": "Skyrim",
    "bind_toggle": "f8", "bind_panic": "f10", "bind_gui": "insert", "bind_debug": "f9",
    "bar": [913, 470, 58, 530],          # область шкалы мини-игры (x, y, w, h) для 1920x1080
    "equip_on_start": True,              # брать удочку из инвентаря, если её нет в руках
    "auto_cast": True,                   # автоматически закидывать удочку (если False - только мини-игра)
    "cast_after_catch": True,            # закидывать удочку после каждой рыбы
    "bait_check_every": 12,              # проверять наживку по инвентарю каждые N рыб
    "bite_timeout": 90,                  # сколько секунд ждать поклёвку
    "no_bite_limit": 3,                  # столько таймаутов подряд -> стоп (нет поклёвок/перегруз)
    "post_catch_delay": 1.8,
    "after_equip_delay": 1.2,
    "cast_delay": 0.8,                   # пауза перед закидыванием удочки
    "idle_cursor": [1250, 500],
    "use_offset": [86, 20],              # смещение пункта «Использовать» от точки клика ПКМ
    "rod_click_pos": [125, 260],               # [x, y] координаты удочки в инвентаре (None = авто поиск)
    "use_click_pos": [205, 279],               # [x, y] координаты кнопки «Использовать» (None = авто смещение)
    "inv_wheel_center": [320, 600],
    "sound_start": True, "sound_end": True, "sound_catch": False, "volume": 60,
    "hide_when_running": True,           # прятать окно, пока бот ловит (оверлей не мешает «зрению»)
    "ui_scale": 0.72,
    "win_pos": None,
    "cast_mode": "inventory",       # inventory: Использовать=заброс; hand: ЛКМ
    "rod_mode": "fixed",            # fixed или template
    "check_bait": False,            # включить только после захвата bait.png
    "inventory_timeout": 5.0, "menu_timeout": 2.0,
    "rod_roi": [80, 215, 500, 785], "bait_roi": [80, 215, 500, 785],
    "inv_header_roi": [60, 20, 300, 110],
    "template_thresholds": {"rod": 0.90, "bait": 0.90, "inv_header": 0.80, "warning": 0.81},
    "menu_roi": [115, 245, 190, 110],  # красная НИЖНЯЯ строка контекстного меню
    "menu_min_red": 0.025, "menu_up": 36,
    "progress_roi": [984, 470, 13, 530],
    "warning_roi": [1035, 640, 345, 115],
    "green_hsv": [[30, 80, 80], [85, 255, 255]],
    "blue_hsv": [[90, 25, 35], [130, 255, 255]],
    "fish_hsv": [[8, 40, 90], [30, 255, 255]],
    "red_hsv": [[0, 95, 70], [13, 255, 255]],
    "green_samples": [], "blue_samples": [], "fish_samples": [], "red_samples": [],
    "sample_tolerance": [9, 35, 35], "fish_mode": "exclude", # либо samples
    "min_zone_area": 150, "zone_width_ratio": 0.55, "min_zone_height_ratio": 0.035,
    "min_fish_area": 10, "max_fish_area_ratio": 0.09,
    "min_fish_height_ratio": 0.008, "min_fish_width_ratio": 0.08,
    "fish_side_margin": 0.06, "fish_tracking_radius": 50,
    "fish_min_s": 42, "fish_min_v": 72, "fish_row_diff": 28,
    "progress_min_v": 172, "progress_max_s": 95, "progress_row_ratio": 0.60,
    "progress_crop_side": 0.08, "progress_bottom_trim": 0.012, "progress_gap_rows": 3,
    "progress_full": 0.97, "progress_full_frames": 2,
    "warning_red_ratio": 0.008, "warning_template_threshold": 0.81,
    "warning_seconds": 3.0, "warning_clear_frames": 10,
    "lost_limit": 25, "bite_seen_frames": 3, "loop_delay": 0.03,
    "minigame_timeout": 90.0, "fish_timeout": 0.8,
    "deadzone": 6.0, "lookahead": 0.08, "emergency_lookahead": 0.16,
    "max_vel": 1200.0, "max_lead": 35.0,
    "max_hold": 2.5, "forced_release": 0.12, "min_switch": 0.03,
    "max_lost_games": 3, "max_failures": 8,
}
CFG = json.loads(json.dumps(DEFAULT_CFG))

THR = {"rod": 0.90, "bait": 0.90, "inv_header": 0.80,
       "hud_fish": 0.85, "hud_bait": 0.85, "hud_shield": 0.85, "warning": 0.81}
REGIONS = {
    "rod": [80, 215, 500, 785], "bait": [80, 215, 500, 785], "inv_header": [60, 20, 300, 110],
    "hud_fish": [0, 872, 420, 66], "hud_bait": [0, 872, 420, 66], "hud_shield": [0, 872, 420, 66], "warning": [1035, 640, 345, 115],
}
TEMPLATE_NAMES = ["rod", "bait", "inv_header", "hud_fish", "hud_bait", "hud_shield", "warning"]
TEMPLATE_LABELS = {"rod": "Удочка (инвентарь)", "bait": "Наживка (инвентарь)", "inv_header": "Окно инвентаря",
                   "hud_fish": "Значок удочки (HUD)", "hud_bait": "Значок наживки (HUD)", "hud_shield": "HUD виден", "warning": "Текст предупреждения"}

def load_cfg():
    """True — загружено из файла."""
    if os.path.exists(CFG_PATH):
        try:
            with open(CFG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            CFG.update({k: v for k, v in data.items() if k in DEFAULT_CFG})
            REGIONS["warning"] = CFG["warning_roi"]
            _tpl_cache.clear()
            return True
        except Exception as e:
            print("Конфиг не прочитан:", e)
    return False


def save_cfg():
    try:
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(CFG, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def reset_cfg():
    CFG.clear()
    CFG.update(json.loads(json.dumps(DEFAULT_CFG)))
    REGIONS["warning"] = CFG["warning_roi"]
    _tpl_cache.clear()


# ==========================================================================
# 2. СОСТОЯНИЕ, ЖУРНАЛ, СОБЫТИЯ
# ==========================================================================
class Stopped(Exception):
    pass


class Fail(Exception):
    pass


stop_event = threading.Event()
EVENTS = queue.Queue()                 # движок -> интерфейс
LOG = collections.deque(maxlen=300)
STATE = {"running": False, "title": "ОСТАНОВЛЕНО", "detail": "Нажми СТАРТ или F8", "kind": "idle", "reason": ""}
STATS = {"catches": 0, "escapes": 0, "unknown": 0, "t0": None, "t_end": None, "mg": [], "checks": 0}
TOTAL = {"catches": 0, "escapes": 0, "unknown": 0, "sessions": 0, "best": 0, "last_reason": "—"}
worker = None
worker_lock = threading.Lock()
GAME_TITLE = ""
GAME_HWND = 0
held_keys = set()
mouse_down = False
last_switch = last_up_sent = hold_since = 0.0
_tls = threading.local()
_tpl_cache = {}
_pause_logged = False
PAUSE_TOTAL = 0.0


def log(text):
    line = f"[{time.strftime('%H:%M:%S')}] {text}"
    LOG.append(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def set_state(title, detail="", kind="idle"):
    STATE["title"], STATE["detail"], STATE["kind"] = title, detail, kind


def notify(text, kind="ok"):
    EVENTS.put(("toast", text, kind))


def load_totals():
    try:
        with open(STATS_PATH, "r", encoding="utf-8") as f:
            TOTAL.update(json.load(f))
    except Exception:
        pass


def save_totals():
    try:
        with open(STATS_PATH, "w", encoding="utf-8") as f:
            json.dump(TOTAL, f, ensure_ascii=False)
    except Exception:
        pass


# ==========================================================================
# 3. ЗВУКИ (генерируются сами; можно подложить свои wav в папку sounds/)
# ==========================================================================
SOUND_DEFS = {
    # (частота Гц, длительность с, смещение старта с)
    "start": [(659.25, 0.30, 0.0), (987.77, 0.55, 0.13)],
    "end": [(783.99, 0.28, 0.0), (659.25, 0.28, 0.14), (493.88, 0.60, 0.28)],
    "alert": [(329.63, 0.25, 0.0), (329.63, 0.25, 0.22), (246.94, 0.55, 0.44)],
    "catch": [(1318.5, 0.10, 0.0)],
}


def synth_wav(path, notes, volume, sr=22050):
    total = max(o + d for _, d, o in notes) + 0.05
    buf = np.zeros(int(sr * total), np.float64)
    for f, d, o in notes:
        n = int(sr * d)
        t = np.arange(n) / sr
        env = np.minimum(1.0, t / 0.008) * np.exp(-t * 4.2 / d)
        w = (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t) + 0.12 * np.sin(6 * np.pi * f * t)) * env
        i = int(sr * o)
        buf[i:i + n] += w[:len(buf) - i]
    peak = float(np.abs(buf).max()) or 1.0
    data = (buf / peak * 0.85 * (volume / 100.0) * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(data.tobytes())


def ensure_sounds():
    auto = os.path.join(SND_DIR, "auto")
    os.makedirs(auto, exist_ok=True)
    stamp = os.path.join(auto, ".volume")
    try:
        old = open(stamp).read().strip()
    except Exception:
        old = ""
    regen = old != str(CFG["volume"])
    for name, notes in SOUND_DEFS.items():
        p = os.path.join(auto, name + ".wav")
        if regen or not os.path.exists(p):
            synth_wav(p, notes, CFG["volume"])
    with open(stamp, "w") as f:
        f.write(str(CFG["volume"]))


def play(name):
    """Свой файл sounds/<name>.wav главнее сгенерированного."""
    if winsound is None:
        return
    custom = os.path.join(SND_DIR, name + ".wav")
    path = custom if os.path.exists(custom) else os.path.join(SND_DIR, "auto", name + ".wav")
    try:
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
    except Exception:
        pass


# ==========================================================================
# 4. ЭКРАН И ШАБЛОНЫ
# ==========================================================================
def get_sct():
    s = getattr(_tls, "sct", None)
    if s is None:
        s = mss.mss()
        _tls.sct = s
    return s


def monitor():
    return get_sct().monitors[1]


def scale():
    m = monitor()
    return m["width"] / REF_W, m["height"] / REF_H


def P(x, y):
    m = monitor()
    sx, sy = scale()
    return int(m["left"] + x * sx), int(m["top"] + y * sy)


def grab_px(left, top, w, h):
    box = {"left": int(left), "top": int(top), "width": max(1, int(w)), "height": max(1, int(h))}
    return np.ascontiguousarray(np.array(get_sct().grab(box))[:, :, :3])


def grab(rect=None):
    m = monitor()
    if rect is None:
        return grab_px(m["left"], m["top"], m["width"], m["height"])
    sx, sy = scale()
    x, y, w, h = rect
    return grab_px(m["left"] + x * sx, m["top"] + y * sy, w * sx, h * sy)


def tpl(name):
    if name in _tpl_cache:
        return _tpl_cache[name]
    path = os.path.join(TPL_DIR, name + ".png")
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE) if os.path.exists(path) else None
    if img is not None:
        sx, sy = scale()
        if abs(sx - 1) > 0.01 or abs(sy - 1) > 0.01:
            img = cv2.resize(img, None, fx=sx, fy=sy, interpolation=cv2.INTER_AREA)
    _tpl_cache[name] = img
    return img


def _match_map(name):
    t = tpl(name)
    if t is None:
        return None, None, None
    reg = CFG.get(name + "_roi", REGIONS[name])
    img = cv2.cvtColor(grab(reg), cv2.COLOR_BGR2GRAY)
    if img.shape[0] < t.shape[0] or img.shape[1] < t.shape[1]:
        return None, t, reg
    r = cv2.matchTemplate(img, t, cv2.TM_CCOEFF_NORMED)
    return np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=0.0), t, reg


def best_score(name):
    r, _, _ = _match_map(name)
    return None if r is None else float(r.max())


def find_all(name, thr=None, min_dist=40):
    thr = CFG["template_thresholds"].get(name, THR.get(name, 0.85)) if thr is None else thr
    r, t, reg = _match_map(name)
    if r is None:
        return []
    m = monitor()
    sx, sy = scale()
    ys, xs = np.where(r >= thr)
    pts = sorted(zip(r[ys, xs].tolist(), xs.tolist(), ys.tolist()), reverse=True)[:300]
    out = []
    for s, x, y in pts:
        if all((x - a) ** 2 + (y - b) ** 2 > min_dist ** 2 for _, a, b in out):
            out.append((s, x, y))
    h, w = t.shape
    ox, oy = m["left"] + int(reg[0] * sx), m["top"] + int(reg[1] * sy)
    return [(s, ox + x + w // 2, oy + y + h // 2) for s, x, y in out]


def find(name, thr=None):
    res = find_all(name, thr)
    return res[0] if res else None


def context_menu_open(x=None, y=None):
    """Нижняя красная строка подтверждает меню; возвращает центр красной строки.
    Никогда не кликаем по ней: «Использовать» ВЫШЕ.
    """
    roi = CFG["menu_roi"]
    img = grab(roi)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    red = hsv_mask(hsv, CFG["red_hsv"])
    if (red > 0).mean() < CFG["menu_min_red"]:
        return None
    n, labels, stats, cents = cv2.connectedComponentsWithStats(red)
    candidates = [(stats[i, cv2.CC_STAT_AREA], cents[i]) for i in range(1, n)
                  if stats[i, cv2.CC_STAT_WIDTH] >= img.shape[1] * 0.3]
    if not candidates:
        return None
    _, center = max(candidates, key=lambda item: item[0])
    return P(roi[0] + center[0] / scale()[0], roi[1] + center[1] / scale()[1])


# ==========================================================================
# 5. ВВОД, ОСТАНОВКА, ФОКУС
# ==========================================================================

# --- низкоуровневый ввод через SendInput (без DPI-нормализации pydirectinput) ---
_SM_CXSCREEN = 0
_SM_CYSCREEN = 1
MOUSEEVENTF_MOVE        = 0x0001
MOUSEEVENTF_LEFTDOWN    = 0x0002
MOUSEEVENTF_LEFTUP      = 0x0004
MOUSEEVENTF_RIGHTDOWN   = 0x0008
MOUSEEVENTF_RIGHTUP     = 0x0010
MOUSEEVENTF_ABSOLUTE    = 0x8000

class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

class _INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT)]
    _anonymous_ = ("_i",)
    _fields_ = [("type", ctypes.c_ulong), ("_i", _I)]

def _send_mouse(flags, dx=0, dy=0):
    inp = _INPUT()
    inp.type = 0  # INPUT_MOUSE
    inp.mi.dx = dx
    inp.mi.dy = dy
    inp.mi.mouseData = dy if flags & 0x0800 else 0
    inp.mi.dwFlags = flags
    inp.mi.time = 0
    inp.mi.dwExtraInfo = None
    if ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp)) != 1:
        raise OSError("SendInput не отправил событие (права игры?)")

def logical_to_physical(lx, ly):
    """Конвертирует логические координаты Windows (GetCursorPos) в физические (mss/grab)."""
    try:
        m = monitor()
        sw_phys = m["width"]
        sh_phys = m["height"]
    except Exception:
        return lx, ly
    sw_log = ctypes.windll.user32.GetSystemMetrics(0)
    sh_log = ctypes.windll.user32.GetSystemMetrics(1)
    return int(lx * sw_phys / max(sw_log, 1)), int(ly * sh_phys / max(sh_log, 1))


def mouse_move_abs(x, y):
    """Перемещает мышь в абсолютные экранные координаты через SendInput.
    Использует физические размеры монитора из mss, чтобы не зависеть от DPI-масштабирования Windows.
    """
    try:
        m = monitor()
        sw = m["width"]   # физические пиксели — совпадают с тем, что видит mss/grab
        sh = m["height"]
    except Exception:
        sw = ctypes.windll.user32.GetSystemMetrics(_SM_CXSCREEN)
        sh = ctypes.windll.user32.GetSystemMetrics(_SM_CYSCREEN)
    m = monitor()
    vm = get_sct().monitors[0]
    nx = int((x - vm["left"]) * 65535 / max(vm["width"] - 1, 1))
    ny = int((y - vm["top"]) * 65535 / max(vm["height"] - 1, 1))
    _send_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | 0x4000, nx, ny)

def mouse_lmb_down():
    if not game_focused():
        wait_focus()
    check_stop()
    _send_mouse(MOUSEEVENTF_LEFTDOWN)
    global mouse_down, hold_since
    mouse_down = True
    hold_since = time.perf_counter()

def mouse_lmb_up():
    _send_mouse(MOUSEEVENTF_LEFTUP)
    global mouse_down, last_up_sent
    mouse_down = False
    last_up_sent = time.perf_counter()

def mouse_rmb_click(x, y):
    """ПКМ в точке (x, y) через SendInput."""
    mouse_move_abs(x, y)
    time.sleep(0.05)
    _send_mouse(MOUSEEVENTF_RIGHTDOWN)
    time.sleep(0.08)
    _send_mouse(MOUSEEVENTF_RIGHTUP)

def mouse_lmb_click(x, y):
    """ЛКМ в точке (x, y) через SendInput."""
    mouse_move_abs(x, y)
    time.sleep(0.05)
    _send_mouse(MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.08)
    _send_mouse(MOUSEEVENTF_LEFTUP)

def pdi_key(name):
    return name if name in pydirectinput.KEYBOARD_MAPPING else None


def key_down(name):
    check_stop()
    k = pdi_key(name)
    if k:
        pydirectinput.keyDown(k)
        held_keys.add(k)


def key_up(name):
    k = pdi_key(name)
    if k:
        pydirectinput.keyUp(k)
        held_keys.discard(k)


def release_all():
    global mouse_down
    for k in list(held_keys):
        try:
            pydirectinput.keyUp(k)
        except Exception:
            pass
    held_keys.clear()
    # Отпускаем обе кнопки мыши через SendInput
    for _ in range(3):
        for flag in (MOUSEEVENTF_LEFTUP, MOUSEEVENTF_RIGHTUP):
            try:
                _send_mouse(flag)
            except OSError:
                pass
    mouse_down = False


def foreground_title():
    try:
        u = ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        n = u.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value
    except Exception:
        return ""


def is_own_window(title):
    return APP_NAME.lower() in (title or "").lower()


def game_focused():
    if not GAME_HWND:
        return False
    try:
        return ctypes.windll.user32.GetForegroundWindow() == GAME_HWND
    except Exception:
        return False


def learn_game_window(timeout=15.0):
    """Запоминает активное окно (не наше) как окно игры. Бот работает ТОЛЬКО пока оно активно."""
    global GAME_TITLE, GAME_HWND
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        if stop_event.is_set():
            raise Stopped()
        t = foreground_title()
        if t and not is_own_window(t) and t not in ("Program Manager", "Task Switching") and CFG["game_title_hint"].lower() in t.lower():
            GAME_TITLE = t
            GAME_HWND = ctypes.windll.user32.GetForegroundWindow()
            log(f"🎮 Окно игры: «{t}»")
            return t
        time.sleep(0.25)
    raise Fail("не удалось определить окно игры: проверь game_title_hint и вернись в игру")


def wait_focus():
    global _pause_logged, PAUSE_TOTAL
    release_all()
    if not _pause_logged:
        set_state("ПАУЗА", "Окно игры не в фокусе", "busy")
        log("⏸ Окно игры не активно — пауза (вернись в игру)")
        notify("Пауза: вернись в игру", "warn")
        _pause_logged = True
    t0 = time.perf_counter()
    while not game_focused():
        if stop_event.is_set():
            raise Stopped()
        time.sleep(0.2)
    _pause_logged = False
    elapsed = time.perf_counter() - t0
    PAUSE_TOTAL += elapsed
    log("▶ Окно игры снова активно")
    set_state("ВОЗОБНОВЛЕНО", "Фокус игры возвращён", "run")
    return elapsed


def check_stop():
    if stop_event.is_set():
        raise Stopped()
    if GAME_TITLE and not game_focused():
        return wait_focus()
    return 0.0


def nap(sec):
    end = time.perf_counter() + sec
    while True:
        end += check_stop()
        left = end - time.perf_counter()
        if left <= 0:
            return
        time.sleep(min(left, 0.02))


def tap(name, hold=0.06):
    check_stop()
    key_down(name)
    try:
        nap(hold)
    finally:
        key_up(name)
    nap(0.05)


def move_px(x, y):
    check_stop()
    mouse_move_abs(int(x), int(y))
    time.sleep(0.03)


def click_px(x, y, button="left", pre=0.12, post=0.15):
    check_stop()
    mouse_move_abs(int(x), int(y))
    nap(pre)
    check_stop()
    if button == "left":
        _send_mouse(MOUSEEVENTF_LEFTDOWN)
        try:
            nap(0.06)
        finally:
            _send_mouse(MOUSEEVENTF_LEFTUP)
    else:
        _send_mouse(MOUSEEVENTF_RIGHTDOWN)
        try:
            nap(0.06)
        finally:
            _send_mouse(MOUSEEVENTF_RIGHTUP)
    nap(post)


def wheel(notches):
    """Колесо мыши: отрицательное — вниз."""
    check_stop()
    _send_mouse(0x0800, 0, int(notches * 120) & 0xFFFFFFFF)


def set_mouse(down, force=False):
    """ЛКМ для мини-игры через SendInput (без DPI проблем)."""
    global mouse_down, last_switch, last_up_sent, hold_since
    now = time.perf_counter()
    if down and not game_focused():
        wait_focus()
        return
    if down != mouse_down:
        if not force and now - last_switch < CFG["min_switch"]:
            return
        if down:
            mouse_lmb_down()
        else:
            mouse_lmb_up()
        last_switch = now
    elif not down and now - last_up_sent >= 0.2:
        # периодически повторяем mouseUp чтобы не залипало
        _send_mouse(MOUSEEVENTF_LEFTUP)
        last_up_sent = now


# ==========================================================================
# 6. МИНИ-ИГРА
# ==========================================================================
def analyze(bgr):
    """Совместимый интерфейс старой диагностики; расширенный анализ в vision.py."""
    o = analyze_bar(bgr, CFG)
    return o.zone, o.fish_y, o.green_mask, o.fish_mask


def observe(last_fish=None):
    o = analyze_bar(grab(CFG["bar"]), CFG, last_fish)
    o.progress = analyze_progress(grab(CFG["progress_roi"]), CFG)
    warning = tpl("warning")
    o.warning, o.warning_score = analyze_warning(grab(CFG["warning_roi"]), CFG, warning)
    return o


def wait_for_minigame(timeout):
    """Поклёвка = появление зелёной зоны И синего фона подряд N кадров."""
    end = time.perf_counter() + timeout
    last_pause = PAUSE_TOTAL
    seen = 0
    while True:
        check_stop()
        end += PAUSE_TOTAL - last_pause
        last_pause = PAUSE_TOTAL
        if time.perf_counter() >= end:
            break
        bgr = grab(CFG["bar"])
        o = analyze_bar(bgr, CFG)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        blue = hsv_mask(hsv, CFG['blue_hsv'])
        seen = seen + 1 if o.present and (blue > 0).mean() > 0.10 else 0
        if seen >= CFG['bite_seen_frames']:
            return True
        set_state("КЛЁВ", f"Ожидание клёва… {max(0, int(timeout - (end - time.perf_counter())))} с", "run")
        nap(0.05)
    return False


def play_minigame():
    """Возвращает (success|escape|unknown, длительность).

    Исчезновение шкалы без 100%/подтверждения — НЕ доказательство улова.
    Предупреждение без OCR: обратный отсчёт оценивается локально от первого
    обнаруженного кадра. При неподтверждённом исходе запись unknown.
    """
    global mouse_down
    t0 = time.perf_counter()
    lost = full = clear = 0
    last_fish, last_fish_t = None, 0.0
    prev_zone, prev_t, vel = None, 0.0, 0.0
    warning_t = None
    last_progress = 0.0
    last_pause = PAUSE_TOTAL
    forced_until = 0.0
    result = 'unknown'
    release_all()
    log("🎣 Мини-игра началась")
    try:
        while True:
            check_stop()
            paused = PAUSE_TOTAL - last_pause
            last_pause = PAUSE_TOTAL
            if paused:
                t0 += paused
                last_fish_t += paused
                if warning_t is not None:
                    warning_t += paused
                prev_zone = None
            now = time.perf_counter()
            if now - t0 > CFG['minigame_timeout']:
                log("⚠ Мини-игра: таймаут")
                break
            o = observe(last_fish)
            if o.progress is not None:
                last_progress = o.progress
            full = full + 1 if o.present and o.progress is not None and o.progress >= CFG['progress_full'] else 0
            if full >= CFG['progress_full_frames']:
                result = 'success'
                break
            if not o.present:
                lost += 1
                set_mouse(False, True)
                if lost >= CFG['lost_limit']:
                    result = 'escape' if warning_t is not None else ('success' if last_progress >= CFG['progress_full'] else 'unknown')
                    break
                nap(CFG['loop_delay'])
                continue
            lost = 0
            if o.warning:
                if warning_t is None:
                    warning_t = now
                    log("⚠ Рыба срывается — экстренное управление")
                clear = 0
            elif warning_t is not None:
                # Красная рамка пульсирует. Пустой красный кадр сам по себе
                # не означает спасение: ждём возвращения спрайта в зону.
                inside = o.fish_y is not None and o.zone[0] <= o.fish_y <= o.zone[1]
                clear = clear + 1 if inside else 0
                if clear >= CFG['warning_clear_frames']:
                    warning_t = None
                    log("✓ Угроза срыва миновала")
            emergency = warning_t is not None
            if emergency:
                left = max(0., CFG['warning_seconds'] - (now - warning_t))
                set_state("⚠ РЫБА СРЫВАЕТСЯ!", f"Таймер ≈ {left:.1f} с (оценка)", "error")
                if left == 0:
                    result = 'escape'
                    break
            else:
                set_state("МИНИ-ИГРА", f"Рыба в зоне · прогресс {last_progress:.0%}", "run")
            center = o.zone[2]
            if prev_zone is not None and now > prev_t:
                raw = (center - prev_zone) / (now - prev_t)
                vel = max(-CFG['max_vel'], min(CFG['max_vel'], 0.6 * vel + 0.4 * raw))
            prev_zone, prev_t = center, now
            if o.fish_y is not None:
                last_fish, last_fish_t = o.fish_y, now
            if last_fish is None or now - last_fish_t > CFG['fish_timeout']:
                want = False
            else:
                look = CFG['emergency_lookahead'] if emergency else CFG['lookahead']
                predicted = center + max(-CFG['max_lead'], min(CFG['max_lead'], vel * look))
                error = last_fish - predicted
                dead = CFG['deadzone'] * (0.5 if emergency else 1)
                want = mouse_down if abs(error) <= dead else error < 0
            if mouse_down and now - hold_since >= CFG['max_hold']:
                forced_until = now + CFG['forced_release']
            if now < forced_until:
                want = False
            if want != mouse_down and now - last_switch >= CFG['min_switch']:
                # Повторная проверка прямо перед вводом; после потери фокуса
                # check_stop освободит все кнопки и сбросит удержание.
                check_stop()
                set_mouse(want, True)
            elif not want:
                set_mouse(False)
            nap(CFG['loop_delay'])
    finally:
        release_all()
    return result, time.perf_counter() - t0


# ==========================================================================
# 7. ИНВЕНТАРЬ, УДОЧКА, НАЖИВКА
# ==========================================================================
def hud_present(name):
    return find(name) is not None


def inventory_open():
    return find("inv_header") is not None


def open_inventory():
    if inventory_open():
        return True
    deadline = time.perf_counter() + CFG['inventory_timeout']
    last_pause = PAUSE_TOTAL
    while True:
        check_stop()
        deadline += PAUSE_TOTAL - last_pause
        last_pause = PAUSE_TOTAL
        if time.perf_counter() >= deadline:
            break
        tap("tab")
        nap(0.8)
        if inventory_open():
            return True
    return False


def close_inventory():
    for _ in range(3):
        if not inventory_open():
            return True
        tap("tab")
        nap(0.7)
    if inventory_open():
        tap("esc")
        nap(0.7)
    return not inventory_open()


def scroll_inventory(notches):
    move_px(*P(*CFG["inv_wheel_center"]))
    nap(0.15)
    wheel(notches)
    nap(0.45)


def locate_in_inventory(name, pages=5):
    for _ in range(pages + 1):
        move_px(*P(*CFG["idle_cursor"]))
        nap(0.2)
        m = find(name)
        if m:
            return m
        scroll_inventory(-3)
    return None


def use_rod():
    """ПКМ в фиксированном слоте (или по шаблону), затем ВЕРХНИЙ пункт.
    Красная нижняя строка — только датчик меню; никогда не жмём по ней.
    """
    if CFG['rod_mode'] == 'fixed':
        scroll_inventory(10)  # bait-поиск мог оставить сетку прокрученной
        if not CFG['rod_click_pos']:
            raise Fail("Укажи координаты удочки на вкладке Настройки")
        rx, ry = P(*CFG['rod_click_pos'])
    else:
        scroll_inventory(10)
        m = locate_in_inventory('rod')
        if not m:
            raise Fail("удочка не найдена по шаблону")
        _, rx, ry = m
    click_px(rx, ry, 'right', 0.3, 0.18)
    end = time.perf_counter() + CFG['menu_timeout']
    last_pause = PAUSE_TOTAL
    red = None
    while True:
        check_stop()
        end += PAUSE_TOTAL - last_pause
        last_pause = PAUSE_TOTAL
        if time.perf_counter() >= end:
            break
        red = context_menu_open()
        if red:
            break
        nap(0.1)
    if not red:
        raise Fail("меню удочки не обнаружено: выбери ROI меню / пипетку красного")
    if CFG['use_click_pos']:
        ux, uy = P(*CFG['use_click_pos'])
    else:
        ux, uy = red[0], red[1] - int(CFG['menu_up'] * scale()[1])
    # Защитный барьер: точка 'Использовать' обязана быть НАД красной строкой.
    if uy >= red[1] - int(8 * scale()[1]):
        raise Fail("опасные координаты: «Использовать» совпадает с красным «Выбросить»")
    click_px(ux, uy, pre=0.3, post=0.3)
    nap(CFG['after_equip_delay'])
    if inventory_open():
        raise Fail("инвентарь не закрылся после «Использовать»: проверь координаты")
    log("🎣 «Использовать» нажато — заброс выполнен")


def bait_in_open_inventory():
    scroll_inventory(10)
    stacks = len(find_all("bait"))
    present = stacks > 0 or locate_in_inventory("bait") is not None
    STATS["checks"] += 1
    log(f"🪱 Наживка: {'есть' if present else 'НЕТ'} (стаков на экране: {stacks})")
    return present


def bait_check():
    """True — есть, False — нет, None — инвентарь не открылся."""
    if not open_inventory():
        return None
    present = bait_in_open_inventory() if CFG["check_bait"] else True
    close_inventory()
    nap(0.5)
    return present


def prepare(equip):
    """Открывает инвентарь, проверяет наживку и (если нужно) берёт удочку."""
    if not open_inventory():
        return None
    present = bait_in_open_inventory() if CFG["check_bait"] else True
    if not present:
        close_inventory()
        return False
    if equip:
        # use_rod сам закрывает инвентарь (игра делает это после «Использовать»)
        use_rod()
    else:
        close_inventory()
        nap(0.5)
    return True


# ==========================================================================
# 8. РЫБАЛКА (главный цикл)
# ==========================================================================
REASONS = {"user": "остановлено вручную", "no_bait": "наживка закончилась",
           "no_bite": "нет поклёвок (проверь вес/место)", "lost_games": "мини-игра не распознана", "failures": "много срывов подряд", "error": "ошибка"}


def cast():
    """Старый режим: зажатие ЛКМ в фоне с принудительным отпусканием."""
    global mouse_down
    release_all()
    nap(CFG['cast_delay'])
    check_stop()
    log('🪝 Заброс ЛКМ…')
    try:
        mouse_lmb_down()
        nap(0.18)
    finally:
        mouse_lmb_up()
    nap(0.3)


def fishing_run():
    STATS.update({"catches": 0, "escapes": 0, "unknown": 0, "t0": time.time(), "t_end": None, "mg": [], "checks": 0})
    if tpl('inv_header') is None:
        raise Fail('нет templates/inv_header.png: сними шаблон заголовка инвентаря')
    if CFG['check_bait'] and tpl('bait') is None:
        raise Fail('контроль наживки включён: сними templates/bait.png')
    if CFG['rod_mode'] == 'template' and tpl('rod') is None:
        raise Fail('режим шаблона удочки: сними templates/rod.png')
    no_bite = lost_games = failures = 0
    checked = 0
    while True:
        check_stop()
        set_state('ПОДГОТОВКА', 'Открываю инвентарь / забрасываю', 'busy')
        if CFG['cast_mode'] == 'inventory':
            if not open_inventory():
                raise Fail('инвентарь не открылся — проверь TAB/шаблон заголовка')
            try:
                if CFG['check_bait'] and not bait_in_open_inventory():
                    return 'no_bait'
                use_rod()  # само закрывает инвентарь и забрасывает
            finally:
                # При ошибке НЕ кликаем; отпускание input — в bot_thread.
                pass
        elif CFG['cast_mode'] == 'hand':
            if CFG['check_bait'] and (checked == 0 or checked >= CFG['bait_check_every']):
                r = bait_check()
                if r is None:
                    raise Fail('инвентарь не открылся')
                if not r:
                    return 'no_bait'
                checked = 0
            set_state('ЗАКИДЫВАЮ', 'ЛКМ: удочка в руках', 'busy')
            cast()
        else:
            raise Fail('неизвестный режим заброса')
        checked += 1
        set_state('КЛЁВ', 'Жду появления шкалы', 'run')
        if not wait_for_minigame(CFG['bite_timeout']):
            no_bite += 1
            log(f"⌛ Нет поклёвки ({no_bite}/{CFG['no_bite_limit']})")
            if no_bite >= CFG['no_bite_limit']:
                return 'no_bite'
            nap(CFG['post_catch_delay'])
            continue
        no_bite = 0
        result, dur = play_minigame()
        STATS['mg'].append(dur)
        if result == 'success':
            STATS['catches'] += 1
            lost_games = failures = 0
            log(f"🐟 Улов #{STATS['catches']}, мини-игра {dur:.1f} с")
            if CFG['sound_catch']:
                play('catch')
        else:
            failures += 1
            if result == 'escape':
                STATS['escapes'] += 1
                log('⚠ Рыба сорвалась')
            else:
                STATS['unknown'] += 1
                lost_games += 1
                log(f"? Шкала пропала без подтверждённого исхода ({lost_games}/{CFG['max_lost_games']})")
                if lost_games >= CFG['max_lost_games']:
                    return 'lost_games'
            if failures >= CFG['max_failures']:
                return 'failures'
        nap(CFG['post_catch_delay'])


def bot_thread():
    global GAME_TITLE, GAME_HWND
    reason, detail = "error", ""
    STATS.update({"catches": 0, "escapes": 0, "unknown": 0, "t0": time.time(), "t_end": None, "mg": [], "checks": 0})
    try:
        STATE["running"] = True
        EVENTS.put(("run", True))
        set_state("ЗАПУСК", "Определяю окно игры…", "busy")
        GAME_TITLE = ""
        GAME_HWND = 0
        learn_game_window()
        log("▶ Рыбалка началась")
        notify("Рыбалка началась", "ok")
        if CFG["sound_start"]:
            play("start")
        reason = fishing_run()
    except Stopped:
        reason = "user"
    except Fail as e:
        reason, detail = "error", str(e)
    except Exception as e:
        reason, detail = "error", f"{type(e).__name__}: {e}"
        log(traceback.format_exc())
    finally:
        release_all()
        STATS["t_end"] = time.time()
        TOTAL["catches"] += STATS["catches"]
        TOTAL["escapes"] += STATS["escapes"]
        TOTAL["unknown"] += STATS["unknown"]
        TOTAL["sessions"] += 1
        TOTAL["best"] = max(TOTAL["best"], STATS["catches"])
        text = REASONS.get(reason, reason) + (f": {detail}" if detail else "")
        TOTAL["last_reason"] = text
        save_totals()
        log(f"■ Рыбалка закончилась — {text}. Поймано: {STATS['catches']}")
        set_state("ОСТАНОВЛЕНО", text[:80], "error" if reason in ("error", "no_bite") else "idle")
        STATE["running"] = False
        notify("Рыбалка закончилась: " + text[:60], "warn" if reason in ("error", "no_bite") else "ok")
        if CFG["sound_end"]:
            play("alert" if reason in ("error", "no_bite") else "end")
        EVENTS.put(("run", False))


def start_bot():
    global worker
    with worker_lock:
        if worker is not None and worker.is_alive():
            return
        stop_event.clear()
        worker = threading.Thread(target=bot_thread, daemon=True)
        worker.start()


def stop_bot():
    stop_event.set()
    release_all()


def toggle_bot():
    if worker is not None and worker.is_alive():
        stop_bot()
    else:
        start_bot()


def panic():
    stop_event.set()
    release_all()


def dump_debug():
    try:
        screen = grab()
        cv2.imwrite(os.path.join(BASE_DIR, 'debug_screen.png'), screen)
        bgr, pr = grab(CFG['bar']), grab(CFG['progress_roi'])
        o = analyze_bar(bgr, CFG)
        o.progress = analyze_progress(pr, CFG)
        o.warning, o.warning_score = analyze_warning(grab(CFG['warning_roi']), CFG, tpl('warning'))
        cv2.imwrite(os.path.join(BASE_DIR, 'debug_bar.png'), annotate(bgr, pr, o))
        cv2.imwrite(os.path.join(BASE_DIR, 'debug_green.png'), o.green_mask)
        cv2.imwrite(os.path.join(BASE_DIR, 'debug_fish.png'), o.fish_mask)
        log(f"📷 debug_*: зона={o.zone} рыба={o.fish_y} прогресс={o.progress} тревога={o.warning} ({o.warning_score:.3f})")
        notify('Снимок и маски сохранены (debug_*.png)')
    except Exception as ex:
        log(f"❌ debug: {ex}")


CAPTURE = {"rod": (-34, -33, 68, 68), "bait": (-39, -39, 67, 57), "warning": (-110, -16, 220, 32), "inv_header": (-50, -20, 100, 40)}


def capture_template(name):
    """Через 4 с снимает шаблон вокруг курсора (для rod/bait: навести на центр иконки в инвентаре)."""
    from ctypes import wintypes
    for i in (4, 3, 2, 1):
        notify(f"Шаблон «{name}»: наведи курсор… {i}", "ok")
        time.sleep(1.0)
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    ox, oy, w, h = CAPTURE.get(name, (-14, -14, 28, 28))
    sx, sy = scale()
    shot = grab_px(pt.x + ox * sx, pt.y + oy * sy, w * sx, h * sy)
    # Шаблоны хранятся в эталонном разрешении; tpl() масштабирует при поиске.
    shot = cv2.resize(shot, (w, h), interpolation=cv2.INTER_AREA)
    os.makedirs(TPL_DIR, exist_ok=True)
    cv2.imwrite(os.path.join(TPL_DIR, name + ".png"), shot)
    _tpl_cache.pop(name, None)
    notify(f"Шаблон «{name}» сохранён", "ok")


# ==========================================================================
# 9. ИНТЕРФЕЙС: ОТРИСОВАННЫЕ ЗАРАНЕЕ СКРУГЛЁННЫЕ ЭЛЕМЕНТЫ (OpenCV, без Pillow)
# ==========================================================================
SS = 4                                  # суперсэмплинг для сглаживания
KEY = "#010101"                         # цвет «прозрачности» окна
RED = (42, 42, 184)                     # BGR для #b82a2a
FONT = "Segoe UI"
MONO = "Consolas"


def _enc(bgra):
    ok, buf = cv2.imencode(".png", bgra)
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _rr_mask(w, h, r):
    W, H, R = w * SS, h * SS, min(r, w // 2, h // 2) * SS
    m = np.zeros((H, W), np.uint8)
    cv2.rectangle(m, (R, 0), (W - R - 1, H - 1), 255, -1)
    cv2.rectangle(m, (0, R), (W - 1, H - R - 1), 255, -1)
    for cx, cy in ((R, R), (W - R - 1, R), (R, H - R - 1), (W - R - 1, H - R - 1)):
        cv2.circle(m, (cx, cy), R, 255, -1, cv2.LINE_AA)
    return cv2.resize(m, (w, h), interpolation=cv2.INTER_AREA)


def tile_img(w, h, r, fill=(60, 60, 60), grain=4.0, seed=1):
    """Тёмная плитка с мягким градиентом и «зерном», как на макете."""
    rng = np.random.RandomState(seed)
    base = np.zeros((h, w, 3), np.float32) + np.array(fill, np.float32)
    base += np.linspace(5, -5, h, dtype=np.float32)[:, None, None]
    base += rng.randn(h, w, 1).astype(np.float32) * grain
    return np.dstack([np.clip(base, 0, 255).astype(np.uint8), _rr_mask(w, h, r)])


def solid_img(w, h, r, color):
    m = _rr_mask(w, h, r)
    out = np.zeros((h, w, 4), np.uint8)
    out[..., :3] = color
    out[..., 3] = m
    return out


def over(bg, fg, x=0, y=0):
    """Альфа-композиция fg на bg (оба BGRA)."""
    h, w = fg.shape[:2]
    H, W = bg.shape[:2]
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, W), min(y + h, H)
    if x0 >= x1 or y0 >= y1:
        return bg
    f = fg[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32)
    b = bg[y0:y1, x0:x1].astype(np.float32)
    fa, ba = f[..., 3:4] / 255.0, b[..., 3:4] / 255.0
    oa = fa + ba * (1 - fa)
    rgb = (f[..., :3] * fa + b[..., :3] * ba * (1 - fa)) / np.maximum(oa, 1e-6)
    bg[y0:y1, x0:x1, :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    bg[y0:y1, x0:x1, 3:4] = np.clip(oa * 255, 0, 255).astype(np.uint8)
    return bg


def _icon_mask(name, size):
    """Маска иконки (uint8, size x size). Рисуется в 64-клеточной сетке с суперсэмплингом."""
    N = size * SS
    k = N / 64.0
    m = np.zeros((N, N), np.uint8)

    def p(x, y):
        return (int(round(x * k)), int(round(y * k)))

    def c(v):
        return int(round(v * k))
    if name == "target":
        cv2.circle(m, p(32, 32), c(19), 255, c(4), cv2.LINE_AA)
        cv2.circle(m, p(32, 32), c(8.5), 255, -1, cv2.LINE_AA)
        for a, b in (((32, 3), (32, 14)), ((32, 50), (32, 61)), ((3, 32), (14, 32)), ((50, 32), (61, 32))):
            cv2.line(m, p(*a), p(*b), 255, c(4), cv2.LINE_AA)
    elif name == "person":
        cv2.circle(m, p(32, 14), c(7.5), 255, -1, cv2.LINE_AA)
        cv2.rectangle(m, p(21, 25), p(43, 44), 255, -1, cv2.LINE_AA)
        cv2.circle(m, p(26, 27), c(5), 255, -1, cv2.LINE_AA)
        cv2.circle(m, p(38, 27), c(5), 255, -1, cv2.LINE_AA)
        cv2.rectangle(m, p(24, 40), p(30.5, 60), 255, -1, cv2.LINE_AA)
        cv2.rectangle(m, p(33.5, 40), p(40, 60), 255, -1, cv2.LINE_AA)
    elif name == "eye":
        pts = []
        for t in np.linspace(0, math.pi, 30):
            pts.append((32 + 25 * math.cos(t), 32 - 14 * math.sin(t)))
        for t in np.linspace(math.pi, 2 * math.pi, 30):
            pts.append((32 + 25 * math.cos(t), 32 - 14 * math.sin(t)))
        cv2.fillPoly(m, [np.array([p(x, y) for x, y in pts], np.int32)], 255, cv2.LINE_AA)
        cv2.circle(m, p(32, 32), c(9.5), 0, -1, cv2.LINE_AA)
        cv2.circle(m, p(32, 32), c(5), 255, -1, cv2.LINE_AA)
        for (x, y), (dx, dy) in (((6, 12), (1, 1)), ((58, 12), (-1, 1)), ((6, 52), (1, -1)), ((58, 52), (-1, -1))):
            cv2.line(m, p(x, y), p(x + 9 * dx, y), 255, c(3.5), cv2.LINE_AA)
            cv2.line(m, p(x, y), p(x, y + 9 * dy), 255, c(3.5), cv2.LINE_AA)
    elif name == "grid":
        s = 20
        cv2.rectangle(m, p(8, 8), p(8 + s, 8 + s), 255, -1, cv2.LINE_AA)
        cv2.rectangle(m, p(36, 8), p(36 + s, 8 + s), 255, c(3.5), cv2.LINE_AA)
        cv2.rectangle(m, p(8, 36), p(8 + s, 36 + s), 255, c(3.5), cv2.LINE_AA)
        cv2.line(m, p(13, 41), p(23, 51), 255, c(3.2), cv2.LINE_AA)
        cv2.line(m, p(23, 41), p(13, 51), 255, c(3.2), cv2.LINE_AA)
        cv2.rectangle(m, p(36, 36), p(36 + s, 36 + s), 255, c(3.5), cv2.LINE_AA)
        cv2.circle(m, p(46, 46), c(3.5), 255, -1, cv2.LINE_AA)
    elif name == "gear":
        teeth, ro, ri = 10, 29, 23
        pts = []
        for i in range(teeth * 4):
            a = 2 * math.pi * i / (teeth * 4)
            r = ro if (i % 4) in (1, 2) else ri
            pts.append(p(32 + r * math.cos(a), 32 + r * math.sin(a)))
        cv2.fillPoly(m, [np.array(pts, np.int32)], 255, cv2.LINE_AA)
        cv2.circle(m, p(32, 32), c(17.5), 0, -1, cv2.LINE_AA)
        for ang in (-90, 30, 150):
            a = math.radians(ang)
            cv2.line(m, p(32, 32), p(32 + 19 * math.cos(a), 32 + 19 * math.sin(a)), 255, c(4.2), cv2.LINE_AA)
        cv2.circle(m, p(32, 32), c(4.5), 255, -1, cv2.LINE_AA)
    return m


def icon_img(name, size, glow=False):
    N = size * SS
    big = _icon_mask(name, size)
    if glow:
        g = cv2.GaussianBlur(big, (0, 0), N / 14.0)
        big = np.maximum(big, (g.astype(np.float32) * 1.6).clip(0, 150).astype(np.uint8))
        big = np.maximum(big, _icon_mask(name, size))
    m = cv2.resize(big, (size, size), interpolation=cv2.INTER_AREA)
    out = np.zeros((size, size, 4), np.uint8)
    out[..., :3] = RED
    out[..., 3] = m
    return out


def tile_with_icon(w, h, r, name, isize, state):
    fill = {"normal": (58, 58, 58), "hover": (70, 70, 70), "active": (62, 60, 60)}[state]
    t = tile_img(w, h, r, fill)
    ic = icon_img(name, isize, glow=(state == "active"))
    return over(t, ic, (w - isize) // 2, (h - isize) // 2)


def switch_img(w, h, on):
    t = solid_img(w, h, h // 2, RED if on else (96, 96, 96))
    kn = np.zeros((h, w, 4), np.uint8)
    d = h - 6
    cx = w - 3 - d // 2 if on else 3 + d // 2
    big = np.zeros((h * SS, w * SS), np.uint8)
    cv2.circle(big, (cx * SS, h * SS // 2), d * SS // 2, 255, -1, cv2.LINE_AA)
    kn[..., :3] = (240, 240, 240)
    kn[..., 3] = cv2.resize(big, (w, h), interpolation=cv2.INTER_AREA)
    return over(t, kn)


def check_img(size):
    t = tile_img(size, size, size // 4, fill=(138, 138, 138), grain=2)
    big = np.zeros((size * SS, size * SS, 4), np.uint8)
    cx = cy = size * SS // 2
    cv2.circle(big, (cx, cy), int(size * SS * 0.32), (*RED, 255), -1, cv2.LINE_AA)
    s = size * SS
    pts = np.array([(cx - 0.14 * s, cy + 0.01 * s), (cx - 0.04 * s, cy + 0.11 * s), (cx + 0.16 * s, cy - 0.10 * s)], np.int32)
    cv2.polylines(big, [pts], False, (235, 235, 235, 255), max(2, int(size * SS * 0.07)), cv2.LINE_AA)
    ic = cv2.resize(big, (size, size), interpolation=cv2.INTER_AREA)
    return over(t, ic)


def dot_img(d, color):
    big = np.zeros((d * SS, d * SS), np.uint8)
    cv2.circle(big, (d * SS // 2, d * SS // 2), d * SS // 2 - 1, 255, -1, cv2.LINE_AA)
    out = np.zeros((d, d, 4), np.uint8)
    out[..., :3] = color
    out[..., 3] = cv2.resize(big, (d, d), interpolation=cv2.INTER_AREA)
    return out


def gray_to_bgra(g):
    return np.dstack([g, g, g, np.full(g.shape, 255, np.uint8)])


# ==========================================================================
# 10. ИНТЕРФЕЙС: ОКНО
# ==========================================================================
SIDE_X, TILE_W, TILE_H, GAP, TOP = 17, 131, 100, 18, 40
PANEL_X, PANEL_Y, PANEL_W, PANEL_H = 160, 40, 800, 572
WIN_W, WIN_H = 980, 652
ICONS = ["target", "person", "eye", "grid", "gear"]
PAGES = [("Рыбалка", "Полуавтомат: сам закидывает, проходит мини-игру и следит за наживкой"),
         ("Статистика", "Итоги этой сессии и за всё время"),
         ("Зрение", "Что видит бот: шкала мини-игры и шаблоны"),
         ("Модули", "Поведение рыбалки и звуки"),
         ("Настройки", "Клавиши, громкость, конфиг")]
EMOJI = re.compile("[\U00010000-\U0010FFFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u25A0-\u25FF]")
C_TEXT, C_DIM, C_RED, C_GREEN, C_WARN = "#ececec", "#9a9a9a", "#d63a3a", "#5fd38a", "#e0a23a"


class App:
    def __init__(self):
        self.S = float(CFG["ui_scale"])
        self.root = tk.Tk()
        r = self.root
        r.title(APP_NAME)
        r.overrideredirect(True)
        r.configure(bg=KEY)
        try:
            r.attributes("-transparentcolor", KEY)
        except Exception:
            pass
        try:
            r.attributes("-topmost", True)
        except Exception:
            pass
        W, H = self.u(WIN_W), self.u(WIN_H)
        pos = CFG.get("win_pos") or [max(0, r.winfo_screenwidth() - W - 40), 70]
        r.geometry(f"{W}x{H}+{int(pos[0])}+{int(pos[1])}")
        self.cv = tk.Canvas(r, width=W, height=H, bg=KEY, highlightthickness=0, bd=0)
        self.cv.pack()
        self.imgs, self.ids = {}, itertools.count(1)
        self.page, self.dyn, self.toasts, self.hidden = 0, {}, [], False
        self._page_wins = []   # tk-виджеты текущей страницы, уничтожаем при смене
        self.drag = (0, 0)
        self.pill = None
        self.pill_msg, self.pill_until = "", 0.0
        self.capturing = None
        self.build_static()
        self.show_page(0)
        r.protocol("WM_DELETE_WINDOW", self.quit)
        r.after(60, self.pump)
        r.after(250, self.tick)

    # ------------------------------------------------------------ вспомогательное
    def u(self, v):
        return int(round(v * self.S))

    def img(self, key, builder):
        if key not in self.imgs:
            self.imgs[key] = tk.PhotoImage(data=_enc(builder()))
        return self.imgs[key]

    def put(self, image, x, y, tags=(), anchor="nw"):
        return self.cv.create_image(self.u(x), self.u(y), image=image, anchor=anchor, tags=tags)

    def txt(self, x, y, text, size=12, color=C_TEXT, bold=False, anchor="nw", tags=("page",), mono=False):
        font = (MONO if mono else FONT, max(7, int(round(size * self.S))), "bold" if bold else "normal")
        return self.cv.create_text(self.u(x), self.u(y), text=text, fill=color, font=font, anchor=anchor, tags=tags)

    def card(self, x, y, w, h, fill=(46, 46, 46), r=16, tags=("page",)):
        im = self.img(("card", w, h, r, fill), lambda: tile_img(self.u(w), self.u(h), self.u(r), fill, 3.0, 7))
        return self.put(im, PANEL_X + x, PANEL_Y + y, tags)

    def button(self, x, y, w, h, label, cmd, style="gray", size=12):
        ax, ay = PANEL_X + x, PANEL_Y + y
        colors = {"red": ((42, 42, 184), (58, 58, 208)), "gray": ((84, 84, 84), (104, 104, 104)),
                  "dark": ((66, 66, 66), (88, 88, 88))}[style]          # BGR
        rad = h // 2 if style == "red" else 10
        n_img = self.img(("btn", style, w, h, 0), lambda: solid_img(self.u(w), self.u(h), self.u(rad), colors[0]))
        h_img = self.img(("btn", style, w, h, 1), lambda: solid_img(self.u(w), self.u(h), self.u(rad), colors[1]))
        tag = f"b{next(self.ids)}"
        it = self.put(n_img, ax, ay, ("page", tag))
        tx = self.txt(ax + w / 2, ay + h / 2, label, size, "#ffffff", True, "center", ("page", tag))
        self.cv.tag_bind(tag, "<Button-1>", lambda e: cmd())
        self.cv.tag_bind(tag, "<Enter>", lambda e: self.cv.itemconfig(it, image=h_img))
        self.cv.tag_bind(tag, "<Leave>", lambda e: self.cv.itemconfig(it, image=n_img))
        return it, tx

    def toggle(self, x, y, key):
        on_i = self.img(("sw", 1), lambda: switch_img(self.u(52), self.u(28), True))
        off_i = self.img(("sw", 0), lambda: switch_img(self.u(52), self.u(28), False))
        tag = f"t{next(self.ids)}"
        it = self.put(on_i if CFG[key] else off_i, PANEL_X + x, PANEL_Y + y, ("page", tag))

        def flip(_e=None):
            CFG[key] = not CFG[key]
            self.cv.itemconfig(it, image=on_i if CFG[key] else off_i)
            save_cfg()
        self.cv.tag_bind(tag, "<Button-1>", flip)
        return it

    def stepper(self, x, y, key, lo, hi, step, fmt="{:g}", on_change=None):
        tag_m, tag_p = f"m{next(self.ids)}", f"p{next(self.ids)}"
        mi = self.img(("stp", "-"), lambda: self._step_tile("−"))
        pl = self.img(("stp", "+"), lambda: self._step_tile("+"))
        self.put(mi, PANEL_X + x, PANEL_Y + y, ("page", tag_m))
        self.put(pl, PANEL_X + x + 112, PANEL_Y + y, ("page", tag_p))
        val = self.txt(PANEL_X + x + 71, PANEL_Y + y + 15, fmt.format(CFG[key]), 13, C_TEXT, True, "center")

        def bump(d):
            v = round(min(hi, max(lo, CFG[key] + d * step)), 3)
            CFG[key] = int(v) if float(v).is_integer() and isinstance(DEFAULT_CFG[key], int) else v
            self.cv.itemconfig(val, text=fmt.format(CFG[key]))
            save_cfg()
            if on_change:
                on_change()
        self.cv.tag_bind(tag_m, "<Button-1>", lambda e: bump(-1))
        self.cv.tag_bind(tag_p, "<Button-1>", lambda e: bump(+1))

    def xy_entry(self, x, y, cfg_key, label):
        """Два поля ввода X / Y + кнопка Задать + кнопка Сброс для ручного ввода координат."""
        self.txt(PANEL_X + 56, PANEL_Y + y + 10, label, 12, C_TEXT)

        cur = CFG.get(cfg_key) or [0, 0]
        vx = tk.StringVar(value=str(int(cur[0])))
        vy = tk.StringVar(value=str(int(cur[1])))

        S = self.S
        ex = tk.Entry(self.cv, textvariable=vx, width=6, font=(FONT, max(8, int(11 * S))),
                      bg="#3a3a3a", fg="#ffffff", insertbackground="#ffffff",
                      relief="flat", bd=4, highlightthickness=0)
        ey = tk.Entry(self.cv, textvariable=vy, width=6, font=(FONT, max(8, int(11 * S))),
                      bg="#3a3a3a", fg="#ffffff", insertbackground="#ffffff",
                      relief="flat", bd=4, highlightthickness=0)

        # Размещаем через create_window чтобы тег page их не удалял — сами следим через _page_wins
        wx = self.cv.create_window(self.u(PANEL_X + 390), self.u(PANEL_Y + y + 8), window=ex, anchor="nw", tags=("page",))
        wy = self.cv.create_window(self.u(PANEL_X + 460), self.u(PANEL_Y + y + 8), window=ey, anchor="nw", tags=("page",))
        self._page_wins.extend([ex, ey])

        self.txt(PANEL_X + 382, PANEL_Y + y + 10, "X:", 11, C_DIM)
        self.txt(PANEL_X + 452, PANEL_Y + y + 10, "Y:", 11, C_DIM)

        def apply_coords():
            try:
                xi, yi = int(vx.get()), int(vy.get())
                if not (0 <= xi < REF_W and 0 <= yi < REF_H):
                    raise ValueError("вне базового экрана")
                CFG[cfg_key] = [xi, yi]
                save_cfg()
                self.toast(f"{label} → ({xi}, {yi})", "ok")
                self.show_page(self.page)
            except ValueError:
                self.toast("Введи целые числа", "warn")

        def reset_coord():
            CFG[cfg_key] = None
            save_cfg()
            self.toast(f"{label} → авто", "ok")
            self.show_page(self.page)

        def pick_and_fill():
            def chosen(pt):
                vx.set(str(pt[0]))
                vy.set(str(pt[1]))
                CFG[cfg_key] = list(pt)
                save_cfg()
                self.toast(f"{label}: {pt[0]}, {pt[1]}")
            self.pick_on_screen(chosen)

        # Всё в одну строку — 📍 | Задать | Авто
        self.button(540, y, 32, 32, "📍", pick_and_fill, "gray", 12)
        self.button(580, y, 82, 32, "Задать", apply_coords, "gray", 10)
        self.button(670, y, 68, 32, "Авто", reset_coord, "dark", 10)

    def pick_on_screen(self, callback, rectangle=False, sample=False):
        """Оверлей над основным монитором; отрисовка рамки Canvas, Esc — отмена.
        Выбранные физические координаты переводятся в систему 1920x1080.
        Пипетка снимает пиксель ПОСЛЕ закрытия прозрачного оверлея.
        """
        if STATE['running']:
            self.toast("Сначала останови бота (F8)", "warn")
            return
        m = monitor()
        sx, sy = scale()
        self.root.withdraw()
        if self.pill:
            self.pill[0].withdraw()
        t = tk.Toplevel(self.root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.attributes("-alpha", 0.35)
        t.geometry(f"{m['width']}x{m['height']}+{m['left']}+{m['top']}")
        c = tk.Canvas(t, bg="#1e3438", cursor="crosshair", highlightthickness=0)
        c.pack(fill="both", expand=True)
        c.create_text(25, 20, text="Протяни рамку" if rectangle else "Кликни по экрану", fill="white", anchor="nw", font=(FONT, 20, "bold"))
        start = [None]
        box = [None]

        def local(e):
            return max(0, min(m['width'] - 1, e.x)), max(0, min(m['height'] - 1, e.y))

        def end(e=None, cancel=False):
            a = start[0]
            b = local(e) if e is not None else a
            t.destroy()
            if not sample or cancel:
                self.root.deiconify()
                self.hidden = False
            if cancel or a is None:
                return
            if rectangle:
                x0, x1 = sorted((a[0], b[0]))
                y0, y1 = sorted((a[1], b[1]))
                if x1 - x0 < 5 or y1 - y0 < 5:
                    self.toast("Прямоугольник слишком мал", "warn")
                    return
                rect = [round(x0 / sx), round(y0 / sy), round((x1-x0) / sx), round((y1-y0) / sy)]
                callback(rect)
            elif sample:
                px, py = m['left'] + b[0], m['top'] + b[1]
                # окно убрано; Tk успевает перерисовать экран перед mss.grab
                def sample_pixel():
                    try:
                        callback(grab_px(px, py, 1, 1)[0, 0])
                    finally:
                        self.root.deiconify()
                        self.hidden = False
                self.root.after(200, sample_pixel)
            else:
                callback((round(b[0] / sx), round(b[1] / sy)))

        def press(e):
            start[0] = local(e)
            if rectangle:
                box[0] = c.create_rectangle(*start[0], *start[0], outline="#5fd38a", width=4)

        def motion(e):
            if rectangle and box[0]:
                c.coords(box[0], *start[0], *local(e))

        c.bind("<ButtonPress-1>", press)
        c.bind("<B1-Motion>", motion)
        c.bind("<ButtonRelease-1>", lambda e: end(e))
        t.bind("<Escape>", lambda e: end(cancel=True))
        t.focus_force()

    def choose_roi(self, key):
        def chosen(rect):
            CFG[key] = rect
            if key == 'warning_roi':
                REGIONS['warning'] = rect
            save_cfg()
            self.toast(f"{key}: {rect}")
            self.show_page(2)
        self.pick_on_screen(chosen, rectangle=True)

    def eyedrop(self, key):
        def chosen(bgr):
            hsv = cv2.cvtColor(np.uint8([[bgr]]), cv2.COLOR_BGR2HSV)[0, 0].tolist()
            CFG[key + '_samples'].append(hsv)
            CFG[key + '_hsv'] = bounds_from_samples(CFG[key + '_samples'], CFG['sample_tolerance'])
            save_cfg()
            self.toast(f"{key}: HSV {hsv} · образцов {len(CFG[key + '_samples'])}")
            self.show_page(2)
        self.pick_on_screen(chosen, sample=True)

    def advanced(self):
        """Редактор всех численных порогов и HSV/ROI без правки JSON вручную."""
        if STATE['running']:
            self.toast("Останови бота перед калибровкой", "warn")
            return
        w = tk.Toplevel(self.root)
        w.title("Калибровка · пороги и области")
        w.geometry("700x620")
        w.configure(bg="#303030")
        frame = tk.Frame(w, bg="#303030")
        frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(frame, bg="#303030", highlightthickness=0)
        scroll = tk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg="#303030")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        keys = [k for k in CFG if (k in ('game_title_hint', 'template_thresholds') or k.endswith('_roi') or k.endswith('_hsv') or
                k in ('bar', 'menu_roi', 'menu_min_red', 'menu_up', 'use_offset',
                      'min_zone_area', 'zone_width_ratio', 'min_zone_height_ratio',
                      'min_fish_area', 'max_fish_area_ratio', 'min_fish_height_ratio',
                      'min_fish_width_ratio', 'fish_side_margin', 'fish_tracking_radius',
                      'fish_min_s', 'fish_min_v', 'fish_row_diff', 'progress_min_v', 'progress_max_s',
                      'progress_row_ratio', 'progress_crop_side', 'progress_bottom_trim',
                      'progress_gap_rows', 'progress_full', 'progress_full_frames',
                      'warning_red_ratio', 'warning_template_threshold',
                      'warning_seconds', 'warning_clear_frames', 'sample_tolerance',
                      'lost_limit', 'bite_seen_frames', 'loop_delay', 'minigame_timeout',
                      'fish_timeout', 'deadzone', 'lookahead', 'emergency_lookahead',
                      'max_vel', 'max_lead', 'max_hold', 'forced_release', 'min_switch',
                      'max_lost_games', 'max_failures', 'no_bite_limit', 'inventory_timeout',
                      'menu_timeout', 'after_equip_delay', 'post_catch_delay'))]
        fields = {}
        for i, key in enumerate(keys):
            tk.Label(inner, text=key, bg="#303030", fg="white", width=26, anchor="w").grid(row=i, column=0, padx=8, pady=3)
            v = tk.StringVar(value=json.dumps(CFG[key], ensure_ascii=False))
            tk.Entry(inner, textvariable=v, width=48, bg="#454545", fg="white", insertbackground="white").grid(row=i, column=1)
            fields[key] = v

        def apply():
            try:
                values = {k: json.loads(v.get()) for k, v in fields.items()}
                for key in ('bar', 'menu_roi', 'rod_roi', 'bait_roi', 'inv_header_roi', 'progress_roi', 'warning_roi'):
                    x, y, ww, hh = values[key]
                    if ww < 5 or hh < 5 or x < 0 or y < 0 or x + ww > REF_W or y + hh > REF_H:
                        raise ValueError(key + ': область вне экрана')
                for k in keys:
                    if k.endswith('_hsv'):
                        z = values[k]
                        if len(z) != 2 or any(len(row) != 3 for row in z):
                            raise ValueError(k + ': ожидаются [[H,S,V],[H,S,V]]')
                    elif isinstance(DEFAULT_CFG[k], (int, float)) and not isinstance(values[k], (int, float)):
                        raise ValueError(k + ': ожидается число')
                if not isinstance(values['game_title_hint'], str) or not isinstance(values['template_thresholds'], dict):
                    raise ValueError('game_title_hint: строка, template_thresholds: JSON-словарь')
                if any(not isinstance(v, (int, float)) or not 0 <= v <= 1 for v in values['template_thresholds'].values()):
                    raise ValueError('template_thresholds: числа от 0 до 1')
                CFG.update(values)
                REGIONS['warning'] = CFG['warning_roi']
                save_cfg()
                w.destroy()
                self.show_page(self.page)
                self.toast("Калибровка сохранена")
            except (ValueError, TypeError, KeyError) as ex:
                from tkinter import messagebox
                messagebox.showerror("Ошибка калибровки", str(ex), parent=w)
        tk.Button(w, text="Применить", command=apply, bg="#5fd38a").pack(pady=8)

    def _step_tile(self, sign):
        s = self.u(30)
        t = tile_img(s, s, self.u(8), (74, 74, 74), 2)
        big = np.zeros((s * SS, s * SS), np.uint8)
        c, L = s * SS // 2, int(s * SS * 0.22)
        cv2.line(big, (c - L, c), (c + L, c), 255, max(2, SS * 2), cv2.LINE_AA)
        if sign == "+":
            cv2.line(big, (c, c - L), (c, c + L), 255, max(2, SS * 2), cv2.LINE_AA)
        ic = np.zeros((s, s, 4), np.uint8)
        ic[..., :3] = (240, 240, 240)
        ic[..., 3] = cv2.resize(big, (s, s), interpolation=cv2.INTER_AREA)
        return over(t, ic)

    # ------------------------------------------------------------ статичные части
    def build_static(self):
        S = self.S
        panel = self.img(("panel",), lambda: tile_img(self.u(PANEL_W), self.u(PANEL_H), self.u(22), (58, 58, 58), 4.0, 3))
        self.put(panel, PANEL_X, PANEL_Y, ("static", "drag"))
        self.cv.tag_bind("drag", "<ButtonPress-1>", self.drag_start)
        self.cv.tag_bind("drag", "<B1-Motion>", self.drag_move)
        self.side = []
        for i, name in enumerate(ICONS):
            y = TOP + i * (TILE_H + GAP)
            imgs = {st: self.img(("side", name, st), lambda st=st, name=name: tile_with_icon(
                self.u(TILE_W), self.u(TILE_H), self.u(18), name, self.u(60), st)) for st in ("normal", "hover", "active")}
            tag = f"side{i}"
            it = self.put(imgs["normal"], SIDE_X, y, ("static", tag))
            self.side.append((it, imgs))
            self.cv.tag_bind(tag, "<Button-1>", lambda e, i=i: self.show_page(i))
            self.cv.tag_bind(tag, "<Enter>", lambda e, i=i: self._side_hover(i, True))
            self.cv.tag_bind(tag, "<Leave>", lambda e, i=i: self._side_hover(i, False))

    def _side_hover(self, i, on):
        it, imgs = self.side[i]
        if i != self.page:
            self.cv.itemconfig(it, image=imgs["hover" if on else "normal"])

    def drag_start(self, e):
        self.drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def drag_move(self, e):
        self.root.geometry(f"+{e.x_root - self.drag[0]}+{e.y_root - self.drag[1]}")
        CFG["win_pos"] = [e.x_root - self.drag[0], e.y_root - self.drag[1]]

    # ------------------------------------------------------------ страницы
    def show_page(self, i):
        self.page = i
        self.cv.delete("page")
        # Уничтожаем tk-виджеты (Entry и т.п.) предыдущей страницы
        for w in self._page_wins:
            try:
                w.destroy()
            except Exception:
                pass
        self._page_wins = []
        self.dyn = {}
        for k, (it, imgs) in enumerate(self.side):
            self.cv.itemconfig(it, image=imgs["active" if k == i else "normal"])
        title, sub = PAGES[i]
        self.txt(PANEL_X + 30, PANEL_Y + 24, title, 24, "#ffffff", True)
        self.txt(PANEL_X + 30, PANEL_Y + 62, sub, 11, C_DIM)
        self.button(PANEL_W - 96, 22, 34, 34, "–", self.hide_window, "dark", 14)
        self.button(PANEL_W - 52, 22, 34, 34, "×", self.quit, "dark", 14)
        getattr(self, f"page{i}")()
        self.refresh()
        self.cv.tag_raise("toast")

    def page0(self):
        self.card(30, 100, 740, 132)
        self.dyn["title"] = self.txt(PANEL_X + 56, PANEL_Y + 122, "", 28, C_RED, True)
        self.dyn["detail"] = self.txt(PANEL_X + 56, PANEL_Y + 174, "", 12, C_DIM)
        self.dyn["btn"] = self.button(536, 148, 206, 62, "", self.toggle_click, "red", 15)
        for k, (lab, x) in enumerate((("ПОЙМАНО", 30), ("ВРЕМЯ", 284), ("РЫБ / ЧАС", 538))):
            self.card(x, 252, 232, 104)
            self.txt(PANEL_X + x + 24, PANEL_Y + 270, lab, 10, C_DIM, True)
            self.dyn[f"s{k}"] = self.txt(PANEL_X + x + 24, PANEL_Y + 298, "0", 28, "#ffffff", True)
        self.card(30, 376, 740, 176)
        self.txt(PANEL_X + 54, PANEL_Y + 388, "ЖУРНАЛ", 10, C_DIM, True)
        self.dyn["log"] = [self.txt(PANEL_X + 54, PANEL_Y + 414 + i * 20, "", 10, "#c8c8c8", False, "nw", ("page",), True)
                           for i in range(6)]

    def page1(self):
        self.card(30, 100, 740, 440)
        rows = ["Поймано за эту сессию", "Время сессии", "Рыб в час", "Среднее время мини-игры", "Проверок наживки",
                "Срывов за сессию", "Неясных исходов", "Поймано за всё время", "Срывов за всё время", "Сессий всего", "Лучшая сессия", "Последняя остановка"]
        for k, lab in enumerate(rows):
            y = 116 + k * 35
            self.txt(PANEL_X + 62, PANEL_Y + y, lab, 12, C_DIM)
            self.dyn[f"r{k}"] = self.txt(PANEL_X + 740, PANEL_Y + y - 1, "", 13, "#ffffff", True, "ne")

    def page2(self):
        self.card(30, 100, 250, 440)
        self.txt(PANEL_X + 48, PANEL_Y + 116, "ОСНОВНАЯ + ПРОГРЕСС", 10, C_DIM, True)
        self.dyn["bar"] = self.put(self.img(("bar0",), lambda: tile_img(self.u(84), self.u(290), self.u(8), (30, 30, 30))),
                                   PANEL_X + 50, PANEL_Y + 142, ("page",))
        self.dyn["bartxt"] = self.txt(PANEL_X + 145, PANEL_Y + 145, "", 10, C_TEXT)
        self.dyn['vision_dots'] = [self.cv.create_oval(self.u(PANEL_X + 258), self.u(PANEL_Y + 146 + i * 21),
                                    self.u(PANEL_X + 268), self.u(PANEL_Y + 156 + i * 21),
                                    fill=C_DIM, outline='', tags=('page',)) for i in range(4)]
        self.txt(PANEL_X + 48, PANEL_Y + 454, "F9 · скриншот + маски", 10, C_DIM)
        self.card(300, 100, 470, 440)
        self.txt(PANEL_X + 320, PANEL_Y + 112, "ДЕТЕКЦИЯ / КАЛИБРОВКА", 11, C_DIM, True)
        for k, n in enumerate(('rod', 'bait', 'inv_header', 'warning')):
            y = 136 + k * 30
            self.dyn[f"d{k}"] = self.put(self.img(("dot", "gray"), lambda: dot_img(self.u(14), (110, 110, 110))),
                                         PANEL_X + 322, PANEL_Y + y + 3, ("page",))
            self.txt(PANEL_X + 346, PANEL_Y + y, TEMPLATE_LABELS[n], 11, C_TEXT)
            self.dyn[f"v{k}"] = self.txt(PANEL_X + 751, PANEL_Y + y, "", 10, C_DIM, False, "ne")
        self.txt(PANEL_X + 320, PANEL_Y + 262, "ОБЛАСТИ · протяни рамку мышью", 10, C_DIM)
        for x, label, key in ((320, "Основная", "bar"), (462, "Прогресс", "progress_roi"), (604, "Тревога", "warning_roi")):
            self.button(x, 282, 130, 32, label, lambda key=key: self.choose_roi(key), "gray", 10)
        self.txt(PANEL_X + 320, PANEL_Y + 322, "ПИПЕТКА · кликни по цвету в игре", 10, C_DIM)
        for x, label, key in ((320, "Зелёная", "green"), (430, "Фон", "blue"), (540, "Рыба", "fish"), (650, "Тревога", "red")):
            self.button(x, 342, 100, 32, label, lambda key=key: self.eyedrop(key), "gray", 10)
        self.txt(PANEL_X + 320, PANEL_Y + 388, "Для рыбы: samples или exclude в расширенной настройке", 10, C_DIM)
        self.button(320, 408, 134, 34, "Удочка PNG", lambda: self.cap('rod'), "dark", 10)
        self.button(464, 408, 134, 34, "Наживка PNG", lambda: self.cap('bait'), "dark", 10)
        self.button(608, 408, 142, 34, "Предупр. PNG", lambda: self.cap('warning'), "dark", 10)
        self.button(320, 455, 204, 42, "Пороги / ROI / HSV", self.advanced, "gray", 11)
        self.button(540, 455, 210, 42, "Рыба: " + ("маска" if CFG['fish_mode'] == 'exclude' else "образцы"), self.switch_fish_mode, "dark", 10)
        self.button(320, 502, 204, 30, "Очистить образцы", self.clear_samples, "dark", 10)
        self.button(540, 502, 210, 30, "Заголовок PNG", lambda: self.cap('inv_header'), "dark", 10)

    def switch_fish_mode(self):
        if STATE['running']:
            return
        CFG['fish_mode'] = 'samples' if CFG['fish_mode'] == 'exclude' else 'exclude'
        save_cfg()
        self.toast('Рыба: ' + CFG['fish_mode'])
        self.show_page(2)

    def clear_samples(self):
        if STATE['running']:
            return
        for k in ('green', 'blue', 'fish', 'red'):
            CFG[k + '_samples'] = []
        save_cfg()
        self.toast("Образцы очищены; диапазоны оставлены")

    def page3(self):
        self.card(30, 100, 740, 440)
        self.txt(PANEL_X + 56, PANEL_Y + 113, "ЗАБРОС: инвентарь каждый раз / удочка в руках", 12, C_TEXT)
        self.button(550, 106, 186, 36, "Сменить режим", self.switch_mode, "red", 10)
        self.dyn['mode'] = self.txt(PANEL_X + 730, PANEL_Y + 156, "", 11, C_GREEN, True, "ne")
        self.txt(PANEL_X + 56, PANEL_Y + 159, "Поиск удочки: фиксированный слот / шаблон", 12, C_TEXT)
        self.button(550, 153, 186, 36, "Сменить поиск", self.switch_rod_mode, "gray", 10)
        self.dyn['rodmode'] = self.txt(PANEL_X + 730, PANEL_Y + 202, "", 11, C_GREEN, True, "ne")
        rows = [("Контроль наживки (нужен bait.png)", "t", "check_bait"),
                ("Проверять каждые N забросов (в режиме в руке)", "s", ("bait_check_every", 1, 50, 1, "{:g}")),
                ("Ждать поклёвку, сек", "s", ("bite_timeout", 10, 180, 10, "{:g}")),
                ("Пауза после мини-игры, сек", "s", ("post_catch_delay", 0.2, 8, 0.2, "{:.1f}")),
                ("Прятать окно во время ловли", "t", "hide_when_running"),
                ("Звук: старт", "t", "sound_start"),
                ("Звук: стоп", "t", "sound_end"),
                ("Звук: улов", "t", "sound_catch")]
        for k, (lab, kind, arg) in enumerate(rows):
            y = 209 + k * 40
            self.txt(PANEL_X + 56, PANEL_Y + y + 6, lab, 11, C_TEXT)
            if kind == 't':
                self.toggle(660, y + 2, arg)
            else:
                self.stepper(600, y, *arg)

    def switch_mode(self):
        if STATE['running']:
            self.toast('Сначала останови бота', 'warn')
            return
        CFG['cast_mode'] = 'hand' if CFG['cast_mode'] == 'inventory' else 'inventory'
        save_cfg()
        self.show_page(3)

    def switch_rod_mode(self):
        if STATE['running']:
            self.toast('Сначала останови бота', 'warn')
            return
        CFG['rod_mode'] = 'template' if CFG['rod_mode'] == 'fixed' else 'fixed'
        save_cfg()
        self.show_page(3)

    def page4(self):
        self.card(30, 100, 740, 460)
        rows = [("Старт / Стоп", "bind_toggle"), ("Аварийный стоп", "bind_panic"), ("Показать / скрыть окно", "bind_gui"), ("Снимок отладки", "bind_debug")]
        for k, (lab, key) in enumerate(rows):
            y = 114 + k * 40
            self.txt(PANEL_X + 56, PANEL_Y + y + 8, lab, 12, C_TEXT)
            self.dyn[f"k_{key}"] = self.txt(PANEL_X + 540, PANEL_Y + y + 8, CFG[key].upper(), 13, "#ffffff", True, "ne")
            self.button(560, y, 160, 36, "Изменить", lambda key=key: self.rebind(key), "gray", 11)
        y = 114 + 4 * 40
        self.txt(PANEL_X + 56, PANEL_Y + y + 8, "Громкость звуков, %", 12, C_TEXT)
        self.stepper(560, y, "volume", 0, 100, 10, "{:g}", on_change=lambda: (ensure_sounds(), play("start")))
        y = 114 + 5 * 40
        self.txt(PANEL_X + 56, PANEL_Y + y + 8, "Задержка заброса, сек", 12, C_TEXT)
        self.stepper(560, y, "cast_delay", 0.3, 3.0, 0.1, "{:.1f}")
        # Поля ввода координат удочки и «Использовать»
        y = 114 + 6 * 40
        self.xy_entry(0, y, "rod_click_pos", "ПКМ удочка:")
        y = 114 + 7 * 40
        self.xy_entry(0, y, "use_click_pos", "ЛКМ «Использовать»:")
        self.dyn["game"] = self.txt(PANEL_X + 56, PANEL_Y + 444, "", 11, C_DIM)
        self.button(56, 464, 148, 36, "Сохранить", self.do_save, "gray", 11)
        self.button(214, 464, 148, 36, "Загрузить", self.do_load, "gray", 11)
        self.button(372, 464, 148, 36, "Сбросить", self.do_reset, "dark", 11)

    # ------------------------------------------------------------ действия
    def toggle_click(self):
        toggle_bot()

    def cap(self, name):
        threading.Thread(target=capture_template, args=(name,), daemon=True).start()

    def do_save(self):
        self.toast("Конфиг сохранён успешно" if save_cfg() else "Не удалось сохранить конфиг", "ok")

    def do_load(self):
        if STATE['running']:
            self.toast('Сначала останови бота', 'warn')
            return
        ok = load_cfg()
        if ok:
            register_hotkeys()
        self.toast("Конфиг загружен успешно" if ok else "Файл конфига не найден", "ok" if ok else "warn")
        self.show_page(self.page)

    def do_reset(self):
        if STATE['running']:
            self.toast('Сначала останови бота', 'warn')
            return
        reset_cfg()
        save_cfg()
        register_hotkeys()
        self.toast("Настройки сброшены", "ok")
        self.show_page(self.page)

    def rebind(self, key):
        if self.capturing:
            return
        self.capturing = key
        self.cv.itemconfig(self.dyn[f"k_{key}"], text="…")

        def worker():
            while True:
                ev = keyboard.read_event()
                if ev.event_type == keyboard.KEY_DOWN:
                    break
            EVENTS.put(("bind", key, ev.name))
        threading.Thread(target=worker, daemon=True).start()

    def hide_window(self):
        self.root.withdraw()
        self.hidden = True
        # Скрываем курсор когда бот работает
        try:
            ctypes.windll.user32.ShowCursor(False)
        except Exception:
            pass

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.attributes("-topmost", True)
        except Exception:
            pass
        self.hidden = False
        # Показываем курсор когда открыто меню
        try:
            ctypes.windll.user32.ShowCursor(True)
        except Exception:
            pass

    def quit(self):
        stop_bot()
        release_all()
        save_cfg()
        save_totals()
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        self.root.destroy()

    # ------------------------------------------------------------ тосты
    def toast(self, text, kind="ok"):
        self.pill_msg, self.pill_until = text, time.time() + 3.5
        if self.hidden:
            return
        w = min(420, max(230, int(len(text) * 9.6) + 40))
        n = len(self.toasts)
        y = 84 + n * 54
        tag = f"toast{next(self.ids)}"
        x = PANEL_W - 30 - 44 - 10 - w
        bar = self.img(("tbar", w), lambda: tile_img(self.u(w), self.u(40), self.u(12), (138, 138, 138), 2))
        chk = self.img(("chk",), lambda: check_img(self.u(40)))
        self.put(bar, PANEL_X + x, PANEL_Y + y, (tag, "toast"))
        self.txt(PANEL_X + x + 16, PANEL_Y + y + 20, text, 12, "#202020", True, "w", (tag, "toast"))
        self.put(chk, PANEL_X + x + w + 10, PANEL_Y + y, (tag, "toast"))
        self.toasts.append(tag)
        self.root.after(2800, lambda: self.drop_toast(tag))

    def drop_toast(self, tag):
        self.cv.delete(tag)
        if tag in self.toasts:
            self.toasts.remove(tag)

    # ------------------------------------------------------------ оверлей-«пилюля»
    def build_pill(self):
        t = tk.Toplevel(self.root)
        t.title(APP_NAME + " status")
        t.overrideredirect(True)
        t.configure(bg=KEY)
        try:
            t.attributes("-transparentcolor", KEY)
            t.attributes("-topmost", True)
        except Exception:
            pass
        w, h = self.u(380), self.u(46)
        x = max(0, (t.winfo_screenwidth() - w) // 2)
        t.geometry(f"{w}x{h}+{x}+6")
        cv = tk.Canvas(t, width=w, height=h, bg=KEY, highlightthickness=0, bd=0)
        cv.pack()
        bg = self.img(("pill",), lambda: tile_img(self.u(380), self.u(46), self.u(23), (50, 50, 50), 3, 5))
        cv.create_image(0, 0, image=bg, anchor="nw")
        dot_r = self.img(("dot", "red"), lambda: dot_img(self.u(14), RED))
        cv.create_image(self.u(20), self.u(16), image=dot_r, anchor="nw")
        label = cv.create_text(self.u(44), self.u(23), text="", fill=C_TEXT, anchor="w",
                               font=(FONT, max(8, int(round(12 * self.S))), "bold"))
        self.pill = (t, label, cv)

    def update_pill(self):
        if self.pill is None:
            return
        t, label, cv = self.pill
        if time.time() < self.pill_until and STATE['kind'] != 'error':
            text = self.pill_msg
        else:
            n = STATS["catches"]
            text = f"{STATE['title']} {STATE['detail'] if STATE['kind'] == 'error' else ''} · поймано {n} · {self.elapsed_text()}"
        cv.itemconfig(label, text=text)

    # ------------------------------------------------------------ обновление
    def elapsed(self):
        if not STATS["t0"]:
            return 0
        end = STATS["t_end"] if (STATS["t_end"] and not STATE["running"]) else time.time()
        return int(end - STATS["t0"])

    def elapsed_text(self):
        s = self.elapsed()
        return f"{s // 3600:d}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"

    def refresh(self):
        d, p = self.dyn, self.page
        run = STATE["running"]
        if p == 0 and "title" in d:
            col = {"run": C_GREEN, "busy": C_WARN, "error": C_RED}.get(STATE["kind"], C_DIM if not run else C_GREEN)
            self.cv.itemconfig(d["title"], text=STATE["title"], fill=col)
            self.cv.itemconfig(d["detail"], text=STATE["detail"])
            self.cv.itemconfig(d["btn"][1], text="СТОП  ·  F8" if run else "СТАРТ  ·  F8")
            n, el = STATS["catches"], max(1, self.elapsed())
            self.cv.itemconfig(d["s0"], text=str(n))
            self.cv.itemconfig(d["s1"], text=self.elapsed_text())
            self.cv.itemconfig(d["s2"], text=f"{n * 3600 / el:.0f}" if STATS["t0"] and n else "0")
            lines = list(LOG)[-6:]
            lines = [""] * (6 - len(lines)) + lines
            for it, line in zip(d["log"], lines):
                self.cv.itemconfig(it, text=EMOJI.sub("", line)[:78].replace("  ", " "))
        elif p == 1 and "r0" in d:
            mg = STATS["mg"]
            vals = [str(STATS["catches"]), self.elapsed_text(),
                    f"{STATS['catches'] * 3600 / max(1, self.elapsed()):.0f}" if STATS["catches"] else "0",
                    f"{sum(mg) / len(mg):.1f} с" if mg else "—", str(STATS["checks"]),
                    str(STATS["escapes"]), str(STATS["unknown"]),
                    str(TOTAL["catches"] + (STATS["catches"] if run else 0)),
                    str(TOTAL["escapes"] + (STATS["escapes"] if run else 0)), str(TOTAL["sessions"]),
                    str(max(TOTAL["best"], STATS["catches"])), TOTAL["last_reason"][:46]]
            for k, v in enumerate(vals):
                self.cv.itemconfig(d[f"r{k}"], text=v)
        elif p == 2 and "bar" in d:
            try:
                bgr = grab(CFG['bar'])
                pr = grab(CFG['progress_roi'])
                o = analyze_bar(bgr, CFG)
                o.progress = analyze_progress(pr, CFG)
                o.warning, o.warning_score = analyze_warning(grab(CFG['warning_roi']), CFG, tpl('warning'))
                vis = annotate(bgr, pr, o)
                vis = cv2.resize(vis, (self.u(84), self.u(290)), interpolation=cv2.INTER_AREA)
                self.imgs['barlive'] = tk.PhotoImage(data=_enc(cv2.cvtColor(vis, cv2.COLOR_BGR2BGRA)))
                self.cv.itemconfig(d['bar'], image=self.imgs['barlive'])
                status = (f"ЗОНА {'●' if o.present else '○'}\n"
                          f"РЫБА {'●' if o.fish_y is not None else '○'}\n"
                          f"ПРОГРЕСС {o.progress:.0%}\n" if o.progress is not None else "ПРОГРЕСС —\n")
                self.cv.itemconfig(d['bartxt'], text=status + f"ТРЕВОГА {'●' if o.warning else '○'}")
                for dot, good in zip(d['vision_dots'], (o.present, o.fish_y is not None,
                                                         o.progress is not None and o.progress > 0,
                                                         o.warning)):
                    self.cv.itemconfig(dot, fill=C_GREEN if good else C_RED)
            except Exception as ex:
                self.cv.itemconfig(d['bartxt'], text=str(ex)[:35])
            for k, n in enumerate(('rod', 'bait', 'inv_header', 'warning')):
                try:
                    score = best_score(n)
                except Exception:
                    score = None
                threshold = CFG["template_thresholds"].get(n, THR[n])
                good = score is not None and score >= threshold
                key = ('dot', 'ok' if good else ('none' if score is None else 'bad'))
                col = (138, 211, 95) if good else ((110, 110, 110) if score is None else (58, 58, 214))
                self.cv.itemconfig(d[f'd{k}'], image=self.img(key, lambda col=col: dot_img(self.u(14), col)))
                self.cv.itemconfig(d[f'v{k}'], text='нет файла' if score is None else f'{score:.2f}/{threshold:.2f}')
        elif p == 3 and 'mode' in d:
            self.cv.itemconfig(d['mode'], text='ИНВЕНТАРЬ' if CFG['cast_mode'] == 'inventory' else 'В РУКЕ')
            self.cv.itemconfig(d['rodmode'], text='ФИКС. СЛОТ' if CFG['rod_mode'] == 'fixed' else 'ШАБЛОН')
        elif p == 4 and "game" in d:
            self.cv.itemconfig(d["game"], text=f"Окно игры: «{GAME_TITLE}»" if GAME_TITLE else "Окно игры определяется при старте (F8 в игре)")

    def tick(self):
        try:
            self.refresh()
            self.update_pill()
        finally:
            self.root.after(500 if self.page == 2 else 250, self.tick)

    def pump(self):
        try:
            while True:
                ev = EVENTS.get_nowait()
                kind = ev[0]
                if kind == "toast":
                    self.toast(ev[1], ev[2])
                elif kind == "run":
                    self.on_run(ev[1])
                elif kind == "toggle":
                    toggle_bot()
                elif kind == "gui":
                    self.hide_window() if not self.hidden else self.show_window()
                elif kind == "debug":
                    dump_debug()
                elif kind == "bind":
                    self.apply_bind(ev[1], ev[2])
                elif kind == "refresh_page":
                    self.show_page(self.page)
        except queue.Empty:
            pass
        self.root.after(60, self.pump)

    def on_run(self, running):
        if running:
            if CFG["hide_when_running"]:
                self.hide_window()
                if self.pill is None:
                    self.build_pill()
                self.pill[0].deiconify()
        else:
            if self.pill is not None:
                self.pill[0].withdraw()
            self.show_window()
            self.show_page(self.page)

    def apply_bind(self, key, name):
        if name != 'esc':
            others = [CFG[k] for k in ('bind_toggle', 'bind_panic', 'bind_gui', 'bind_debug') if k != key]
            if name in others:
                self.toast('Клавиша уже занята другим действием', 'warn')
            else:
                old = CFG[key]
                CFG[key] = name
                try:
                    register_hotkeys()
                    save_cfg()
                except Exception as ex:
                    CFG[key] = old
                    register_hotkeys()
                    self.toast(f'Ошибка хоткея: {ex}', 'warn')
        self.capturing = None
        if self.page == 4:
            self.show_page(4)


HK = []


def register_hotkeys():
    for h in HK:
        try:
            keyboard.remove_hotkey(h)
        except Exception:
            pass
    HK.clear()
    HK.append(keyboard.add_hotkey(CFG["bind_toggle"], lambda: EVENTS.put(("toggle",))))
    HK.append(keyboard.add_hotkey(CFG["bind_panic"], panic))
    HK.append(keyboard.add_hotkey(CFG["bind_gui"], lambda: EVENTS.put(("gui",))))
    HK.append(keyboard.add_hotkey(CFG["bind_debug"], lambda: EVENTS.put(("debug",))))


def main():
    missing = [n for n, m in (("opencv-python", cv2), ("mss", mss), ("pydirectinput", pydirectinput),
                              ("keyboard", keyboard), ("tkinter", tk)) if m is None]
    if os.name != "nt":
        print("Этот проект отправляет ввод через Windows SendInput и запускается только в Windows")
        return
    if missing:
        print("Не установлено:", ", ".join(missing))
        print("pip install opencv-python numpy mss pydirectinput keyboard")
        input("Enter для выхода")
        sys.exit(1)
    ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass
    pydirectinput.PAUSE = 0
    pydirectinput.FAILSAFE = False
    load_cfg()
    load_totals()
    os.makedirs(TPL_DIR, exist_ok=True)
    ensure_sounds()
    app = App()
    register_hotkeys()
    log(f"{APP_NAME}: готов. {CFG['bind_toggle'].upper()} — старт/стоп, {CFG['bind_panic'].upper()} — аварийный стоп")
    app.root.mainloop()


if __name__ == "__main__":
    main()
