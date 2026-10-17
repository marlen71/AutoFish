# -*- coding: utf-8 -*-
"""
Eternal FishMod — полуавтомат рыбалки для Skyrim RP-сервера (Sovngarde и т.п.).

Сам берёт удочку, закидывает, проходит мини-игру (ПИД-регулятор), следит за наживкой
и ОТКЛЮЧАЕТСЯ, когда наживка кончилась. Никакой ходьбы, торговли и маршрутов.

Что нового в этой версии:
  * Захват экрана: DXGPU Desktop Duplication (dxcam / bettercam) как ОСНОВНОЙ метод
    для ВСЕХ путей (мини-игра, шаблоны, инвентарь, отладочный снимок, страница «Зрение»).
    Резерв без единой зависимости — собственный GDI-захват региона (ctypes, BitBlt).
    Сторонний резервный пакет вырезан полностью: он пересоздавал контекст на каждый
    кадр и конвертировал весь монитор -> ~12 мс за кадр, что ломало ШИМ мини-игры.
  * Мини-игра: РЕЛЕ с предсказанием останова — каждый кадр бот считает, где зелёная
    зона остановится при «жать» и при «отпустить», и выбирает действие с точкой
    останова ближе к ЦЕНТРУ рыбы. Ни ПИД, ни ШИМ, ни скважности: решение всегда
    двоичное и привязано к кадрам, поэтому не насыщается и не «зажимает» зону над
    рыбой даже на медленном захвате; разгоны зоны измеряются по кадрам (адаптация).
  * Распознавание рыбы не зависит от её цвета (контраст по горизонтали внутри шкалы),
    поэтому подходит для любых видов рыб.
  * Полная локализация интерфейса: RU / EN / UA, переключение на лету (страница «Настройки»).
  * Авто-закидывание — ЗРЕНИЕ (v1.21, запись макро удалена): в открытом инвентаре
    бот сам находит удочку по шаблону rod.png и кликает «Использовать» (белая строка
    над красной «Выбросить»). Клики ставятся ПРЯМО В ОКНО интерфейса игры (DOM в
    CEF/Chromium) — курсор мыши Windows не двигается вовсе, поэтому игровой курсор
    (клиент ведёт его сам) ни на что не влияет. Работает при любом разрешении
    (мульти-масштабный поиск). Инвентарь открывает человек (TAB бот не жмёт).
    «Только мини-игра» = инвентарь и забросы отключены.
  * Лаунчер launch.py / start.bat, файл VERSION + scripts/release.py (релизы на GitHub).

Установка:  python launch.py   (сам поставит зависимости)   или   pip install -r requirements.txt
Запуск:     python eternal_fishmod.py    (от администратора, если игра запущена от админа)

Клавиши:    F8 — старт/стоп, F10 — аварийный стоп, Insert — показать/скрыть окно, F9 — диагностика.
Рядом:      templates/ (картинки-шаблоны), sounds/ (свои start/end/alert/catch.wav необязательны)
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
import threading
import itertools
import traceback
import collections
import re

import cv2
import numpy as np

try:
    import tkinter as tk
except ImportError:
    tk = None
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

# --- захват через дублирование DXGI: dxcam (основной) и bettercam (второй DXGI) ---
# Прежний сторонний резервный захватчик вырезан из проекта целиком: он подключался
# МОЛЧА и на ~20 к/с ломал ШИМ (ЛКМ «залипало», зона улетала наверх и не догоняла
# рыбу). Вместо него — собственный GDI-путь (_GdiBackend на ctypes: user32.GetDC +
# gdi32.BitBlt/GetDIBits, ноль зависимостей, берётся только регион, DC живёт в
# потоке). Он третий в списке кандидатов и не подменяет DXGI незаметно: бэкенд и его
# fps всегда видны в шапке, в журнале и на странице «Зрение».
# Причина отказа импорта сохраняется: без неё пользователь видит «dxcam не установлен»,
# хотя на самом деле пакет стоит и падает, например, из-за comtypes или защищённого окна.
_CAP_IMPORT_ERR = {}


def _import_capture(modname):
    try:
        return __import__(modname)
    except Exception as e:
        _CAP_IMPORT_ERR[modname] = "%s: %s" % (type(e).__name__, str(e).strip()[:200])
        return None


dxcam = _import_capture("dxcam")
bettercam = _import_capture("bettercam")

APP_NAME = "Eternal FishMod"
APP_VERSION = "1.24.2"            # синхронизируется скриптом scripts/release.py с файлом VERSION
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TPL_DIR = os.path.join(BASE_DIR, "templates")
SND_DIR = os.path.join(BASE_DIR, "sounds")
CFG_PATH = os.path.join(BASE_DIR, "fishmod_config.json")
STATS_PATH = os.path.join(BASE_DIR, "fishmod_stats.json")
LOG_PATH = os.path.join(BASE_DIR, "fishmod.log")
VERSION_PATH = os.path.join(BASE_DIR, "VERSION")
CFG_VERSION = 11                 # формат конфига: меняем только при НЕсовместимых правках
REF_W, REF_H = 1920, 1080


def read_version():
    """Файл VERSION — источник истины; APP_VERSION в коде синхронизируется release.py."""
    global APP_VERSION
    try:
        with open(VERSION_PATH, "r", encoding="utf-8") as f:
            v = f.read().strip()
        if re.match(r"^\d+\.\d+\.\d+$", v):
            if v != APP_VERSION:
                APP_VERSION = v
    except Exception:
        pass
    return APP_VERSION


# ==========================================================================
# 1. НАСТРОЙКИ
# ==========================================================================
DEFAULT_CFG = {
    "lang": "ru",                      # ru | en | ua — язык интерфейса (RU/EN/UA на странице «Настройки»)
    "bind_toggle": "f8", "bind_panic": "f10", "bind_gui": "insert", "bind_debug": "f9",
    "ui_click_window": True,             # клики экипировки прямо в окно интерфейса (курсор не двигается)
    "rod_thr": 0.80,                     # порог поиска удочки в инвентаре (шаблон rod.png)
    "bar": [913, 471, 50, 529],          # область шкалы мини-игры (x, y, w, h) для 1920x1080
    "bar_pad": 22,                       # расширить кадр вокруг шкалы — нужен для красной рамки «РЫБА СРЫВАЕТСЯ»
    "bar_refine": True,                  # каждое измерение сверяется с РЕАЛЬНОЙ шкалой на кадре
                                         # (cfg-координаты = только подсказка): лечит «бот не
                                         # видит рыбу» после смены разрешения/масштаба Windows
    "bar_autofit": True,                 # если шкала вовсе вылезла из окна захвата — пересчитать
                                         # CFG["bar"] по всему экрану и продолжить (с записью в конфиг)
    "equip_on_start": True,              # брать удочку из инвентаря, если её нет в руках
    "auto_cast": True,                   # автоматически закидывать удочку (если False - только мини-игра)
    "cast_after_catch": True,            # закидывать удочку после каждой рыбы
    "bite_timeout": 90,                  # сколько секунд ждать поклёвку
    "no_bite_limit": 3,                  # столько таймаутов подряд -> стоп (нет поклёвок/перегруз)
    "post_catch_delay": 2.5,             # пауза после пойманной рыбы перед следующим циклом
    "after_equip_delay": 1.2,            # пауза после «Использовать» до заброса
    "cast_delay": 0.8,                   # пауза перед закидыванием удочки
    # ВИЗУАЛЬНЫЙ АВТО-ЗАКИД (v1.9): жёстких координат НЕТ. Удочка ищется по ВСЕМУ экрану
    # (мульти-масштабный шаблон rod.png), «Использовать» — по красной строке «Выбросить»
    # в открытом меню. Ключи ниже — только РУЧНОЕ переопределение (страница «Настройки»):
    # 📍 у «ПКМ удочка» заодно снимает шаблон rod.png с экрана; пусто/None = автопоиск.
    "tpl_selflearn": True,               # наживка: лучший стек обновляет bait.png с экрана
    # АВТО-ЗАКИД = ЗРЕНИЕ (v1.21): удочка ищется по шаблону rod.png в открытом
    # инвентаре, «Использовать» — по красной строке меню предмета; клики ставятся
    # прямо в окно интерфейса игры (ui_click_window), курсор Windows не двигается.
    "sound_start": True, "sound_end": True, "sound_catch": False, "volume": 60,
    "hide_when_running": True,           # прятать окно, пока бот ловит (оверлей не мешает «зрению»)
    "ui_scale": 0.72,
    "win_pos": None,
    # ---------------- ЗАХВАТ ЭКРАНА (только DXGI; gdi = резерв без зависимостей) ----------------
    "capture_backend": "auto",           # auto | dxcam | bettercam | gdi
    "capture_fps": 144,                  # target_fps потока мини-игры (видео-режим)
    "capture_monitor": 0,                # индекс монитора захвата (0 = основной)
    # ---------------- РЕЛЕ-РЕГУЛЯТОР МИНИ-ИГРЫ (предсказание останова) ----------------
    # В этой игре ЛКМ управляет УСКОРЕНИЕМ зелёной зоны: зажал — зона разгоняется вверх,
    # отпустил — разгоняется вниз. Любой ПИД/ШИМ на таком объекте периодически «перекидывает»
    # зону выше рыбы и зажимает её там: интегратор копит ошибку, выход упирается в 100%,
    # а обратная связь запаздывает. Поэтому регулятор v1.6 — РЕЛЕ с предсказанием:
    # каждый кадр бот считает, ГДЕ зона остановится, если продолжить текущее действие, и
    # ГДЕ остановилась бы при противоположном; выбирает то действие, чья точка останова
    # ближе к ЦЕНТРУ рыбы (с гистерезисом от дребезга). «Зажать зону выше рыбы» физически
    # невозможно: как только предсказанная точка останова уходит от рыбы — ЛКМ отпускается.
    # Скважность не назначается вообще (нечему насыщаться), решения принимаются по кадрам,
    # поэтому медленный захват (20 к/с) не ломает закон управления.
    "relay_look_ms": 300,                # горизонт предсказания, мс: дальше — спокойнее, но вязче
    "relay_hyst": 12.0,                  # гистерезис решения, px: меньше — живее, больше — реже щёлкает
    "relay_a_up": 1750.0,                # разгон зоны ВВЕРХ при зажатой ЛКМ, px/с^2 (стартовая оценка;
                                         # при relay_adapt уточняется по кадрам каждой мини-игры)
    "relay_g": 800.0,                   # разгон зоны ВНИЗ при отпущенной ЛКМ, px/с^2 (аналогично)
    "relay_vmax": 850.0,                 # предел скорости зоны в предсказании, px/с (эталон 1080p)
    "relay_tau_ms": 90,                  # упреждение цели по скорости рыбы, мс (рыба рыскает — цель
                                         # ставится чуть впереди её движения)
    "relay_lead_max": 0.12,              # предел упреждения, долей высоты шкалы
    "relay_adapt": True,                 # измерять реальные разгоны зоны по кадрам и поправлять
                                         # relay_a_up/relay_g на лету (кэш на сессию)
    "vel_alpha": 0.35,                   # фильтр скорости зоны/рыбы (меньше = гладче)
    "acc_alpha": 0.18,
    "fish_thr": 34,                      # порог «неоднородности строки» для поиска рыбы (0..255)
    "fish_detect": "auto",               # auto = контраст | both = контраст + HSV | hsv = только старые HSV-диапазоны
    "slip_thr": 0.16,                    # доля красных пикселей в боковых полосах = «РЫБА СРЫВАЕТСЯ»
    "slip_frames": 2,                    # сколько кадров подряд красная рамка = подтверждение срыва
    "max_hold": 2.5,                     # защита: дольше этого держать нельзя (принудительный отпуск)
    "forced_release": 0.12,              # на сколько отпускать после срабатывания max_hold
    "lost_ms": 140,                      # потеря зелёной зоны (мс) -> выход из мини-игры (было LOST_LIMIT=35 кадров)
    "fish_timeout": 0.8,                 # рыба не видна столько секунд -> не держим
    "min_switch": 0.030,                 # мин. пауза между событиями ЛКМ, с (защита от дребезга)
}
# Ключи регуляторов v1.3-1.5 (ПИД/ШИМ/равновесие): вырезаны при переписывании мини-игры.
# Найденные в конфиге пользователя значения удаляются с записью в журнал (CFG_DROPPED).
REMOVED_CFG_KEYS = ("pid_mode", "pid_kp", "pid_ki", "pid_kd", "pid_ilim", "pid_dband",
                    "pid_bias", "pid_em_kp", "pid_em_ki", "pid_em_kd", "pid_em_bias",
                    "pwm_hz", "vel_gain", "vel_max", "stop_acc", "zone_margin", "deadzone",
                    "lead_time", "lead_max", "hover_adapt", "hover_ref", "hover_k", "hover_span",
                    "brake_ms", "bait_check_every", "use_offset", "equip_retry_delay",
                    "inv_wheel_center", "rod_click_pos", "use_click_pos", "rod_match_min",
                    "move_time", "use_menu_delay", "rod_retry_delay", "idle_cursor",
                    "cast_macro", "macro_click_window", "bind_macro")
THR = {"rod": 0.90, "rod2": 0.90, "bait": 0.90, "inv_header": 0.80,
       "hud_fish": 0.85, "hud_bait": 0.85, "hud_shield": 0.85}
REGIONS = {
    "rod": [80, 215, 500, 785], "rod2": [80, 215, 500, 785],
    "bait": [80, 215, 500, 785], "inv_header": [60, 20, 300, 110],
    "hud_fish": [0, 872, 420, 66], "hud_bait": [0, 872, 420, 66], "hud_shield": [0, 872, 420, 66],
}
TEMPLATE_NAMES = ["rod", "rod2", "bait", "inv_header", "hud_fish", "hud_bait", "hud_shield"]
TEMPLATE_LABEL_KEYS = {"rod": "tpl_rod", "rod2": "tpl_rod2", "bait": "tpl_bait", "inv_header": "tpl_inv",
                       "hud_fish": "tpl_hud_fish", "hud_bait": "tpl_hud_bait", "hud_shield": "tpl_hud_shield"}

# мини-игра (HSV — только как дополнительный/резервный детектор рыбы, CFG["fish_detect"]="hsv"/"both")
LOWER_GREEN = np.array([30, 80, 80]);   UPPER_GREEN = np.array([85, 255, 255])
LOWER_GOLD = np.array([8, 40, 90]);     UPPER_GOLD = np.array([30, 255, 255])
LOWER_CYAN = np.array([78, 80, 100]);   UPPER_CYAN = np.array([105, 255, 255])
LOWER_BLUE = np.array([92, 35, 35]);     UPPER_BLUE = np.array([140, 255, 255])
LOWER_RED = np.array([0, 60, 90]);      UPPER_RED = np.array([8, 255, 255])
LOWER_RED2 = np.array([172, 60, 90]);   UPPER_RED2 = np.array([180, 255, 255])
MIN_ZONE_AREA, MIN_FISH_AREA, MIN_FISH_HEIGHT = 150, 10, 6
MAX_VEL = 1200.0
KERNEL = np.ones((7, 7), np.uint8)
ZONE_KERNEL = np.ones((5, 5), np.uint8)
LOOP_DELAY = 0.004                        # только для резервного пути (GDI), когда нет потока
RESYNC = 0.20
MIN_SWITCH, FORCED_RELEASE = 0.030, 0.12  # легаси-константы; рабочие значения берутся из CFG

# AI-зрение (v1.24): ключи ai_* живут в том же конфиге; дефолты — в ai/config.py.
# Аддитивно: старые конфиги получают недостающие ключи, значения пользователя
# не перетираются, без ai-моделей всё работает как раньше.
# Пакет ai/ вшит в ЭТОТ файл (payload ниже): бот разворачивается как ОДИН файл
# и не требует каталог ai/ рядом. Если каталог есть — используется он (dev).
# Синхронизация payload с ai/: python scripts/embed_ai.py (проверка: --check).
# [AI-EMBED-BEGIN] (генерируется scripts/embed_ai.py — не править руками)
_AI_EMBED_B64 = (
    "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"
)
class _AiEmbLoader:
    """Загрузчик модулей ai.* из встроенного payload (одна копия кода — файл)."""

    def create_module(self, spec):
        return None                              # стандартная семантика

    def exec_module(self, module):
        src = _AI_EMBED_SRC.get(module.__name__)
        if src is None:
            raise ImportError("ai-embed: нет модуля %s" % module.__name__)
        if module.__name__ == "ai":
            module.__path__ = []                 # это пакет (подмодули отдаёт finder)
        exec(compile(src, "<ai-embedded/%s>" % module.__name__, "exec"),
             module.__dict__)


class _AiEmbFinder:
    """Meta-path finder: обслуживает ТОЛЬКО отсутствующий на диске пакет ai.
    Если рядом с ботом есть каталог ai/ — PathFinder найдёт его раньше (dev)."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "ai" or fullname.startswith("ai."):
            import importlib.util as _iu
            return _iu.spec_from_loader(fullname, _AiEmbLoader(),
                                        is_package=("." not in fullname))
        return None


import base64 as _b64e, zlib as _zle     # noqa: E402
_AI_EMBED_SRC = json.loads(_zle.decompress(
    _b64e.b64decode(_AI_EMBED_B64)).decode("utf-8"))
sys.meta_path.append(_AiEmbFinder())
# [AI-EMBED-END]
from ai.config import AI_DEFAULTS as _AI_DEFAULTS          # noqa: E402
DEFAULT_CFG.update(_AI_DEFAULTS)
# ВАЖНО: копия конфига — СТРОГО после пополнения DEFAULT_CFG ai-ключами
# (в 1.24.0/1.24.1 копия бралась раньше и CFG жил без ai_*: страница
# «AI-ЗРЕНИЕ» падала с KeyError: 'ai_mode').
CFG = dict(DEFAULT_CFG)


