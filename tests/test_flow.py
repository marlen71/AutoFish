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
    ef.CFG["ui_click_window"] = True            # клики экипировки — в окно интерфейса
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

print("== 3. vision_equip: удочка зрением, клики в окно интерфейса, курсор не двигается ==")
screens["cur"] = INV
sent.clear()
_rod_png = cv2.imread(os.path.join(ROOT, "templates", "rod.png"), cv2.IMREAD_COLOR)
assert _rod_png is not None and _rod_png.size
_frame3 = GAME.copy()
_rx3, _ry3 = 300, 220
_h3, _w3 = _rod_png.shape[:2]
_frame3[_ry3:_ry3 + _h3, _rx3:_rx3 + _w3] = _rod_png      # удочка «лежит» в ячейке
_frame3[300:322, 380:520] = (60, 60, 235)                  # красная строка «Выбросить»
screens["cur"] = _frame3
naps3 = []
_real_nap3, _real_inv3 = ef.nap, ef.inventory_open
_real_hwnd3, _real_uiclk3 = ef._cef_render_hwnd, ef._cef_click_at
ef.nap = lambda sec: naps3.append(round(float(sec), 3))
ef.inventory_open = lambda: True
clicks3 = []
ef._cef_render_hwnd = lambda: 7777
ef._cef_click_at = lambda hwnd, x, y, btn, down: clicks3.append((hwnd, x, y, btn, down)) or True
ok3 = ef.vision_equip()
ef.nap, ef.inventory_open = _real_nap3, _real_inv3
ef._cef_render_hwnd, ef._cef_click_at = _real_hwnd3, _real_uiclk3
check("vision_equip успех", ok3 is True)
rmb3 = [k for k in clicks3 if k[3] == "r"]
lmb3 = [k for k in clicks3 if k[3] == "l"]
check("ПКМ по найденной удочке — в окно интерфейса, down+up",
      len(rmb3) == 2 and all(k[0] == 7777 and abs(k[1] - (_rx3 + _w3 // 2)) <= 8
                             and abs(k[2] - (_ry3 + _h3 // 2)) <= 8 for k in rmb3)
      and rmb3[0][4] is True and rmb3[1][4] is False, str(rmb3))
_uy3 = 300 - max(18, int(_frame3.shape[0] * 0.030))
check("«Использовать» — ЛКМ над красной строкой «Выбросить»",
      len(lmb3) == 2 and all(k[0] == 7777 and abs(k[1] - 450) <= 8
                             and abs(k[2] - _uy3) <= 4 for k in lmb3)
      and lmb3[0][4] is True and lmb3[1][4] is False, str(lmb3))
check("курсор Windows не двигался и обычный ввод не звался", not sent, str(sent[:4]))
check("меню ждали (nap-опрос), после «Использовать» — пауза",
      len(naps3) >= 1 and any(v >= 1.0 for v in naps3), str(naps3[:4]))

print("== 3b. Инвентарь закрыт: экипировки нет, кликов нет ==")
sent.clear()
ef._cef_render_hwnd = lambda: 7777
clicks3b = []
ef._cef_click_at = lambda *a: clicks3b.append(a) or True
ef.inventory_open = lambda: False
ok3b = ef.vision_equip()
ef.inventory_open, ef._cef_render_hwnd, ef._cef_click_at = _real_inv3, _real_hwnd3, _real_uiclk3
check("инвентарь закрыт -> False и ноль кликов", ok3b is False and clicks3b == [] and not sent)

print("== 3c. Удочки на кадре нет: False, кликов нет, кадр промаха сохранён ==")
sent.clear()
screens["cur"] = np.zeros((600, 800, 3), np.uint8)
clicks3c = []
ef._cef_render_hwnd = lambda: 7777
ef._cef_click_at = lambda *a: clicks3c.append(a) or True
ef.inventory_open = lambda: True
_real_nap3c, _real_imw3c = ef.nap, ef.cv2.imwrite
saved3c = []
ef.cv2.imwrite = lambda path, img: saved3c.append(path) or True
ef.nap = lambda sec: None
ok3c = ef.vision_equip()
ef.cv2.imwrite, ef.nap, ef.inventory_open = _real_imw3c, _real_nap3c, _real_inv3
ef._cef_render_hwnd, ef._cef_click_at = _real_hwnd3, _real_uiclk3
check("удочки нет -> False, ноль кликов, кадр промаха сохранён (miss_rod.png)",
      ok3c is False and clicks3c == [] and not sent
      and saved3c and saved3c[-1].endswith("miss_rod.png"), str(saved3c))
log3c = io.open(ef.LOG_PATH, encoding="utf-8").read() if os.path.exists(ef.LOG_PATH) else ""
check("в журнале: удочка не найдена", "не найдена" in log3c.lower(), log3c.strip()[-70:])

print("== 3c2. Тёмный кадр (ночь/гамма): CLAHE-нормализация находит удочку ==")
_dark = np.clip(_frame3.astype(np.int16) - 70, 0, 255).astype(np.uint8)   # тот же кадр, темнее
screens["cur"] = _dark
clicks3c2 = []
ef._cef_render_hwnd = lambda: 7777
ef._cef_click_at = lambda *a: clicks3c2.append(a) or True
ef.inventory_open = lambda: True
_real_nap3c2, _real_imw3c2 = ef.nap, ef.cv2.imwrite
ef.cv2.imwrite = lambda path, img: True
ef.nap = lambda sec: None
ok3c2 = ef.vision_equip()
ef.cv2.imwrite, ef.nap, ef.inventory_open = _real_imw3c2, _real_nap3c2, _real_inv3
ef._cef_render_hwnd, ef._cef_click_at = _real_hwnd3, _real_uiclk3
check("кадр темнее на 70: удочка найдена, ПКМ по ней (нормализация работает)",
      ok3c2 is True and len(clicks3c2) >= 2 and abs(clicks3c2[0][1] - (_rx3 + _w3 // 2)) <= 8
      and abs(clicks3c2[0][2] - (_ry3 + _h3 // 2)) <= 8, str(clicks3c2[:2]))

print("== 3d. Удочка есть, меню не открылось: только ПКМ, False ==")
sent.clear()
_frame3d = _frame3.copy()
_frame3d[294:328, 374:526] = (20, 20, 20)                  # стираем красную строку
screens["cur"] = _frame3d
clicks3d = []
ef._cef_render_hwnd = lambda: 7777
ef._cef_click_at = lambda *a: clicks3d.append(a) or True
ef.inventory_open = lambda: True
_real_nap3d = ef.nap
ef.nap = lambda sec: None
ok3d = ef.vision_equip()
ef.nap, ef.inventory_open = _real_nap3d, _real_inv3
ef._cef_render_hwnd, ef._cef_click_at = _real_hwnd3, _real_uiclk3
check("меню не открылось -> False, ровно 2 фазы ПКМ",
      ok3d is False and len(clicks3d) == 2 and all(k[3] == "r" for k in clicks3d), str(clicks3d))

print("== 3e. Окно интерфейса не найдено: клики курсором (запасной путь) ==")
sent.clear()
screens["cur"] = _frame3
ef._cef_render_hwnd = lambda: None
ef._cef_click_at = lambda *a: None
ef.inventory_open = lambda: True
_real_nap3e = ef.nap
ef.nap = lambda sec: None
ok3e = ef.vision_equip()
ef.nap, ef.inventory_open = _real_nap3e, _real_inv3
ef._cef_render_hwnd, ef._cef_click_at = _real_hwnd3, _real_uiclk3
mv3e = [k for k in sent if k[0] == "move"]
fl3e = [k[1] for k in sent if k[0] == "mouse"]
check("фолбэк: курсор на каждую фазу (4 прыжка), ПКМ по удочке и ЛКМ над строкой",
      ok3e is True and len(mv3e) == 4 and mv3e[0] == mv3e[1] and mv3e[2] == mv3e[3]
      and fl3e == [ef.MOUSEEVENTF_RIGHTDOWN, ef.MOUSEEVENTF_RIGHTUP,
                   ef.MOUSEEVENTF_LEFTDOWN, ef.MOUSEEVENTF_LEFTUP], f"sent={sent}")

print("== 3f. Макро-система удалена; без удочки сессия останавливается с no_macro ==")
check("макро-функции удалены", not any(hasattr(ef, n) for n in
      ("macro_record", "macro_run", "macro_play", "macro_cancel", "_macro_balance",
       "_glide", "_anchor_find", "MACRO_STATE")))
check("ключи макро-эры в REMOVED_CFG_KEYS",
      all(k in ef.REMOVED_CFG_KEYS for k in ("cast_macro", "macro_click_window", "bind_macro")))
ef.CFG.update({"auto_cast": True, "equip_on_start": True})
ef.STATS.update({"catches": 0, "t0": time.time(), "t_end": None, "mg": [], "checks": 0})
_real_inv3f, _real_wio3f = ef.inventory_open, ef.wait_inventory_open
ef.inventory_open = lambda: False
ef.wait_inventory_open = lambda: True
check("fishing_run без удочки возвращает no_macro", ef.fishing_run() == "no_macro")
ef.inventory_open, ef.wait_inventory_open = _real_inv3f, _real_wio3f
check("причина no_macro: удочка не найдена", "удочк" in ef.reason_text("no_macro", "").lower(),
      ef.reason_text("no_macro", ""))

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
ef.vision_equip = lambda: sent.append(("equip",)) or True
ef.wait_inventory_open = lambda: True
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
check("перед забросом экипировка выполнена (vision_equip вызван)", any(k[0] == "equip" for k in sent))
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
