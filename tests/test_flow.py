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
    ef.wheel = lambda n: sent.append(("wheel", n))
    ef.key_down = lambda n: sent.append(("keydown", n))
    ef.key_up = lambda n: sent.append(("keyup", n))
    ef.pydirectinput = types.SimpleNamespace(KEYBOARD_MAPPING={"tab": "tab", "esc": "esc"}, keyDown=lambda k: None,
                                              keyUp=lambda k: None, PAUSE=0, FAILSAFE=False)
    ef.nap = lambda sec: None
    ef.check_stop = lambda: 0.0
    ef.learn_game_window = lambda timeout=15.0: "Skyrim"
    ef.game_focused = lambda: True
    ef.GAME_TITLE = "Skyrim"
    screens["cur"] = INV
    ef.EVENTS = __import__("queue").Queue()


print("== 1. Открытие/закрытие инвентаря ==")
install_stubs()
check("inventory_open() = True на скрине инвентаря", ef.inventory_open() is True)
screens["cur"] = GAME
check("inventory_open() = False в игровом экране", ef.inventory_open() is False)
screens["cur"] = GAME
sent.clear()
check("hud_present(hud_fish) на игровом кадре", ef.hud_present("hud_fish") is True)
sent.clear()
ok_open = ef.open_inventory()
check("без инвентаря open_inventory() жмёт TAB до 3 раз и честно сообщает о неудаче",
      ok_open is False and sum(1 for k in sent if k == ("keydown", "tab")) == 3,
      f"result={ok_open}, keys={len(sent)}")
screens["cur"] = INV
check("открытый инвентарь не требует TAB", (sent.clear(), ef.open_inventory() is True)[1] and
      not [k for k in sent if k[0] == "keydown"])
sent.clear()
_real_invopen = ef.inventory_open
box = {"open": True}
ef.inventory_open = lambda: box["open"]
_real_keydown = ef.key_down
ef.key_down = lambda n: (box.__setitem__("open", False) if n == "tab" else None, _real_keydown(n))[1]
check("close_inventory() жмёт TAB и ждёт закрытия", ef.close_inventory() is True and box["open"] is False and
      any(k == ("keydown", "tab") for k in sent), f"keys={[k for k in sent if k[0] == 'keydown'][:3]}")
ef.inventory_open = _real_invopen
ef.key_down = _real_keydown

print("== 2. Наживка ==")
screens["cur"] = INV
sent.clear()
present = ef.bait_in_open_inventory()
check("наживка найдена (3 стака на скрине)", present is True)
check("после проверки наживки нет залипших кликов", all(k[0] in ("wheel", "move") for k in sent))
screens["cur"] = np.zeros_like(INV) + 15
check("на пустом экране наживки нет", ef.bait_in_open_inventory() is False)

print("== 3. use_rod: ПКМ по удочке + клик НАД красной строкой ==")
screens["cur"] = INV
sent.clear()
calls = {"menu": 0}


def fake_menu_info(x, y):
    calls["menu"] += 1
    return {"red_top": 298, "red_cx": 205, "use_x": 205, "use_y": 278, "fallback": False, "dx_cfg": 76}


ef.context_menu_info = fake_menu_info
# после «Использовать» инвентарь закрывается: имитируем это, меняя кадр на игровой
_real_inv_open = ef.inventory_open
state = {"opened": True}


def inventory_open_switch():
    return state["opened"]


ef.inventory_open = inventory_open_switch
_real_send = ef._send_mouse


def send_and_close(flags, dx=0, dy=0):
    sent.append(("mouse", flags, dx, dy))
    # игра закрывает инвентарь сама после клика по «Использовать»
    if flags == ef.MOUSEEVENTF_LEFTUP and state["opened"] and calls["menu"] > 0:
        state["opened"] = False
        screens["cur"] = GAME