def load_cfg():
    """True — загружено из файла. Старые конфиги мигрируются: новые ключи получают дефолты."""
    if os.path.exists(CFG_PATH):
        try:
            with open(CFG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("config is not an object")
            known = {k: v for k, v in data.items() if k in DEFAULT_CFG}
            CFG.update(known)
            # Ключи старых регуляторов (ПИД/ШИМ/равновесие v1.3-1.5) вырезаны: удаляем их
            # из конфига пользователя и перечисляем в журнале, чтобы было видно, что менять.
            for k in REMOVED_CFG_KEYS:
                if k in data and k not in CFG_DROPPED:
                    CFG_DROPPED.append(k)
            # устаревшие ЗНАЧЕНИЯ мигрируем явно (CFG_VERSION не меняем — ключ-то на месте).
            # mss из проекта вырезан, а конфиги версий 1.2-1.3 успели записать
            # "capture_backend": "mss" при тихом откате — иначе пользователь навсегда
            # остался бы на резервном захвате, сам того не подозревая.
            if str(CFG.get("capture_backend", "")).lower().strip() in ("mss", "no", "dxgpu-dxs"):
                CFG["capture_backend"] = DEFAULT_CFG["capture_backend"]
                CFG_MIGRATED.append("capture_backend")
            # Аддитивные ключи добавляем ВСЕГДА (сверяемся с ФАЙЛОМ, не с CFG:
            # CFG уже содержит дефолты), а не только при миграции версии —
            # конфиг v1.23 (cfg_version=11) не трогался и остался без ai_*.
            missing = {k: v for k, v in DEFAULT_CFG.items() if k not in data}
            if missing:
                CFG.update(missing)
            if int(data.get("cfg_version", 1) or 1) < CFG_VERSION or missing:
                save_cfg()
            return True
        except Exception as e:
            print("Config is not readable / конфиг не прочитан:", e)
    return False


CFG_MIGRATED = []                         # что починили в load_cfg; печатается в журнал при старте
CFG_DROPPED = []                          # устаревшие ключи конфига (регулятор v1.3-1.5), удалены


def save_cfg():
    try:
        data = dict(CFG)
        data["cfg_version"] = CFG_VERSION
        data["app_version"] = APP_VERSION
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def reset_cfg():
    CFG.clear()
    CFG.update(DEFAULT_CFG)


# ==========================================================================
# 1B. ЛОКАЛИЗАЦИЯ (RU / EN / UA) — ЕДИНЫЙ СЛОВАРЬ СТРОК
# ==========================================================================
# Все строки, которые видит пользователь (GUI, журнал, тосты, пилюля-оверлей), живут здесь.
# Внутренние идентификаторы (ключи CFG, имена шаблонов, hotkey-имена, kind-состояния) НЕ переводятся.
# Ключи одинаковые во всех трёх языках; при пропуске берётся ru, потом сам ключ.
STRINGS = {
"ru": {
    "pg0_t": "Рыбалка", "pg0_s": "Полуавтомат: сам закидывает, проходит мини-игру и следит за наживкой",
    "pg1_t": "Статистика", "pg1_s": "Итоги этой сессии и за всё время",
    "pg2_t": "Зрение", "pg2_s": "Что видит бот: шкала мини-игры, шаблоны, захват",
    "pg3_t": "Модули", "pg3_s": "Поведение рыбалки, ПИД и звуки",
    "pg4_t": "Настройки", "pg4_s": "Язык, клавиши, громкость, конфиг",
    "b_start": "СТАРТ  ·  F8", "b_stop": "СТОП  ·  F8",
    "b_snapshot": "Снимок (F9)", "b_tpl_rod": "Шаблон: удочка", "b_tpl_bait": "Шаблон: наживка",
    "b_save": "Сохранить", "b_load": "Загрузить", "b_reset": "Сбросить",
    "b_change": "Изменить", "b_apply": "Задать", "b_auto": "Авто", "b_pick": "📍",
    "k_catches": "ПОЙМАНО", "k_time": "ВРЕМЯ", "k_per_hour": "РЫБ / ЧАС", "k_log": "ЖУРНАЛ",
    "s_catches_session": "Поймано за эту сессию", "s_session_time": "Время сессии",
    "s_fish_hour": "Рыб в час", "s_avg_mini": "Среднее время мини-игры", "s_bait_checks": "Проверок наживки",
    "s_all_catches": "Поймано за всё время", "s_sessions": "Сессий всего", "s_best": "Лучшая сессия",
    "s_last_stop": "Последняя остановка",
    "v_bar": "ШКАЛА МИНИ-ИГРЫ", "v_tpl": "ШАБЛОНЫ", "v_capture": "ЗАХВАТ ЭКРАНА", "v_pid": "РЕГУЛЯТОР · МИНИ-ИГРА",
    "unit_s": "с", "v_spark_lab": "ошибка, ±20% шкалы (кр.) · ЛКМ (зел.)", "v_ctl_hint": "Регулятор сам измеряет физику зоны (реле с предсказанием останова) — ручная настройка не нужна. Параметры: «Модули».", "v_tpl_hint1": "Шаблон снимается через 4 с", "v_tpl_hint2": "открой инвентарь и наведи курсор на иконку",
    "v_zone": "зона", "v_fish": "рыба", "v_slip": "срыв", "v_err": "ошибка", "v_press": "ЛКМ",
    "v_press_on": "ДЕРЖИТ", "v_press_off": "пусто", "v_zv": "зона", "v_fv": "рыба", "v_brk": "выбег",
    "v_mode": "режим", "v_mode_norm": "норма", "v_mode_emerg": "АВАРИЯ", "v_lost": "потеря", "v_ms": "кадр/мс",
    "v_none": "—", "v_no_file": "нет файла", "v_fps": "FPS", "v_latency": "задержка",
    "v_fallback": "⚠ Резервный захват GDI — чуть медленнее DXGI (DXGI не поднялся)",
    "v_primary": "основной захват DXGI", "v_stream_off": "поток выключен", "v_stream_on": "поток {fps} fps",
    "tpl_rod": "Удочка (инвентарь)", "tpl_rod2": "Удочка №2 (второй эталон)", "tpl_bait": "Наживка (инвентарь)", "tpl_inv": "Окно инвентаря",
    "tpl_hud_fish": "Значок удочки (HUD)", "tpl_hud_bait": "Значок наживки (HUD)", "tpl_hud_shield": "HUD виден",
    "m_card_fish": "РЫБАЛКА И ЗВУКИ", "m_card_pid": "РЕГУЛЯТОР И РАСПОЗНАВАНИЕ",
    "m_equip": "Брать удочку при старте", "m_autocast": "Авто-закидывание удочки",
    "m_castafter": "Закидывать после каждой рыбы",
    "m_biteto": "Ждать поклёвку, сек", "m_postdelay": "Пауза после рыбы, сек",
    "m_hide": "Прятать окно, пока бот ловит", "m_snd_start": "Звук: рыбалка началась",
    "m_snd_end": "Звук: рыбалка закончилась", "m_snd_catch": "Звук: каждая рыба",
    "m_maxhold": "Макс. удержание, с",
    "m_lostms": "Потеря зоны, мс", "m_fishthr": "Порог контраста рыбы", "m_fishdet": "Поиск рыбы",
    "m_barpad": "Отступ рамки, px", "m_slipthr": "Порог красной рамки",
    "s_sec_lang": "ЯЗЫК / LANGUAGE / МОВА", "s_sec_binds": "Горячие клавиши", "s_lang": "Язык интерфейса", "s_bind_toggle": "Старт / Стоп", "s_bind_panic": "Аварийный стоп",
    "s_bind_gui": "Показать / скрыть окно", "s_volume": "Громкость звуков, %", "s_cast_delay": "Задержка заброса, сек",
    "s_game_none": "Окно игры определяется при старте (F8 в игре)", "s_game": "Окно игры: «{title}»",
    "s_version": "Версия {v} · захват: {b}", "s_capture_backend": "Захват при старте",
    "toast_cfg_saved": "Конфиг сохранён успешно", "toast_cfg_save_fail": "Не удалось сохранить конфиг",
    "toast_cfg_loaded": "Конфиг загружен успешно", "toast_cfg_missing": "Файл конфига не найден",
    "toast_cfg_reset": "Настройки сброшены", "toast_lang": "Язык: {lang}",
    "s_sec_equip": "ЭКИПИРОВКА УДОЧКИ (v1.21 — зрение, запись макро удалена)",
    "s_equip_hint": "Бот сам найдёт удочку в открытом инвентаре и кликнет «Использовать»",
    "b_equip": "▷ Экипировать",
    "nt_equip_need_inv": "Открой инвентарь в игре — бот сам возьмёт удочку",
    "m_clickwin": "Клики прямо в окно интерфейса игры (курсор не двигается)",
    "log_equip_rod": "🎣 Удочка найдена: ({x}, {y}), точность {s:.2f} — ПКМ",
    "log_equip_rod_nofind": "❌ Удочка не найдена в инвентаре (шаблон rod.png) — открой инвентарь",
    "log_equip_win": "🖱 Клики — прямо в окно интерфейса игры, курсор Windows не двигается",
    "log_drive_step": "Контур: игровой курсор ({x}, {y})",
    "log_drive_fail": "Контур не подтвердил курсор на цели — кликаю как есть",
    "log_equip_cur": "🖱 Окно интерфейса не найдено — кликаю курсором",
    "log_use_nofind": "❌ Меню предмета не открылось (красная строка не найдена)",
    "log_equip_miss": "Кадр момента промаха сохранён: miss_rod.png — пришли его, если промах повторится",
    "reason_no_macro": "удочка не найдена в инвентаре",
    "log_rod_skip": "🎣 equip_on_start выключен — начинаю с заброса (удочка уже в руках)",
    "st_stopped": "ОСТАНОВЛЕНО", "st_idle_d": "Нажми СТАРТ или F8",
    "st_starting": "ЗАПУСК", "st_starting_d": "Определяю окно игры…",
    "st_prepare": "ПОДГОТОВКА", "st_prepare_d": "Проверяю удочку и наживку",
    "st_cast": "ЗАКИДЫВАЮ", "st_cast_d": "Закидываю удочку…",
    "st_bite": "КЛЁВ", "st_bite_d": "Ожидание клёва…", "st_bite_wait_d": "Ожидание клёва… {n} с",
    "st_mini": "МИНИ-ИГРА", "st_mini_d": "Вылавливаю рыбу!", "st_mini_hold_d": "Удерживаю рыбу в зоне",
    "st_caught": "ЛОВЛЯ", "st_caught_d": "Рыба поймана",
    "st_check": "ПРОВЕРКА", "st_check_d": "Проверяю наживку", "st_check_nobite_d": "Нет поклёвки — проверяю наживку",
    "st_await": "ОЖИДАНИЕ", "st_await_d": "Жду мини-игру рыбалки…",
    "st_slip": "СРЫВ!", "st_slip_d": "Рыба уходит — аварийный режим",
    "log_game_window": "🎮 Окно игры: «{title}»", "log_pause": "⏸ Окно игры не активно — пауза (вернись в игру)",
    "log_resume": "▶ Окно игры снова активно", "log_start": "▶ Рыбалка началась",
    "log_stop": "■ Рыбалка закончилась — {reason}. Поймано: {n}", "log_mini": "🎣 Мини-игра",
    "log_caught": "🐟 Поймано #{n} (мини-игра {dur:.1f} с)", "log_no_bite": "⌛ Нет поклёвки {t} с ({k}/{lim})",
    "m_det_auto": "авто (контраст)", "m_det_both": "контраст+HSV", "m_det_hsv": "только HSV", "log_use_found": "🖱 «Использовать» найдено по красной строке меню: ({ux}, {uy}), одна ЛКМ",
    "log_self_learn": "🧠 Шаблон {name}.png обновлён с экрана (совпадение {s:.2f}) — поиск станет точнее",
    "log_bait_notpl": "Нет шаблона bait.png — наживка не проверяется («Зрение» → «Шаблон: наживка»)",
    "log_bait": "🪱 Наживка: {state} (стаков на экране: {n})",
    "bait_yes": "есть", "bait_no": "НЕТ", "log_rod_missing": "🎣 Удочки нет в руках — беру",
    "log_bait_icon": "🪱 Значок наживки пропал — проверяю инвентарь",
    "log_mode_mini_only": "🎣 Режим: только мини-игра — инвентарь и забросы полностью отключены",
    "log_inv_wait": "📂 Жду, пока откроешь инвентарь (сам я его не открываю)",
    "nt_inv_wait": "Открой инвентарь в игре",
    "log_bait_skip": "Проверка наживки пропущена — инвентарь закрыт",
    "st_inv_wait": "ОТКРОЙ ИНВЕНТАРЬ", "st_inv_wait_d": "Открой инвентарь — бот ждёт…",
    "m_selflearn": "Обновлять шаблоны с экрана",
    "log_cast": "🪝 Заброс удочки…", "log_cast_done": "🪝 Заброс выполнен — жду клёва",
    "log_slip": "⚠ Рыба срывается — аварийное удержание", "log_mini_done": "✔ Мини-игра: {dur:.1f} с, срывов {slip}, ЛКМ {sw:.1f} перекл/с",
    "log_debug": "📷 debug_screen.png, debug_bar.png сохранены. {parts} | zone={zone} fish={fish}",
    "log_debug_fail": "❌ debug: {e}", "log_tpl_none": "нет файла",
    "log_capture": "🖥 Захват: {backend} ({detail})", "log_capture_fallback": "⚠️ DXGI-захват недоступен ({err}) — работаю через GDI (резерв без зависимостей)",
    "log_capture_skipped": "🖥 {reason}",
    "log_cfg_migrate": "⚙ Конфиг: значение \"{key}\": \"mss\" устарело (mss вырезан) — включено {to}.",
    "log_cfg_drop": "⚙ Конфиг: ключ \"{key}\" устарел — значение удалено из конфига.",
    "hint_capture": "Что сделать: python -m pip install -U dxcam bettercam (и перезапусти). Если экран игры защищён от захвата или это RDP/виртуалка — бот сам возьмёт GDI-резерв; чтобы работать строго по DXGI, поставь в fishmod_config.json \"capture_backend\": \"dxcam\"",
    "log_stream": "🖥 Поток мини-игры: {backend}, {fps} fps, регион {rect}",
    "log_stream_stop": "🖥 Поток мини-игры остановлен",
    "log_stream_fail": "❌ Поток не запустился: {err}", "log_capture_error": "⚠ Захват: ошибка {err}",
    "log_fallback_now": "⚠ Весь захват перешёл на GDI (резервный режим)",
    "log_bar_fit": "📐 Шкала уехала: калибровка обновлена {old} -> {new} (совпадение {cov}), причина: {why}",
    "log_bar_fit_off": "📐 Шкала уехала, но bar_autofit выключен — проверь CFG[\"bar\"] вручную",
    "nt_bar_fit": "Пересчитана область шкалы — проверь страницу «Зрение»",
    "m_hyst": "Гистерезис решения, px", "m_look": "Горизонт предсказания, мс",
    "m_aup": "Разгон зоны вверх, px/с²", "m_g": "Падение зоны, px/с²",
    "m_vmax": "Предел скорости зоны, px/с",
    "m_barfit": "Самокалибровка шкалы", "m_barref": "Измерять по реальной шкале",
    "v_scale_lab": "шкала", "v_bar_edge": "шкала обрезана краем кадра",
    "log_adapt": "⚖ Физика зоны измерена: разгон вверх {up:.0f} px/с², падение {dn:.0f} px/с² (замеров {n})",
    "m_adapt": "Измерять физику зоны",
    "log_ready": "{app}: готов. {toggle} — старт/стоп, {panic} — аварийный стоп",
    "pg5_t": "AI-ЗРЕНИЕ", "pg5_s": "Локальный анализ кадра: наблюдение и события, офлайн",
    "ai_sec_status": "Состояние конвейера", "ai_sec_mode": "Режим поиска удочки (экипировка)",
    "ai_state": "Конвейер", "ai_state_screen": "Экран", "ai_model": "Модель", "ai_lat": "инференс",
    "ai_frames": "Кадров", "ai_dropped": "Пропущено", "ai_events": "Событий", "ai_errs": "Ошибок",
    "ai_diag_ev": "Событий в диагностике", "ai_diag_sn": "Снимков",
    "ai_warn_nomodel": "⚠ Модель не установлена — работаю легаси-зрением (это нормально)",
    "b_ai_report": "Журнал AI", "b_ai_restart": "Перезапустить AI",
    "ai_hint_local": "Всё локально: CPU, офлайн; модели никогда не скачиваются сами",
    "ai_hint_noclick": "AI только наблюдает и пишет события — клики делает прежняя логика",
    "ai_hint_models": "Модели: ai/models/manifest.json — как обучить/подключить: docs/AI_VISION.md",
    "ai_lbl_mode": "Стратегия", "ai_lbl_enabled": "AI-наблюдение",
    "ai_lbl_change": "Детектор изменений", "ai_lbl_ocr": "OCR интерфейса",
    "ai_lbl_snap": "Снимки неизвестного", "ai_lbl_fps": "Полный анализ, к/с",
    "ai_lbl_ocrfps": "OCR, к/с", "ai_lbl_conf": "Порог уверенности",
    "ai_lbl_confirm": "Подтверждений состояния", "ai_lbl_threads": "Потоки ONNX (0=авто)",
    "ai_mode_legacy": "Легаси (шаблоны)", "ai_mode_ai": "AI (ONNX)", "ai_mode_hybrid": "Гибрид",
    "ai_st_off": "выключен", "ai_st_startup": "стартует", "ai_st_running": "работает",
    "ai_st_degraded": "деградировал (без модели)", "ai_st_stopped": "остановлен",
    "log_ai_on": "🤖 AI-наблюдение включено (режим удочки: {mode})",
    "log_ai_off": "🤖 AI-наблюдение выключено",
    "log_ai_ev": "🤖 AI: {typ} (уверенность {conf:.2f})",
    "log_ai_fail": "🤖 AI-конвейер не запустился: {e} — рыбалка продолжается без AI",
    "log_ai_nomodel": "🤖 AI-модель недоступна ({st}) — ищу удочку шаблонами",
    "log_ai_rod": "🤖 AI: удочка ({x}, {y}), уверенность {s:.2f}",
    "log_ai_report": "🤖 Журнал AI (последние события):",
    "log_ai_diag": "🤖 Диагностика: событий {ev}, снимков {sn}, отключено: {dis}",
    "log_ai_off_short": "🤖 Конвейер выключен (включите на странице «AI-ЗРЕНИЕ»)",
    "log_equip_retry": "Меню не открылось — повторяю экипировку ({n}/2)",
    "ai_rec_sec": "Запись сессий (ИИ учится на твоих действиях)",
    "b_rec_start": "⏺ Записать сессию", "b_rec_stop": "⏹ Остановить запись",
    "b_rec_export": "Собрать датасет", "ai_rec_idle": "Запись не ведётся",
    "ai_rec_status": "Идёт запись: кадров {f}, кликов {c}, {mb} МБ, курсор seen {g}",
    "ai_rec_hint": "Играй руками — бот пишет кадры и твои клики (это будущие метки).\nПотом «Собрать датасет» → обучи модель (docs/LEARNING.md)",
    "log_rec_on": "⏺ Запись сессии начата ({fps} к/с, предел {mb} МБ) — играй как обычно",
    "log_rec_off": "⏹ Запись остановлена: кадров {f}, кликов {c}, {mb} МБ",
    "log_rec_fail": "⏺ Запись не начата: {e}",
    "log_ds_nosession": "Сессий нет — сначала запиши свою игру («Записать сессию»)",
    "log_ds_ok": "📊 Датасет собран: кадров {f}, кликов-меток {c}, объектов {o}, фон {b} → {path}",
    "log_ds_fail": "📊 Датасет не собран: {e}",
    "fail_capture": "ни один бэкенд захвата не запустился", "fail_templates": "нет шаблонов в папке templates: {files}", "fail_window": "не удалось определить окно игры: переключись в игру и нажми F8",
    "nt_started": "Рыбалка началась", "nt_finished": "Рыбалка закончилась: {text}", "nt_pause": "Пауза: вернись в игру",
    "nt_snapshot": "Снимок сохранён (debug_screen.png)", "nt_tpl_saved": "Шаблон «{name}» сохранён",
    "nt_tpl_countdown": "Шаблон «{name}»: наведи курсор… {i}",
    "reason_user": "остановлено вручную", "reason_no_bait": "наживка закончилась",
    "reason_no_bite": "нет поклёвок (проверь вес/место)", "reason_error": "ошибка",
    "pill_fmt": "{state}  ·  поймано {n}  ·  {time}",
},
"en": {
    "pg0_t": "Fishing", "pg0_s": "Semi-auto: casts, plays the minigame and watches your bait",
    "pg1_t": "Statistics", "pg1_s": "This session and all-time totals",
    "pg2_t": "Vision", "pg2_s": "What the bot sees: minigame bar, templates, capture",
    "pg3_t": "Modules", "pg3_s": "Fishing behaviour, PID controller and sounds",
    "pg4_t": "Settings", "pg4_s": "Language, hotkeys, volume, config",
    "b_start": "START  ·  F8", "b_stop": "STOP  ·  F8",
    "b_snapshot": "Snapshot (F9)", "b_tpl_rod": "Template: rod", "b_tpl_bait": "Template: bait",
    "b_save": "Save", "b_load": "Load", "b_reset": "Reset",
    "b_change": "Change", "b_apply": "Set", "b_auto": "Auto", "b_pick": "📍",
    "k_catches": "CAUGHT", "k_time": "TIME", "k_per_hour": "FISH / HOUR", "k_log": "LOG",
    "s_catches_session": "Caught this session", "s_session_time": "Session time",
    "s_fish_hour": "Fish per hour", "s_avg_mini": "Average minigame time", "s_bait_checks": "Bait checks",
    "s_all_catches": "Caught all time", "s_sessions": "Total sessions", "s_best": "Best session",
    "s_last_stop": "Last stop",
    "v_bar": "MINIGAME BAR", "v_tpl": "TEMPLATES", "v_capture": "SCREEN CAPTURE", "v_pid": "CONTROLLER · MINIGAME",
    "unit_s": "s", "v_spark_lab": "error, ±20% of bar (red) · LMB (green)", "v_ctl_hint": "The controller measures the zone physics itself (stop-point relay) — no manual tuning needed. Parameters: Modules page.", "v_tpl_hint1": "Template is grabbed after 4 s.", "v_tpl_hint2": "Open the inventory and hover the icon",
    "v_zone": "zone", "v_fish": "fish", "v_slip": "slip", "v_err": "error", "v_press": "LMB",
    "v_press_on": "HOLDING", "v_press_off": "idle", "v_zv": "zone", "v_fv": "fish", "v_brk": "glide",
    "v_mode": "mode", "v_mode_norm": "normal", "v_mode_emerg": "EMERGENCY", "v_lost": "lost", "v_ms": "frame/ms",
    "v_none": "—", "v_no_file": "no file", "v_fps": "FPS", "v_latency": "latency",
    "v_fallback": "⚠ GDI fallback capture — a bit slower than DXGI (DXGI did not start)",
    "v_primary": "primary DXGI capture", "v_stream_off": "stream off", "v_stream_on": "stream {fps} fps",
    "tpl_rod": "Rod (inventory)", "tpl_rod2": "Rod #2 (second reference)", "tpl_bait": "Bait (inventory)", "tpl_inv": "Inventory window",
    "tpl_hud_fish": "Rod icon (HUD)", "tpl_hud_bait": "Bait icon (HUD)", "tpl_hud_shield": "HUD visible",
    "m_card_fish": "FISHING AND SOUNDS", "m_card_pid": "CONTROLLER AND DETECTION",
    "m_equip": "Take the rod on start", "m_autocast": "Auto-cast the rod",
    "m_castafter": "Cast after every fish",
    "m_biteto": "Wait for a bite, s", "m_postdelay": "Delay after a fish, s",
    "m_hide": "Hide window while fishing", "m_snd_start": "Sound: session started",
    "m_snd_end": "Sound: session finished", "m_snd_catch": "Sound: every fish",
    "m_maxhold": "Max hold, s",
    "m_lostms": "Zone lost, ms", "m_fishthr": "Fish contrast threshold", "m_fishdet": "Fish detection",
    "m_barpad": "Bar border pad, px", "m_slipthr": "Red frame threshold",
    "s_sec_lang": "ЯЗЫК / LANGUAGE / МОВА", "s_sec_binds": "Hotkeys", "s_lang": "Interface language", "s_bind_toggle": "Start / Stop", "s_bind_panic": "Panic stop",
    "s_bind_gui": "Show / hide window", "s_volume": "Sound volume, %", "s_cast_delay": "Cast delay, s",
    "s_game_none": "Game window is detected on start (press F8 inside the game)", "s_game": "Game window: “{title}”",
    "s_version": "Version {v} · capture: {b}", "s_capture_backend": "Capture on start",
    "toast_cfg_saved": "Config saved successfully", "toast_cfg_save_fail": "Failed to save config",
    "toast_cfg_loaded": "Config loaded successfully", "toast_cfg_missing": "Config file not found",
    "toast_cfg_reset": "Settings reset", "toast_lang": "Language: {lang}",
    "s_sec_equip": "ROD EQUIP (v1.21 — vision, macro recording removed)",
    "s_equip_hint": "The bot finds the rod in your open inventory and clicks “Use” itself",
    "b_equip": "▷ Equip",
    "nt_equip_need_inv": "Open the in-game inventory — the bot will take the rod itself",
    "m_clickwin": "Click straight into the game UI window (cursor stays put)",
    "log_equip_rod": "🎣 Rod found: ({x}, {y}), score {s:.2f} — RMB",
    "log_equip_rod_nofind": "❌ Rod not found in the inventory (rod.png template) — open the inventory",
    "log_equip_win": "🖱 Clicks go straight into the game UI window; the Windows cursor never moves",
    "log_drive_step": "Servo: game cursor at ({x}, {y})",
    "log_drive_fail": "Servo did not confirm the cursor on target — clicking anyway",
    "log_equip_cur": "🖱 UI window not found — clicking via cursor",
    "log_use_nofind": "❌ Item menu did not open (red row not found)",
    "log_equip_miss": "Frame of the miss saved: miss_rod.png — send it if the miss repeats",
    "reason_no_macro": "rod not found in the inventory",
    "log_rod_skip": "🎣 equip_on_start is off — starting with the cast (rod already in hands)",
    "st_stopped": "STOPPED", "st_idle_d": "Press START or F8",
    "st_starting": "STARTING", "st_starting_d": "Detecting the game window…",
    "st_prepare": "PREPARING", "st_prepare_d": "Checking rod and bait",
    "st_cast": "CASTING", "st_cast_d": "Casting the rod…",
    "st_bite": "WAITING", "st_bite_d": "Waiting for a bite…", "st_bite_wait_d": "Waiting for a bite… {n} s",
    "st_mini": "MINIGAME", "st_mini_d": "Reeling the fish in!", "st_mini_hold_d": "Holding the fish in the zone",
    "st_caught": "FISHING", "st_caught_d": "Fish caught",
    "st_check": "CHECKING", "st_check_d": "Checking the bait", "st_check_nobite_d": "No bite — checking the bait",
    "st_await": "IDLE", "st_await_d": "Waiting for the fishing minigame…",
    "st_slip": "SLIPPING!", "st_slip_d": "Fish is escaping — emergency mode",
    "log_game_window": "🎮 Game window: “{title}”", "log_pause": "⏸ Game window is not active — paused (go back to the game)",
    "log_resume": "▶ Game window is active again", "log_start": "▶ Fishing started",
    "log_stop": "■ Fishing finished — {reason}. Caught: {n}", "log_mini": "🎣 Minigame",
    "log_caught": "🐟 Caught #{n} (minigame {dur:.1f} s)", "log_no_bite": "⌛ No bite for {t} s ({k}/{lim})",
    "m_det_auto": "auto (contrast)", "m_det_both": "contrast+HSV", "m_det_hsv": "HSV only", "log_use_found": "🖱 “Use” found via the red row: ({ux}, {uy}), one LMB",
    "log_self_learn": "🧠 Template {name}.png updated from screen (match {s:.2f}) — detection gets sharper",
    "log_bait_notpl": "No bait.png template — bait not checked (Vision → “Bait template”)",
    "log_bait": "🪱 Bait: {state} (stacks on screen: {n})",
    "bait_yes": "yes", "bait_no": "NONE", "log_rod_missing": "🎣 Rod not in hands — taking it",
    "log_bait_icon": "🪱 Bait icon disappeared — checking the inventory",
    "log_mode_mini_only": "🎣 Mode: minigame only — inventory and casting are fully disabled",
    "log_inv_wait": "📂 Waiting for you to open the inventory (I never open it myself)",
    "nt_inv_wait": "Open the inventory in game",
    "log_bait_skip": "Bait check skipped — inventory is closed",
    "st_inv_wait": "OPEN INVENTORY", "st_inv_wait_d": "Open the inventory — the bot is waiting…",
    "m_selflearn": "Auto-refresh templates from screen",
    "log_cast": "🪝 Casting…", "log_cast_done": "🪝 Cast done — waiting for a bite",
    "log_slip": "⚠ Fish is slipping — emergency hold", "log_mini_done": "✔ Minigame: {dur:.1f} s, slips {slip}, LMB {sw:.1f} switches/s",
    "log_debug": "📷 debug_screen.png, debug_bar.png saved. {parts} | zone={zone} fish={fish}",
    "log_debug_fail": "❌ debug: {e}", "log_tpl_none": "no file",
    "log_capture": "🖥 Capture: {backend} ({detail})", "log_capture_fallback": "⚠️ DXGI capture unavailable ({err}) — using GDI (fallback, no extra deps)",
    "log_capture_skipped": "🖥 {reason}",
    "log_cfg_migrate": "⚙ Config: value \"{key}\": \"mss\" is obsolete (mss removed) — switched to {to}.",
    "log_cfg_drop": "⚙ Config: key \"{key}\" is obsolete — the minigame controller was rewritten (v1.6), value removed.",
    "hint_capture": "What to do: python -m pip install -U dxcam bettercam (then restart). If the game window is capture-protected or you are on RDP/VM, the bot takes the GDI fallback on its own; to force DXGI only, set \"capture_backend\": \"dxcam\" in fishmod_config.json",
    "log_stream": "🖥 Minigame stream: {backend}, {fps} fps, region {rect}",
    "log_stream_stop": "🖥 Minigame stream stopped",
    "log_stream_fail": "❌ Stream failed to start: {err}", "log_capture_error": "⚠ Capture error: {err}",
    "log_fallback_now": "⚠ All capture switched to GDI (fallback mode)",
    "log_bar_fit": "📐 The scale moved: calibration updated {old} -> {new} (match {cov}), reason: {why}",
    "log_bar_fit_off": "📐 The scale moved but bar_autofit is off — fix CFG[\"bar\"] manually",
    "nt_bar_fit": "Scale area recalculated — check the Vision page",
    "m_hyst": "Decision hysteresis, px", "m_look": "Prediction horizon, ms",
    "m_aup": "Zone lift accel, px/s²", "m_g": "Zone fall accel, px/s²",
    "m_vmax": "Zone speed limit, px/s",
    "m_barfit": "Scale auto-calibration", "m_barref": "Measure the real scale",
    "v_scale_lab": "scale", "v_bar_edge": "scale is cut by the frame edge",
    "log_adapt": "⚖ Zone physics measured: lift {up:.0f} px/s², fall {dn:.0f} px/s² ({n} samples)",
    "m_adapt": "Measure zone physics",
    "log_ready": "{app}: ready. {toggle} — start/stop, {panic} — panic stop",
    "pg5_t": "AI VISION", "pg5_s": "Local frame analysis: observation and events, offline",
    "ai_sec_status": "Pipeline status", "ai_sec_mode": "Rod search mode (equipping)",
    "ai_state": "Pipeline", "ai_state_screen": "Screen", "ai_model": "Model", "ai_lat": "inference",
    "ai_frames": "Frames", "ai_dropped": "Dropped", "ai_events": "Events", "ai_errs": "Errors",
    "ai_diag_ev": "Diagnostic events", "ai_diag_sn": "Snapshots",
    "ai_warn_nomodel": "⚠ No model installed — using legacy vision (this is fine)",
    "b_ai_report": "AI log", "b_ai_restart": "Restart AI",
    "ai_hint_local": "Fully local: CPU, offline; models are never downloaded by themselves",
    "ai_hint_noclick": "AI only observes and reports events — clicks are made by the legacy logic",
    "ai_hint_models": "Models: ai/models/manifest.json — see docs/AI_VISION.md",
    "ai_lbl_mode": "Strategy", "ai_lbl_enabled": "AI observation",
    "ai_lbl_change": "Change detector", "ai_lbl_ocr": "Interface OCR",
    "ai_lbl_snap": "Unknown snapshots", "ai_lbl_fps": "Full analysis, fps",
    "ai_lbl_ocrfps": "OCR, fps", "ai_lbl_conf": "Confidence threshold",
    "ai_lbl_confirm": "State confirmations", "ai_lbl_threads": "ONNX threads (0=auto)",
    "ai_mode_legacy": "Legacy (templates)", "ai_mode_ai": "AI (ONNX)", "ai_mode_hybrid": "Hybrid",
    "ai_st_off": "off", "ai_st_startup": "starting", "ai_st_running": "running",
    "ai_st_degraded": "degraded (no model)", "ai_st_stopped": "stopped",
    "log_ai_on": "🤖 AI observation on (rod mode: {mode})",
    "log_ai_off": "🤖 AI observation off",
    "log_ai_ev": "🤖 AI: {typ} (confidence {conf:.2f})",
    "log_ai_fail": "🤖 AI pipeline failed to start: {e} — fishing continues without AI",
    "log_ai_nomodel": "🤖 AI model unavailable ({st}) — searching for the rod with templates",
    "log_ai_rod": "🤖 AI: rod at ({x}, {y}), confidence {s:.2f}",
    "log_ai_report": "🤖 AI log (recent events):",
    "log_ai_diag": "🤖 Diagnostics: events {ev}, snapshots {sn}, disabled: {dis}",
    "log_ai_off_short": "🤖 Pipeline is off (enable it on the AI VISION page)",
    "log_equip_retry": "Menu did not open — retrying equip ({n}/2)",
    "ai_rec_sec": "Session recording (AI learns from your actions)",
    "b_rec_start": "⏺ Record session", "b_rec_stop": "⏹ Stop recording",
    "b_rec_export": "Build dataset", "ai_rec_idle": "Not recording",
    "ai_rec_status": "Recording: frames {f}, clicks {c}, {mb} MB, cursor seen {g}",
    "ai_rec_hint": "Play manually — the bot records frames and your clicks (future labels).\nThen “Build dataset” → train a model (docs/LEARNING.md)",
    "log_rec_on": "⏺ Session recording started ({fps} fps, {mb} MB limit) — play as usual",
    "log_rec_off": "⏹ Recording stopped: frames {f}, clicks {c}, {mb} MB",
    "log_rec_fail": "⏺ Could not start recording: {e}",
    "log_ds_nosession": "No sessions yet — record your game first (“Record session”)",
    "log_ds_ok": "📊 Dataset built: frames {f}, click-labels {c}, objects {o}, background {b} → {path}",
    "log_ds_fail": "📊 Dataset not built: {e}",
    "fail_capture": "no capture backend could be started", "fail_templates": "no templates in the templates folder: {files}", "fail_window": "cannot detect the game window: focus the game and press F8",
    "nt_started": "Fishing started", "nt_finished": "Fishing finished: {text}", "nt_pause": "Paused: go back to the game",
    "nt_snapshot": "Snapshot saved (debug_screen.png)", "nt_tpl_saved": "Template “{name}” saved",
    "nt_tpl_countdown": "Template “{name}”: hover the cursor… {i}",
    "reason_user": "stopped manually", "reason_no_bait": "out of bait",
    "reason_no_bite": "no bites (check weight/spot)", "reason_error": "error",
    "pill_fmt": "{state}  ·  caught {n}  ·  {time}",
},
"ua": {
    "pg0_t": "Рибалка", "pg0_s": "Напівтомат: сам закидає, проходить міні-гру та стежить за наживкою",
    "pg1_t": "Статистика", "pg1_s": "Підсумки цієї сесії та за весь час",
    "pg2_t": "Зір", "pg2_s": "Що бачить бот: шкала міні-гри, шаблони, захват",
    "pg3_t": "Модулі", "pg3_s": "Поведінка риболовлі, ПІД та звуки",
    "pg4_t": "Налаштування", "pg4_s": "Мова, клавіші, гучність, конфіг",
    "b_start": "СТАРТ  ·  F8", "b_stop": "СТОП  ·  F8",
    "b_snapshot": "Знімок (F9)", "b_tpl_rod": "Шаблон: вудка", "b_tpl_bait": "Шаблон: наживка",
    "b_save": "Зберегти", "b_load": "Завантажити", "b_reset": "Скинути",
    "b_change": "Змінити", "b_apply": "Задати", "b_auto": "Авто", "b_pick": "📍",
    "k_catches": "СПІЙМАНО", "k_time": "ЧАС", "k_per_hour": "РИБ / ГОД", "k_log": "ЖУРНАЛ",
    "s_catches_session": "Спіймано за цю сесію", "s_session_time": "Час сесії",
    "s_fish_hour": "Риб на годину", "s_avg_mini": "Середній час міні-гри", "s_bait_checks": "Перевірок наживки",
    "s_all_catches": "Спіймано за весь час", "s_sessions": "Сесій усього", "s_best": "Найкраща сесія",
    "s_last_stop": "Остання зупинка",
    "v_bar": "ШКАЛА МІНІ-ГРИ", "v_tpl": "ШАБЛОНИ", "v_capture": "ЗАХВАТ ЕКРАНА", "v_pid": "РЕГУЛЯТОР · МІНІ-ГРА",
    "unit_s": "с", "v_spark_lab": "помилка, ±20% шкали (черв.) · ЛКМ (зел.)", "v_ctl_hint": "Регулятор сам міряє фізику зони (реле з передбаченням зупинки) — ручне налаштування не потрібне. Параметри: «Модулі».", "v_tpl_hint1": "Шаблон знімається через 4 с", "v_tpl_hint2": "відкрий інвентар і наведи курсор на іконку",
    "v_zone": "зона", "v_fish": "риба", "v_slip": "зрив", "v_err": "помилка", "v_press": "ЛКМ",
    "v_press_on": "ТРИМАЄ", "v_press_off": "пусто", "v_zv": "зона", "v_fv": "риба", "v_brk": "вибіг",
    "v_mode": "режим", "v_mode_norm": "норма", "v_mode_emerg": "АВАРІЯ", "v_lost": "втрата", "v_ms": "кадр/мс",
    "v_none": "—", "v_no_file": "немає файла", "v_fps": "FPS", "v_latency": "затримка",
    "v_fallback": "⚠ Резервне захоплення GDI — трішки повільніше за DXGI (DXGI не стартував)",
    "v_primary": "основний захват DXGI", "v_stream_off": "потік вимкнено", "v_stream_on": "потік {fps} fps",
    "tpl_rod": "Вудка (інвентар)", "tpl_rod2": "Вудка №2 (другий еталон)", "tpl_bait": "Наживка (інвентар)", "tpl_inv": "Вікно інвентарю",
    "tpl_hud_fish": "Значок вудки (HUD)", "tpl_hud_bait": "Значок наживки (HUD)", "tpl_hud_shield": "HUD видно",
    "m_card_fish": "РИБОЛОВЛЯ ТА ЗВУКИ", "m_card_pid": "ПІД ТА РОЗПІЗНАВАННЯ",
    "m_equip": "Брати вудку на старті", "m_autocast": "Авто-закидання вудки",
    "m_castafter": "Закидати після кожної риби",
    "m_biteto": "Чекати клювання, с", "m_postdelay": "Пауза після риби, с",
    "m_hide": "Ховати вікно, поки бот ловить", "m_snd_start": "Звук: сесію почато",
    "m_snd_end": "Звук: сесію завершено", "m_snd_catch": "Звук: кожна риба",
    "m_maxhold": "Макс. утримання, с",
    "m_lostms": "Втрата зони, мс", "m_fishthr": "Поріг контрасту риби", "m_fishdet": "Пошук риби",
    "m_barpad": "Відступ рамки, px", "m_slipthr": "Поріг червоної рамки",
    "s_sec_lang": "ЯЗЫК / LANGUAGE / МОВА", "s_sec_binds": "Гарячі клавіші", "s_lang": "Мова інтерфейсу", "s_bind_toggle": "Старт / Стоп", "s_bind_panic": "Аварійний стоп",
    "s_bind_gui": "Показати / сховати вікно", "s_volume": "Гучність звуків, %", "s_cast_delay": "Затримка закидання, с",
    "s_game_none": "Вікно гри визначається на старті (F8 у грі)", "s_game": "Вікно гри: «{title}»",
    "s_version": "Версія {v} · захват: {b}", "s_capture_backend": "Захват на старті",
    "toast_cfg_saved": "Конфіг збережено успішно", "toast_cfg_save_fail": "Не вдалося зберегти конфіг",
    "toast_cfg_loaded": "Конфіг завантажено успішно", "toast_cfg_missing": "Файл конфігу не знайдено",
    "toast_cfg_reset": "Налаштування скинуто", "toast_lang": "Мова: {lang}",
    "s_sec_equip": "ЕКІПІРУВАННЯ ВУДКИ (v1.21 — зір, запис макро видалено)",
    "s_equip_hint": "Бот сам знайде вудку у відкритому інвентарі і клікне «Використати»",
    "b_equip": "▷ Екіпірувати",
    "nt_equip_need_inv": "Відкрий інвентар у грі — бот сам візьме вудку",
    "m_clickwin": "Кліки прямо у вікно інтерфейсу гри (курсор не рухається)",
    "log_equip_rod": "🎣 Вудку знайдено: ({x}, {y}), точність {s:.2f} — ПКМ",
    "log_equip_rod_nofind": "❌ Вудку не знайдено в інвентарі (шаблон rod.png) — відкрий інвентар",
    "log_equip_win": "🖱 Кліки — прямо у вікно інтерфейсу гри, курсор Windows не рухається",
    "log_drive_step": "Контур: ігровий курсор ({x}, {y})",
    "log_drive_fail": "Контур не підтвердив курсор на цілі — клікаю як є",
    "log_equip_cur": "🖱 Вікно інтерфейсу не знайдено — клікаю курсором",
    "log_use_nofind": "❌ Меню предмета не відкрилося (червоний рядок не знайдено)",
    "log_equip_miss": "Кадр моменту промаху збережено: miss_rod.png — надішли його, якщо промах повториться",
    "reason_no_macro": "вудку не знайдено в інвентарі",
    "log_rod_skip": "🎣 equip_on_start вимкнено — починаю з закидання (вудку вже в руках)",
    "st_stopped": "ЗУПИНЕНО", "st_idle_d": "Натисни СТАРТ або F8",
    "st_starting": "ЗАПУСК", "st_starting_d": "Визначаю вікно гри…",
    "st_prepare": "ПІДГОТОВКА", "st_prepare_d": "Перевіряю вудку та наживку",
    "st_cast": "ЗАКИДАЮ", "st_cast_d": "Закидаю вудку…",
    "st_bite": "КЛЮВАННЯ", "st_bite_d": "Очікування клювання…", "st_bite_wait_d": "Очікування клювання… {n} с",
    "st_mini": "МІНІ-ГРА", "st_mini_d": "Витягую рибу!", "st_mini_hold_d": "Утримую рибу в зоні",
    "st_caught": "ЛОВЛЯ", "st_caught_d": "Рибу спіймано",
    "st_check": "ПЕРЕВІРКА", "st_check_d": "Перевіряю наживку", "st_check_nobite_d": "Немає клювання — перевіряю наживку",
    "st_await": "ОЧІКУВАННЯ", "st_await_d": "Чекаю на міні-гру риболовлі…",
    "st_slip": "ЗРИВ!", "st_slip_d": "Риба йде — аварійний режим",
    "log_game_window": "🎮 Вікно гри: «{title}»", "log_pause": "⏸ Вікно гри не активне — пауза (повернись у гру)",
    "log_resume": "▶ Вікно гри знову активне", "log_start": "▶ Риболовля почалась",
    "log_stop": "■ Риболовля завершилась — {reason}. Спіймано: {n}", "log_mini": "🎣 Міні-гра",
    "log_caught": "🐟 Спіймано #{n} (міні-гра {dur:.1f} с)", "log_no_bite": "⌛ Немає клювання {t} с ({k}/{lim})",
    "m_det_auto": "авто (контраст)", "m_det_both": "контраст+HSV", "m_det_hsv": "лише HSV", "log_use_found": "🖱 «Використати» знайдено за червоним рядком меню: ({ux}, {uy}), одна ЛКМ",
    "log_self_learn": "🧠 Шаблон {name}.png оновлено з екрана (збіг {s:.2f}) — пошук стане точнішим",
    "log_bait_notpl": "Немає шаблону bait.png — наживку не перевірено («Зір» → «Шаблон: наживка»)",
    "log_bait": "🪱 Наживка: {state} (стеків на екрані: {n})",
    "bait_yes": "є", "bait_no": "НЕМАЄ", "log_rod_missing": "🎣 Вудки немає в руках — беру",
    "log_bait_icon": "🪱 Значок наживки зник — перевіряю інвентар",
    "log_mode_mini_only": "🎣 Режим: лише міні-гра — інвентар та закидання повністю вимкнено",
    "log_inv_wait": "📂 Чекаю, поки відкриєш інвентар (сам я його не відкриваю)",
    "nt_inv_wait": "Відкрий інвентар у грі",
    "log_bait_skip": "Перевірку наживки пропущено — інвентар закрито",
    "st_inv_wait": "ВІДКРИЙ ІНВЕНТАР", "st_inv_wait_d": "Відкрий інвентар — бот чекає…",
    "m_selflearn": "Оновлювати шаблони з екрана",
    "log_cast": "🪝 Закидання вудки…", "log_cast_done": "🪝 Закидання виконано — чекаю клювання",
    "log_slip": "⚠ Риба зривається — аварійне утримання", "log_mini_done": "✔ Міні-гра: {dur:.1f} с, зривів {slip}, ЛКМ {sw:.1f} перемик/с",
    "log_debug": "📷 debug_screen.png, debug_bar.png збережено. {parts} | zone={zone} fish={fish}",
    "log_debug_fail": "❌ debug: {e}", "log_tpl_none": "немає файла",
    "log_capture": "🖥 Захват: {backend} ({detail})", "log_capture_fallback": "⚠️ DXGI-захват недоступний ({err}) — працюю через GDI (резерв без залежностей)",
    "log_capture_skipped": "🖥 {reason}",
    "log_cfg_migrate": "⚙ Конфіг: значення \"{key}\": \"mss\" застаріле (mss вирізано) — увімкнено {to}.",
    "log_cfg_drop": "⚙ Конфіг: ключ \"{key}\" застарілий — регулятор міні-гри переписано (v1.6), значення видалено.",
    "hint_capture": "Що робити: python -m pip install -U dxcam bettercam (і перезапусти). Якщо DXGI недоступний (RDP, віртуалка, вікно захищене від захоплення) — бот сам візьме GDI-резерв; щоб працювати суто за DXGI, поставь у fishmod_config.json \"capture_backend\": \"dxcam\"",
    "log_stream": "🖥 Потік міні-гри: {backend}, {fps} fps, регіон {rect}",
    "log_stream_stop": "🖥 Потік міні-гри зупинено",
    "log_stream_fail": "❌ Потік не запустився: {err}", "log_capture_error": "⚠ Захват: помилка {err}",
    "log_fallback_now": "⚠ Весь захват перейшов на GDI (резервний режим)",
    "log_bar_fit": "📐 Шкала з'їхала: калібрування оновлено {old} -> {new} (збіг {cov}), причина: {why}",
    "log_bar_fit_off": "📐 Шкала з'їхала, але bar_autofit вимкнено — поправ CFG[\"bar\"] вручну",
    "nt_bar_fit": "Перераховано область шкали — глянь сторінку «Зір»",
    "m_hyst": "Гістерезис рішення, px", "m_look": "Горизонт передбачення, мс",
    "m_aup": "Розгін зони вгору, px/с²", "m_g": "Падіння зони, px/с²",
    "m_vmax": "Границя швидкості зони, px/с",
    "m_barfit": "Самокалібрування шкали", "m_barref": "Міряти справжню шкалу",
    "v_scale_lab": "шкала", "v_bar_edge": "шкалу обрізано краєм кадру",
    "log_adapt": "⚖ Фізику зони виміряно: розгін вгору {up:.0f} px/с², падіння {dn:.0f} px/с² (вимірів {n})",
    "m_adapt": "Міряти фізику зони",
    "log_ready": "{app}: готово. {toggle} — старт/стоп, {panic} — аварійний стоп",
    "pg5_t": "AI-ЗІР", "pg5_s": "Локальний аналіз кадру: спостереження і події, офлайн",
    "ai_sec_status": "Стан конвеєра", "ai_sec_mode": "Режим пошуку вудочки (екіпірування)",
    "ai_state": "Конвеєр", "ai_state_screen": "Екран", "ai_model": "Модель", "ai_lat": "інференс",
    "ai_frames": "Кадрів", "ai_dropped": "Пропущено", "ai_events": "Подій", "ai_errs": "Помилок",
    "ai_diag_ev": "Подій у діагностиці", "ai_diag_sn": "Знімків",
    "ai_warn_nomodel": "⚠ Модель не встановлена — працюю легасі-зором (це нормально)",
    "b_ai_report": "Журнал AI", "b_ai_restart": "Перезапустити AI",
    "ai_hint_local": "Усе локально: CPU, офлайн; моделі ніколи не завантажуються самі",
    "ai_hint_noclick": "AI лише спостерігає і пише події — кліки робить колишня логіка",
    "ai_hint_models": "Моделі: ai/models/manifest.json — див. docs/AI_VISION.md",
    "ai_lbl_mode": "Стратегія", "ai_lbl_enabled": "AI-спостереження",
    "ai_lbl_change": "Детектор змін", "ai_lbl_ocr": "OCR інтерфейсу",
    "ai_lbl_snap": "Знімки невідомого", "ai_lbl_fps": "Повний аналіз, к/с",
    "ai_lbl_ocrfps": "OCR, к/с", "ai_lbl_conf": "Поріг впевненості",
    "ai_lbl_confirm": "Підтверджень стану", "ai_lbl_threads": "Потоки ONNX (0=авто)",
    "ai_mode_legacy": "Легасі (шаблони)", "ai_mode_ai": "AI (ONNX)", "ai_mode_hybrid": "Гібрид",
    "ai_st_off": "вимкнено", "ai_st_startup": "стартує", "ai_st_running": "працює",
    "ai_st_degraded": "деградував (без моделі)", "ai_st_stopped": "зупинено",
    "log_ai_on": "🤖 AI-спостереження увімкнено (режим вудочки: {mode})",
    "log_ai_off": "🤖 AI-спостереження вимкнено",
    "log_ai_ev": "🤖 AI: {typ} (впевненість {conf:.2f})",
    "log_ai_fail": "🤖 AI-конвеєр не запустився: {e} — рибалка триває без AI",
    "log_ai_nomodel": "🤖 AI-модель недоступна ({st}) — шукаю вудочку шаблонами",
    "log_ai_rod": "🤖 AI: вудочка ({x}, {y}), впевненість {s:.2f}",
    "log_ai_report": "🤖 Журнал AI (останні події):",
    "log_ai_diag": "🤖 Діагностика: подій {ev}, знімків {sn}, вимкнено: {dis}",
    "log_ai_off_short": "🤖 Конвеєр вимкнено (увімкніть на сторінці «AI-ЗІР»)",
    "log_equip_retry": "Меню не відкрилося — повторюю екіпірування ({n}/2)",
    "ai_rec_sec": "Запис сесій (ШІ вчиться на твоїх діях)",
    "b_rec_start": "⏺ Записати сесію", "b_rec_stop": "⏹ Зупинити запис",
    "b_rec_export": "Зібрати датасет", "ai_rec_idle": "Запис не ведеться",
    "ai_rec_status": "Триває запис: кадрів {f}, кліків {c}, {mb} МБ, курсор seen {g}",
    "ai_rec_hint": "Грай руками — бот пише кадри і твої кліки (це майбутні мітки).\nПотім «Зібрати датасет» → навч модель (docs/LEARNING.md)",
    "log_rec_on": "⏺ Запис сесії почато ({fps} к/с, межа {mb} МБ) — грай як зазвичай",
    "log_rec_off": "⏹ Запис зупинено: кадрів {f}, кліків {c}, {mb} МБ",
    "log_rec_fail": "⏺ Запис не почато: {e}",
    "log_ds_nosession": "Сесій немає — спершу запиши свою гру («Записати сесію»)",
    "log_ds_ok": "📊 Датасет зібрано: кадрів {f}, кліків-міток {c}, об'єктів {o}, фон {b} → {path}",
    "log_ds_fail": "📊 Датасет не зібрано: {e}",
    "fail_capture": "жоден бекенд захвату не запустився", "fail_templates": "немає шаблонів у папці templates: {files}", "fail_window": "не вдалося визначити вікно гри: перемкнись у гру та натисни F8",
    "nt_started": "Риболовля почалась", "nt_finished": "Риболовля завершилась: {text}", "nt_pause": "Пауза: повернись у гру",
    "nt_snapshot": "Знімок збережено (debug_screen.png)", "nt_tpl_saved": "Шаблон «{name}» збережено",
    "nt_tpl_countdown": "Шаблон «{name}»: наведи курсор… {i}",
    "reason_user": "зупинено вручну", "reason_no_bait": "наживка закінчилась",
    "reason_no_bite": "немає клювання (перевір вагу/місце)", "reason_error": "помилка",
    "pill_fmt": "{state}  ·  спіймано {n}  ·  {time}",
},
}

LANGS = [("ru", "RU"), ("en", "EN"), ("ua", "UA")]


def t(k, **kw):
    """Перевод строки по ключу для CFG['lang']; при пропуске — ru, потом сам ключ.
    Первый параметр намеренно назван k: вызовы вида t("...", key=..., to=...) подставляют
    значения для format() и не должны конфликтовать с именем параметра."""
    table = STRINGS.get(CFG.get("lang", "ru")) or STRINGS["ru"]
    s = table.get(k)
    if s is None:
        s = STRINGS["ru"].get(k, k)
    if kw:
        try:
            s = s.format(**kw)
        except Exception:
            pass
    return s


def tpl_label(name):
    return t(TEMPLATE_LABEL_KEYS.get(name, name))


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
# В STATE хроня КЛЮЧИ перевода, а не готовые строки — язык меняется на лету.
STATE = {"running": False, "title_key": "st_stopped", "detail_key": "st_idle_d",
         "detail_args": {}, "kind": "idle", "reason": ""}
STATS = {"catches": 0, "t0": None, "t_end": None, "mg": [], "checks": 0}
TOTAL = {"catches": 0, "sessions": 0, "best": 0, "last_reason_key": "", "last_reason_detail": ""}
# Живая телеметрия регулятора/захвата для страницы «Зрение» (пишет воркер, читает GUI)
CTL_VIEW = {"press": False, "err": 0.0, "mode": "norm", "lost": 0, "slip": 0,
            "zone": None, "fish": None, "fps": 0.0, "frame_ms": 0.0, "hist": [],
            "zone_v": 0.0, "fish_v": 0.0, "a_up": 0.0, "g_dn": 0.0, "brake": 0.0,
            "clamp": "", "cov": 0.0, "detected": False, "adapt_n": 0}
worker = None
GAME_TITLE = ""
# Физика зоны, измеренная ботом (разгон вверх при зажатой ЛКМ / вниз при отпущенной).
# Зависит от клиента, а между забросами не меняется — поэтому живёт всю сессию.
RELAY_PHYS = {"up": None, "dn": None, "n": 0, "logged": False}
held_keys = set()
mouse_down = False
last_switch = last_up_sent = hold_since = 0.0
_tls = threading.local()
_tpl_cache = {}
_tpl_trim_cache = {}                   # шаблоны после обрезки тёмных полей (см. _tpl_trimmed)
_pause_logged = False


def log(text):
    line = f"[{time.strftime('%H:%M:%S')}] {text}"
    LOG.append(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def set_state(title_key, detail_key="", kind="idle", **detail_args):
    """title_key/detail_key — ключи перевода из STRINGS (см. раздел 1B)."""
    STATE["title_key"], STATE["detail_key"], STATE["kind"] = title_key, detail_key, kind
    STATE["detail_args"] = detail_args


def state_text():
    return t(STATE["title_key"]), (t(STATE["detail_key"], **STATE["detail_args"]) if STATE["detail_key"] else "")


def notify(text_key, kind="ok", **kw):
    """text_key — ключ перевода; готовая строка тоже проходит (t() вернёт её как есть)."""
    EVENTS.put(("toast", t(text_key, **kw), kind))


def load_totals():
    try:
        with open(STATS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        TOTAL.update({k: v for k, v in data.items() if k in TOTAL})
        if "last_reason" in data and not TOTAL.get("last_reason_key"):
            TOTAL["last_reason_detail"] = str(data.get("last_reason") or "")
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
# 4. ЗАХВАТ ЭКРАНА — ЕДИНАЯ ТОЧКА ВХОДА (DXGI: dxcam/bettercam, резерв — GDI)
# ==========================================================================
# ВАЖНО: это ЕДИНСТВЕННЫЙ путь захвата во всём приложении. Все функции типа
# grab()/grab_px()/tpl()/find() работают через CAP; у бэкенда общий интерфейс
# (grab/can_stream/start/stop/close), поэтому «кто сейчас активен» не влияет ни на что
# выше. Прежний сторонний резерв удалён: вместо него — _GdiBackend на чистом ctypes.
#
# Почему один камера-объект: DXGI Desktop Duplication разрешает только ОДНУ активную
# дупликацию на выход, поэтому для потока мини-игры тот же camera.start(region=...),
# а разовые захват-вызовы во время потока обслуживаются последним кадром потока
# (или CAP.paused() — короткая остановка потока, захват, восстановление).

def _frame_ok(frame):
    """Кадр пригоден, только если это ndarray разумного размера и он НЕ полностью чёрный.

    Проверяется у каждого кандидата: «create() прошёл» ничего не значит, если буфер пуст
    или окно защищено от захвата — тогда приходят чёрные картинки, и бот вместо игры
    ловит тёмный фон (именно так выглядит «бот ничего не видит и зажимает ЛКМ»).
    """
    try:
        if frame is None or not hasattr(frame, "shape") or frame.ndim < 2:
            return False, "кадр не пришёл"
        h, w = frame.shape[:2]
        if w < 64 or h < 64:
            return False, "кадр %dx%d — подозрительно маленький" % (w, h)
        if int(np.max(frame)) <= 6:
            return False, "кадр полностью чёрный (экран защищён от захвата?)"
        return True, "%dx%d" % (w, h)
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)


# ------------------------------------------------------------------ резерв без зависимостей: GDI
class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]


class _GdiBackend:
    """Аварийный захват региона средствами GDI (user32/gdi32 через ctypes), 0 зависимостей.

    Нужен там, где DXGI не поднимается в принципе: RDP, виртуалка без 3D, «защищённое»
    окно, кривой драйвер. Это НЕ молчаливая подмена: бэкенд подписан в шапке, в журнале
    и на странице «Зрение», а первый кадр проверяется через _frame_ok так же строго,
    как у dxcam/bettercam.

    Почему своим кодом, а не сторонним пакетом (вырезан): тот на каждый захват заново создавал
    контекст и конвертировал ВЕСЬ монитор (на машине пользователя — 12 мс на кадр одной
    шкалы). При таком шаге цикла ШИМ-окно оказывается длиннее цикла регулятора, и ЛКМ
    «залипает». Здесь DC и bitmap переиспользуются в потоке, забирается только регион,
    выгрузка — один GetDIBits (32bpp, top-down) в переиспользуемый буфер.
    """
    name = "gdi"
    SRCCOPY = 0x00CC0020
    HORZRES, VERTRES, LOGPIXELSX = 8, 10, 88

    def __init__(self, monitor_idx=0):
        self._tls = threading.local()
        self._stop = None
        self._th = None
        if os.name != "nt" or not hasattr(ctypes, "windll"):
            raise RuntimeError("GDI-захват доступен только в Windows")
        usr, gdi = ctypes.windll.user32, ctypes.windll.gdi32
        hdc = usr.GetDC(None)
        if not hdc:
            raise RuntimeError("GDI: GetDC(NULL) вернул 0")
        try:
            w = int(gdi.GetDeviceCaps(hdc, self.HORZRES) or 0)
            h = int(gdi.GetDeviceCaps(hdc, self.VERTRES) or 0)
            dpi = int(gdi.GetDeviceCaps(hdc, self.LOGPIXELSX) or 96)
        finally:
            usr.ReleaseDC(None, hdc)
        if w < 160 or h < 120:                     # вдруг DC пустой (headless/RDP-сессия)
            w, h = int(usr.GetSystemMetrics(0) or 0), int(usr.GetSystemMetrics(1) or 0)
        if w < 160 or h < 120:
            raise RuntimeError("GDI: разрешение экрана %dx%d — непонятно, что захватывать" % (w, h))
        self.mon = {"left": 0, "top": 0, "width": int(w), "height": int(h)}
        self.note = "GDI %dx%d" % (w, h) + ("" if dpi in (0, 96) else " @%ddpi" % dpi)
        try:
            probe = self.grab(0, 0, min(w, 320), min(h, 240))
        except Exception as e:
            self.close()
            raise RuntimeError("GDI: %s: %s" % (type(e).__name__, str(e).strip()[:120]))
        ok, why = _frame_ok(probe)
        self.close()                               #_DC на время проверки держать незачем
        if not ok:
            raise RuntimeError("GDI: " + why)
        self.note = "кадр %s (GDI)" % why

    # ------------------------------------------------------------------ контекст GDI (на поток)
    def _ctx(self, w, h):
        c = getattr(self._tls, "c", None)
        if c is not None and c["w"] == w and c["h"] == h:
            return c
        if c is not None:
            self._free(c)
        usr, gdi = ctypes.windll.user32, ctypes.windll.gdi32
        hdc = usr.GetDC(None)
        if not hdc:
            raise RuntimeError("GDI: GetDC(NULL) вернул 0")
        mem = gdi.CreateCompatibleDC(hdc)
        bmp = gdi.CreateCompatibleBitmap(hdc, w, h) if mem else 0
        if not mem or not bmp:
            self._free({"hdc": hdc, "mem": mem, "bmp": bmp, "w": 0, "h": 0})
            raise RuntimeError("GDI: не удалось создать bitmap %dx%d (GDI-лимиты?)" % (w, h))
        gdi.SelectObject(mem, bmp)
        c = {"hdc": hdc, "mem": mem, "bmp": bmp, "w": w, "h": h,
             "buf": (ctypes.c_uint8 * (w * h * 4))()}
        self._tls.c = c
        return c

    @staticmethod
    def _free(c):
        try:
            usr, gdi = ctypes.windll.user32, ctypes.windll.gdi32
            if c.get("bmp"):
                gdi.DeleteObject(c["bmp"])
            if c.get("mem"):
                gdi.DeleteDC(c["mem"])
            if c.get("hdc"):
                usr.ReleaseDC(None, c["hdc"])
        except Exception:
            pass

    # ------------------------------------------------------------------ захват
    def grab(self, left, top, width, height):
        x, y = int(left), int(top)
        w, h = max(1, int(width)), max(1, int(height))
        c = self._ctx(w, h)
        gdi = ctypes.windll.gdi32
        if not gdi.BitBlt(c["mem"], 0, 0, w, h, c["hdc"], x, y, self.SRCCOPY):
            raise RuntimeError("BitBlt не выполнен (окно защищено от захвата?)")
        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h                # отрицательная высота = top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        if not gdi.GetDIBits(c["mem"], c["bmp"], 0, h, c["buf"], ctypes.byref(bmi), 0):
            raise RuntimeError("GetDIBits вернул 0 (экран не отрисован?)")
        arr = np.frombuffer(c["buf"], dtype=np.uint8, count=w * h * 4).reshape(h, w, 4)
        return np.ascontiguousarray(arr[:, :, :3])   # BGRA -> BGR, как у dxcam с output_color=BGR

    # ------------------------------------------------------------------ «поток» (pump-поток)
    def can_stream(self):
        return True

    def start(self, left, top, width, height, fps, on_frame):
        self.stop()
        self._stop = threading.Event()
        self._th = threading.Thread(target=self._loop, daemon=True,
                                    args=(left, top, width, height, fps, on_frame, self._stop))
        self._th.start()

    def _loop(self, left, top, width, height, fps, on_frame, stop):
        period = 1.0 / max(10.0, float(fps))
        nxt = time.perf_counter()
        while not stop.is_set():
            try:
                on_frame(self.grab(left, top, width, height), time.perf_counter())
            except Exception:
                if stop.is_set():
                    break
                time.sleep(0.004)
            nxt += period
            delay = nxt - time.perf_counter()
            if delay > 0:
                time.sleep(min(delay, period))
            else:
                nxt = time.perf_counter()

    def stop(self):
        ev = getattr(self, "_stop", None)
        if ev is not None:
            ev.set()
            th = getattr(self, "_th", None)
            if th is not None:
                try:
                    th.join(timeout=0.5)
                except Exception:
                    pass
            self._stop = None
            self._th = None

    def close(self):
        self.stop()
        tls = getattr(self, "_tls", None)
        if tls is not None:
            c = getattr(tls, "c", None)
            if c is not None:
                self._free(c)
                tls.c = None


# ------------------------------------------------------------------ DXGI-поток (dxcam / bettercam)
class _DxgiStream:
    """Общая часть dxcam/bettercam: ОДИН camera-объект, region-захват и видеопоток.

    Обе библиотеки — обёртки над IDXGIOutputDuplication с почти одинаковым API, но НАБОР
    ПАРАМЕТРОВ зависит от версии: у dxcam 0.0.x регион ставится отдельным set_region(),
    у dxcam 0.3.x его принимает сам start(region=...), а get_latest_frame() там вообще без
    timeout; у bettercam 1.0.0 нет callback-а, только get_latest_frame(). Поэтому вместо
    «угадывания версии» тут короткий список кандидатов create()/start() и обязательная
    ПРОВЕРКА, что кадр действительно приходит: молчаливый откат на медленный путь стоил
    пользователю рабочего режима (20 к/с вместо 120+, ПИД «зажимает» ЛКМ).
    """

    name = "dxgi"
    module = None                                 # dxcam | bettercam — задаётся потомком

    # Потомок отвечает только за то, КАКИМИ аргументами звать create():
    def _create_candidates(self, monitor_idx):
        raise NotImplementedError

    # ------------------------------------------------------------------ создание
    _frame_ok = staticmethod(_frame_ok)      # общая проверка кадра — на уровне модуля (см. выше)

    def _grab_probe(self):
        """Первый кадр: новыми вариантами API, с короткими повторами (буфер мог быть пуст)."""
        cam = self.cam
        why = "кадр не пришёл"
        for attempt in range(4):
            for kw in ({"new_frame_only": False}, {"region": None}, {}):
                try:
                    f = cam.grab(**kw)
                except Exception:
                    continue
                ok, _note = self._frame_ok(f)
                if ok:
                    return f, None
                why = _note                       # например «кадр полностью чёрный»
            if attempt == 0:
                try:                            # иногда дупликация «просыпается» со 2-3-го кадра
                    cam.start(target_fps=60, video_mode=True)
                    time.sleep(0.12)
                    f = cam.get_latest_frame()
                    cam.stop()
                    if isinstance(f, tuple):
                        f = f[0]
                    ok, _note = self._frame_ok(f)
                    if ok:
                        return f, None
                    why = _note
                except Exception:
                    try:
                        cam.stop()
                    except Exception:
                        pass
            time.sleep(0.05)
        return None, why

    def __init__(self, monitor_idx=0):
        self.why = []
        self.cam = None
        self.note = ""
        self.mon = {"left": 0, "top": 0, "width": REF_W, "height": REF_H}
        self.streaming = False
        self._lkf_kw = "probe"
        mod = self.module
        if mod is None:
            raise RuntimeError("пакет «%s» не импортирован (%s)"
                              % (self.name, _CAP_IMPORT_ERR.get(self.name,
                                       "установи: python -m pip install -U dxcam bettercam")))
        if not hasattr(mod, "create"):
            raise RuntimeError("у %s нет create() — неподдерживаемая версия" % self.name)
        for kwargs in self._create_candidates(int(monitor_idx)):
            tag = ", ".join("%s=%r" % (k, v) for k, v in sorted(kwargs.items())) or "без параметров"
            try:
                cam = mod.create(**kwargs)
            except Exception as e:
                self.why.append("create(%s): %s: %s" % (tag, type(e).__name__, str(e).strip()[:150]))
                continue
            if cam is None:
                self.why.append("create(%s): вернул None" % tag)
                continue
            self.cam = cam
            frame, err = self._grab_probe()
            if frame is None:
                self.why.append("create(%s): %s" % (tag, err))
                self._release(cam)
                self.cam = None
                continue
            w = int(getattr(cam, "width", 0) or 0)
            h = int(getattr(cam, "height", 0) or 0)
            if w > 0 and h > 0:                   # dxcam/bettercam отсчитывают регион от левого
                self.mon = {"left": int(getattr(cam, "left", 0) or 0),   # верха ВЫХОДА, не всего
                            "top": int(getattr(cam, "top", 0) or 0),      # десктопа
                            "width": w, "height": h}
            self.note = "кадр %dx%d" % (w or frame.shape[1], h or frame.shape[0])
            break
        if self.cam is None:
            raise RuntimeError("; ".join(self.why[-2:]) or "камера не создана")

    @staticmethod
    def _release(cam):
        for m in ("stop", "release"):
            try:
                getattr(cam, m)()
            except Exception:
                pass

    # ------------------------------------------------------------------ захват
    def _local(self, left, top, width, height):
        l = int(left) - self.mon["left"]
        t = int(top) - self.mon["top"]
        return l, t, l + max(1, int(width)), t + max(1, int(height))

    def grab(self, left, top, width, height):
        l, t, r, b = self._local(left, top, width, height)
        frame = None
        for kw in ({"region": (l, t, r, b), "new_frame_only": False},
                   {"region": (l, t, r, b)}, {}):
            try:
                frame = self.cam.grab(**kw)
            except (TypeError, ValueError, AttributeError):
                continue
            if frame is not None:
                break
        if frame is None:
            raise RuntimeError("%s: кадр не получен" % self.name)
        if isinstance(frame, tuple):
            frame = frame[0]
        fh, fw = frame.shape[:2]
        if (r - l, b - t) != (min(r, fw) - max(0, l), min(b, fh) - max(0, t)) and (fw, fh) != (r - l, b - t):
            x0, y0 = max(0, min(l, fw - 1)), max(0, min(t, fh - 1))
            x1, y1 = max(x0 + 1, min(r, fw)), max(y0 + 1, min(b, fh))
            frame = frame[y0:y1, x0:x1]
        return np.ascontiguousarray(frame[:, :, :3])

    def can_stream(self):
        return True

    # ------------------------------------------------------------------ видеопоток
    def _start_variants(self, region, fps):
        cam = self.cam

        def _set_region():
            f = getattr(cam, "set_region", None)
            if f is None:
                raise AttributeError("set_region нет")
            f(region)

        return [
            lambda: cam.start(region=region, target_fps=fps, video_mode=True),   # dxcam 0.3.x, bettercam 1.0
            lambda: (_set_region(), cam.start(target_fps=fps, video_mode=True)),  # dxcam 0.0.x
            lambda: cam.start(target_fps=fps, video_mode=True),
            lambda: cam.start(target_fps=fps),
        ]

    def start(self, left, top, width, height, fps, on_frame):
        if self.streaming:
            self.stop()
        l, t, r, b = self._local(left, top, width, height)
        errs = []
        for attempt in self._start_variants((l, t, r, b), int(fps)):
            try:
                attempt()
                break
            except Exception as e:
                errs.append("%s: %s" % (type(e).__name__, str(e).strip()[:120]))
        else:
            raise RuntimeError("start() не запустился (%s)" % "; ".join(errs[-2:]))
        self._on_frame_cb = on_frame
        self.streaming = True
        self._th = threading.Thread(target=self._pump, daemon=True)
        self._th.start()

    def _latest(self):
        try:
            f = self.cam.get_latest_frame(**(self._lkf_kw if isinstance(self._lkf_kw, dict) else {}))
        except TypeError:
            f = self.cam.get_latest_frame()
        except Exception:
            return None
        if isinstance(f, tuple):
            f = f[0]
        return f

    def _pump(self):
        while self.streaming:
            try:
                if self._lkf_kw == "probe":                     # timeout= есть не во всех версиях
                    try:
                        frame = self.cam.get_latest_frame(timeout=1.0)
                        self._lkf_kw = {"timeout": 1.0}
                    except TypeError:
                        frame = self.cam.get_latest_frame()
                        self._lkf_kw = {}
                else:
                    frame = self.cam.get_latest_frame(**self._lkf_kw)
            except Exception:
                if not self.streaming:
                    break
                time.sleep(0.003)
                continue
            if frame is None:
                continue
            if isinstance(frame, tuple):
                frame = frame[0]
            try:
                self._on_frame_cb(np.ascontiguousarray(frame[:, :, :3]), time.perf_counter())
            except Exception:
                pass

    def stop(self):
        self.streaming = False
        th = getattr(self, "_th", None)
        if th is not None:
            try:
                th.join(timeout=1.0)
            except Exception:
                pass
            self._th = None
        if self.cam is not None:
            for m in ("stop", "clear_queue"):
                try:
                    getattr(self.cam, m)()
                except Exception:
                    pass

    def close(self):
        cam, self.cam = self.cam, None
        self.streaming = False
        th = getattr(self, "_th", None)
        if th is not None:
            try:
                th.join(timeout=1.0)
            except Exception:
                pass
            self._th = None
        if cam is not None:
            self._release(cam)


class _DxcamBackend(_DxgiStream):
    """Основной захват: dxcam (IDXGIOutputDuplication)."""
    name = "dxcam"
    module = dxcam

    def _create_candidates(self, monitor_idx):
        out = monitor_idx
        try:                                            # output_idxs() есть только в старых 0.0.x
            idxs = list(self.module.output_idxs())
            if idxs and out not in idxs:
                out = idxs[0]
        except Exception:
            pass
        bgr = {"output_color": "BGR"}                   # BGR, а не RGB: cv2 у нас везде в BGR
        return [{"output_idx": out, **bgr},
                {"output_idx": out},
                {"device_idx": 0, "output_idx": out, **bgr},
                dict(bgr),
                {}]


class _BettercamBackend(_DxgiStream):
    """Запасной DXGI-бэкенд: bettercam (актуальный форк dxcam, ставится вместе с ним)."""
    name = "bettercam"
    module = bettercam

    def _create_candidates(self, monitor_idx):
        bgr = {"output_color": "BGR"}
        return [{"output_idx": monitor_idx, **bgr},     # bettercam 1.0.0
                {"monitor_index": monitor_idx + 1},     # bettercam 0.x
                dict(bgr),
                {}]
class ScreenCapture:
    """
    Единая обёртка над захватом экрана.

    * "dxcam" -> "bettercam" — DXGI Desktop Duplication, основной режим: region-capture
      (не весь экран с кропом) + video_mode с target_fps для мини-игры (минимальная
      задержка, ~120-144 к/с).
    * "gdi" — резерв БЕЗ зависимостей (ctypes, BitBlt по экрану) для случаев, где DXGI
      не поднимается вовсе: RDP, виртуалка без 3D, защищённое от захвата окно. Он всегда
      подписан в интерфейсе и в журнале, «незаметной» подмены не бывает.
    * fallback_reason — список причин, по которым каждый из DXGI-бэкендов не подошёл
      (его печатает журнал и страница «Зрение»); is_fallback — режим не-DXGI.
    """

    CANDIDATES = {"auto": ("dxcam", "bettercam", "gdi"), "dxcam": ("dxcam",),
                  "bettercam": ("bettercam",), "gdi": ("gdi",)}

    def __init__(self, want="auto", monitor_idx=0):
        self.frame = None                 # последний кадр потока (BGR) для превью
        self.frame_ts = 0.0
        self.frame_w = self.frame_h = 0
        self.stream_rect = None
        self.streaming = False
        self.frames = 0
        self.fps = 0.0
        self.avg_ms = 0.0
        self.last_grab_ms = 0.0
        self.grabs = 0
        self.errors = 0
        self._lock = threading.RLock()
        self._new = threading.Event()
        self.fallback_reason = ""
        self._bg = None                       # иначе «ни один бэкенд не подошёл» падало
        self.backend = ""                      # AttributeError вместо внятного Fail-сообщения
        self.cam_note = ""
        order = self.CANDIDATES.get(str(want or "auto").lower().strip())
        if order is None:                       # любое неизвестное значение = auto
            order = self.CANDIDATES["auto"]
        reasons = []
        for name in order:
            try:
                if name == "dxcam":
                    bg = _DxcamBackend(monitor_idx)
                elif name == "bettercam":
                    bg = _BettercamBackend(monitor_idx)
                elif name == "gdi":
                    bg = _GdiBackend(monitor_idx)
                else:
                    continue
                self.backend, self._bg = name, bg
                self.cam_note = getattr(bg, "note", "") or ""
                break
            except Exception as e:
                self.errors += 1
                reasons.append("%s: %s" % (name, str(e) or type(e).__name__))
        self.fallback_reason = " | ".join(reasons)
        if self._bg is None:
            raise Fail(t("fail_capture") + " — " + (self.fallback_reason or "—")
                       + "\n" + t("hint_capture"))
        self.is_fallback = self.backend == "gdi"
        m = getattr(self._bg, "mon", None) or {"left": 0, "top": 0, "width": REF_W, "height": REF_H}
        self.mon = {"left": int(m.get("left", 0)), "top": int(m.get("top", 0)),
                    "width": max(1, int(m.get("width", REF_W))), "height": max(1, int(m.get("height", REF_H)))}
        self.sx = self.mon["width"] / float(REF_W)
        self.sy = self.mon["height"] / float(REF_H)

    # ---------------------------------------------------------------- низкоуровневое
    def _on_frame(self, bgr, ts):
        with self._lock:
            self.frame, self.frame_ts = bgr, ts
            self.frame_h, self.frame_w = bgr.shape[:2]
            self.frames += 1
            dt = ts - self.frame_prev if getattr(self, "frame_prev", 0) else 0.0
            self.frame_prev = ts
            if dt > 0:
                self.avg_ms = dt * 1000.0 if not self.avg_ms else self.avg_ms * 0.9 + dt * 900.0
                inst = 1.0 / dt
                self.fps = inst if not self.fps else self.fps * 0.9 + inst * 0.1
        self._new.set()

    def _raw(self, left, top, width, height):
        t0 = time.perf_counter()
        out = self._bg.grab(left, top, width, height)
        self.last_grab_ms = time.perf_counter() - t0
        self.grabs += 1
        return out

    # ---------------------------------------------------------------- API
    def grab_region(self, left, top, width, height):
        """Физические пиксели экрана -> BGR ndarray. Всегда через активный бэкенд."""
        width, height = max(1, int(round(width))), max(1, int(round(height)))
        left, top = int(round(left)), int(round(top))
        with self._lock:
            if self.streaming:
                rect = self.stream_rect
                if rect is not None and left >= rect[0] and top >= rect[1] \
                        and left + width <= rect[0] + rect[2] and top + height <= rect[1] + rect[3]:
                    if self.frame is not None:      # превью во время потока берём из потока
                        fy = self.frame_h / float(rect[3])
                        fx = self.frame_w / float(rect[2])
                        y0, x0 = int((top - rect[1]) * fy), int((left - rect[0]) * fx)
                        y1, x1 = min(self.frame_h, y0 + int(height * fy)), min(self.frame_w, x0 + int(width * fx))
                        if y1 > y0 and x1 > x0:
                            return np.ascontiguousarray(self.frame[y0:y1, x0:x1])
                else:
                    # запрос на ДРУГОЙ регион (инвентарь, отладка) во время потока:
                    # поток временно гасим, чтобы не мешать единственному DXGI-дубликатору
                    self._restart_after = rect
                    self.stop_stream()
            try:
                return self._raw(left, top, width, height)
            except Exception as e:
                self.errors += 1
                if not self.is_fallback:
                    log(t("log_capture_error", err=f"{type(e).__name__}: {e}"))
                    try:
                        self._degrade_to_gdi()
                    except Exception as ed:
                        log(t("log_stream_fail", err=f"gdi: {type(ed).__name__}: {ed}"))
                        raise
                return self._raw(left, top, width, height)
            finally:
                self._maybe_resume()

    def grab_ref(self, rect):
        """Прямоугольник в эталонных координатах 1920x1080 -> BGR ndarray (масштаб учитывается)."""
        x, y, w, h = rect
        return self.grab_region(self.mon["left"] + x * self.sx, self.mon["top"] + y * self.sy,
                                w * self.sx, h * self.sy)

    def grab_full(self):
        m = self.mon
        return self.grab_region(m["left"], m["top"], m["width"], m["height"])

    def start_stream(self, rect_ref, fps=None):
        """Видео-поток DXGI с target_fps для мини-игры (только нужный регион).
        self.stream_rect хранится как (left, top, width, height) в ФИЗИЧЕСКИХ пикселях."""
        with self._lock:
            if self.streaming:
                self.stop_stream()
            if not self._bg.can_stream():
                return False
            x, y, w, h = rect_ref
            phys = (self.mon["left"] + x * self.sx, self.mon["top"] + y * self.sy, w * self.sx, h * self.sy)
            self.stream_rect = (int(round(phys[0])), int(round(phys[1])), int(round(phys[2])), int(round(phys[3])))
            self.frames, self.fps, self.avg_ms, self.frame_prev = 0, 0.0, 0.0, 0.0
            try:
                self._bg.start(*self.stream_rect, int(fps or CFG["capture_fps"]), self._on_frame)
            except Exception as e:
                self.errors += 1
                log(t("log_capture_error", err=f"{type(e).__name__}: {e}"))
                if not self.is_fallback:
                    try:
                        self._degrade_to_gdi()          # GDI может быть недоступен (не Windows,
                    except Exception as ed:              # чёрный экран) — ронять мини-игру нельзя
                        self.errors += 1
                        log(t("log_stream_fail", err=f"gdi: {type(ed).__name__}: {ed}"))
                        self.stream_rect = None
                        return False
                    try:
                        self._bg.start(*self.stream_rect, int(fps or CFG["capture_fps"]), self._on_frame)
                    except Exception as e2:
                        self.stream_rect = None
                        log(t("log_stream_fail", err=str(e2)))
                        return False
                else:
                    self.stream_rect = None
                    return False
            self.streaming = True
            log(t("log_stream", backend=self.backend, fps=int(CFG["capture_fps"]),
                  rect=f"{self.stream_rect[2]}x{self.stream_rect[3]} @({self.stream_rect[0]},{self.stream_rect[1]})"))
            return True

    def wait_frame(self, timeout=0.25):
        """Ждёт новый кадр потока; возвращает (BGR | None, ts)."""
        if not self.streaming:
            return None, 0.0
        self._new.clear()
        got = self._new.wait(timeout)
        with self._lock:
            return (self.frame, self.frame_ts) if got and self.frame is not None else (None, self.frame_ts)

    def _maybe_resume(self):
        r = getattr(self, "_restart_after", None)
        if r and self.streaming:          # бэкенд уже сам поднял поток (например, после _degrade_to_gdi)
            self._restart_after = None
            return
        if r:
            self._restart_after = None
            try:
                self._bg.start(*r, int(CFG["capture_fps"]), self._on_frame)
                self.stream_rect = tuple(r)
                self.streaming = True
            except Exception:
                pass

    def stop_stream(self):
        with self._lock:
            if self.streaming:
                try:
                    self._bg.stop()
                except Exception:
                    pass
                self.streaming = False
                self.stream_rect = None
                self._new.set()
                log(t("log_stream_stop"))

    def _degrade_to_gdi(self):
        """DXGI сломался в полёте — единообразно переходим на GDI (весь захват, без зависимостей)."""
        was, rect = self.streaming, self.stream_rect
        try:
            self._bg.close()
        except Exception:
            pass
        self.streaming = False
        self.stream_rect = None
        self._bg = _GdiBackend()
        self.backend, self.is_fallback = "gdi", True
        self.fallback_reason = "DXGI failed at runtime"
        m = self._bg.mon
        self.mon = {"left": int(m["left"]), "top": int(m["top"]), "width": int(m["width"]), "height": int(m["height"])}
        self.sx = self.mon["width"] / float(REF_W)
        self.sy = self.mon["height"] / float(REF_H)
        log(t("log_fallback_now"))
        if was and rect:
            try:
                self._bg.start(*rect, int(CFG["capture_fps"]), self._on_frame)
                self.stream_rect = tuple(rect)
                self.streaming = True
            except Exception:
                pass

    def close(self):
        try:
            self.stop_stream()
        except Exception:
            pass
        try:
            self._bg.close()
        except Exception:
            pass


CAP = None


def init_capture():
    """Создаёт единственный экземпляр захвата. Вызывается один раз из main()/launcher.

    В журнал всегда попадает и ИМЯ бэкенда, и каждая причина, по которой DXGI-кандидат
    не подошёл: «тихой» деградации больше нет ни здесь, ни в мини-игре.
    """
    global CAP
    if CAP is not None:
        return CAP
    for k in CFG_MIGRATED:
        log(t("log_cfg_migrate", key=k, to=DEFAULT_CFG["capture_backend"]))
    for k in CFG_DROPPED:
        log(t("log_cfg_drop", key=k))
    CAP = ScreenCapture(CFG.get("capture_backend", "auto"), int(CFG.get("capture_monitor", 0) or 0))
    detail = getattr(CAP, "cam_note", "") or t("v_primary" if not CAP.is_fallback else "v_fallback")
    log(t("log_capture", backend=CAP.backend, detail=detail))
    if CAP.fallback_reason:                       # DXGI-кандидаты, которые не подошли, — видны
        for part in CAP.fallback_reason.split(" | "):
            log(t("log_capture_skipped", reason=part))
    if CAP.is_fallback:
        log(t("log_capture_fallback", err=CAP.fallback_reason or "—"))
        notify("v_fallback", "warn")
    return CAP


def monitor():
    """Геометрия монитора захвата (физические пиксели) — тоже через CAP."""
    if CAP is None:
        init_capture()
    return CAP.mon


def scale():
    if CAP is None:
        init_capture()
    return CAP.sx, CAP.sy


def P(x, y):
    m = monitor()
    sx, sy = scale()
    return int(m["left"] + x * sx), int(m["top"] + y * sy)


def grab_px(left, top, w, h):
    """Единственная «сырая» функция захвата — вся она проксирует в ScreenCapture."""
    if CAP is None:
        init_capture()
    return CAP.grab_region(left, top, w, h)


def grab(rect=None):
    if CAP is None:
        init_capture()
    if rect is None:
        return CAP.grab_full()
    return CAP.grab_ref(rect)


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
    t_ = tpl(name)
    if t_ is None:
        return None, None, None
    reg = REGIONS[name]
    img = cv2.cvtColor(grab(reg), cv2.COLOR_BGR2GRAY)
    if img.shape[0] < t_.shape[0] or img.shape[1] < t_.shape[1]:
        return None, t_, reg
    r = cv2.matchTemplate(img, t_, cv2.TM_CCOEFF_NORMED)
    return np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=0.0), t_, reg


