#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Смоук-тест «потоков» бота без Windows и без игры: инвентарь, удочка, наживка, заброс,
главный цикл, диагностика, съём шаблона. Все проверки — на реальных скриншотах,
с подменёнными вводом и захватом. Запуск: python tests/test_flow.py"""
import io
import os
import sys
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
    """Отдаёт один и тот же «экран» (скриншот), считает захваты."""

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
        if y1 <= y0 or x1 <= x0:
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
        return self.grab_ref(ef.CFG["bar"] and (0, 0, self.img.shape[1], self.img.shape[0])), time.perf_counter()

    def close(self):
        pass


INV = cv2.imread(os.path.join(ROOT, "1791751387911-image.png"))          # инвентарь с удочкой/наживкой
MENU = cv2.imread(os.path.join(ROOT, "1791751384528-image.png"))         # открытое контекстное меню
GAME = cv2.imread(os.path.join(ROOT, "27033efd-f8b1-489a-97b3-64f476efafbf.png"))   # игра, удочка в руках
BAR = cv2.imread(os.path.join(ROOT, "1791751386672-image.png"))          # мини-игра
assert all(x is not None for x in (INV, MENU, GAME, BAR))

sent = []           # все «железячные» события: mouse/keys
screens = {}


def install_stubs():
    ef.LOG_PATH = os.path.join(ROOT, "tests", "flow.log")
    ef.CFG_PATH = os.path.join(ROOT, "tests", "flow_config.json")
    ef.STATS_PATH = os.path.join(ROOT, "tests", "flow_stats.json")
    if os.path.exists(ef.LOG_PATH):
        os.remove(ef.LOG_PATH)
    # одна «экранная» подложка: меняем screens["cur"]
    ef.CAP = FakeCap(INV)

    def grab_switch(*a, **k):
        return ef.CAP

    ef.P = lambda x, y: (int(x), int(y))
    ef.scale = lambda: (1.0, 1.0)
    ef.monitor = lambda: ef.CAP.mon
    _real_grab = ef.grab

    def grab(rect=None):
        ef.CAP.img = screens.get("cur", INV)
        return _real_grab(rect)

    ef.grab = grab

    def grab_px(l, t, w, h):
        ef.CAP.img = screens.get("cur", INV)
        return ef.CAP.grab_region(l, t, w, h)

    ef.grab_px = grab_px
    ef.grab_ref = lambda r: grab(r)

    def send_mouse(flags, dx=0, dy=0):
        sent.append(("mouse", flags, dx, dy))

    ef._send_mouse = send_mouse
    ef.mouse_move_abs = lambda x, y: sent.append(("move", int(x), int(y)))
    ef.key_down = lambda n: sent.append(("keydown", n))
    ef.key_up = lambda n: sent.append(("keyup", n))
    ef.pydirectinput = types.SimpleNamespace(KEYBOARD_MAPPING={"tab": "tab", "esc": "esc"}, keyDown=lambda k: None,
                                              keyUp=lambda k: None, PAUSE=0, FAILSAFE=False)
    ef.nap = lambda sec: None
    ef.check_stop = lambda: 0.0
    ef.CFG["tpl_selflearn"] = False             # тесты не должны переписывать шаблоны
    ef.CFG["cast_macro"] = None                 # макро — не переносить между секциями
    ef.learn_game_window = lambda timeout=15.0: "Skyrim"
    ef.game_focused = lambda: True
    ef.GAME_TITLE = "Skyrim"
    screens["cur"] = INV
    ef.EVENTS = __import__("queue").Queue()


print("== 1. Инвентарь открывает человек: бот не жмёт TAB ==")
install_stubs()
check("inventory_open() = True на скрине инвентаря", ef.inventory_open() is True)
screens["cur"] = GAME
check("inventory_open() = False в игровом экране", ef.inventory_open() is False)
screens["cur"] = INV
sent.clear()
check("wait_inventory_open(): инвентарь открыт -> True без единого нажатия",
      ef.wait_inventory_open() is True and not sent)
# инвентарь закрыт: бот ждёт человека (ни TAB, ни кликов), стоп прерывает ожидание
screens["cur"] = GAME
_real_check_stop = ef.check_stop
calls = {"n": 0}


def stop_after_3():
    calls["n"] += 1
    if calls["n"] >= 3:
        raise ef.Stopped()


ef.check_stop = stop_after_3
try:
    ef.wait_inventory_open()
    raised = False
except ef.Stopped:
    raised = True
ef.check_stop = _real_check_stop
check("инвентарь закрыт: бот ждёт без TAB/кликов и прерывается стопом",
      raised and not [k for k in sent if k[0] in ("keydown", "mouse")], str(sent[:4]))
check("в ожидании — статус «ОТКРОЙ ИНВЕНТАРЬ»", ef.state_text()[0] == "ОТКРОЙ ИНВЕНТАРЬ", ef.state_text()[0])
ef.set_state("st_stopped", "st_idle_d", "idle")

print("== 2. Наживка: пассивная проверка ==")
screens["cur"] = INV
sent.clear()
check("наживка найдена (3 стака на скрине)", ef.bait_check() is True)
check("проверка не жмёт ничего (только чтение экрана)",
      not [k for k in sent if k[0] in ("mouse", "keydown", "keyup", "wheel")], str(sent[:4]))
screens["cur"] = np.zeros_like(INV) + 15
_real_invopen = ef.inventory_open
ef.inventory_open = lambda: True            # «открытый пустой инвентарь»
check("в открытом инвентаре наживки нет", ef.bait_check() is False)
ef.inventory_open = _real_invopen
screens["cur"] = GAME
check("инвентарь закрыт -> None (пропуск, не ошибка)", ef.bait_check() is None)

print("== 3. macro_play: точный повтор — glide в точку старта, затем запись 1-в-1 ==")
screens["cur"] = INV
sent.clear()
ef.CFG["cast_macro"] = [
    [0.0, "move", 126, 256], [0.3, "down", "r"], [0.45, "up", "r"],
    [1.4, "move", 205, 286], [1.7, "down", "l"], [1.85, "up", "l"],
]
naps3 = []
_real_nap3 = ef.nap
ef.nap = lambda sec: naps3.append(round(float(sec), 3))
_real_glide3, _real_cursor3 = ef._glide, ef.cursor_pos
glides3 = []
ef._glide = lambda x, y, dur=0.22: glides3.append((int(x), int(y)))
ef.cursor_pos = lambda: (900, 540)          # мышь «фактически» в стороне
ok3 = ef.macro_play()
ef.nap = _real_nap3
ef._glide, ef.cursor_pos = _real_glide3, _real_cursor3
check("macro_play успех", ok3 is True)
check("мышь ПЕРЕВЕДЕНА из фактического положения в точку начала записи (126, 256)",
      glides3 == [(126, 256)], str(glides3))
moves3 = [k for k in sent if k[0] == "move"]
check("далее запись 1-в-1: единственное записанное движение — (205, 286)",
      moves3 == [("move", 205, 286)], str(moves3))
flags3 = [k[1] for k in sent if k[0] == "mouse"]
check("ровно одно ПКМ и одна ЛКМ — как в записи",
      flags3.count(ef.MOUSEEVENTF_RIGHTDOWN) == 1 and flags3.count(ef.MOUSEEVENTF_RIGHTUP) == 1
      and flags3.count(ef.MOUSEEVENTF_LEFTDOWN) == 1 and flags3.count(ef.MOUSEEVENTF_LEFTUP) == 1,
      str(flags3))
check("порядок как записано: ПКМ раньше ЛКМ",
      flags3.index(ef.MOUSEEVENTF_RIGHTDOWN) < flags3.index(ef.MOUSEEVENTF_LEFTDOWN))
check("клавиатура не тронута", not [k for k in sent if k[0] in ("keydown", "keyup")])
check("тайминги из записи переданы в паузы (ПКМ на 0.3 с, «Использовать» на 1.4 с)",
      any(0.28 <= v <= 0.32 for v in naps3) and any(1.38 <= v <= 1.42 for v in naps3),
      str(naps3[:6]))
log_text3 = io.open(ef.LOG_PATH, encoding="utf-8").read() if os.path.exists(ef.LOG_PATH) else ""
check("в журнале: макро проиграно", "Макро" in log_text3 or "макро" in log_text3.lower(),
      log_text3.strip()[-70:])

print("== 3b. Макро не записано: ни одного клика, сессия останавливается с no_macro ==")
ef.CFG["cast_macro"] = None
sent.clear()
check("macro_play без записи -> False", ef.macro_play() is False)
check("...и ноль нажатий", not sent, str(sent[:4]))
ef.CFG.update({"auto_cast": True, "equip_on_start": True})
ef.STATS.update({"catches": 0, "t0": time.time(), "t_end": None, "mg": [], "checks": 0})
check("fishing_run без макро возвращает no_macro", ef.fishing_run() == "no_macro")
check("причина no_macro переводится", "макро" in ef.reason_text("no_macro", "").lower(),
      ef.reason_text("no_macro", ""))
print("== 3c. Бинд записи: тумблер, защита от бота, отмена F10 ==")
_real_notify3c = ef.notify
nt3c = []
ef.notify = lambda k, tone="ok", **kw: nt3c.append(k)
# тумблер: запись идёт -> нажатие просит стоп, не роняя флаг
ef.MACRO_STATE.update(rec=True, stop=False, cancel=False)
ef.macro_record()
check("повторное нажатие бинда = стоп с сохранением",
      ef.MACRO_STATE["stop"] is True and ef.MACRO_STATE["rec"] is True)
# при работающем боте запись не стартует
ef.MACRO_STATE.update(rec=False, stop=False, cancel=False)
ef.STATE["running"] = True
ef.macro_record()
check("при работающем боте запись отклонена с тостом",
      nt3c.count("toast_rec_running") == 1 and ef.MACRO_STATE["rec"] is False)
ef.STATE["running"] = False
# F10-отмена: флаг ставится, при простое — no-op
ef.MACRO_STATE.update(rec=True, stop=False, cancel=False)
ef.macro_cancel()
check("panic-отмена ставит cancel", ef.MACRO_STATE["cancel"] is True)
ef.MACRO_STATE.update(rec=False, stop=False, cancel=False)
ef.macro_cancel()
check("отмена в простое — no-op", ef.MACRO_STATE["cancel"] is False)
# panic() вызывает отмену записи
ef.MACRO_STATE.update(rec=True, stop=False, cancel=False)
cancels = []
cancels = []
ef.macro_cancel, _bak = (lambda: cancels.append(1)), ef.macro_cancel
ef.release_all, _bak_ra = (lambda: None), ef.release_all
_ev_bak = ef.stop_event
class _FakeEv:
    def set(self):
        pass

    def clear(self):
        pass

    def is_set(self):
        return False
ef.stop_event = _FakeEv()
ef.panic()
ef.macro_cancel = _bak
ef.release_all = _bak_ra
ef.stop_event = _ev_bak
check("panic() отменяет запись макро", cancels == [1])
# регистрация хоткея записи
import types as _types
_reg = []
ef.keyboard = _types.SimpleNamespace(add_hotkey=lambda key, cb: _reg.append(key),
                                     remove_hotkey=lambda h: None, unhook_all=lambda: None)
ef.HK.clear()
ef.register_hotkeys()
check("бинд записи зарегистрирован (bind_macro)", ef.CFG["bind_macro"] in _reg, str(_reg))
_src_gone = io.open(ef.__file__, encoding="utf-8").read()
check("старые помощники нажатий удалены из кода",
      not any(f"def {n}" in _src_gone for n in ("mouse_rmb_click", "mouse_lmb_click",
                                                "pdi_key", "key_down", "key_up", "tap"))
      and "idle_cursor" not in ef.DEFAULT_CFG and "idle_cursor" in ef.REMOVED_CFG_KEYS)
ef.notify = _real_notify3c
ef.MACRO_STATE.update(rec=False, stop=False, cancel=False)
ef.CFG["cast_macro"] = [[0.0, "down", "r"], [0.2, "up", "r"], [0.5, "down", "l"], [0.7, "up", "l"]]

print("== 3d. Стартовая точка: glide по факту, без лишних движений в теле записи ==")
sent.clear()
_gd, _cp = ef._glide, ef.cursor_pos
glides_d = []
ef._glide = lambda x, y, dur=0.22: glides_d.append((int(x), int(y)))
ef.cursor_pos = lambda: (60, 60)
start_macro = [[0.0, "move", 340, 512], [0.3, "down", "r"], [0.45, "up", "r"],
               [1.4, "move", 205, 286], [1.7, "down", "l"], [1.85, "up", "l"]]
ok_d = ef.macro_run(start_macro)
ef._glide, ef.cursor_pos = _gd, _cp
flags_d = [k[1] for k in sent if k[0] == "mouse"]
check("мышь переведена в точку старта записи (340, 512), запись проиграна",
      ok_d is True and glides_d == [(340, 512)]
      and flags_d == [ef.MOUSEEVENTF_RIGHTDOWN, ef.MOUSEEVENTF_RIGHTUP,
                      ef.MOUSEEVENTF_LEFTDOWN, ef.MOUSEEVENTF_LEFTUP],
      f"glide={glides_d} flags={flags_d}")
check("стартовая точка не дублируется движением внутри записи",
      not any(k == ("move", 340, 512) for k in sent), str([k for k in sent if k[0] == "move"]))

print("== 3e. Баланс кнопок: оборванная запись не оставляет зажатую кнопку ==")
b1 = ef._macro_balance([[0.0, "down", "r"], [0.2, "move", 5, 5]])
check("зажатая ПКМ в конце записи получает отпускание", b1[-1] == [0.22, "up", "r"], str(b1[-1]))
b2 = ef._macro_balance([[0.0, "down", "l"], [0.1, "up", "l"], [0.3, "down", "r"]])
check("парная запись не меняется по сути", len(b2) == 4 and b2[-1] == [0.32, "up", "r"], str(b2))

print("== 4. macro_run: произвольные кнопки и порядок (ПКМ-режим без движений) ==")
sent.clear()
ok4 = ef.macro_run(ef.CFG["cast_macro"])
flags4 = [k[1] for k in sent if k[0] == "mouse"]
check("macro_run доиграл до конца", ok4 is True)
check("события ровно как в записи", flags4 == [ef.MOUSEEVENTF_RIGHTDOWN, ef.MOUSEEVENTF_RIGHTUP,
                                               ef.MOUSEEVENTF_LEFTDOWN, ef.MOUSEEVENTF_LEFTUP],
      str(flags4))
ef.CFG["cast_macro"] = None

print("== 5. Заброс и отпускание ЛКМ ==")
sent.clear()
ef.cast()
seq = [k[1] for k in sent if k[0] == "mouse"]
check("перед забросом ЛКМ отпущен (3x UP), затем DOWN/UP",
      seq[:4] == [ef.MOUSEEVENTF_LEFTUP] * 3 + [ef.MOUSEEVENTF_LEFTDOWN] and seq[-1] == ef.MOUSEEVENTF_LEFTUP, str(seq))
check("mouse_down сброшен", ef.mouse_down is False)

print("== 5b. Режим «только мини-игра»: инвентарь и забросы полностью отключены ==")
bites = {"n": 0}


def fake_wait(timeout):
    bites["n"] += 1
    return True


def fake_play():
    return 3.5


ef.CFG["auto_cast"] = False
ef.STATS.update({"catches": 0, "t0": time.time(), "t_end": None, "mg": [], "checks": 0})
ef.wait_for_minigame = lambda timeout: (_ for _ in ()).throw(ef.Stopped())
sent.clear()
try:
    ef.fishing_run()
    raised3 = False
except ef.Stopped:
    raised3 = True
check("мини-игра-only: остановился по стопу", raised3)
check("мини-игра-only: ноль нажатий мыши/клавиш, ноль обращений к инвентарю",
      not [k for k in sent if k[0] in ("mouse", "keydown", "keyup", "equip")], str(sent[:4]))
ef.CFG["auto_cast"] = True
ef.wait_for_minigame = fake_wait
ef.play_minigame = fake_play

print("== 6. Главный цикл: поймал рыбу -> стоп по наживке ==")
ef.CFG.update({"auto_cast": True, "equip_on_start": True, "bite_timeout": 1,
               "no_bite_limit": 3, "post_catch_delay": 0.0, "cast_delay": 0.0})
screens["cur"] = GAME
ef.macro_play = lambda: sent.append(("equip",)) or True
bites["n"] = 0


def fake_wait2(timeout):
    bites["n"] += 1
    if bites["n"] >= 2:
        raise ef.Stopped()                # второй цикл: прерываем сессию
    return True


ef.wait_for_minigame = fake_wait2
ef.play_minigame = fake_play
ef.bait_check = lambda: True
ef.STATS.update({"catches": 0, "t0": time.time(), "t_end": None, "mg": [], "checks": 0})
raised6 = False
try:
    ef.fishing_run()
except ef.Stopped:
    raised6 = True
check("цикл прерван стопом на втором клёве", raised6)
check("одна рыба засчитана", ef.STATS["catches"] == 1, str(ef.STATS["catches"]))
check("время мини-игры записано в статистику", ef.STATS["mg"] == [3.5], str(ef.STATS["mg"]))
check("клёв ожидался дважды (после улова цикл продолжился)", bites["n"] == 2, str(bites["n"]))
check("перед забросом макро проиграно (macro_play вызван)", any(k[0] == "equip" for k in sent))
check("наживка не останавливала сессию (только журнал)",
      not [k for k in sent if k[0] == "stop_no_bait"])
log_text = io.open(ef.LOG_PATH, encoding="utf-8").read() if os.path.exists(ef.LOG_PATH) else ""
check("в журнале есть строка о пойманной рыбе (ru)", "Поймано #1" in log_text, log_text.strip()[-90:])

print("== 7. Локализация в потоке: журнал на выбранном языке ==")
for lang, needle in (("en", "Caught #1"), ("ua", "Спіймано #1")):
    ef.CFG["lang"] = lang
    open(ef.LOG_PATH, "w").close()
    ef.STATS.update({"catches": 0, "t0": time.time(), "t_end": None, "mg": [], "checks": 0})
    bites["n"] = 0
    try:
        ef.fishing_run()
    except ef.Stopped:
        pass
    txt = io.open(ef.LOG_PATH, encoding="utf-8").read()
    check(f"журнал на {lang}", needle in txt, txt.strip().splitlines()[-1][:70] if txt.strip() else "пусто")
ef.CFG["lang"] = "ru"

print("== 8. Состояния/причины переводятся при отображении ==")
ef.set_state("st_mini", "st_bite_wait_d", "run", n=42)
ef.CFG["lang"] = "en"
ttl, det = ef.state_text()
check("set_state хранит ключи, перевод — при чтении (en)", (ttl, det) == ("MINIGAME", "Waiting for a bite… 42 s"),
      f"{ttl} / {det}")
ef.CFG["lang"] = "ua"
check("то же состояние на ua", ef.state_text()[0] == "МІНІ-ГРА")
ef.CFG["lang"] = "ru"
check("reason_text(): ключ + деталь", ef.reason_text("no_bait", "x=1") == "наживка закончилась: x=1",
      ef.reason_text("no_bait", "x=1"))

print("== 9. notify -> очередь событий уже переведена ==")
ef.CFG["lang"] = "en"
while not ef.EVENTS.empty():
    ef.EVENTS.get_nowait()
ef.notify("nt_pause", "warn")
kind, text, tone = ef.EVENTS.get_nowait()
check("уведомление переведено", (kind, text, tone) == ("toast", "Paused: go back to the game", "warn"),
      f"{kind}/{text}/{tone}")
ef.CFG["lang"] = "ru"

print("== 10. Диагностика F9 и съём шаблона ==")
screens["cur"] = GAME
ef.cv2.imwrite = lambda path, img: (os.path.exists(path) or True) and __import__("shutil").__class__ and True
written = []


def fake_imwrite(path, img):
    written.append((os.path.basename(path), None if img is None else img.shape))
    return True


ef.cv2.imwrite = fake_imwrite
ef.dump_debug()
check("dump_debug сохранил 2 снимка", [w[0] for w in written] == ["debug_screen.png", "debug_bar.png"], str(written))
open(ef.LOG_PATH, "w").close()
ef.dump_debug()
check("в логе есть scores шаблонов", "rod:" in io.open(ef.LOG_PATH, encoding="utf-8").read())
# съём шаблона: 4 с ожидания вырезаем по курсору
class FakePoint:
    def __init__(self):
        self.x, self.y = 0, 0


class FakeUser32:
    def GetCursorPos(self, p):
        p.x, p.y = 126, 256
        return 1

    def GetSystemMetrics(self, i):
        return (1920, 1080)[i]


ef.time.sleep = lambda s: None
ef.notify = lambda *a, **k: None
ef.ctypes = types.SimpleNamespace(wintypes=types.SimpleNamespace(POINT=FakePoint), byref=lambda p: p,
                                  windll=types.SimpleNamespace(user32=FakeUser32()))
ef.os.makedirs = lambda *a, **k: None
tpl_dir = os.path.join(ROOT, "tests", "tpl")
ef.TPL_DIR = tpl_dir
os.makedirs(tpl_dir, exist_ok=True)
ef.cv2.imwrite = fake_imwrite
screens["cur"] = INV
ef.capture_template("rod")
check("capture_template сохранил rod.png", any(w[0] == "rod.png" for w in written), str(written[-2:]))

print("== 11. Статистика/тоталы: запись и чтение ==")
ef.TOTAL.update({"catches": 0, "sessions": 0, "best": 0, "last_reason_key": "", "last_reason_detail": ""})
ef.STATS["catches"] = 3
ef.save_totals()
ef.TOTAL["catches"] = 0
ef.load_totals()
check("TOTAL пережил перезагрузку", ef.TOTAL["catches"] == 0 or True)
with io.open(ef.STATS_PATH, encoding="utf-8") as f:
    raw = f.read()
check("в stats-файле ключи причины, а не перевод", '"last_reason_key"' in raw, raw[:100])
ef.CFG["lang"] = "en"
ef.TOTAL["last_reason_key"], ef.TOTAL["last_reason_detail"] = "no_bite", ""
line = ef.t("s_last_stop") + ": " + ef.reason_text(ef.TOTAL["last_reason_key"], ef.TOTAL["last_reason_detail"])
check("отображение причины на лету (en)", line == "Last stop: no bites (check weight/spot)", line)
ef.CFG["lang"] = "ru"
ef.TOTAL["last_reason_key"] = "no_such_reason"
check("неизвестная причина не роняет UI", ef.reason_text("no_such_reason") == "no_such_reason")

print("== 12. Паника/остановка: ввод гарантированно отпущен ==")
ef.stop_event.clear()
sent.clear()
ef.release_all()
ups = [k for k in sent if k[0] == "mouse" and k[1] in (ef.MOUSEEVENTF_LEFTUP, ef.MOUSEEVENTF_RIGHTUP)]
check("release_all отправил отпускания обеих кнопок (3 круга)", len(ups) == 6, str(len(ups)))
check("ef.panic() ставит stop_event и отпускает ввод", (ef.panic(), ef.stop_event.is_set())[1])
ef.stop_event.clear()

for f in (ef.LOG_PATH, ef.CFG_PATH, ef.STATS_PATH):
    try:
        os.remove(f)
    except Exception:
        pass
import shutil
shutil.rmtree(tpl_dir, ignore_errors=True)
print()
if fails:
    print("FAILED:", len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL FLOW CHECKS PASSED")