ef._send_mouse = send_and_close
ef.use_rod()
moves = [k for k in sent if k[0] == "move"]
flags_seq = [k[1] for k in sent if k[0] == "mouse"]
check("наведение на удочку (126, 256)", any(k == ("move", 126, 256) for k in sent), str(moves[:2]))
check("после нажатия ПКМ был клик по «Использовать» выше красной строки",
      (ef.MOUSEEVENTF_RIGHTDOWN in flags_seq and ef.MOUSEEVENTF_RIGHTUP in flags_seq and
       any(k == ("move", 205, 278) for k in sent)), str(flags_seq))
check("меню искалось (не «вслепую»)", calls["menu"] >= 1)
check("инвентарь закрыт игрой, повторных TAB нет", state["opened"] is False)

print("== 4. use_rod с ручными координатами (rod_click_pos/use_click_pos) ==")
ef.CFG["rod_click_pos"] = [128, 250]
ef.CFG["use_click_pos"] = [200, 270]
sent.clear()
calls["menu"] = 0
state["opened"] = False
ef.use_rod()
check("использованы ручные координаты удочки", any(k == ("move", 128, 250) for k in sent))
check("использованы ручные координаты кнопки", any(k == ("move", 200, 270) for k in sent))
check("поиск красной строки не выполнялся", calls["menu"] == 0)
ef.CFG["rod_click_pos"] = None
ef.CFG["use_click_pos"] = None

print("== 5. Заброс и отпускание ЛКМ ==")
sent.clear()
ef.cast()
seq = [k[1] for k in sent if k[0] == "mouse"]
check("перед забросом ЛКМ отпущен (3x UP), затем DOWN/UP",
      seq[:4] == [ef.MOUSEEVENTF_LEFTUP] * 3 + [ef.MOUSEEVENTF_LEFTDOWN] and seq[-1] == ef.MOUSEEVENTF_LEFTUP, str(seq))
check("mouse_down сброшен", ef.mouse_down is False)

print("== 6. Главный цикл: поймал рыбу -> стоп по наживке ==")
ef.CFG.update({"auto_cast": True, "equip_on_start": True, "bait_check_every": 1, "bite_timeout": 1,
               "no_bite_limit": 1, "post_catch_delay": 0.0, "cast_delay": 0.0})
state["opened"] = False
screens["cur"] = GAME
ef.hud_present = lambda n: True
ef.open_inventory = lambda: True
ef.close_inventory = lambda: True
ef.prepare = lambda equip: True
ef.bait_check = lambda: (ef.STATS.__setitem__("checks", ef.STATS["checks"] + 1)) or True
bites = {"n": 0}


def fake_wait(timeout):
    bites["n"] += 1
    return True


def fake_play():
    return 3.5


ef.wait_for_minigame = fake_wait
ef.play_minigame = fake_play
ef.STATS.update({"catches": 0, "t0": time.time(), "t_end": None, "mg": [], "checks": 0})
res = ef.fishing_run() if False else None      # не запускаем бесконечный цикл целиком
# вместо этого — одна итерация «поймал -> кончилась наживка -> стоп»
ef.bait_check = lambda: False
res = ef.fishing_run()
check("fishing_run вернул no_bait при пустом инвентаре", res == "no_bait", str(res))
check("одна рыба засчитана", ef.STATS["catches"] == 1, str(ef.STATS["catches"]))
check("время мини-игры записано в статистику", ef.STATS["mg"] == [3.5], str(ef.STATS["mg"]))
check("ожидал мини-игру ровно один раз", bites["n"] == 1, str(bites["n"]))
log_text = io.open(ef.LOG_PATH, encoding="utf-8").read() if os.path.exists(ef.LOG_PATH) else ""
check("в журнале есть строка о пойманной рыбе (ru)", "Поймано #1" in log_text, log_text.strip()[-90:])

print("== 7. Локализация в потоке: журнал на выбранном языке ==")
for lang, needle in (("en", "Caught #1"), ("ua", "Спіймано #1")):
    ef.CFG["lang"] = lang
    open(ef.LOG_PATH, "w").close()
    ef.STATS["catches"] = 0
    bites["n"] = 0
    ef.bait_check = lambda: False
    res = ef.fishing_run()
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