def best_score(name):
    r, _, _ = _match_map(name)
    return None if r is None else float(r.max())


def find_all(name, thr=None, min_dist=40):
    thr = THR.get(name, 0.85) if thr is None else thr
    r, t_, reg = _match_map(name)
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
    h, w = t_.shape
    ox, oy = m["left"] + int(reg[0] * sx), m["top"] + int(reg[1] * sy)
    return [(s, ox + x + w // 2, oy + y + h // 2) for s, x, y in out]


def find(name, thr=None):
    res = find_all(name, thr)
    return res[0] if res else None




# ==========================================================================
# 5. ВВОД, ОСТАНОВКА, ФОКУС
# ==========================================================================

# --- низкоуровневый ввод через SendInput (без DPI-нормализации pydirectinput) ---
_SM_CXSCREEN = 0
_SM_CYSCREEN = 1
_SM_XVIRTUALSCREEN = 76               # левая граница виртуального рабочего стола
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78              # размер ВСЕГО рабочего стола (все мониторы)
_SM_CYVIRTUALSCREEN = 79
MOUSEEVENTF_MOVE        = 0x0001
MOUSEEVENTF_LEFTDOWN    = 0x0002
MOUSEEVENTF_LEFTUP      = 0x0004
MOUSEEVENTF_RIGHTDOWN   = 0x0008
MOUSEEVENTF_RIGHTUP     = 0x0010
MOUSEEVENTF_ABSOLUTE    = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000      # абсолютные координаты всего рабочего стола

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
    inp.mi.mouseData = 0
    inp.mi.dwFlags = flags
    inp.mi.time = 0
    inp.mi.dwExtraInfo = None
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

def logical_to_physical(lx, ly):
    """Конвертирует логические координаты Windows (GetCursorPos) в физические пиксели экрана захвата."""
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
    """Перемещает мышь в точку (x, y) КООРДИНАТ ЗАХВАТА (физические пиксели монитора,
    который снимает ScreenCapture). Отрисовка и клик всегда в одной системе координат:
    координаты кадра складываются с origin монитора захвата и маппятся на ВЕСЬ
    виртуальный рабочий стол (MOUSEEVENTF_VIRTUALDESK) — на мультимониторе курсор
    встаёт именно туда, куда смотрит бот, а не «куда-то» на первом экране."""
    try:
        m = monitor()
        ml, mt = int(m["left"]), int(m["top"])
        mw, mh = int(m["width"]), int(m["height"])
    except Exception:
        ml = mt = 0
        mw = ctypes.windll.user32.GetSystemMetrics(_SM_CXSCREEN)
        mh = ctypes.windll.user32.GetSystemMetrics(_SM_CYSCREEN)
    try:
        vx = ctypes.windll.user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)
        vy = ctypes.windll.user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)
        vw = ctypes.windll.user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN)
        vh = ctypes.windll.user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN)
    except Exception:
        vx, vy, vw, vh = 0, 0, mw, mh
    if vw > mw + 2 or vh > mh + 2 or vx != 0 or vy != 0:      # несколько мониторов
        nx = int((ml + int(x)) * 65535 / max(vw - 1, 1))
        ny = int((mt + int(y)) * 65535 / max(vh - 1, 1))
        _send_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny)
        return
    nx = int(int(x) * 65535 / max(mw - 1, 1))
    ny = int(int(y) * 65535 / max(mh - 1, 1))
    _send_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, nx, ny)

def mouse_lmb_down():
    _send_mouse(MOUSEEVENTF_LEFTDOWN)
    global mouse_down, hold_since
    mouse_down = True
    hold_since = time.perf_counter()

def mouse_lmb_up():
    _send_mouse(MOUSEEVENTF_LEFTUP)
    global mouse_down, last_up_sent
    mouse_down = False
    last_up_sent = time.perf_counter()

# (v1.21) старые помощники нажатий удалены: mouse_rmb_click/mouse_lmb_click,
# pdi_key/key_down/key_up и вся макро-система (запись/повтор). Весь ввод — зрительная
# экипировка (_ui_click: окно интерфейса или курсор) и mouse_lmb_down/up мини-игры.


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
        _send_mouse(MOUSEEVENTF_LEFTUP)
        _send_mouse(MOUSEEVENTF_RIGHTUP)
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
    return (not GAME_TITLE) or GAME_TITLE.lower() in foreground_title().lower()


def learn_game_window(timeout=15.0):
    """Запоминает активное окно (не наше) как окно игры. Бот работает ТОЛЬКО пока оно активно."""
    global GAME_TITLE
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        if stop_event.is_set():
            raise Stopped()
        ttl = foreground_title()
        if ttl and not is_own_window(ttl) and ttl not in ("Program Manager", "Task Switching"):
            GAME_TITLE = ttl
            log(t("log_game_window", title=ttl))
            return ttl
        time.sleep(0.25)
    raise Fail(t("fail_window"))


def wait_focus():
    global _pause_logged
    release_all()
    if not _pause_logged:
        log(t("log_pause"))
        notify("nt_pause", "warn")
        _pause_logged = True
    t0 = time.perf_counter()
    while not game_focused():
        if stop_event.is_set():
            raise Stopped()
        time.sleep(0.2)
    _pause_logged = False
    log(t("log_resume"))
    return time.perf_counter() - t0


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


def move_px(x, y):
    mouse_move_abs(int(x), int(y))
    time.sleep(0.03)


def click_px(x, y, button="left", pre=0.12, post=0.15):
    mouse_move_abs(int(x), int(y))
    nap(pre)
    if button == "left":
        _send_mouse(MOUSEEVENTF_LEFTDOWN)
        nap(0.06)
        _send_mouse(MOUSEEVENTF_LEFTUP)
    else:
        _send_mouse(MOUSEEVENTF_RIGHTDOWN)
        nap(0.06)
        _send_mouse(MOUSEEVENTF_RIGHTUP)
    nap(post)


def set_mouse(down, force=False):
    """ЛКМ для мини-игры через SendInput (без DPI проблем)."""
    global mouse_down, last_switch, last_up_sent, hold_since
    now = time.perf_counter()
    if down != mouse_down:
        if not force and now - last_switch < MIN_SWITCH:
            return
        if down:
            mouse_lmb_down()
        else:
            mouse_lmb_up()
        last_switch = now
    elif not down and now - last_up_sent >= RESYNC:
        # периодически повторяем mouseUp чтобы не залипало
        _send_mouse(MOUSEEVENTF_LEFTUP)
        last_up_sent = now


# ==========================================================================
# 6. МИНИ-ИГРА: РАСПОЗНАВАНИЕ + ПИД-РЕГУЛЯТОР + ШИМ
# ==========================================================================
# Как это работает (коротко):
#   1) Кадр берётся ПОТОКОМ DXGI (ScreenCapture.start_stream) с target_fps 120-144 — только
#      регион шкалы + отступ на рамку «РЫБА СРЫВАЕТСЯ».
#   2) analyze() находит зелёную зону (HSV) и рыбку НЕ по цвету, а по «неоднородности»
#      строки шкалы: фон шкалы внутри одной строки почти постоянен по горизонтали, а спрайт
#      рыбы — нет. Поэтому работает для любых видов рыб (разные текстуры/цвета).
#   3) Регулятор — РЕЛЕ С ПРЕДСКАЗАНИЕМ ОСТАНОВА (relay_decide): каждый кадр бот
#      предсказывает, где зона остановится при «жать» и при «отпустить», и выбирает
#      действие с точкой останова ближе к центру рыбы. Скважности/ШИМ нет — решение
#      всегда двоичное, привязано к кадрам и не насыщается (это и ломало ПИД).
#   4) Упреждение: цель = центр рыбы, сдвинутый вперёд по её измеренной скорости.
#   5) «РЫБА СРЫВАЕТСЯ!» — красная рамка вокруг шкалы: телеметрия «АВАРИЯ»; закон
#      управления тот же (он сам даёт длинное устойчивое движение к рыбе).

def relay_decide(zc, zv, tgt, pressed, a_up, g_dn, vmax, look, hyst):
    """РЕЛЕ С ПРЕДСКАЗАНИЕМ ОСТАНОВА: True = держать ЛКМ.

    zc, zv — центр зоны (px) и её скорость (px/с, вниз +); tgt — цель (центр рыбы
    с упреждением); pressed — текущее состояние ЛКМ; a_up / g_dn — разгон зоны вверх
    при зажатой ЛКМ / вниз при отпущенной (px/с^2); vmax — предел скорости для
    предсказания; look — горизонт предсказания, с; hyst — гистерезис решения, px.

    Каждый кадр считаем, где зона будет через look секунд при каждом из двух действий:
    продолжать текущее или немедленно сменить. Скорость при смене действия не
    обнуляется (инерция), поэтому предсказание учитывает и выбег после отпускания —
    бот отпускает ЛКМ ЗАРАНЕЕ, пока зону ещё несёт к рыбе. Выбираем действие с
    точкой, ближе к цели; смена только если другое действие лучше на hyst px
    (иначе дребезг кликов). Закон самосбалансирован: около цели он продолжает
    короткие циклы «прижал-отпустил», которые держат центр зоны на рыбе, а вдали от
    цели даёт длинное устойчивое движение — без насыщения и без интегратора.
    """

    def future(a):
        # позиция через look при ускорении a (со срезом по предельной скорости)
        v = zv + a * look
        if v > vmax:
            a = (vmax - zv) / look
        elif v < -vmax:
            a = (-vmax - zv) / look
        return zc + zv * look + 0.5 * a * look * look

    e_on = abs(future(-a_up) - tgt)          # где будем, если ЖАТЬ
    e_off = abs(future(g_dn) - tgt)          # где будем, если ОТПУСТИТЬ
    if pressed:
        return e_on <= e_off + hyst          # жмём, пока это не хуже отпущенных
    return e_on + hyst < e_off               # для нажатия требуется явный выигрыш


def bar_rects():
    """(rect_ref, inner): расширенный прямоугольник для захвата в эталонных координатах и
    прямоугольник самой шкалы внутри полученного кадра (в реальных пикселях)."""
    bx, by, bw, bh = CFG["bar"]
    pad = max(4, int(CFG["bar_pad"]))
    sx, sy = scale()
    rect = [bx - pad, by - pad, bw + 2 * pad, bh + 2 * pad]
    inner = (int(round(pad * sx)), int(round(pad * sy)), int(round(bw * sx)), int(round(bh * sy)))
    return rect, inner


def _runs(flag, lo_frac=0.0):
    """Список непрерывных отрезков True в булевом массиве: [(start, end_incl), ...]."""
    out, start = [], None
    for i, v in enumerate(flag):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i - 1)); start = None
    if start is not None:
        out.append((start, len(flag) - 1))
    return out


def _scale_sanity(sc, img, hint):
    """Стоит ли верить найденной рамке шкалы.

    Кадр мини-игры маленький (шкала + bar_pad), и на однотонном фоне (сине-серая вода,
    небо, тёмный интерфейс) маска закрывает всё сразу: такая «шкала» равна всему кадру, и
    лучше не измерять ничего, чем верить ей — иначе измерения становятся хуже, чем просто
    доверие CFG["bar"]. Поэтому отказ, если найдено ~всё (структуры нет) или рамка сильно
    БОЛЬШЕ подсказки.
    """
    x0, y0, x1, y1, cov = sc
    H, W = img.shape[:2]
    w, h = x1 - x0, y1 - y0
    if w < 8 or h < 40 or h < 1.6 * w:
        return None
    if w >= 0.85 * W and h >= 0.85 * H:
        return None                                  # «шкала» = весь кадр: структуры нет
    if hint is not None and (w > 1.8 * hint[2] or h > 1.5 * hint[3]):
        return None                                  # сильно больше подсказки = не шкала
    return sc


def _runs_merge(runs, gap):
    """Соседние отрезки с разрывом <= gap склеиваем: рыба, антиалиасинг края зоны и
    тёмная полоска-разделитель делают в «столбце шкалы» дырки в 1-6 пикселей, и без
    склейки вертикальный отрезок шкалы рвётся ровно посередине (проверено на синтетике
    tests/test_bar_detect.py)."""
    out = []
    for a, b in runs:
        if out and a - out[-1][1] <= gap:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def scale_rect(img, hint=None):
    """Где на кадре НА САМОМ ДЕЛЕ шкала мини-игры: (x0, y0, x1, y1, cov) или None.

    CFG["bar"] — только ПОДСКАЗКА. При смене разрешения, масштаба Windows, другого монитора
    или просто неточной калибровки окно захвата уезжает, и бот начинает измерять «зону» и
    «рыбу» в несуществующих координатах: он «зажимает ЛКМ» и «не ведёт за рыбой» ровно тогда,
    когда смотрит не туда. Поэтому границы шкалы каждый кадр берутся из самой картинки.

    Порядок поиска: зелёная зона — самый различимый элемент, и она ВСЕГДА внутри шкалы,
    поэтому колонку находим по ней (а по голубому градиенту — только верх/низ шкалы).
    Если зоны в кадре нет (ушла за край, только что появилась) — ищем просто голубую
    вертикальную полосу. hint = (x, y, w, h) помогает не перепрыгнуть на чужую полоску UI.
    """
    H, W = img.shape[:2]
    if H < 40 or W < 8:
        return None
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, LOWER_GREEN, UPPER_GREEN)
    bonly = cv2.inRange(hsv, np.array([95, 70, 55]), np.array([135, 255, 255]))
    both = cv2.bitwise_or(bonly, green)
    gcol = (green > 0).sum(axis=0)
    gcols = _runs(gcol >= max(6, 0.4 * int(gcol.max()))) if gcol.max() else []
    gcols = [r for r in gcols if (r[1] - r[0] + 1) >= 8]
    if gcols:
        gcols.sort(key=lambda r: -int(gcol[r[0]:r[1] + 1].sum()))
        gx0, gx1 = gcols[0]
        grow = _runs((green[:, gx0:gx1 + 1] > 0).sum(axis=1) >= max(2, 0.35 * (gx1 - gx0 + 1)))
        if not grow:
            return None
        grow.sort(key=lambda r: -(r[1] - r[0]))
        gy0, gy1 = grow[0]
        cy = (gy0 + gy1) / 2.0
        if hint is not None and abs(cy - (hint[1] + hint[3] / 2.0)) > max(hint[3], 60) * 1.2:
            return None                              # «зона» слишком далеко от шкалы — это не она
        # ширина шкалы: зелёная зона задаёт середину, а края добираем по голубым столбцам
        bcol = (bonly > 0).sum(axis=0)
        ref = max(1, int(bcol[gx0:gx1 + 1].max()) if gx1 > gx0 else 1)
        thr_b = 0.45 * max(int(bcol.max()), ref)
        x0, x1 = gx0, gx1
        while x0 > 0 and bcol[x0 - 1] >= thr_b:
            x0 -= 1
        while x1 < W - 1 and bcol[x1 + 1] >= thr_b:
            x1 += 1
        w = x1 - x0 + 1
        rcol = (both[:, x0:x1 + 1] > 0).sum(axis=1)
        rows = _runs_merge(_runs(rcol >= 0.30 * w), max(6, w // 4))
        if not rows:
            return int(x0), int(gy0), int(x1) + 1, int(gy1) + 1, 0.9
        mid = (gy0 + gy1) // 2                       # берём отрезок, в котором лежит зона
        pick = next((r for r in rows if r[0] <= mid <= r[1]), None)
        if pick is None:
            pick = max(rows, key=lambda r: r[1] - r[0])
        y0, y1 = pick
        cov = float(rcol[y0:y1 + 1].mean() / w) if y1 > y0 else 0.0
        return _scale_sanity((int(x0), int(y0), int(x1) + 1, int(y1) + 1, round(cov, 3)), img, hint)
    colcnt = (both > 0).sum(axis=0).astype(np.float64)
    if colcnt.max() < 0.35 * H:
        return None
    cand = [r for r in _runs(colcnt >= 0.5 * colcnt.max())
            if (r[1] - r[0] + 1) >= 8 and (r[1] - r[0] + 1) <= max(12, int(W * 0.7))]
    if not cand:
        return None
    if hint is not None:
        hx, hy, hw, hh = hint
        cx = hx + hw / 2.0
        cand.sort(key=lambda r: abs((r[0] + r[1] + 1) / 2.0 - cx))
    x0, x1 = cand[0]
    w = x1 - x0 + 1
    rowcnt = (both[:, x0:x1 + 1] > 0).sum(axis=1).astype(np.float64)
    rr = [r for r in _runs_merge(_runs(rowcnt >= 0.30 * w), max(6, w // 4))
          if (r[1] - r[0] + 1) >= max(40, int(1.8 * w))]
    if not rr:
        return None
    rr.sort(key=lambda r: -(r[1] - r[0]))
    y0, y1 = rr[0]
    cov = float(rowcnt[y0:y1 + 1].mean() / w)
    if cov < 0.5 or (y1 - y0 + 1) < 0.2 * H:
        return None
    return _scale_sanity((int(x0), int(y0), int(x1) + 1, int(y1) + 1, round(cov, 3)), img, hint)


def _red_frame_mask(bgr):
    """Красный «на светлом фоне»: канал R заметно больше обоих остальных (рамка свечения)."""
    a = bgr.astype(np.int16)
    r, g, bb = a[..., 2], a[..., 1], a[..., 0]
    return (r > 50) & (r - np.maximum(g, bb) > 25)


def slip_score(img, box):
    """Доля строк шкалы, у которых слева/справа есть красная рамка (= «РЫБА СРЫВАЕТСЯ»).
    Рамка тонкая (1-3 пикселя в строке), поэтому считаем строки с >=1 красным пикселем."""
    x0, y0, x1, y1 = box
    H, W = img.shape[:2]
    best = 0.0
    for strip in (img[y0:y1, 0:max(1, x0 - 1)], img[y0:y1, min(W, x1 + 2):W]):
        if strip.size == 0 or strip.shape[1] < 3:
            continue
        rows = _red_frame_mask(strip).sum(axis=1) >= 1
        best = max(best, float(rows.mean()))
    return best


def analyze(bgr, inner=None, refine=True):
    """
    Разбор кадра мини-игры.
      bgr  — кадр (можно расширенный на CFG["bar_pad"] вокруг шкалы)
      inner — (x0, y0, w, h) положение шкалы внутри кадра в реальных пикселях, None = весь кадр
    Возвращает dict: zone=(top, bottom, center) | None, fish=y | None,
             slip=доля красной рамки, green/fishmask — маски для отладки, ih=высота шкалы.
    """
    H, W = bgr.shape[:2]
    if inner is None:
        x0, y0, x1, y1 = 0, 0, W, H
    else:
        ix, iy, iw, ih = inner
        x0 = max(0, min(W - 6, int(ix)))
        y0 = max(0, min(H - 6, int(iy)))
        x1 = max(x0 + 6, min(W, x0 + int(iw)))
        y1 = max(y0 + 6, min(H, y0 + int(ih)))
    clipped, moved, cov, detected = False, (0, 0, 0, 0), 0.0, False
    if refine and CFG.get("bar_refine", True):
        # доверяем картинке, а не конфигу: шкала могла уехать (разрешение, масштаб Windows)
        # или конфиг мог быть просто «на глаз». ih и положение зоны/рыбы считаем по НЕЙ.
        sc = scale_rect(bgr, hint=(x0, y0, x1 - x0, y1 - y0))
        if sc is not None:
            sx0, sy0, sx1, sy1, cov = sc
            if (sy1 - sy0) >= 40 and (sx1 - sx0) >= 8:
                moved = (sx0 - x0, sy0 - y0, sx1 - x1, sy1 - y1)
                detected = True
                x0, y0, x1, y1 = sx0, sy0, sx1, sy1
                clipped = (x0 <= 0 and y0 <= 0) or (x1 >= W) or (y1 >= H)
    bar = np.ascontiguousarray(bgr[y0:y1, x0:x1])
    h, w = bar.shape[:2]
    hsv = cv2.cvtColor(bar, cv2.COLOR_BGR2HSV)

    # --- зелёная зона ---
    green = cv2.inRange(hsv, LOWER_GREEN, UPPER_GREEN)
    green = cv2.morphologyEx(green, cv2.MORPH_OPEN, ZONE_KERNEL)
    n_z, _, z_stats, _ = cv2.connectedComponentsWithStats(green)
    tops, bottoms = [], []
    for i in range(1, n_z):
        if z_stats[i, cv2.CC_STAT_AREA] >= MIN_ZONE_AREA and z_stats[i, cv2.CC_STAT_WIDTH] >= w * 0.6:
            tp = int(z_stats[i, cv2.CC_STAT_TOP])
            tops.append(tp)
            bottoms.append(tp + int(z_stats[i, cv2.CC_STAT_HEIGHT]) - 1)
    zone = None
    if tops:
        top, bottom = min(tops), max(bottoms)
        zone = (top, bottom, (top + bottom) / 2.0)

    # --- рыба: отклонение пикселей строки от медианы строки (не зависит от цвета рыбы) ---
    gray = cv2.cvtColor(bar, cv2.COLOR_BGR2GRAY).astype(np.float32)
    med = np.median(gray, axis=1, keepdims=True)
    dev = np.abs(gray - med)
    row_dev = dev.mean(axis=1)
    fmask = (dev > float(CFG["fish_thr"]) * 0.55).astype(np.uint8) * 255
    if str(CFG["fish_detect"]) in ("hsv", "both"):
        hsv_mask = cv2.bitwise_or(cv2.inRange(hsv, LOWER_GOLD, UPPER_GOLD), cv2.inRange(hsv, LOWER_CYAN, UPPER_CYAN))
        fmask = cv2.bitwise_or(fmask, hsv_mask) if CFG["fish_detect"] == "both" else hsv_mask
    if zone is not None:                        # 5 строк у ВЕРХНЕЙ/НИЖНЕЙ кромки зоны — это
        band = np.zeros(h, np.bool_)             # антиалиасинг края зоны, а не рыба
        for edge in (int(zone[0]), int(zone[1])):
            band[max(0, edge - 4):min(h, edge + 5)] = True
        drop = band & (row_dev <= float(CFG["fish_thr"]) * 1.5)
        if drop.any():
            fmask[drop] = 0
    fmask = cv2.morphologyEx(fmask, cv2.MORPH_CLOSE, KERNEL)
    fmask = cv2.morphologyEx(fmask, cv2.MORPH_OPEN, ZONE_KERNEL)
    n, _, st, cents = cv2.connectedComponentsWithStats(fmask)
    fish_y, best_area, best_h = None, 0, 0
    for i in range(1, n):
        area = int(st[i, cv2.CC_STAT_AREA])
        hh = int(st[i, cv2.CC_STAT_HEIGHT])
        if area >= MIN_FISH_AREA and hh >= MIN_FISH_HEIGHT and area > best_area:
            best_area, best_h, fish_y = area, hh, float(cents[i][1])
    return {"zone": zone, "fish": fish_y,
            "slip": slip_score(bgr, (x0, y0, x1, y1)) if inner is not None else 0.0,
            "green": green, "fishmask": fmask, "ih": max(1, h), "area": best_area,
            "box": (x0, y0, x1, y1), "scale": (x0, y0, x1, y1), "cov": cov,
            "moved": moved, "clipped": clipped, "detected": detected}


def autofit_bar(search=None, why=""):
    """Находит шкалу по всему экрану и ПОПРАВЛЯЕТ CFG["bar"]: калибровка могла уехать.

    Причина «бот зажимает ЛКМ и не ведёт за рыбой» часто вообще не в регуляторе, а в том,
    что окно захвата смотрит не на шкалу (сменилось разрешение/масштаб Windows, игра
    переехала на другой монитор, конфиг когда-то подогнали «на глаз»). Тогда зона и рыба
    измеряются в несуществующих координатах, и никаких коэффициентов ПИД не хватит.

    Возвращает True, если CFG["bar"] изменили (вызывающему надо пересобрать rect/inner).
    """
    if CAP is None:
        init_capture()
    m, sx, sy = CAP.mon, CAP.sx, CAP.sy
    frame = search if search is not None else None
    if frame is None:
        try:
            frame = CAP.grab_full()
        except Exception:
            return False
    if frame is None or frame.ndim < 2 or frame.shape[0] < 120:
        return False
    sc = scale_rect(frame)
    if sc is None:
        return False
    x0, y0, x1, y1, cov = sc
    w, h = x1 - x0, y1 - y0
    if w < 8 or h < 120 or h < 2.2 * w:            # чужая голубая полоска интерфейса
        return False
    # самопроверка: внутри найденной рамки зона должна читаться
    pad = max(6, int(CFG["bar_pad"]))
    crop = frame[max(0, y0 - pad):min(frame.shape[0], y1 + pad),
                 max(0, x0 - pad):min(frame.shape[1], x1 + pad)]
    if crop.shape[0] < 60 or crop.shape[1] < 12:
        return False
    in2 = (pad, pad, w, h)
    if analyze(crop, in2, refine=False)["zone"] is None:
        return False
    new = [int(round((x0 - m["left"]) / sx)), int(round((y0 - m["top"]) / sy)),
           int(round(w / sx)), int(round(h / sy))]
    if new == list(CFG["bar"]):
        return False
    old = list(CFG["bar"])
    CFG["bar"] = new
    log(t("log_bar_fit", old=old, new=new, cov=cov, why=why or "—"))
    if CFG.get("bar_autofit", True):
        save_cfg()
    else:
        CFG["bar"] = old
        log(t("log_bar_fit_off"))
        return False
    notify("nt_bar_fit", "warn")
    return True


def ensure_bar_stream(rect):
    """Запускает DXGI-поток по региону шкалы (если ещё не запущен)."""
    if CAP is None:
        init_capture()
    if CAP.streaming and CAP.stream_rect == tuple(int(round(v)) for v in
                                                   (CAP.mon["left"] + rect[0] * CAP.sx, CAP.mon["top"] + rect[1] * CAP.sy,
                                                    CAP.mon["left"] + (rect[0] + rect[2]) * CAP.sx,
                                                    CAP.mon["top"] + (rect[1] + rect[3]) * CAP.sy)):
        return True
    return CAP.start_stream(rect, CFG["capture_fps"])


def bar_frame(rect, inner):
    """Один кадр мини-игры: из потока (если идёт) или разовым DXGI/GDI-захватом."""
    if CAP is not None and CAP.streaming:
        fr, _ts = CAP.wait_frame(0.25)
        if fr is not None:
            return fr
        return None
    return grab(rect)


def wait_for_minigame(timeout):
    """Ждёт появления мини-игры (зелёная зона в шкале) в потоке DXGI.
    Поток после нахождения НЕ останавливается — его подхватит play_minigame()."""
    end = time.perf_counter() + timeout
    seen = 0
    t0 = time.perf_counter()
    last_upd = 0.0
    next_fit = 0.0
    rect, inner = bar_rects()
    ensure_bar_stream(rect)
    while time.perf_counter() < end:
        check_stop()
        now = time.perf_counter()
        if now - last_upd >= 1.0:
            set_state("st_bite", "st_bite_wait_d", "run", n=int(now - t0))
            last_upd = now
        frame = bar_frame(rect, inner)
        if frame is None:
            time.sleep(LOOP_DELAY)
            continue
        zone = analyze(frame, inner)["zone"]
        seen = seen + 1 if zone is not None else 0
        if seen >= 3:
            set_state("st_mini", "st_mini_d", "run")
            return True
        if CFG.get("bar_autofit", True) and zone is None and now - t0 > 2.0 and now > next_fit:
            next_fit = now + 2.5                       # возможно смотрим не туда — ищем шкалу
            if autofit_bar(why="wait"):                # по всему экрану (см. autofit_bar)
                rect, inner = bar_rects()
                ensure_bar_stream(rect)
        if CAP is not None and not CAP.streaming:
            time.sleep(LOOP_DELAY)
    if CAP is not None:
        CAP.stop_stream()
    return False


def play_minigame():
    """
    Мини-игра рыбалки: поток захвата + РЕЛЕ С ПРЕДСКАЗАНИЕМ ОСТАНОВА (relay_decide).
    Каждая итерация: 1 кадр -> измерение зоны/рыбы/скоростей -> предсказание точек
    останова для «жать»/«отпустить» -> явное событие ЛКМ DOWN/UP. Скважности и ШИМ
    больше нет: решение всегда двоичное и привязано к кадрам, поэтому медленный
    захват (20 к/с GDI) не ломает закон управления. При любом выходе ЛКМ
    гарантированно отпущен (max_hold + принудительный отпуск).
    """
    rect, inner = bar_rects()
    t_start = time.perf_counter()
    ensure_bar_stream(rect)
    lost_limit = max(0.03, float(CFG["lost_ms"]) / 1000.0)
    min_switch = max(0.015, float(CFG["min_switch"]))
    tau = max(0.0, float(CFG["relay_tau_ms"])) / 1000.0
    hyst0 = max(2.0, float(CFG["relay_hyst"]))
    vmax = max(150.0, float(CFG["relay_vmax"]))
    adapt = bool(CFG.get("relay_adapt", True))
    # измеренная в прошлых забросах физика зоны точнее стартовых оценок из конфига
    a_up = float(RELAY_PHYS["up"] or CFG["relay_a_up"]) if adapt else float(CFG["relay_a_up"])
    g_dn = float(RELAY_PHYS["dn"] or CFG["relay_g"]) if adapt else float(CFG["relay_g"])
    n_up = n_dn = 0
    ema_up = ema_dn = 0.0

    log(t("log_mini"))
    for _ in range(5):                       # гарантированно отпускаем ЛКМ перед стартом
        _send_mouse(MOUSEEVENTF_LEFTUP)
        time.sleep(0.01)
    global mouse_down
    mouse_down = False

    pressed = False
    last_evt = forced_until = hold_since = 0.0
    press_frames = 0                         # итераций в текущем состоянии ЛКМ (для адаптива)
    last_zone_t = time.perf_counter()
    prev_fish = prev_fish_t = None
    fish_v = fish_a = prev_raw_v = 0.0
    prev_zone = None
    prev_zone_t = 0.0
    zone_v = 0.0
    zone_v_prev = 0.0                        # фильтрованная скорость кадром ранее (для ускорения)
    dt_ema = 1.0 / 60.0
    slip = False
    prev_now = None
    slip_cnt = 0
    slip_ok_cnt = 0
    slip_events = 0
    switches = [0]                           # события ЛКМ (телеметрия «переключений/с»)
    lost = 0
    hist = CTL_VIEW["hist"]
    hist.clear()
    next_fit = 0.0                           # «найти шкалу заново» не чаще раза в 2.5 с

    def press(state, now):
        """Явная смена состояния ЛКМ с защитой от дребезга и принудительным отпуском."""
        global mouse_down
        nonlocal pressed, last_evt, hold_since, press_frames
        if state == pressed or now - last_evt < min_switch:
            return
        if state and now < forced_until:
            return
        _send_mouse(MOUSEEVENTF_LEFTDOWN if state else MOUSEEVENTF_LEFTUP)
        pressed = state
        press_frames = 0
        mouse_down = state
        last_evt = now
        switches[0] += 1
        if state:
            hold_since = now

    try:
        while True:
            check_stop()
            frame = bar_frame(rect, inner)
            now = time.perf_counter()
            if frame is None:
                if now - last_zone_t > lost_limit + 1.0:
                    break
                press(False, now)
                continue
            r = analyze(frame, inner)
            zone, fish_y = r["zone"], r["fish"]
            ih = float(r["ih"]) or 1.0

            # ---------- шкала уехала из окна захвата? лечим калибровку на лету ----------
            # Пока бот смотрит «мимо» шкалы, любой ПИД бесполезен: зона и рыба измеряются
            # в координатах, которых не существует. Признаки: шкала вообще не найдена,
            # упёрлась в край кадра (обрезана) или сместилась больше чем на треть высоты.
            if CFG.get("bar_autofit", True) and now > next_fit and (
                    not r["detected"] or r["clipped"]
                    or max(abs(int(v)) for v in r["moved"]) > 0.35 * ih):
                next_fit = now + 2.5
                if autofit_bar(why="mini-game"):
                    rect, inner = bar_rects()
                    ensure_bar_stream(rect)
                    lost = 0
                    continue

            # ---------- состояние «РЫБА СРЫВАЕТСЯ» (красная рамка) ----------
            if r["slip"] >= float(CFG["slip_thr"]):
                slip_cnt += 1
            else:
                slip_cnt = 0
            slip_ok_cnt = 0 if r["slip"] >= float(CFG["slip_thr"]) else slip_ok_cnt + 1
            if not slip and slip_cnt >= int(CFG["slip_frames"]):
                slip = True
                slip_events += 1
                set_state("st_slip", "st_slip_d", "run")
                log(t("log_slip"))
            elif slip and slip_ok_cnt >= max(2, int(CFG["slip_frames"])):
                # выход из аварии с задержкой: на 20 к/с красный контур моргает на
                # 1 кадр, и без задержки режим «мигает» в телеметрии
                slip = False
                set_state("st_mini", "st_mini_hold_d", "run")

            # ---------- зелёная зона ----------
            if zone is None:
                lost += 1
                press(False, now)
                if now - last_zone_t >= lost_limit:
                    break
                time.sleep(LOOP_DELAY if (CAP is None or not CAP.streaming) else 0)
                continue
            lost = 0
            last_zone_t = now
            zone_c = float(zone[2])

            # ---------- рыба: скорость/ускорение для упреждения ----------
            if fish_y is not None:
                if prev_fish is not None and now > prev_fish_t:
                    dt_f = now - prev_fish_t
                    raw_v = (fish_y - prev_fish) / dt_f
                    a_f, a_v = float(CFG["acc_alpha"]), float(CFG["vel_alpha"])
                    fish_a = fish_a * (1 - a_f) + ((raw_v - prev_raw_v) / dt_f) * a_f
                    fish_v = fish_v * (1 - a_v) + raw_v * a_v
                    prev_raw_v = raw_v
                prev_fish, prev_fish_t = fish_y, now
            fish_lost = prev_fish is None or (now - (prev_fish_t or 0.0)) > float(CFG["fish_timeout"])
            fish_now = None if fish_lost else (fish_y if fish_y is not None else prev_fish)

            # ---------- скорость СОБСТВЕННО зоны + шаг времени ----------
            dt = 1.0 / max(30.0, (CAP.fps if CAP else 120.0)) if prev_now is None \
                else max(1e-4, now - prev_now)                  # dt по реальным кадрам потока
            prev_now = now
            dt_ema = dt_ema * 0.7 + dt * 0.3
            # Горизонт предсказания не короче двух кадров: на медленном захвате короткий
            # горизонт выродился бы в дребезг — решение не успевает подействовать до
            # следующего кадра.
            look = min(0.40, max(float(CFG["relay_look_ms"]) / 1000.0, 2.0 * dt_ema))
            if prev_zone is not None and now > prev_zone_t:
                zv = (zone_c - prev_zone) / max(1e-4, now - prev_zone_t)
                zone_v_prev = zone_v
                zone_v = zone_v * (1 - float(CFG["vel_alpha"])) + zv * float(CFG["vel_alpha"])
            prev_zone, prev_zone_t = zone_c, now

            # ---------- цель: ЦЕНТР рыбы с упреждением по её скорости ----------
            # Зона должна висеть так, чтобы рыба была ПО СЕРЕДИНЕ зелёного прямоугольника.
            # Рыба рыскает, а кадры запаздывают, поэтому цель ставится ВПЕРЕДИ рыбы по её
            # измеренной скорости. Упреждение масштабируется горизонтом предсказания:
            # обе кандидатуры «жать/отпустить» смотрят на look секунд вперёд, и цель
            # должна показывать, ГДЕ рыба будет к тому моменту, иначе регулятор
            # устойчиво отстаёт от быстро плывущей рыбы (перманентный лаг ~v*цикл).
            # Предел упреждения — relay_lead_max * высота шкалы.
            lead_cap = max(0.0, float(CFG["relay_lead_max"])) * ih
            if fish_now is None:
                tgt = zone_c
            else:
                tgt = fish_now + max(-lead_cap, min(lead_cap, fish_v * (tau + 0.75 * look)))
                tgt = min(max(tgt, 0.0), ih - 1.0)
            err_px = zone_c - tgt                               # >0 => зона НИЖЕ рыбы => поднимать

            # ---------- адаптивная физика: измеряем разгоны зоны ----------
            # Пока ЛКМ не переключалась ≥ press_frames кадров и зона не упёрлась в край,
            # ускорение зоны равно -a_up (жмём) или +g (отпустили) — независимо от
            # направления движения (после отпускания зону вверх ещё тормозит та же g).
            # Первые кадры после переключения пропускаем: фильтр скорости ещё не
            # устоялся и завышает ускорение. Замеры сглаживаются EMA с отсечкой
            # выбросов; оценка живёт с 8-го замера и уточняется до конца мини-игры.
            press_frames += 1
            at_top = zone[0] <= max(1.0, 0.02 * ih)
            at_bottom = zone[1] >= ih - max(2.0, 0.02 * ih)
            if adapt and press_frames >= 5 and not (at_top or at_bottom) \
                    and abs(zone_v) < 0.92 * vmax:
                a_meas = (zone_v - zone_v_prev) / dt
                cand = -a_meas if pressed else a_meas
                if 150.0 < cand < 8000.0:
                    if pressed:
                        if n_up == 0:
                            ema_up = cand
                        elif cand < 3.0 * ema_up:
                            ema_up += (cand - ema_up) * 0.20
                        n_up += 1
                        if n_up >= 8:
                            a_up = ema_up
                    else:
                        if n_dn == 0:
                            ema_dn = cand
                        elif cand < 3.0 * ema_dn:
                            ema_dn += (cand - ema_dn) * 0.20
                        n_dn += 1
                        if n_dn >= 8:
                            g_dn = ema_dn

            # ---------- РЕЛЕ: предсказать останов, выбрать «жать»/«отпустить» ----------
            # Гистерезис на медленном кадре шире: решения обновляются реже, и узкий
            # гистерезис дал бы лишние переключения.
            hyst = hyst0 * max(1.0, dt_ema / 0.034)
            clamp = ""
            if fish_now is None:
                want = False                                    # рыбы не видим — не держим
            else:
                want = relay_decide(zone_c, zone_v, tgt, pressed, a_up, g_dn, vmax, look, hyst)
                if at_top:
                    want, clamp = False, "top"                  # выше кромки некуда — жать бессмысленно
                elif at_bottom and fish_now > zone[1] - 2.0:
                    want, clamp = True, "bottom"                # зона у дна, рыба ниже — держим позицию

            # ---------- защита от залипания ----------
            if want and not pressed and now < forced_until:
                want = False
            if pressed and now - hold_since > float(CFG["max_hold"]):
                want = False
                forced_until = now + float(CFG["forced_release"])
            press(want, now)

            # ---------- телеметрия для страницы «Зрение» ----------
            brake = 0.0
            if zone_v < -20.0:                                  # выбег вверх: сколько зона ещё пройдёт
                brake = min(0.5 * zone_v * zone_v / max(200.0, g_dn), 4.0 * ih)
            CTL_VIEW.update(press=pressed, err=err_px / ih, mode="emerg" if slip else "norm",
                            lost=lost, slip=slip_cnt, zone=zone_c, fish=fish_y,
                            fps=CAP.fps if CAP else 0.0, frame_ms=CAP.avg_ms if CAP else 0.0,
                            zone_v=zone_v, fish_v=(fish_v if fish_now is not None else 0.0),
                            a_up=a_up, g_dn=g_dn, brake=brake, clamp=clamp,
                            cov=float(r.get("cov", 0.0) or 0.0), detected=bool(r.get("detected", False)),
                            adapt_n=n_up + n_dn)
            hist.append((err_px / ih, 1.0 if pressed else 0.0))
            if len(hist) > 160:
                del hist[0]
    finally:
        for _ in range(5):                   # гарантированный отпуск при любом выходе
            _send_mouse(MOUSEEVENTF_LEFTUP)
            time.sleep(0.01)
        mouse_down = False
        if CAP is not None:
            CAP.stop_stream()
        CTL_VIEW.update(mode="norm", press=False, err=0.0, lost=0, slip=0)
    dur = time.perf_counter() - t_start
    log(t("log_mini_done", dur=dur, slip=slip_events, sw=switches[0] / max(0.1, dur)))
    if adapt and n_up >= 8 and n_dn >= 8:
        RELAY_PHYS["up"], RELAY_PHYS["dn"] = a_up, g_dn
        RELAY_PHYS["n"] = int(RELAY_PHYS["n"]) + min(n_up, n_dn)
        if not RELAY_PHYS["logged"]:
            RELAY_PHYS["logged"] = True
            log(t("log_adapt", up=a_up, dn=g_dn, n=RELAY_PHYS["n"]))
    return dur


# ==========================================================================
# 7. ИНВЕНТАРЬ, УДОЧКА, НАЖИВКА
# ==========================================================================
def inventory_open():
    return find("inv_header") is not None


def wait_inventory_open():
    """Инвентарь открывает ЧЕЛОВЕК: бот никогда не нажимает TAB/ESC. Если окна инвентаря
    на экране нет — статус/журнал/тост «Открой инвентарь» и ожидание (прервать F8/F10).
    Рыбалка продолжится сама, как только инвентарь появится."""
    if inventory_open():
        return True
    set_state("st_inv_wait", "st_inv_wait_d", "busy")
    log(t("log_inv_wait"))
    notify("nt_inv_wait", "warn")
    last_note = time.perf_counter()
    while not inventory_open():
        check_stop()
        if time.perf_counter() - last_note >= 20.0:      # напоминание раз в 20 с
            last_note = time.perf_counter()
            log(t("log_inv_wait"))
        nap(0.4)
    return True


# --- v1.12.0: координаты курсора для записи макро ---
# cursor_pos() возвращает позицию мыши В СИСТЕМЕ КАДРА ЗАХВАТА — те же координаты,
# что у поиска на экране и у кликов (mouse_move_abs), поэтому записанное макро
# повторяется точно, в том числе на мультимониторе.

def cursor_pos():
    """Текущая позиция курсора в координатах кадра захвата (физические пиксели
    монитора, минус его origin) — та же система координат, что у поиска и кликов."""
    from ctypes import wintypes
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    lx, ly = logical_to_physical(pt.x, pt.y)
    try:
        m = monitor()
        return (max(0, min(int(m["width"]) - 1, lx - int(m["left"]))),
                max(0, min(int(m["height"]) - 1, ly - int(m["top"]))))
    except Exception:
        return lx, ly


def _tpl_trimmed(name):
    """Шаблон с обрезанными тёмными полями: кривой ручной кроп (снят с запасом фона или
    чужого разрешения) после обрезки совпадает с иконкой 1-в-1. Кэшируется по объекту."""
    t_ = tpl(name)
    if t_ is None:
        return None
    hit = _tpl_trim_cache.get(name)
    if hit is not None and hit[0] is t_:
        return hit[1]
    ys, xs = np.where(t_ > 45)
    t2 = t_[ys.min():ys.max() + 1, xs.min():xs.max() + 1] if xs.size else t_
    if min(t2.shape) < 10:                     # обрезали слишком много — оставить как было
        t2 = t_
    _tpl_trim_cache[name] = (t_, t2)
    return t2


def _self_learn(name, frame, x, y, fw, fh, score):
    """САМООБУЧЕНИЕ: цель найдена с высоким совпадением — сохраняем её текущий вид
    с экрана как новый шаблон. Лечит кривые/чужие шаблоны: после первого же успеха
    предмет ищется по свежему снимку 1-в-1."""
    m = monitor()
    x0 = max(m["left"], int(x - fw // 2))
    y0 = max(m["top"], int(y - fh // 2))
    x1 = min(m["left"] + m["width"], x0 + fw)
    y1 = min(m["top"] + m["height"], y0 + fh)
    if x1 - x0 < 12 or y1 - y0 < 12:
        return
    try:
        os.makedirs(TPL_DIR, exist_ok=True)
        cv2.imwrite(os.path.join(TPL_DIR, name + ".png"), frame[y0:y1, x0:x1])
        _tpl_cache.pop(name, None)
        _tpl_trim_cache.pop(name, None)
        log(t("log_self_learn", name=name, s=score))
    except Exception:
        pass                                    # шаблон — не критично, не роняем поиск


def _coarse_hits(gray, t_, k=2):
    """ГРУБАЯ лестница масштабов 0.40-2.0 (шаг ~12%) на ПОЛУКАДРЕ (пирамида, быстро):
    топ-k попаданий [(score, topleft_small, f), ...] по убыванию."""
    H, W = gray.shape
    th, tw = t_.shape
    small = cv2.resize(gray, (max(1, W // 2), max(1, H // 2)), interpolation=cv2.INTER_AREA)
    coarse = []
    f = 0.40
    while f <= 2.0:
        fh, fw = int(th * f / 2), int(tw * f / 2)
        if 8 <= fh < small.shape[0] and 8 <= fw < small.shape[1]:
            t2 = cv2.resize(t_, (fw, fh), interpolation=cv2.INTER_AREA)
            r = np.nan_to_num(cv2.matchTemplate(small, t2, cv2.TM_CCOEFF_NORMED))
            _, mv, _, ml = cv2.minMaxLoc(r)
            coarse.append((float(mv), ml, f))
        f *= 1.12
    coarse.sort(key=lambda z: -z[0])
    return coarse[:k]


def _fine_match(gray, t_, entry):
    """ТОЧНАЯ стадия вокруг одного грубого попадания: масштаб уточняется шагами ~3%
    на полном кадре (ROI +-48 px). Возвращает (score, topleft, f); topleft=None, если
    ни один масштаб не влез."""
    H, W = gray.shape
    th, tw = t_.shape
    _, ml0, f0 = entry
    best = (0.0, None, f0)
    seen = set()
    for df in (0.88, 0.91, 0.94, 0.97, 1.0, 1.03, 1.06, 1.09, 1.12):
        ff = f0 * df
        k = round(ff, 3)
        if k in seen:
            continue
        seen.add(k)
        fh, fw = int(th * ff), int(tw * ff)
        if not (12 <= fh < H and 12 <= fw < W):
            continue
        t2 = cv2.resize(t_, (fw, fh), interpolation=cv2.INTER_AREA)
        cx, cy = ml0[0] * 2, ml0[1] * 2
        x0, y0 = max(0, cx - 48), max(0, cy - 48)
        x1, y1 = min(W, cx + fw + 48), min(H, cy + fh + 48)
        roi = gray[y0:y1, x0:x1]
        if roi.shape[0] < fh or roi.shape[1] < fw:
            continue
        r = np.nan_to_num(cv2.matchTemplate(roi, t2, cv2.TM_CCOEFF_NORMED))
        _, mv, _, ml = cv2.minMaxLoc(r)
        if mv > best[0]:
            best = (float(mv), (x0 + ml[0], y0 + ml[1]), ff)
    return best


def _match_scales(gray, t_, max_n=1, thr=0.60, with_f=False):
    """МУЛЬТИ-МАСШТАБНЫЙ ПОИСК шаблона по кадру — «вижу весь экран»:
    грубая лестница на полукадре (_coarse_hits) + точный подбор масштаба на полном
    кадре (_fine_match, итоговая точность масштаба ~1.5%). max_n=1 -> (score, (x, y), f);
    max_n>1 -> [(score, x, y[, f]), ...] (NMS, score >= thr)."""
    H, W = gray.shape
    th, tw = t_.shape
    if min(th, tw) < 8 or H <= th or W <= tw:
        return (0.0, None, None) if max_n == 1 else []
    coarse = _coarse_hits(gray, t_, 2)
    if not coarse:
        return (0.0, None, None) if max_n == 1 else []
    if max_n == 1:
        best = (0.0, None, None)
        for entry in coarse:
            s_, tl, ff = _fine_match(gray, t_, entry)
            if tl is not None and s_ > best[0]:
                best = (s_, (tl[0] + int(tw * ff) // 2, tl[1] + int(th * ff) // 2), ff)
        return best
    # --- несколько целей: точный масштаб по лучшему, затем NMS на полной карте ---
    _, _, fbest = _fine_match(gray, t_, coarse[0])
    fh, fw = int(th * fbest), int(tw * fbest)
    if fh >= H or fw >= W or fh < 12 or fw < 12:
        return []
    t2 = cv2.resize(t_, (fw, fh), interpolation=cv2.INTER_AREA)
    r = np.nan_to_num(cv2.matchTemplate(gray, t2, cv2.TM_CCOEFF_NORMED))
    ys, xs = np.where(r >= thr)
    pts = sorted(zip(r[ys, xs].tolist(), xs.tolist(), ys.tolist()), reverse=True)[:300]
    min_dist = max(40, int(max(fw, fh) * 0.6))
    out = []
    for s_, x, y in pts:
        if all((x - a) ** 2 + (y - b) ** 2 > min_dist ** 2 for _, a, b, *r_ in out):
            out.append((float(s_), x + fw // 2, y + fh // 2) + ((fbest,) if with_f else ()))
            if len(out) >= max_n:
                break
    return out


# --- v1.21.0: АВТО-ЗАКИД = ЗРЕНИЕ + КЛИКИ В ОКНО ИНТЕРФЕЙСА (без записи макро) ---
# Запись/повтор макро УДАЛЕНЫ (v1.21): игровой курсор живёт своей жизнью (raw-input
# клиента), поэтому любые записанные движения/точки курсора Windows ненадёжны.
# Вместо записи бот КАЖДЫЙ РАЗ находит удочку в открытом инвентаре по шаблону
# rod.png (мульти-масштабный поиск) и кликает «Использовать» — белая строка меню
# предмета стоит прямо НАД красной строкой «Выбросить». Клик ставится ПРЯМО В ОКНО
# интерфейса игры (DOM в CEF/Chromium) — курсор мыши Windows не двигается вовсе.

_WM_MOUSEMOVE, _WM_LBDOWN, _WM_LBUP = 0x0200, 0x0201, 0x0202
_WM_RBDOWN, _WM_RBUP = 0x0204, 0x0205
_MK_LBUTTON, _MK_RBUTTON = 0x0001, 0x0002


def _cef_render_hwnd():
    """HWND дочернего окна рендера интерфейса (CEF/Chromium, класс Chrome_*) у
    АКТИВНОГО окна игры: инвентарь и меню «Использовать» — это DOM, и клик можно
    поставить ПРЯМО в это окно сообщением Windows, не двигая курсор мыши вовсе.
    None — окно не найдено (клик уйдёт курсором, запасной путь)."""
    try:
        u32 = ctypes.windll.user32
        top = u32.GetForegroundWindow()
        if not top:
            return None
        found = []
        proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def on_child(h, _lp):
            name = ctypes.create_unicode_buffer(64)
            u32.GetClassNameW(h, name, 64)
            if name.value.startswith("Chrome_"):
                found.append(h)
                return False
            return True

        u32.EnumChildWindows(top, proto(on_child), 0)
        return found[0] if found else None
    except Exception:
        return None


def _cef_click_at(hwnd, fx, fy, btn, down):
    """Одна фаза клика ПРЯМО В ОКНО интерфейса игры: координата берётся из КАДРА
    (та же система, что у поиска удочки), переводится в клиент окна, затем
    WM_MOUSEMOVE + нажатие/отпускание кнопки. Курсор мыши Windows НЕ двигается.
    True — окно приняло сообщение."""
    try:
        from ctypes import wintypes
        m = monitor()
        sx, sy = int(m["left"]) + int(fx), int(m["top"]) + int(fy)
        u32 = ctypes.windll.user32
        pt = wintypes.POINT(sx, sy)
        if not u32.ScreenToClient(hwnd, ctypes.byref(pt)):
            return False
        lp = ((int(pt.y) & 0xFFFF) << 16) | (int(pt.x) & 0xFFFF)
        rdn, rup = (_WM_RBDOWN, _WM_RBUP) if btn == "r" else (_WM_LBDOWN, _WM_LBUP)
        mk = _MK_RBUTTON if btn == "r" else _MK_LBUTTON
        u32.PostMessageW(hwnd, _WM_MOUSEMOVE, 0, lp)
        return bool(u32.PostMessageW(hwnd, rdn if down else rup, mk if down else 0, lp))
    except Exception:
        return False


def _ui_click(fx, fy, btn, down, pre_move=True):
    """Одна фаза клика по интерфейсу: ПРЯМО В ОКНО DOM (ui_click_window, курсор
    стоит на месте) либо, если окно не найдено, курсором (запасной путь).
    pre_move=False — курсор УЖЕ стоит в нужной точке (сервопривод 1.24), не
    передёргиваем его: лишний абсолютный move уводит игровой курсор до нажатия."""
    hwnd = _cef_render_hwnd() if CFG.get("ui_click_window", True) else None
    if hwnd is not None and _cef_click_at(hwnd, int(fx), int(fy), btn, down):
        return "win"
    if pre_move:
        try:
            mouse_move_abs(int(fx), int(fy))
        except Exception:
            pass
    if btn == "r":
        _send_mouse(MOUSEEVENTF_RIGHTDOWN if down else MOUSEEVENTF_RIGHTUP)
    else:
        _send_mouse(MOUSEEVENTF_LEFTDOWN if down else MOUSEEVENTF_LEFTUP)
    return "cur"


def _game_cursor(frame):
    """Детектор ИГРОВОГО курсора (v1.23): клиент рисует на кадре белую стрелку
    ~14×19 px с чёрной обводкой. Ищем компактный почти-белый вертикальный кластер
    в ЛЕВОЙ панели (x < 40% ширины — там слоты инвентаря и меню предмета),
    отбрасывая крупные/плоские пятна (кнопки, ползунки, текст тултипа) и всю
    правую половину экрана (там белые элементы боевого UI ловят детектор).
    (x, y) центра стрелки или None."""
    try:
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        m = (g > 225).astype(np.uint8)
        n, _lab, stats, cent = cv2.connectedComponentsWithStats(m, 8)
        best = None
        H, W = frame.shape[:2]
        x_lim = int(W * 0.40)                # инвентарь/меню — левая панель
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if 6 <= w <= 26 and 9 <= h <= 34 and h > w and area >= 25:
                fill = area / float(w * h)
                if 0.25 <= fill <= 0.75 and y < H * 0.85 and x + w <= x_lim:
                    if best is None or area > best[4]:
                        best = stats[i]
        if best is None:
            return None
        x, y, w, h, area = (int(v) for v in best)
        return (x + w // 2, y + h // 2)
    except Exception:
        return None


def _drive_game_cursor(hwnd, tx, ty, btn="r", timeout=2.6):
    """ЗАМКНУТЫЙ КОНТУР (v1.23): ведём ИГРОВОЙ курсор в цель (tx, ty) — как человек.
    Каждый шаг: ставим КУРСОР WINDOWS в цель (raw-input игры двигает её игровой
    курсор), берём кадр, находим игровой курсор детектором, считаем остаточный
    промах и КОМПЕНСИРУЕМ его следующим шагом. Когда курсор игры стоит на цели
    (или шаги кончились) — клик. Возвращает (okc, (wx, wy), dist), где (wx, wy) —
    последняя точка КУРСОРА WINDOWS (компенсированная), dist — последнее
    расстояние от ИГРОВОГО курсора до цели (None, если курсор так и не увидели):
    если dist мал, клик делаем БЕЗ передёргивания курсора — он уже там, где надо,
    и любой абсолютный move успевает увести игровой курсор до нажатия."""
    w = getattr(ctypes, "windll", None)
    if w is None:                         # не-Windows среда (тест-раннер) — сервопривод недоступен
        return (False, None, None)
    u32 = w.user32
    m = monitor()
    ox, oy = int(m["left"]), int(m["top"])
    t_end = time.perf_counter() + timeout
    cx = cy = None                            # где ИГРОВОЙ курсор сейчас (по кадру)
    off_x = off_y = 0.0                       # ошибка: курсор Windows vs курсор игры
    for _step in range(10):
        if cx is not None and abs(tx - cx) <= 6 and abs(ty - cy) <= 6:
            break                             # курсор игры на цели
        # хотим игровой курсор в (tx, ty): курсор Windows = цель + накопл. ошибка
        off_x = max(-160.0, min(160.0, off_x))   # ошибка не должна уйти в бесконечность
        off_y = max(-160.0, min(160.0, off_y))
        wx = int(max(0, min(4000, tx + off_x)))
        wy = int(max(0, min(4000, ty + off_y)))
        u32.SetCursorPos(ox + wx, oy + wy)
        nap(0.12)                             # игре/кадру нужно время
        fr = grab()
        cur = _game_cursor(fr) if fr is not None and fr.size else None
        if cur:
            nx_, ny_ = int(cur[0]), int(cur[1])
            if _step and nx_ == cx and ny_ == cy:
                break                         # курсор игры не отозвался — дальше ждать глупо
            cx, cy = nx_, ny_
            off_x, off_y = float(wx - cx), float(wy - cy)   # накопленная ошибка
            log(t("log_drive_step", x=cx, y=cy))
        if time.perf_counter() >= t_end:
            break
    okc = cx is not None and abs(tx - cx) <= 14 and abs(ty - cy) <= 14
    dist = None if cx is None else int(max(abs(tx - cx), abs(ty - cy)))
    return okc, (wx, wy), dist


def _aim_click(hwnd, tx, ty):
    """Сервопривод (v1.23/1.24) + выбор точки клика. Возвращает (x, y, in_place):
    in_place=True — Windows-курсор УЖЕ припаркован в компенсированной точке и
    игровой курсор почти на цели (<=34 px): клик делаем БЕЗ абсолютного move,
    иначе игра успевает увести свой курсор до нажатия (урок поля 1.23)."""
    if hwnd:
        okc, _w, _d = _drive_game_cursor(hwnd, tx, ty)
        if not okc:
            log(t("log_drive_fail"))
        return (int(tx), int(ty), False)
    okc, w, d = _drive_game_cursor(None, tx, ty)
    if okc and w is not None:
        return (int(w[0]), int(w[1]), True)
    if d is not None and d <= 34 and w is not None:
        return (int(w[0]), int(w[1]), True)      # курсор игры близко: не трогаем
    log(t("log_drive_fail"))
    return (int(tx), int(ty), False)


def _red_menu_row(frame):
    """Красная строка меню предмета («Выбросить»): строка с плотной насыщенно-красной
    заливкой. Возвращает (x_центр, y) строки или None. «Использовать» — белая строка
    прямо НАД красной (клик экипировки ставится на строку выше, см. vision_equip)."""
    r = frame[:, :, 2].astype(np.int16)
    g = frame[:, :, 1].astype(np.int16)
    b = frame[:, :, 0].astype(np.int16)
    mask = (r > 110) & (r - np.maximum(g, b) > 60)
    if not mask.any():
        return None
    rows = mask.sum(axis=1)
    y = int(np.argmax(rows))
    if int(rows[y]) < 40:                    # узкая красная полоска — не меню предмета
        return None
    xs = np.where(mask[y])[0]
    return (int((int(xs[0]) + int(xs[-1])) // 2), y)


_CLAHE = None


def _sobel(g):
    """Карта градиентов (краёв): инвариантна к ровному сдвигу яркости — тёмная
    сцена/низкая гамма монитора не меняют края, поэтому матч по краям находит
    удочку там, где прямое сравнение проваливается (v1.22)."""
    try:
        gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
        m = cv2.magnitude(gx, gy)
        cv2.normalize(m, m, 0, 255, cv2.NORM_MINMAX)
        return m.astype(np.uint8)
    except Exception:
        return g


def _norm_gray(g):
    """Нормализация освещения (CLAHE по яркости): ночь/гамма монитора/подсветка слота
    под курсором перестают влиять на сравнение с шаблоном — «бедный ИИ», который
    делает матч инвариантным к условиям съёмки (v1.22)."""
    global _CLAHE
    try:
        if _CLAHE is None:
            _CLAHE = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return _CLAHE.apply(g)
    except Exception:
        return g


_ROD_TPL_CACHE = []


def _rod_templates():
    """Эталоны удочки [rod, rod2] (обрезанные, сырые; кэшируются). rod2 — второй
    эталон (другая подсветка/скин); его можно переснять на «Зрении»
    («Шаблон: rod2»), как и основной."""
    if not _ROD_TPL_CACHE:
        for n in ("rod", "rod2"):
            t_ = _tpl_trimmed(n)
            if t_ is not None:
                _ROD_TPL_CACHE.append((n, t_))
    return _ROD_TPL_CACHE


def vision_equip():
    """ЗРИТЕЛЬНАЯ ЭКИПИРОВКА БЕЗ ЗАПИСИ (v1.21): в ОТКРЫТОМ инвентаре бот сам находит
    удочку (шаблон rod.png, мульти-масштабный поиск), делает ПКМ по ней, ждёт меню
    предмета и кликает «Использовать» (белая строка НАД красной «Выбросить»).
    Клик — прямо в окно интерфейса игры (курсор Windows не двигается); окно не
    найдено — курсором. False — удочка/меню не найдены (сессия остановится с
    причиной no_macro — «удочка не найдена в инвентаре»)."""
    if not inventory_open():
        log(t("nt_equip_need_inv"))
        return False
    tpls = _rod_templates()
    if not tpls:
        log(t("log_bait_notpl"))             # тот же смысл: нет шаблона в templates/
        return False
    frame = grab()
    if frame is None or frame.size == 0:
        log(t("log_equip_rod_nofind"))
        return False
    # AI-режим (v1.24): детектор ONNX ищет удочку сам; нет модели/не нашёл —
    # автоматический спуск в шаблонный каскад (поле не ломается).
    ai_hit = ai_rod_find(frame)
    if str(CFG.get("ai_mode", "legacy")) == "ai" and ai_hit is not None:
        rx, ry = int(ai_hit[0]), int(ai_hit[1])
        log(t("log_ai_rod", x=rx, y=ry, s=ai_hit[2]))
        hwnd = _cef_render_hwnd()
        ax, ay, inplace = _aim_click(hwnd, rx, ry)
        how = _ui_click(ax, ay, "r", True, pre_move=not inplace)
        _ui_click(ax, ay, "r", False, pre_move=not inplace)
        log(t("log_equip_win") if how == "win" else t("log_equip_cur"))
        row, fr_menu = _wait_menu(1.5)
        if row is None:
            log(t("log_use_nofind"))
            return False
        return _finish_equip(row, fr_menu, hwnd)
    thr = float(CFG.get("rod_thr", 0.80))
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    best = (0.0, None)                       # (скор, точка) из каскада ниже
    for mk, gi in ((None, g),                # 1) прямое сравнение (обычный свет)
                   (_sobel, _sobel(g)),      # 2) края (тьма/гамма — инвариант)
                   (_norm_gray, _norm_gray(g))):  # 3) выравнивание контраста
        for _n, t_ in tpls:
            s_, pt, _f = _match_scales(gi, t_ if mk is None else mk(t_),
                                       max_n=1, thr=0.0)
            if pt and float(s_ or 0) > best[0]:
                best = (float(s_), pt)
        if best[0] >= thr:                   # нашли — дальнейшие режимы не нужны
            break
    if best[1] is None or best[0] < thr:
        log(t("log_equip_rod_nofind"))
        try:                                 # кадр момента промаха — для разбора
            cv2.imwrite(os.path.join(BASE_DIR, "miss_rod.png"), frame)
            log(t("log_equip_miss"))
        except Exception:
            pass
        return False
    rx, ry = int(best[1][0]), int(best[1][1])
    log(t("log_equip_rod", x=rx, y=ry, s=best[0]))
    hwnd = _cef_render_hwnd()
    row, fr_menu = None, frame
    for attempt in (1, 2):                   # поле 1.23: меню могло не открыться —
        ax, ay, inplace = _aim_click(hwnd, rx, ry)   # повторяем ПКМ вторым заходом
        how = _ui_click(ax, ay, "r", True, pre_move=not inplace)
        _ui_click(ax, ay, "r", False, pre_move=not inplace)
        log(t("log_equip_win") if how == "win" else t("log_equip_cur"))
        row, fr_menu = _wait_menu(1.5)
        if row is not None:
            break
        if attempt < 2:
            log(t("log_equip_retry", n=attempt))
            nap(0.25)
    if row is None:
        log(t("log_use_nofind"))
        return False
    return _finish_equip(row, fr_menu, hwnd)


def _wait_menu(sec=1.5):
    """Ждать красную строку меню предмета. -> (row, frame) или (None, None)."""
    t_end = time.perf_counter() + sec
    while time.perf_counter() < t_end:
        fr = grab()
        if fr is not None and fr.size:
            row = _red_menu_row(fr)
            if row is not None:
                return row, fr
        nap(0.05)
    return None, None


def _finish_equip(row, fr, hwnd):
    """Клик «Использовать» (белая строка НАД красной) — финал vision_equip."""
    ux, uy = int(row[0]), max(0, int(row[1]) - max(18, int(fr.shape[0] * 0.030)))
    ax, ay, inplace = _aim_click(hwnd, ux, uy)
    _ui_click(ax, ay, "l", True, pre_move=not inplace)
    _ui_click(ax, ay, "l", False, pre_move=not inplace)
    log(t("log_use_found", ux=ux, uy=uy))
    nap(float(CFG.get("after_equip_delay", 1.2)))
    return True


def bait_check():
    """Пассивная проверка наживки — СКАНЕРОМ ВСЕГО ЭКРАНА (v1.10): все стеки наживки
    на экране находятся мульти-масштабным поиском (порог THR["bait"], NMS разделяет
    стеки), а не одним совпадением в жёсткой области. Только если инвентарь СЕЙЧАС
    открыт (бот сам его не открывает). Результат — ТОЛЬКО в журнал: сессию наживка
    не останавливает. True — найдена, False — нет, None — инвентарь закрыт."""
    if not inventory_open():
        log(t("log_bait_skip"))
        return None
    t_ = _tpl_trimmed("bait")
    if t_ is None:
        log(t("log_bait_notpl"))
        return None
    frame = grab()
    if frame is None or frame.size == 0:
        log(t("log_bait_notpl"))
        return None
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    bait_thr = max(float(THR.get("bait", 0.90)), 0.93)   # весь экран: круглые предметы
    hits = _match_scales(gray, t_, max_n=24, thr=bait_thr, with_f=True)  # в игре дают шум
    if hits and hits[0][0] < 0.99 and CFG.get("tpl_selflearn", True):
        # лучший стек — свежий эталон наживки (кривой шаблон чинится сам)
        s0, x0, y0, f0 = hits[0]
        _self_learn("bait", frame, x0, y0,
                    max(8, int(t_.shape[1] * f0)), max(8, int(t_.shape[0] * f0)), s0)
    present = len(hits) > 0
    STATS["checks"] += 1
    log(t("log_bait", state=t("bait_yes") if present else t("bait_no"), n=len(hits)))
    return present


# ==========================================================================
# 8. РЫБАЛКА (главный цикл)
# ==========================================================================
REASON_KEYS = ("user", "no_bait", "no_bite", "no_macro", "error")


def reason_text(key, detail=""):
    txt = t("reason_" + key) if key in REASON_KEYS else (key or "")
    return txt + (f": {detail}" if detail else "")


def cast():
    # Перед забросом гарантированно отпускаем ЛКМ
    for _ in range(3):
        _send_mouse(MOUSEEVENTF_LEFTUP)
    global mouse_down
    mouse_down = False
    nap(CFG.get("cast_delay", 0.8))
    log(t("log_cast"))
    _send_mouse(MOUSEEVENTF_LEFTDOWN)
    nap(0.18)                                  # держим достаточно долго, чтобы игра зарегистрировала
    _send_mouse(MOUSEEVENTF_LEFTUP)
    nap(0.3)
    log(t("log_cast_done"))


def fishing_run():
    # Схема заброса — ВИЗУАЛЬНОЕ НАВЕДЕНИЕ (v1.9): удочка и пункт «Использовать» ищутся
    # на кадре экрана (мульти-масштабный шаблон rod.png + красная строка «Выбросить»),
    # курсор плавно ведётся к найденной цели. Жёстких координат нет.
    STATS.update({"catches": 0, "t0": time.time(), "t_end": None, "mg": [], "checks": 0})

    # Если автозакидывание ВЫКЛЮЧЕНО — бот полностью отключён от инвентаря и забросов:
    # никакой TAB/ПКМ/ЛКМ, только наблюдение за шкалой и мини-игра. Рыбачит человек.
    if not CFG["auto_cast"]:
        log(t("log_mode_mini_only"))
        while True:
            check_stop()
            set_state("st_await", "st_await_d", "run")
            if wait_for_minigame(999):
                set_state("st_mini", "st_mini_hold_d", "run")
                dur = play_minigame()
                STATS["catches"] += 1
                STATS["mg"].append(dur)
                log(t("log_caught", n=STATS["catches"], dur=dur))
                if CFG["sound_catch"]:
                    play("catch")
                nap(CFG["post_catch_delay"])
            if CAP is not None:
                CAP.stop_stream()               # сброс потока между рыбами

    # ---------- режим с автозакидыванием ----------
    set_state("st_prepare", "st_prepare_d", "busy")
    no_bite, first = 0, True
    while True:
        check_stop()
        if first or CFG["cast_after_catch"]:
            # Инструкция: поймал -> пауза (post_catch_delay уже выдержана) -> плавно
            # навести курсор на НАЙДЕННУЮ удочку, ОДНО ПКМ -> пауза -> «Использовать»
            # (найдено по красной строке меню, одна ЛКМ) -> заброс.
            set_state("st_cast", "st_cast_d", "busy")
            if first and not CFG["equip_on_start"]:
                log(t("log_rod_skip"))          # удочка уже в руках — начинаем с заброса
            else:
                wait_inventory_open()           # инвентарь открывает человек — ждём
                if not vision_equip():          # зрительная экипировка (v1.21, без записи)
                    return "no_macro"           # удочка/меню не найдены — стоп с причиной
            cast()
        first = False
        set_state("st_bite", "st_bite_d", "run")
        if wait_for_minigame(CFG["bite_timeout"]):
            set_state("st_mini", "st_mini_d", "run")
            dur = play_minigame()
            STATS["catches"] += 1
            STATS["mg"].append(dur)
            log(t("log_caught", n=STATS["catches"], dur=dur))
            if CFG["sound_catch"]:
                play("catch")
            no_bite = 0
            set_state("st_caught", "st_caught_d", "run")
            nap(CFG["post_catch_delay"])
        else:
            no_bite += 1
            log(t("log_no_bite", t=CFG["bite_timeout"], k=no_bite, lim=CFG["no_bite_limit"]))
            set_state("st_check", "st_check_nobite_d", "busy")
            bait_check()                        # только журнал, сессию не останавливает
            if no_bite >= CFG["no_bite_limit"]:
                return "no_bite"
            first = True


def bot_thread():
    global GAME_TITLE
    reason, detail = "error", ""
    try:
        STATE["running"] = True
        EVENTS.put(("run", True))
        ai_start()                                    # AI-наблюдение не мешает fishing_run
        set_state("st_starting", "st_starting_d", "busy")
        GAME_TITLE = ""
        learn_game_window()
        log(t("log_start"))
        notify("nt_started", "ok")
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
        ai_stop()                                     # конвейер наблюдения гасим вместе с сессией
        if CAP is not None:
            try:
                CAP.stop_stream()
            except Exception:
                pass
        STATS["t_end"] = time.time()
        TOTAL["catches"] += STATS["catches"]
        TOTAL["sessions"] += 1
        TOTAL["best"] = max(TOTAL["best"], STATS["catches"])
        TOTAL["last_reason_key"], TOTAL["last_reason_detail"] = reason, detail
        save_totals()
        text = reason_text(reason, detail)
        log(t("log_stop", reason=text, n=STATS["catches"]))
        set_state("st_stopped", text[:80],
                  "error" if reason in ("error", "no_bite", "no_macro") else "idle")
        STATE["running"] = False
        notify("nt_finished", "warn" if reason in ("error", "no_bite", "no_macro") else "ok", text=text[:60])
        if CFG["sound_end"]:
            play("alert" if reason in ("error", "no_bite", "no_macro") else "end")
        EVENTS.put(("run", False))


def start_bot():
    global worker
    if worker is not None and worker.is_alive():
        return
    stop_event.clear()
    worker = threading.Thread(target=bot_thread, daemon=True)
    worker.start()


def stop_bot():
    stop_event.set()


def toggle_bot():
    if worker is not None and worker.is_alive():
        stop_bot()
    else:
        start_bot()


def panic():
    stop_event.set()
    release_all()


def dump_debug():
    """F9: снимок экрана + разбор шкалы + маски + совпадения шаблонов."""
    try:
        cv2.imwrite(os.path.join(BASE_DIR, "debug_screen.png"), grab())
        rect, inner = bar_rects()
        bgr = grab(rect)
        r = analyze(bgr, inner)
        bx0, by0, bx1, by1 = r["box"]
        bar = bgr[by0:by1, bx0:bx1]                     # маски рассчитаны внутри шкалы
        sheet = np.hstack([bar, cv2.cvtColor(r["green"], cv2.COLOR_GRAY2BGR),
                           cv2.cvtColor(r["fishmask"], cv2.COLOR_GRAY2BGR)])
        cv2.imwrite(os.path.join(BASE_DIR, "debug_bar.png"),
                    cv2.resize(sheet, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
        parts = []
        for n in TEMPLATE_NAMES:
            s = best_score(n)
            parts.append(f"{n}: {'—' if s is None else f'{s:.2f}/{THR[n]:.2f}'}")
        tail = f" | slip={r['slip']:.2f} | {CAP.backend} {CAP.fps:.0f}fps" if CAP else ""
        log(t("log_debug", parts=", ".join(parts), zone=r["zone"], fish=r["fish"]) + tail)
        notify("nt_snapshot", "ok")
    except Exception as e:
        log(t("log_debug_fail", e=e))


CAPTURE = {"rod": (-34, -33, 68, 68), "bait": (-39, -39, 67, 57)}


def capture_template(name):
    """Через 4 с снимает шаблон вокруг курсора (для rod/bait: навести на центр иконки в инвентаре)."""
    from ctypes import wintypes
    for i in (4, 3, 2, 1):
        notify("nt_tpl_countdown", "ok", name=name, i=i)
        time.sleep(1.0)
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    px, py = logical_to_physical(pt.x, pt.y)          # координаты курсора — логические, захват — физический
    ox, oy, w, h = CAPTURE.get(name, (-14, -14, 28, 28))
    sx, sy = scale()
    os.makedirs(TPL_DIR, exist_ok=True)
    img = grab_px(px + ox * sx, py + oy * sy, w * sx, h * sy)
    cv2.imwrite(os.path.join(TPL_DIR, name + ".png"), img)
    _tpl_cache.pop(name, None)
    _tpl_trim_cache.pop(name, None)
    notify("nt_tpl_saved", "ok", name=name)


# ==========================================================================
# 8B. AI-ЗРЕНИЕ (v1.24): ЛОКАЛЬНЫЙ КОНВЕЙЕР НАБЛЮДЕНИЯ (ONNX CPU, офлайн)
# ==========================================================================
# Архитектурное правило: конвейер ниже только СМОТРИТ на кадры и публикует
# события (ai/event_bus.py). Он НЕ двигает мышь и НЕ жмёт клавиши — все решения
# и ввод остаются легаси-контроллеру. onnxruntime/rapidocr НЕобязательны:
# без них (и без моделей) работает всё прежнее зрение, а AI-страница честно
# пишет «модель не установлена». Модели никогда не скачиваются сами.
from ai.frame_router import Frame                          # noqa: E402
from ai import pipeline as _ai_pipeline                    # noqa: E402
from ai import config as _aicfg                            # noqa: E402
from ai.detector import make_detector as _ai_make_detector  # noqa: E402
from ai.model_manager import ModelManager as _ai_mm        # noqa: E402
from ai.recorder import SessionRecorder as _AiRec          # noqa: E402
from ai.dataset_export import export_session as _ai_export_session  # noqa: E402

_AI = {"pipe": None, "fid": 0, "det": None, "det_status": "", "det_tried": False,
       "status": {}, "last_log": {}, "last_inv": 0.0}
# события, дублируемые в журнал (переходы и неизвестное — не каждый чих)
_AI_LOG_TYPES = ("ui.inventory_opened", "ui.inventory_closed", "fishing.minigame_started",
                 "game.screen_transition", "game.unknown_visual_change")


def _ai_frame_source():
    """Кадр + метаданные из ЕДИНОГО легаси-захвата (второй процесс захвата
    не запускается). None — кадра нет (CAP не поднят)."""
    if CAP is None:
        return None
    img = grab()
    if img is None or img.size == 0:
        return None
    _AI["fid"] += 1
    m = monitor()
    sx, sy = scale()
    return Frame(_AI["fid"], time.time(), img, m, sx, sy,
                 backend=getattr(CAP, "backend", ""), fps=float(getattr(CAP, "fps", 0.0)))


def _ai_hints():
    """Дешёвые легаси-подсказки для классификатора состояний: ключ STATE +
    инвентарь по шаблону (не чаще 1 р/с — это самое дорогое в подсказках)."""
    h = {"running": bool(STATE.get("running")), "focus": None, "inventory": False,
         "minigame": False, "waiting": False, "catch_result": False}
    key = str(STATE.get("title_key", ""))
    h["minigame"] = key in ("st_mini", "st_slip")
    h["waiting"] = key in ("st_await", "st_bite", "st_cast", "st_prepare")
    h["catch_result"] = key in ("st_caught",)
    try:
        h["focus"] = bool(game_focused())
    except Exception:
        h["focus"] = None
    if time.time() - _AI["last_inv"] > 1.0:
        _AI["last_inv"] = time.time()
        try:
            h["inventory"] = (best_score("inv_header") or 0.0) >= THR["inv_header"]
        except Exception:
            pass
    return h


def _ai_on_event(ev):
    """Подписчик шины: несколько проверенных типов — строкой в журнал (с кулдауном)."""
    if ev.type not in _AI_LOG_TYPES:
        return
    last = _AI["last_log"].get(ev.type, 0.0)
    if time.time() - last < 2.0:
        return
    _AI["last_log"][ev.type] = time.time()
    log(t("log_ai_ev", typ=ev.type, conf=ev.confidence))


def ai_start():
    """Запуск конвейера наблюдения (если ai_enabled). Никогда не падает."""
    if not CFG.get("ai_enabled", False):
        return
    pipe = _AI["pipe"]
    if pipe is not None and getattr(pipe, "_thr", None) and pipe._thr and pipe._thr.is_alive():
        return
    try:
        pipe = _ai_pipeline.VisionPipeline(
            _ai_frame_source, _ai_hints, BASE_DIR,
            cfg_getter=lambda: _aicfg.ai_cfg(CFG),
            log_cb=lambda s: log(s))
        pipe.bus.subscribe(_ai_on_event)
        pipe.start()
        _AI["pipe"] = pipe
        log(t("log_ai_on", mode=CFG.get("ai_mode", "legacy")))
    except Exception as e:
        _AI["pipe"] = None
        log(t("log_ai_fail", e="%s: %s" % (type(e).__name__, e)))


def ai_stop():
    pipe = _AI["pipe"]
    if pipe is None:
        return
    _AI["pipe"] = None
    try:
        pipe.stop()
        log(t("log_ai_off"))
    except Exception:
        pass


def ai_status():
    """Снимок статуса для GUI (Tk-поток). Без конвейера — честный 'off'."""
    pipe = _AI["pipe"]
    if pipe is None:
        return {"state": "off", "detector": "", "model": "—",
                "det_rt": "off" if not CFG.get("ai_enabled", False) else "not_started",
                "det_ms": 0, "ocr_ms": 0, "change_ms": 0, "frames": 0, "dropped": 0,
                "dup": 0, "events": 0, "unknown": 0, "errors": 0, "transitions": 0,
                "bus": {}, "diag": {}, "state_screen": "—", "state_conf": 0.0}
    try:
        return pipe.get_status()
    except Exception:
        return {"state": "off"}


def ai_restart():
    """Перезапуск конвейера (кнопка GUI/тумблер). Не бросает исключений: клик
    интерфейса не должен упасть из-за stop_event/Stopped фоновых потоков."""
    try:
        ai_stop()
        ai_start()
    except Exception:
        pass


# ---------------------------------------------------------------- запись сессий
# «ИИ учится на твоих действиях» (v1.25): пока ты играешь руками, рекордер пишет
# кадры + твои клики (координата клика = готовая метка объекта!) + клавиши + разбор
# мини-игры с состоянием ЛКМ. Потом «Собрать датасет» превращает это в YOLO-набор
# (docs/LEARNING.md). Рекордер ТОЛЬКО пишет файлы — ввод не трогает.
_REC = {"rec": None, "keys": []}
_REC_HOOK = {"on": False}


def _ai_rec_frame_source():
    """Кадр для рекордера: тот же ЕДИНЫЙ захват; CAP поднимаем при нужде."""
    if CAP is None:
        try:
            init_capture()
        except Exception:
            return None
    return _ai_frame_source()


def _ai_input_poll():
    """Кнопки мыши + курсор ОС (экранные физические px) — честный опрос без хуков."""
    w = getattr(ctypes, "windll", None)
    if w is None:
        return {"lmb": False, "rmb": False, "x": None, "y": None}
    u32 = w.user32
    lmb = bool(u32.GetAsyncKeyState(0x01) & 0x8000)
    rmb = bool(u32.GetAsyncKeyState(0x02) & 0x8000)
    try:
        from ctypes import wintypes
        pt = wintypes.POINT()
        u32.GetCursorPos(ctypes.byref(pt))
        return {"lmb": lmb, "rmb": rmb, "x": int(pt.x), "y": int(pt.y)}
    except Exception:
        return {"lmb": lmb, "rmb": rmb, "x": None, "y": None}


def _ai_key_events():
    """Нажатия клавиш, накопленные хуком keyboard (ставится на время записи)."""
    out, _REC["keys"] = _REC["keys"], []
    return out


def _ai_keys_hook(on):
    """Глобальный хук клавиш на время записи (клавиатура уже зависимость бота)."""
    kb = globals().get("keyboard")
    hook = getattr(kb, "hook", None) if kb else None
    unhook = getattr(kb, "unhook", None) if kb else None
    if not hook or _REC_HOOK.get("busy"):
        return
    try:
        if on and not _REC_HOOK.get("on"):
            def _h(e):
                try:
                    if getattr(e, "event_type", "") == getattr(kb, "KEY_DOWN", "down"):
                        _REC["keys"].append((time.time(), getattr(e, "name", "?")))
                except Exception:
                    pass
            hook(_h)
            _REC_HOOK["on"] = True
            _REC_HOOK["fn"] = _h
        elif not on and _REC_HOOK.get("on"):
            unhook(_REC_HOOK.get("fn"))
            _REC_HOOK["on"] = False
    except Exception:
        _REC_HOOK["on"] = False


def _ai_rec_analyzer(bgr):
    """Разбор мини-игры на полном кадре (для imitation-лога): зона/рыба/срыв."""
    rect, inner = bar_rects()
    sx, sy = scale()
    H, W = bgr.shape[:2]
    x0 = max(0, int(rect[0] * sx))
    y0 = max(0, int(rect[1] * sy))
    x1 = min(W, x0 + int(rect[2] * sx))
    y1 = min(H, y0 + int(rect[3] * sy))
    if x1 - x0 < 10 or y1 - y0 < 10:
        return None
    crop = bgr[y0:y1, x0:x1]
    r = analyze(crop, inner)
    if not r:
        return None
    return {"zone": r.get("zone"), "fish": r.get("fish"), "slip": r.get("slip")}


def ai_record_toggle():
    """Кнопка «Записать сессию»: старт/стоп записи твоей игры (бот не управляет)."""
    rec = _REC["rec"]
    if rec is not None and rec.status()["recording"]:
        st = rec.stop()
        _ai_keys_hook(False)
        log(t("log_rec_off", f=st["frames"], c=st["clicks"], mb=st["mb"]))
        return False
    a = _aicfg.ai_cfg(CFG)
    _REC["rec"] = _AiRec(
        _ai_rec_frame_source, _ai_input_poll, os.path.join(BASE_DIR, "sessions"),
        fps=a["ai_rec_fps"], quality=a["ai_rec_quality"], max_width=a["ai_rec_max_width"],
        max_mb=a["ai_rec_max_mb"], cursor_fn=_game_cursor, analyzer_fn=_ai_rec_analyzer,
        key_events=_ai_key_events)
    if not _REC["rec"].start():
        log(t("log_rec_fail", e="уже идёт запись"))
        return True
    if a["ai_rec_keys"]:
        _ai_keys_hook(True)
    log(t("log_rec_on", fps=a["ai_rec_fps"], mb=a["ai_rec_max_mb"]))
    return True


def ai_record_status():
    """Статус записи для GUI; вне сессии — None."""
    rec = _REC["rec"]
    if rec is None:
        return None
    try:
        return rec.status()
    except Exception:
        return None


def ai_record_export():
    """Кнопка «Собрать датасет»: последняя сессия -> YOLO-набор (dataset_out/)."""
    base = os.path.join(BASE_DIR, "sessions")
    cands = sorted((os.path.join(base, n) for n in (os.listdir(base) if os.path.isdir(base) else [])
                    if n.startswith("rec_")), key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
    if not cands:
        log(t("log_ds_nosession"))
        return None
    try:
        r = _ai_export_session(cands[-1], os.path.join(BASE_DIR, "dataset_out"))
        log(t("log_ds_ok", f=r["frames"], c=r["clicks"], o=r["objects"],
              b=r["background"], path=r["out"]))
        return r
    except Exception as e:
        log(t("log_ds_fail", e="%s: %s" % (type(e).__name__, e)))
        return None


def ai_detector():
    """Ленивый детектор для ЭКИПИРОВКИ (режимы ai/hybrid). Отдельный от конвейера:
    VisionPipeline может быть выключен, а поиск удочки по AI — нужен."""
    if _AI["det_tried"]:
        return _AI["det"]
    _AI["det_tried"] = True
    try:
        det, status = _ai_make_detector(_ai_mm(_aicfg.ai_models_dir(CFG.get("ai_model_dir") or None)),
                                        conf=float(CFG.get("ai_conf", 0.45)),
                                        threads=int(CFG.get("ai_threads", 0)))
    except Exception:
        det, status = None, "load_error"
    _AI["det"], _AI["det_status"] = det, status
    return det


def ai_rod_find(frame):
    """AI-поиск удочки (режимы ai/hybrid). (x, y, уверенность) или None.
    Нет модели/не распозналось -> None: вызывающий код обязан уйти в шаблоны."""
    if str(CFG.get("ai_mode", "legacy")) not in ("ai", "hybrid"):
        return None
    det = ai_detector()
    if det is None or det.status != "ok" or not det.ensure_loaded():
        _AI["det_warn"] = _AI.get("det_warn", 0) + 1
        if _AI["det_warn"] == 1:                       # один раз, не спамим журнал
            log(t("log_ai_nomodel", st=_AI["det_status"]))
        return None
    try:
        dets = det.detect(frame, _AI["fid"])
    except Exception:
        return None
    best = None
    for d in dets:
        if d.class_name == "fishing_rod" and d.confidence >= max(0.60, float(CFG.get("ai_conf", 0.45))) \
                and (best is None or d.confidence > best.confidence):
            best = d
    if best is None:
        return None
    x, y, w, h = best.bbox
    return (int(x + w / 2), int(y + h / 2), float(best.confidence))


def ai_report():
    """Кнопка «Журнал AI»: последние события + диагностика — строками в журнал."""
    pipe = _AI["pipe"]
    diag = pipe.diag.report() if pipe else {}
    log(t("log_ai_report"))
    for ev in reversed(pipe.bus.history(12)) if pipe else []:
        log("  %s  %s  conf=%.2f f=%s" % (time.strftime("%H:%M:%S", time.localtime(ev.timestamp)),
                                          ev.type, ev.confidence, ev.frame_id))
    if diag:
        log(t("log_ai_diag", ev=diag.get("events", 0), sn=diag.get("snapshots", 0),
              dis=diag.get("disabled", "") or "—"))
    if not pipe:
        log(t("log_ai_off_short"))


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
    elif name == "ai":
        # «чип + взгляд»: квадрат чипа с ножками и три узла-нейрона внутри
        cv2.rectangle(m, p(15, 15), p(49, 49), 255, c(4), cv2.LINE_AA)
        for i in (24, 32, 40):
            cv2.line(m, p(i, 8), p(i, 15), 255, c(3.4), cv2.LINE_AA)
            cv2.line(m, p(i, 49), p(i, 56), 255, c(3.4), cv2.LINE_AA)
        for j in (8, 32, 56):
            cv2.line(m, p(8, j), p(15, j), 255, c(3.4), cv2.LINE_AA)
            cv2.line(m, p(49, j), p(56, j), 255, c(3.4), cv2.LINE_AA)
        nodes = [(24, 24), (40, 24), (32, 40)]
        for a, b in ((0, 1), (0, 2), (1, 2)):
            cv2.line(m, p(*nodes[a]), p(*nodes[b]), 255, c(3), cv2.LINE_AA)
        for nx, ny in nodes:
            cv2.circle(m, p(nx, ny), c(4.6), 255, -1, cv2.LINE_AA)
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
ICONS = ["target", "person", "eye", "grid", "gear", "ai"]
PAGE_KEYS = [("pg0_t", "pg0_s"), ("pg1_t", "pg1_s"), ("pg2_t", "pg2_s"),
             ("pg3_t", "pg3_s"), ("pg4_t", "pg4_s"), ("pg5_t", "pg5_s")]
EMOJI = re.compile("[\U00010000-\U0010FFFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u25A0-\u25FF]")
C_TEXT, C_DIM, C_RED, C_GREEN, C_WARN = "#ececec", "#9a9a9a", "#d63a3a", "#5fd38a", "#e0a23a"


class App:
    def __init__(self):
        self.S = float(CFG["ui_scale"])
        self.root = tk.Tk()
        r = self.root
        r.title(f"{APP_NAME} v{APP_VERSION}")
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

    def toggle(self, x, y, key, on_change=None):
        on_i = self.img(("sw", 1), lambda: switch_img(self.u(52), self.u(28), True))
        off_i = self.img(("sw", 0), lambda: switch_img(self.u(52), self.u(28), False))
        tag = f"t{next(self.ids)}"
        it = self.put(on_i if CFG.get(key) else off_i, PANEL_X + x, PANEL_Y + y, ("page", tag))

        def flip(_e=None):
            CFG[key] = not CFG.get(key, False)
            self.safe_itemconfig(it, image=on_i if CFG[key] else off_i)
            save_cfg()
            if on_change:
                on_change()
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
            self.safe_itemconfig(val, text=fmt.format(CFG[key]))
            save_cfg()
            if on_change:
                on_change()
        self.cv.tag_bind(tag_m, "<Button-1>", lambda e: bump(-1))
        self.cv.tag_bind(tag_p, "<Button-1>", lambda e: bump(+1))


    def safe_itemconfig(self, item, **kw):
        """Tk бросает TclError, если id уже удалён (страницу перерисовали между кликом и
        обновлением) — для нас это штатная ситуация, просто перерисовываем страницу."""
        try:
            self.cv.itemconfig(item, **kw)
            return True
        except Exception:
            self.show_page(self.page)
            return False

    def do_equip_test(self):
        """«▷ Экипировать»: прямо сейчас найти удочку в открытом инвентаре и взять
        её (зрение + клики в окно интерфейса) — проверка без запуска рыбалки."""
        if not inventory_open():
            self.toast(t("nt_equip_need_inv"), "warn")
            return
        threading.Thread(target=vision_equip, daemon=True).start()

    # ------------------------------------------------------------ выбор из списка / элемент списка CFG
    def choice(self, x, y, key, options, size=11, w=142, h=30, labels=None):
        """Кнопка-переключатель значения из списка (fish_detect: auto|both|hsv)."""
        lbl = labels or {"auto": t("m_det_auto"), "both": t("m_det_both"), "hsv": t("m_det_hsv")}

        def cycle(_e=None):
            try:
                i = (options.index(CFG.get(key, options[0])) + 1) % len(options)
            except ValueError:
                i = 0
            CFG[key] = options[i]
            save_cfg()
            self.show_page(self.page)
        cur = CFG.get(key, options[0])               # ключа нет — показываем первый
        self.button(x, y, w, h, lbl.get(cur, str(cur)), cycle, "gray", size)

    def lang_switcher(self, x, y):
        """Три плитки RU / EN / UA — язык меняется мгновенно, без перезапуска."""
        for code, label in LANGS:
            active = CFG.get("lang") == code
            style = "red" if active else "dark"

            def set_lang(_e=None, c=code):
                if CFG.get("lang") == c:
                    return
                CFG["lang"] = c
                save_cfg()
                self.show_page(self.page)
                self.refresh()
                self.update_pill()

            self.button(x, y, 84, 32, label, set_lang, style, 12)
            x += 92

    def capture_line(self, x, y):
        """Строка диагностики захвата: какой бэкенд реально активен + частота кадров."""
        if CAP is None:
            return t("v_none")
        mode = t("v_stream_on", fps=int(CFG["capture_fps"])) if CAP.streaming else t("v_stream_off")
        return f"{CAP.backend} · {CAP.fps:.0f} fps · {CAP.avg_ms:.1f} ms · {mode}"


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
        for w in self._page_wins:
            try:
                w.destroy()
            except Exception:
                pass
        self._page_wins = []
        self.dyn = {}
        for k, (it, imgs) in enumerate(self.side):
            self.cv.itemconfig(it, image=imgs["active" if k == i else "normal"])
        tk_, sk_ = PAGE_KEYS[i] if i < len(PAGE_KEYS) else ("pg0_t", "pg0_s")
        self.txt(PANEL_X + 30, PANEL_Y + 24, t(tk_), 24, "#ffffff", True)
        self.txt(PANEL_X + 30, PANEL_Y + 62, t(sk_), 11, C_DIM)
        self.dyn["ver"] = self.txt(PANEL_X + PANEL_W - 24, PANEL_Y + 64, f"v{APP_VERSION}", 10, C_DIM, False, "e")
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
        self.dyn["cap"] = self.txt(PANEL_X + 56, PANEL_Y + 200, "", 10, C_DIM, False, "w", ("page",), True)
        for k, (lab, x) in enumerate(((t("k_catches"), 30), (t("k_time"), 284), (t("k_per_hour"), 538))):
            self.card(x, 252, 232, 104)
            self.txt(PANEL_X + x + 24, PANEL_Y + 270, lab, 10, C_DIM, True)
            self.dyn[f"s{k}"] = self.txt(PANEL_X + x + 24, PANEL_Y + 298, "0", 28, "#ffffff", True)
        self.card(30, 376, 740, 176)
        self.txt(PANEL_X + 54, PANEL_Y + 388, t("k_log"), 10, C_DIM, True)
        self.dyn["log"] = [self.txt(PANEL_X + 54, PANEL_Y + 414 + i * 20, "", 10, "#c8c8c8", False, "nw", ("page",), True)
                           for i in range(6)]

    def page1(self):
        self.card(30, 100, 740, 440)
        rows = ["s_catches_session", "s_session_time", "s_fish_hour", "s_avg_mini", "s_bait_checks",
                "s_all_catches", "s_sessions", "s_best", "s_last_stop"]
        for k, key in enumerate(rows):
            y = 126 + k * 44
            self.txt(PANEL_X + 62, PANEL_Y + y, t(key), 12, C_DIM)
            self.dyn[f"r{k}"] = self.txt(PANEL_X + 740, PANEL_Y + y - 1, "", 13, "#ffffff", True, "ne")

    def page2(self):
        # --- слева: живая шкала + телеметрия ПИД + мини-график ---
        self.card(30, 100, 250, 452)
        self.txt(PANEL_X + 54, PANEL_Y + 116, t("v_bar"), 10, C_DIM, True)
        self.dyn["bar"] = self.put(self.img(("bar0",), lambda: tile_img(self.u(70), self.u(240), self.u(8), (30, 30, 30))),
                                   PANEL_X + 60, PANEL_Y + 140, ("page",))
        self.dyn["bartxt"] = self.txt(PANEL_X + 146, PANEL_Y + 146, "", 11, C_TEXT)
        self.txt(PANEL_X + 54, PANEL_Y + 392, t("v_pid"), 10, C_DIM, True)
        self.dyn["pid1"] = self.txt(PANEL_X + 54, PANEL_Y + 408, "", 10, C_TEXT, False, "nw", ("page",), True)
        self.dyn["pid2"] = self.txt(PANEL_X + 54, PANEL_Y + 426, "", 10, C_TEXT, False, "nw", ("page",), True)
        self.dyn["pid3"] = self.txt(PANEL_X + 54, PANEL_Y + 444, "", 10, C_TEXT, False, "nw", ("page",), True)
        self.dyn["sparklab"] = self.txt(PANEL_X + 54, PANEL_Y + 466, "", 9, C_DIM, False, "nw", ("page",), True)
        x0, y0 = self.u(PANEL_X + 54), self.u(PANEL_Y + 482)
        x1, y1 = self.u(PANEL_X + 262), self.u(PANEL_Y + 544)
        self.put(self.img(("sparkbg",), lambda: tile_img(x1 - x0, y1 - y0, self.u(6), (34, 34, 34), 2, 11)),
                 PANEL_X + 54, PANEL_Y + 482, ("page",))
        self.dyn["spark_err"] = self.cv.create_line(x0, (y0 + y1) // 2, x1, (y0 + y1) // 2,
                                                    fill=C_RED, width=1, tags=("page",))
        self.dyn["spark_duty"] = self.cv.create_line(x0, y1 - 1, x1, y1 - 1, fill=C_GREEN, width=1, tags=("page",))
        # --- справа: шаблоны, снимок, диагностика захвата ---
        self.card(300, 100, 470, 452)
        self.txt(PANEL_X + 324, PANEL_Y + 116, t("v_tpl"), 10, C_DIM, True)
        for k, n in enumerate(TEMPLATE_NAMES):
            y = 138 + k * 28
            self.dyn[f"d{k}"] = self.put(self.img(("dot", "gray"), lambda: dot_img(self.u(12), (110, 110, 110))),
                                         PANEL_X + 326, PANEL_Y + y + 3, ("page",))
            self.txt(PANEL_X + 348, PANEL_Y + y, tpl_label(n), 11, C_TEXT)
            self.dyn[f"v{k}"] = self.txt(PANEL_X + 746, PANEL_Y + y, "", 11, C_DIM, False, "ne")
        self.button(324, 320, 138, 40, t("b_snapshot"), dump_debug, "gray", 11)
        self.button(470, 320, 138, 40, t("b_tpl_rod"), lambda: self.cap("rod"), "gray", 11)
        self.button(616, 320, 138, 40, t("b_tpl_bait"), lambda: self.cap("bait"), "gray", 11)
        self.txt(PANEL_X + 324, PANEL_Y + 366, t("v_tpl_hint1") + "\n" + t("v_tpl_hint2"), 10, C_DIM)
        self.txt(PANEL_X + 324, PANEL_Y + 396, t("v_capture"), 10, C_DIM, True)
        self.dyn["cap1"] = self.txt(PANEL_X + 324, PANEL_Y + 412, "", 11, C_TEXT, True, "nw", ("page",), True)
        self.dyn["cap2"] = self.txt(PANEL_X + 324, PANEL_Y + 432, "", 10, C_DIM, False, "nw", ("page",), True)
        self.dyn["cap3"] = self.txt(PANEL_X + 324, PANEL_Y + 458, "", 10, C_RED, True, "nw", ("page",), True)
        self.dyn["cap4"] = self.txt(PANEL_X + 324, PANEL_Y + 482, "", 10, C_DIM, False, "nw", ("page",), True)
        self.dyn["cap5"] = self.txt(PANEL_X + 324, PANEL_Y + 512, "", 10, C_WARN, False, "nw", ("page",), True)

    def page3(self):
        self.card(30, 100, 740, 452)
        self.txt(PANEL_X + 44, PANEL_Y + 110, t("m_card_fish"), 10, C_DIM, True)
        self.txt(PANEL_X + 400, PANEL_Y + 110, t("m_card_pid"), 10, C_DIM, True)
        left = [("m_equip", "t", "equip_on_start"), ("m_autocast", "t", "auto_cast"),
                ("m_castafter", "t", "cast_after_catch"),
                ("m_biteto", "s", ("bite_timeout", 20, 180, 5, "{:g}")),
                ("m_postdelay", "s", ("post_catch_delay", 0.5, 6, 0.25, "{:.2f}")),
                ("m_selflearn", "t", "tpl_selflearn"),
                ("m_hide", "t", "hide_when_running"), ("m_snd_start", "t", "sound_start"),
                ("m_snd_end", "t", "sound_end"), ("m_snd_catch", "t", "sound_catch"),
                ("m_maxhold", "s", ("max_hold", 0.5, 8, 0.25, "{:.2f}")),
                ("m_lostms", "s", ("lost_ms", 40, 900, 20, "{:g}")),
                ("m_clickwin", "t", "ui_click_window")]
        right = [("m_hyst", "s", ("relay_hyst", 2.0, 60.0, 1.0, "{:g}")),
                 ("m_look", "s", ("relay_look_ms", 60, 300, 10, "{:g}")),
                 ("m_aup", "s", ("relay_a_up", 400.0, 4000.0, 100.0, "{:g}")),
                 ("m_g", "s", ("relay_g", 400.0, 4000.0, 100.0, "{:g}")),
                 ("m_vmax", "s", ("relay_vmax", 300.0, 1500.0, 50.0, "{:g}")),
                 ("m_adapt", "t", "relay_adapt"), ("m_barref", "t", "bar_refine"),
                 ("m_barfit", "t", "bar_autofit"),
                 ("m_fishthr", "s", ("fish_thr", 6, 90, 2, "{:g}")),
                 ("m_slipthr", "s", ("slip_thr", 0.02, 0.6, 0.02, "{:.2f}"))]
        for col, rows in ((44, left), (400, right)):
            for k, (lab, kind, arg) in enumerate(rows):
                y = 126 + k * 32
                self.txt(PANEL_X + col, PANEL_Y + y + 6, t(lab), 10, C_TEXT)
                cx = col + 152
                if kind == "t":
                    self.toggle(cx + 60, y + 1, arg)
                elif kind == "c":
                    key, options, w, h = arg
                    self.choice(cx + 10, y, key, options, 10, w, h)
                else:
                    self.stepper(cx + 10, y, *arg)

    def page4(self):
        self.card(30, 100, 740, 452)
        # --- язык ---
        self.txt(PANEL_X + 56, PANEL_Y + 110, t("s_sec_lang"), 10, C_DIM, True)
        self.lang_switcher(56, 124)
        self.dyn["lang_note"] = self.txt(PANEL_X + 340, PANEL_Y + 132, t("s_lang"), 11, C_TEXT)
        self.dyn["ver_big"] = self.txt(PANEL_X + 700, PANEL_Y + 118, f"{APP_NAME} v{APP_VERSION}", 11, C_TEXT, True, "e")
        self.dyn["cap"] = self.txt(PANEL_X + 700, PANEL_Y + 136, "", 10, C_DIM, False, "e", ("page",), True)
        # --- клавиши ---
        self.txt(PANEL_X + 56, PANEL_Y + 168, t("s_sec_binds"), 10, C_DIM, True)
        rows = [("s_bind_toggle", "bind_toggle"), ("s_bind_panic", "bind_panic"),
                ("s_bind_gui", "bind_gui")]
        for k, (lab, key) in enumerate(rows):
            y = 182 + k * 30
            self.txt(PANEL_X + 56, PANEL_Y + y + 8, t(lab), 12, C_TEXT)
            self.dyn[f"k_{key}"] = self.txt(PANEL_X + 300, PANEL_Y + y + 8, CFG[key].upper(), 13, "#ffffff", True, "e")
            self.button(320, y, 140, 30, t("b_change"), lambda key=key: self.rebind(key), "gray", 10)
        y = 300
        self.txt(PANEL_X + 400, PANEL_Y + y + 8, t("s_volume"), 11, C_TEXT)
        self.stepper(600, y, "volume", 0, 100, 10, "{:g}", on_change=lambda: (ensure_sounds(), play("start")))
        y = 336
        self.txt(PANEL_X + 400, PANEL_Y + y + 8, t("s_cast_delay"), 11, C_TEXT)
        self.stepper(600, y, "cast_delay", 0.3, 3.0, 0.1, "{:.1f}")
        # --- экипировка (v1.21: зрение вместо записи макро) ---
        self.txt(PANEL_X + 56, PANEL_Y + 412, t("s_sec_equip"), 10, C_DIM, True)
        self.dyn["macro_st"] = self.txt(PANEL_X + 56, PANEL_Y + 434, t("s_equip_hint"), 11, C_TEXT)
        self.button(56, 458, 160, 32, t("b_equip"), self.do_equip_test, "gray", 10)
        self.dyn["game"] = self.txt(PANEL_X + 56, PANEL_Y + 500, "", 10, C_DIM)
        self.button(424, 496, 100, 30, t("b_save"), self.do_save, "gray", 10)
        self.button(532, 496, 100, 30, t("b_load"), self.do_load, "gray", 10)
        self.button(640, 496, 100, 30, t("b_reset"), self.do_reset, "dark", 10)

    def page5(self):
        """AI-ЗРЕНИЕ (v1.24): статус локального конвейера + настройки наблюдения.
        По умолчанию всё ВЫКЛЮЧЕНО: приложение полностью работает без AI."""
        self.card(30, 100, 740, 452)
        # --- левая колонка: живой статус (обновляет refresh) ---
        self.txt(PANEL_X + 44, PANEL_Y + 112, t("ai_sec_status"), 10, C_DIM, True)
        self.dyn["ai1"] = self.txt(PANEL_X + 44, PANEL_Y + 132, "", 11, C_TEXT, True, "nw", ("page",), True)
        self.dyn["ai2"] = self.txt(PANEL_X + 44, PANEL_Y + 152, "", 10, C_DIM, False, "nw", ("page",), True)
        self.dyn["ai3"] = self.txt(PANEL_X + 44, PANEL_Y + 172, "", 10, C_RED, True, "nw", ("page",), True)
        self.dyn["ai4"] = self.txt(PANEL_X + 44, PANEL_Y + 192, "", 10, C_DIM, False, "nw", ("page",), True)
        self.dyn["ai5"] = self.txt(PANEL_X + 44, PANEL_Y + 212, "", 10, C_DIM, False, "nw", ("page",), True)
        self.button(44, 238, 160, 32, t("b_ai_report"), self.do_ai_report, "gray", 10)
        self.button(212, 238, 160, 32, t("b_ai_restart"), self.do_ai_restart, "gray", 10)
        self.txt(PANEL_X + 44, PANEL_Y + 292, t("ai_hint_local"), 10, C_DIM)
        self.txt(PANEL_X + 44, PANEL_Y + 312, t("ai_hint_noclick"), 10, C_DIM)
        # --- режим распознавания (экипировка: легаси-шаблоны / AI / гибрид) ---
        self.txt(PANEL_X + 44, PANEL_Y + 356, t("ai_sec_mode"), 10, C_DIM, True)
        self.txt(PANEL_X + 44, PANEL_Y + 376, t("ai_lbl_mode"), 11, C_TEXT)
        self.choice(44, 392, "ai_mode", ["legacy", "ai", "hybrid"],
                    labels={"legacy": t("ai_mode_legacy"), "ai": t("ai_mode_ai"),
                            "hybrid": t("ai_mode_hybrid")})
        self.txt(PANEL_X + 230, PANEL_Y + 384, t("ai_lbl_enabled"), 11, C_TEXT)
        self.toggle(442, 384, "ai_enabled", on_change=lambda: ai_restart())
        # --- правая колонка: настройки конвейера ---
        rows = [("ai_lbl_change", "t", "ai_change_detect"),
                ("ai_lbl_ocr", "t", "ai_ocr_enabled"),
                ("ai_lbl_snap", "t", "ai_snapshots"),
                ("ai_lbl_fps", "s", ("ai_detect_fps", 0.5, 5.0, 0.5, "{:.1f}")),
                ("ai_lbl_ocrfps", "s", ("ai_ocr_fps", 0.2, 3.0, 0.1, "{:.1f}")),
                ("ai_lbl_conf", "s", ("ai_conf", 0.10, 0.90, 0.05, "{:.2f}")),
                ("ai_lbl_confirm", "s", ("ai_state_confirm", 1, 6, 1, "{:g}")),
                ("ai_lbl_threads", "s", ("ai_threads", 0, 8, 1, "{:g}"))]
        for k, (lab, kind, arg) in enumerate(rows):
            y = 126 + k * 32
            self.txt(PANEL_X + 400, PANEL_Y + y + 6, t(lab), 10, C_TEXT)
            cx = 400 + 152
            if kind == "t":
                self.toggle(cx + 60, y + 1, arg)
            else:
                self.stepper(cx + 10, y, *arg)
        self.txt(PANEL_X + 400, PANEL_Y + 396, t("ai_hint_models"), 10, C_DIM)
        # --- запись сессий (v1.25): ИИ учится на твоих действиях ---
        self.txt(PANEL_X + 44, PANEL_Y + 432, t("ai_rec_sec"), 10, C_DIM, True)
        self.dyn["rec_btn"] = self.button(44, 446, 168, 32, t("b_rec_start"),
                                          self.do_rec_toggle, "red", 10)
        self.button(220, 446, 168, 32, t("b_rec_export"), self.do_rec_export, "gray", 10)
        self.dyn["rec_st"] = self.txt(PANEL_X + 44, PANEL_Y + 488, "", 10,
                                      C_DIM, False, "nw", ("page",), True)
        self.dyn["rec_hint"] = self.txt(PANEL_X + 400, PANEL_Y + 432, t("ai_rec_hint"),
                                        10, C_DIM)

    def do_rec_toggle(self):
        on = ai_record_toggle()
        self.safe_itemconfig(self.dyn.get("rec_btn")[1], text=t("b_rec_stop") if on
                             else t("b_rec_start"))
        self.refresh()

    def do_rec_export(self):
        ai_record_export()
        self.refresh()

    def do_ai_report(self):
        ai_report()

    def do_ai_restart(self):
        ai_restart()
        self.show_page(self.page)


    # ------------------------------------------------------------ действия
    def toggle_click(self):
        toggle_bot()

    def cap(self, name):
        threading.Thread(target=capture_template, args=(name,), daemon=True).start()

    def do_save(self):
        self.toast(t("toast_cfg_saved") if save_cfg() else t("toast_cfg_save_fail"), "ok")

    def do_load(self):
        ok = load_cfg()
        self.toast(t("toast_cfg_loaded") if ok else t("toast_cfg_missing"), "ok" if ok else "warn")
        self.show_page(self.page)

    def do_reset(self):
        lang = CFG.get("lang", "ru")
        reset_cfg()
        CFG["lang"] = lang                      # язык не сбрасываем — это convenience
        save_cfg()
        ensure_sounds()
        self.toast(t("toast_cfg_reset"), "ok")
        self.show_page(self.page)

    def rebind(self, key):
        if self.capturing:
            return
        self.capturing = key
        self.cv.itemconfig(self.dyn[f"k_{key}"], text="…")

        def worker_fn():
            while True:
                ev = keyboard.read_event()
                if ev.event_type == keyboard.KEY_DOWN:
                    break
            EVENTS.put(("bind", key, ev.name))
        threading.Thread(target=worker_fn, daemon=True).start()


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
        if CAP is not None:                     # освобождаем DXGI-дубликатор корректно
            try:
                CAP.close()
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass

    # ------------------------------------------------------------ тосты
    def toast(self, text, kind="ok"):
        self.pill_msg, self.pill_until = text, time.time() + 3.5
        if self.hidden:
            return
        if len(text) > 88:                      # переводы длиннее русских оригиналов — подрезаем
            text = text[:87] + "…"
        w = min(PANEL_W - 100, max(230, int(len(text) * 8.9) + 46))
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
        t_ = tk.Toplevel(self.root)
        t_.title(f"{APP_NAME} v{APP_VERSION}")
        t_.overrideredirect(True)
        t_.configure(bg=KEY)
        try:
            t_.attributes("-transparentcolor", KEY)
            t_.attributes("-topmost", True)
        except Exception:
            pass
        w, h = self.u(400), self.u(46)
        x = max(0, (t_.winfo_screenwidth() - w) // 2)
        t_.geometry(f"{w}x{h}+{x}+6")
        cv = tk.Canvas(t_, width=w, height=h, bg=KEY, highlightthickness=0, bd=0)
        cv.pack()
        bg = self.img(("pill",), lambda: tile_img(self.u(400), self.u(46), self.u(23), (50, 50, 50), 3, 5))
        cv.create_image(0, 0, image=bg, anchor="nw")
        dot_r = self.img(("dot", "red"), lambda: dot_img(self.u(14), RED))
        cv.create_image(self.u(20), self.u(16), image=dot_r, anchor="nw")
        label = cv.create_text(self.u(44), self.u(23), text="", fill=C_TEXT, anchor="w",
                               font=(FONT, max(8, int(round(12 * self.S))), "bold"))
        ver = cv.create_text(self.u(388), self.u(23), text=f"v{APP_VERSION}", fill=C_DIM, anchor="e",
                             font=(FONT, max(7, int(round(9 * self.S)))))
        self.pill = (t_, label, cv)

    def update_pill(self):
        if self.pill is None:
            return
        t_, label, cv = self.pill
        if time.time() < self.pill_until:
            text = self.pill_msg
        else:
            title, _d = state_text()
            text = t("pill_fmt", state=title, n=STATS["catches"], time=self.elapsed_text())
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

    def cap_summary(self):
        if CAP is None:
            return t("v_none")
        base = f"{CAP.backend.upper()} · {CAP.fps:.0f} fps · grab {CAP.last_grab_ms * 1000:.1f} ms · {CAP.grabs} \u00bb"
        return base + ("  ·  " + t("v_fallback") if CAP.is_fallback else "")

    def _spark(self, d, box):
        """Мини-график: ошибка регулятора (красный) и состояние ЛКМ (зелёный), ~160 кадров."""
        hist = list(CTL_VIEW.get("hist") or ())
        x0, y0, x1, y1 = box
        if len(hist) < 2:
            self.cv.itemconfig(d["spark_err"], points=[x0, (y0 + y1) // 2, x1, (y0 + y1) // 2])
            return
        tail = hist[-160:]
        n = len(tail)
        mid, amp = (y0 + y1) / 2.0, (y1 - y0) / 2.0
        pts_e, pts_d = [], []
        for i, (err, duty) in enumerate(tail):
            x = int(x0 + (x1 - x0) * i / max(1, n - 1))
            pts_e.append(x); pts_e.append(int(mid - max(-1.0, min(1.0, err * 5.0)) * amp))
            pts_d.append(x); pts_d.append(int(y1 - max(0.0, min(1.0, duty)) * (y1 - y0)))
        self.cv.itemconfig(d["spark_err"], points=pts_e)
        self.cv.itemconfig(d["spark_duty"], points=pts_d)

    def refresh(self):
        d, p = self.dyn, self.page
        run = STATE["running"]
        title, detail = state_text()
        if p == 0 and "title" in d:
            col = {"run": C_GREEN, "busy": C_WARN, "error": C_RED}.get(STATE["kind"], C_DIM if not run else C_GREEN)
            self.cv.itemconfig(d["title"], text=title, fill=col)
            self.cv.itemconfig(d["detail"], text=detail)
            self.cv.itemconfig(d["btn"][1], text=t("b_stop") if run else t("b_start"))
            self.cv.itemconfig(d["cap"], text=self.cap_summary())
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
                    f"{sum(mg) / len(mg):.1f} " + t("unit_s") if mg else t("v_none"), str(STATS["checks"]),
                    str(TOTAL["catches"] + (STATS["catches"] if run else 0)), str(TOTAL["sessions"]),
                    str(max(TOTAL["best"], STATS["catches"])),
                    reason_text(TOTAL["last_reason_key"], TOTAL["last_reason_detail"])[:46]]
            for k, v in enumerate(vals):
                self.cv.itemconfig(d[f"r{k}"], text=v)
        elif p == 5 and "ai1" in d:
            st_map = {"off": t("ai_st_off"), "startup": t("ai_st_startup"),
                      "running": t("ai_st_running"), "degraded": t("ai_st_degraded"),
                      "stopped": t("ai_st_stopped")}
            a = ai_status()
            self.cv.itemconfig(d["ai1"], text=f"{t('ai_state')}: "
                               f"{st_map.get(a.get('state'), a.get('state', ''))} · "
                               f"{t('ai_state_screen')}: {a.get('state_screen', '—')} "
                               f"({a.get('state_conf', 0):.2f})")
            self.cv.itemconfig(d["ai2"], text=f"{t('ai_model')}: {a.get('model', '—')}"
                               f" [{a.get('det_rt', '')}] · {t('ai_lat')}: {a.get('det_ms', 0)} мс"
                               f" · OCR: {a.get('ocr', '—')}")
            warn = a.get("det_rt") in ("no_model", "missing_file", "bad_checksum",
                                       "no_onnxruntime", "load_error", "off", "not_started")
            self.cv.itemconfig(d["ai3"], text=t("ai_warn_nomodel") if warn else "")
            self.cv.itemconfig(d["ai4"], text=f"{t('ai_frames')}: {a.get('frames', 0)} · "
                               f"{t('ai_dropped')}: {a.get('dropped', 0)} · "
                               f"{t('ai_events')}: {a.get('events', 0)} · "
                               f"{t('ai_errs')}: {a.get('errors', 0)}")
            dg = a.get("diag") or {}
            self.cv.itemconfig(d["ai5"], text=f"{t('ai_diag_ev')}: {dg.get('events', 0)} · "
                               f"{t('ai_diag_sn')}: {dg.get('snapshots', 0)}"
                               + (f" · {dg.get('disabled')}" if dg.get("disabled") else ""))
            rs = ai_record_status()
            if rs:
                self.cv.itemconfig(d["rec_st"], text=t("ai_rec_status",
                    f=rs["frames"], c=rs["clicks"], mb=rs["mb"],
                    g=rs["cursor_hits"]) + (" · " + rs["dir"] if rs.get("dir") else ""),
                    fill=C_RED if rs.get("recording") else C_DIM)
            else:
                self.cv.itemconfig(d["rec_st"], text=t("ai_rec_idle"))
        elif p == 2 and "bar" in d:
            try:
                rect, inner = bar_rects()
                bgr = grab(rect)
                r = analyze(bgr, inner)
                x0, y0, iw, ih = inner
                crop = bgr[max(0, y0):y0 + ih, max(0, x0):x0 + iw]
                vis = cv2.resize(crop, (self.u(70), self.u(240)), interpolation=cv2.INTER_AREA)
                hh = crop.shape[0] or 1
                if r["zone"]:
                    cv2.rectangle(vis, (0, int(r["zone"][0] / hh * vis.shape[0])),
                                  (vis.shape[1] - 1, int(r["zone"][1] / hh * vis.shape[0])), (60, 220, 60), 2)
                if r["fish"] is not None:
                    yy = int(r["fish"] / hh * vis.shape[0])
                    cv2.line(vis, (0, yy), (vis.shape[1], yy), (60, 120, 255), 2)
                self.imgs["barlive"] = tk.PhotoImage(data=_enc(cv2.cvtColor(vis, cv2.COLOR_BGR2BGRA)))
                self.cv.itemconfig(d["bar"], image=self.imgs["barlive"])
                z, f_ = r["zone"], r["fish"]
                self.cv.itemconfig(d["bartxt"], text=(
                    f"{t('v_zone')}: {'—' if not z else int(z[2])}\n"
                    f"{t('v_fish')}: {'—' if f_ is None else int(f_)}\n"
                    f"{t('v_slip')}: {r['slip'] * 100:.0f}%"))
                v = CTL_VIEW
                md = t("v_mode_emerg") if v.get("mode") == "emerg" else t("v_mode_norm")
                lkm = t("v_press_on") if v.get("press") else t("v_press_off")
                self.cv.itemconfig(d["pid1"], text=(
                    f"{t('v_err')}: {v['err'] * 100:+6.1f}%  {t('v_press')}: {lkm}"))
                self.cv.itemconfig(d["pid2"], text=(
                    f"{t('v_zv')}: {v['zone_v']:+5.0f} px/s  {t('v_fv')}: {v.get('fish_v', 0.0):+5.0f} px/s"))
                self.cv.itemconfig(d["pid3"], text=(
                    f"{t('v_brk')}: {v.get('brake', 0.0):3.0f} px  {t('v_mode')}: {md}  {t('v_lost')}: {v['lost']}"
                    + (f"  {CAP.fps:.0f} fps" if CAP else "")))
                self.cv.itemconfig(d["sparklab"], text=t("v_spark_lab"))
                self._spark(d, (self.u(PANEL_X + 56), self.u(PANEL_Y + 484), self.u(PANEL_X + 260), self.u(PANEL_Y + 542)))
            except Exception:
                pass
            if not run:
                for k, n in enumerate(TEMPLATE_NAMES):
                    try:
                        s = best_score(n)
                    except Exception:
                        s = None
                    good = s is not None and s >= THR[n]
                    key = ("dot", "ok" if good else ("none" if s is None else "bad"))
                    col = (95, 211, 138)[::-1] if good else ((110, 110, 110) if s is None else (58, 58, 214))
                    self.cv.itemconfig(d[f"d{k}"], image=self.img(key, lambda col=col: dot_img(self.u(12), col)))
                    self.cv.itemconfig(d[f"v{k}"], text=t("v_no_file") if s is None else f"{s:.2f} / {THR[n]:.2f}")
            self.cv.itemconfig(d["cap1"], text=self.cap_summary())
            m_ = monitor()
            self.cv.itemconfig(d["cap2"], text=f"mon {m_['width']}x{m_['height']} | scale {CAP.sx:.3f}x{CAP.sy:.3f}" if CAP else "")
            self.cv.itemconfig(d["cap3"], text=t("v_fallback") if (CAP and CAP.is_fallback) else t("v_primary"))
            det = ""
            if isinstance(r, dict):
                det = "%s %s" % (t("v_scale_lab"), list(r["scale"])) if r.get("detected") else "%s: ?" % t("v_scale_lab")
                if r.get("clipped"):
                    det += " | " + t("v_bar_edge")
            self.cv.itemconfig(d["cap4"], text=(
                f"bar {CFG['bar']} pad {CFG['bar_pad']} | relay {CFG['relay_look_ms']:.0f} ms"
                + (("\n" + det) if det else "")))
            self.cv.itemconfig(d["cap5"], text=t("v_ctl_hint") if not run else "")
        elif p == 4 and "game" in d:
            self.cv.itemconfig(d["game"], text=t("s_game", title=GAME_TITLE) if GAME_TITLE else t("s_game_none"))
            self.cv.itemconfig(d["cap"], text=self.capture_line(0, 0))
            self.cv.itemconfig(d["ver_big"], text=f"{APP_NAME} v{APP_VERSION}")

    def tick(self):
        fast = self.page == 2 and (STATE["running"] or CTL_VIEW.get("hist"))
        try:
            self.refresh()
            self.update_pill()
        finally:
            self.root.after(120 if fast else (500 if self.page == 2 else 250), self.tick)



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
        if name != "esc":
            CFG[key] = name
            save_cfg()
            register_hotkeys()
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


def shutdown():
    """Гарантированно отпускаем ввод и освобождаем DXGI-ресурсы при любом выходе."""
    try:
        release_all()
    except Exception:
        pass
    try:
        keyboard.unhook_all()
    except Exception:
        pass
    if CAP is not None:
        try:
            CAP.close()
        except Exception:
            pass


def main():
    missing = [n for n, m in (("opencv-python", cv2), ("numpy", np), ("pydirectinput", pydirectinput),
                             ("keyboard", keyboard), ("tkinter", tk)) if m is None]
    if dxcam is None and bettercam is None:
        missing.append("dxcam (или bettercam)")
    if missing:
        print("Missing packages / не установлено:", ", ".join(missing))
        print("pip install -r requirements.txt")
        try:
            input("Enter to exit / Enter для выхода")
        except Exception:
            pass
        sys.exit(1)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass
    if pydirectinput is not None:
        pydirectinput.PAUSE = 0
        pydirectinput.FAILSAFE = False
    read_version()
    load_cfg()
    load_totals()
    os.makedirs(TPL_DIR, exist_ok=True)
    ensure_sounds()
    init_capture()                     # захват поднимается ДО GUI — сразу видно реальный бэкенд
    app = App()
    register_hotkeys()
    import atexit
    atexit.register(shutdown)
    try:
        # БЕЗ этого sleep(2-5 мс) на Windows спит ~15.6 мс: повторы макро сжимались
        # в рывки («дёрганная быстрая сенса»), тайминги мини-игры плыли.
        # 1 мс разрешение — точные паузы везде.
        ctypes.windll.winmm.timeBeginPeriod(1)

        def _end_period():
            try:
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass
        atexit.register(_end_period)
    except Exception:
        pass
    log(t("log_ready", app=f"{APP_NAME} v{APP_VERSION}", toggle=CFG["bind_toggle"].upper(),
          panic=CFG["bind_panic"].upper()))
    try:
        app.root.mainloop()
    finally:
        save_cfg()
        save_totals()
        shutdown()


if __name__ == "__main__":
    main()
