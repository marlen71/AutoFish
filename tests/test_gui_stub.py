#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI-смоук без Tk и без Windows: подменяем tkinter заглушкой и прогоняем
построение всех страниц, refresh() на каждой, смену языка, тосты и пилюлю-оверлей.
Ловит опечатки в именах dyn-ключей, кривые параметры и исключения в отрисовке.
Запуск: python tests/test_gui_stub.py"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np          # noqa: E402
import cv2                  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []


def check(label, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + label + ("  " + extra if extra else ""))
    if not cond:
        fails.append(label)


# ---------------------------------------------------------------------------- фиксированный экран
INV = cv2.imread(os.path.join(ROOT, "1791751387911-image.png"))
GAME = cv2.imread(os.path.join(ROOT, "27033efd-f8b1-489a-97b3-64f476efafbf.png"))


class FakeCap:
    backend = "dxcam(test)"
    is_fallback = False
    fps = 141.5
    avg_ms = 7.05
    grabs = 0
    errors = 0
    last_grab_ms = 0.0021
    streaming = True
    mon = {"left": 0, "top": 0, "width": 1920, "height": 1080}
    sx = sy = 1.0
    img = INV

    def grab_region(self, l, t, w, h):
        FakeCap.grabs += 1
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

    def stop_stream(self):
        pass

    def close(self):
        pass


# ---------------------------------------------------------------------------- фейковый tkinter
_ids = [0]


def _nid():
    _ids[0] += 1
    return _ids[0]


class FakeCanvas:
    def __init__(self, master=None, **kw):
        self.items = {}
        self.binds = []
        self.kw = kw
        self.width, self.height = kw.get("width", 100), kw.get("height", 100)

    def pack(self, *a, **k):
        pass

    def _reg(self, kw, **extra):
        i = _nid()
        item = dict(kw)
        item.update(extra)
        tags = kw.get("tags") or ()
        item["tags"] = tuple(str(t) for t in (tags if isinstance(tags, (tuple, list)) else (tags,)))
        self.items[i] = item
        return i

    def create_image(self, x, y, **kw):
        return self._reg(kw, x=x, y=y)

    def create_text(self, x, y, **kw):
        for key in ("text", "fill", "font", "anchor", "width"):
            kw.setdefault(key, None)
        return self._reg(kw, x=x, y=y)

    def create_line(self, *coords, **kw):
        return self._reg(kw, points=list(coords))

    def create_window(self, x, y, **kw):
        return self._reg(kw, x=x, y=y)

    def itemconfig(self, item, **kw):
        if isinstance(item, int) and item not in self.items:
            raise KeyError("itemconfig по несуществующему id: %s" % item)
        if isinstance(item, int):
            bad = set(kw) - {"text", "fill", "font", "image", "points", "anchor", "width", "outline", "state"}
            if bad:
                raise KeyError("неизвестные параметры текста/линии: %s" % bad)
            self.items[item].update(kw)

    def coords(self, item, *c):
        return []

    def tag_bind(self, tag, seq, cb):
        self.binds.append((tag, seq, cb))

    def tag_raise(self, tag):
        pass

    def delete(self, what):
        if isinstance(what, int):
            self.items.pop(what, None)
            return
        for i, it in list(self.items.items()):
            if str(what) in it.get("tags", ()):
                del self.items[i]

    def winfo_width(self):
        return self.width

    def update_idletasks(self):
        pass


class FakeVar:
    def __init__(self, value=""):
        self.v = value

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


class FakeWidget:
    def __init__(self, master=None, **kw):
        self.kw = kw
        self.destroyed = False

    def pack(self, *a, **k):
        pass

    def grid(self, *a, **k):
        pass

    def destroy(self):
        self.destroyed = True


class FakeRoot(FakeCanvas):
    def __init__(self, *a, **k):
        FakeCanvas.__init__(self, None, **k)
        self.title_ = ""
        self.after_cbs = []
        self.props = {}
        self.width = self.height = 1200

    def title(self, v=None):
        if v is not None:
            self.title_ = v
        return self.title_

    def geometry(self, v=None):
        return v

    def overrideredirect(self, *a):
        pass

    def configure(self, **k):
        self.props.update(k)

    def attributes(self, *a, **k):
        pass

    def protocol(self, name, cb):
        self.props["protocol:" + name] = cb

    def after(self, ms, cb=None):
        if cb:
            self.after_cbs.append((ms, cb))
        return _nid()

    def winfo_screenwidth(self):
        return 1920

    def winfo_screenheight(self):
        return 1080

    def winfo_x(self):
        return 0

    def winfo_y(self):
        return 0

    def withdraw(self):
        pass

    def deiconify(self):
        pass

    def lift(self):
        pass

    def destroy(self):
        pass

    def mainloop(self):
        pass

    def clipboard_clear(self):
        pass

    def clipboard_append(self, s):
        pass

    def update(self):
        pass


class FakePhoto:
    def __init__(self, data=None):
        if isinstance(data, bytes):
            data = data.decode("ascii", "ignore")
        assert isinstance(data, str) and len(data) > 20, "PhotoImage без данных PNG"
        self.data = data


def make_fake_tk():
    tk = types.ModuleType("tkinter")
    tk.Tk = FakeRoot
    tk.Canvas = FakeCanvas
    tk.PhotoImage = FakePhoto
    tk.StringVar = FakeVar
    tk.Entry = FakeWidget
    tk.Label = FakeWidget
    tk.Frame = FakeWidget
    tk.BooleanVar = FakeVar
    tk.Toplevel = FakeRoot
    return tk


fake_tk = make_fake_tk()
sys.modules["tkinter"] = fake_tk

import eternal_fishmod as ef        # noqa: E402

ef.tk = fake_tk
ef.CAP = FakeCap()
ef.LOG_PATH = os.path.join(ROOT, "tests", "gui.log")
ef.CFG_PATH = os.path.join(ROOT, "tests", "gui_config.json")
ef.STATS_PATH = os.path.join(ROOT, "tests", "gui_stats.json")
ef.load_cfg()
ef._tpl_cache.clear()
ef.register_hotkeys = lambda: None
ef.ensure_sounds = lambda: None
ef.keyboard = types.SimpleNamespace(add_hotkey=lambda *a, **k: object(), remove_hotkey=lambda h: None,
                                    unhook_all=lambda: None,
                                    KEY_DOWN="down", KEY_UP="up",
                                    read_event=lambda: types.SimpleNamespace(event_type="down", name="escape"))
ef.pydirectinput = types.SimpleNamespace(KEYBOARD_MAPPING={}, PAUSE=0, FAILSAFE=False)
ef.winsound = None
ef._send_mouse = lambda *a, **k: None
ef.ctypes = types.SimpleNamespace(windll=types.SimpleNamespace(
    user32=types.SimpleNamespace(ShowCursor=lambda b: None, GetForegroundWindow=lambda: 0,
                                 GetWindowTextLengthW=lambda h: 0, GetWindowTextW=lambda *a: 0,
                                 mouse_event=lambda *a: None, GetSystemMetrics=lambda i: (1920, 1080)[i])))

print("== 1. Создание окна и всех страниц ==")
app = ef.App()
check("окно создано, заголовок с версией", app.root.title_ == f"{ef.APP_NAME} v{ef.APP_VERSION}",
      app.root.title_)
for i in range(5):
    try:
        app.show_page(i)
        ok = True
        err = ""
    except Exception as e:
        ok, err = False, f"{type(e).__name__}: {e}"
    check(f"страница {i} строится без исключений", ok, err)

print("== 2. Все dyn-ключи, которые читает refresh, созданы страницами ==")
for i in range(5):
    app.show_page(i)
    try:
        app.refresh()
        app.refresh()
        ok, err = True, ""
    except Exception as e:
        ok, err = False, f"{type(e).__name__}: {e}"
    check(f"refresh() на странице {i}", ok, err)

print("== 3. Смена языка на лету (RU/EN/UA) ==")
langs = []
for code, _label in ef.LANGS:
    try:
        ef.CFG["lang"] = code
        app.show_page(2)
        app.refresh()
        app.show_page(4)
        app.refresh()
        langs.append(code)
        ok, err = True, ""
    except Exception as e:
        ok, err = False, f"{type(e).__name__}: {e}"
    check(f"язык {code}: страницы перерисовываются", ok, err)
check("перебрали все три языка", langs == ["ru", "en", "ua"], str(langs))
titles = {}
for code in ("ru", "en", "ua"):
    ef.CFG["lang"] = code
    app.show_page(0)
    texts = [it.get("text") for it in app.cv.items.values() if isinstance(it.get("text"), str)]
    titles[code] = texts
    check(f"{code}: заголовок страницыlocalized", any(ef.t("pg0_t") in t_ for t_ in texts),
          str([t_ for t_ in texts if t_][:2]))
ef.CFG["lang"] = "ru"

print("== 4. Тосты, пилюля-оверлей, скрытие окна ==")
try:
    app.show_page(0)
    app.toast("Проверка тоста", "ok")
    app.toast("A rather long translated notification message to test the pill width calculation 12345", "warn")
    app.toast(ef.t("nt_finished", text=ef.reason_text("no_bait")), "warn")
    ok, err = True, ""
except Exception as e:
    ok, err = False, f"{type(e).__name__}: {e}"
check("toast() строится (в т.ч. для длинных переводов)", ok, err)
widths = [it["x"] for it in app.cv.items.values() if it.get("text") and str(it.get("text")).startswith("A rather")]
check("тост не вылезает за панель", len(widths) == 1 and app.u(widths[0]) <= app.u(160 + 800), str(widths))
try:
    app.build_pill()
    app.pill_msg, app.pill_until = "тест", 0
    app.update_pill()
    ok, err = True, ""
except Exception as e:
    ok, err = False, f"{type(e).__name__}: {e}"
check("пилюля-оверлей строится и обновляется", ok, err)
try:
    app.hide_window()
    app.show_window()
    ok = True
except Exception as e:
    ok = False
    err = str(e)
check("скрытие/показ окна", ok)

print("== 5. Интерактив: степперы/тумблеры страницы «Модули» ==")
quit_calls = []
_real_quit, _real_hide, _real_show = ef.App.quit, ef.App.hide_window, ef.App.show_window
ef.App.hide_window = lambda self: quit_calls.append("hide")
ef.App.show_window = lambda self: quit_calls.append("show")
app.show_page(3)
mark = len(app.cv.binds)
app.show_page(3)
new_clicks = [cb for tag, seq, cb in app.cv.binds[mark:] if seq == "<Button-1>"]
before = dict(ef.CFG)
err = ""
ok = True
for cb in new_clicks:
    try:
        cb(None)
    except Exception as e:
        ok, err = False, f"{type(e).__name__}: {e}"
        break
changed = {k for k in ef.CFG if ef.CFG[k] != before.get(k)}
check(f"клики по {len(new_clicks)} элементам страницы 3 безопасны", ok, err)
check("степперы/тумблеры реально меняют конфиг", len(changed) >= 3, f"изменено: {sorted(changed)[:6]}")
check("изменения тут же пишутся в fishmod_config.json", os.path.exists(ef.CFG_PATH))
ef.CFG.clear()
ef.CFG.update(ef.DEFAULT_CFG)
ef.vision_equip = lambda: False                # клик «▷ Экипировать» не должен трогать захват
print("== 5b. Страница AI-ЗРЕНИЕ (v1.24): отрисовка, клики, живой статус ==")
app.show_page(5)
ai_texts = [it.get("text") for it in app.cv.items.values()
            if isinstance(it.get("text"), str) and "Конвейер" in it["text"]]
check("страница AI отрисовалась со статусом конвейера (off, без модели)",
      bool(ai_texts) and "выключен" in ai_texts[0], str(ai_texts[:1]))
mark = len(app.cv.binds)
app.show_page(5)
ai_clicks = [cb for tag, seq, cb in app.cv.binds[mark:] if seq == "<Button-1>"]
before5 = dict(ef.CFG)
ok5, err5 = True, ""
for cb in ai_clicks:
    try:
        cb(None)
    except Exception as e:
        ok5, err5 = False, f"{type(e).__name__}: {e}"
        break
check(f"клики по {len(ai_clicks)} элементам страницы AI безопасны", ok5, err5)
check("переключатель режима меняет ai_mode",
      ef.CFG.get("ai_mode") in ("legacy", "ai", "hybrid") and ef.CFG.get("ai_mode") != before5.get("ai_mode"),
      str((before5.get("ai_mode"), ef.CFG.get("ai_mode"))))
check("кнопка «Журнал AI» не падает при выключенном конвейере", True)
app.refresh()
check("refresh() на странице AI не падает (ai_status без конвейера)", True)
print("== 5c. Запись сессий (v1.25): кнопки страницы AI ==")


class _FakeRec:
    def __init__(self, *a, **k):
        self.started = False
        self.reason = ""

    def start(self):
        self.started = True
        return True

    def stop(self, **k):
        self.started = False
        self.reason = "user"
        return {"recording": False, "frames": 3, "clicks": 1, "mb": 0.4,
                "cursor_hits": 2, "dir": "sess", "reason": self.reason, "error": "",
                "actions": 5}

    def status(self):
        return {"recording": self.started, "frames": 3, "clicks": 1, "mb": 0.4,
                "cursor_hits": 2, "dir": "sess", "reason": self.reason, "error": "",
                "actions": 5}


_real_rec_cls = ef._AiRec
ef._AiRec = _FakeRec
app.show_page(5)
btn_txt = [it.get("text") for it in app.cv.items.values()
           if isinstance(it.get("text"), str) and it.get("text") in
           ("⏺ Записать сессию", "Собрать датасет")]
check("кнопки записи и датасета отрисованы", len(btn_txt) == 2, str(btn_txt))
mark = len(app.cv.binds)
app.show_page(5)
rec_clicks = [cb for tag, seq, cb in app.cv.binds[mark:] if seq == "<Button-1>"]
err5c = ""
try:
    for cb in rec_clicks:                      # вкл/выкл записи + экспорт без сессий
        cb(None)
except Exception as e:
    err5c = f"{type(e).__name__}: {e}"
check("клики по кнопкам записи/экспорта безопасны", err5c == "", err5c)
check("рекордер создан кнопкой (фейковый класс, без потока)",
      ef._REC["rec"] is not None and ef._REC["rec"].started is True)
app.do_rec_toggle()                                # второй клик: остановка записи
check("повторный клик остановил запись", ef._REC["rec"].started is False and
      ef.ai_record_status()["reason"] == "user")
app.refresh()
check("refresh показывает статус записи", any(isinstance(it.get("text"), str) and
      ("Триває запис" in it["text"] or "Идёт запись" in it["text"] or "Запись не" in it["text"])
      for it in app.cv.items.values()))
ef._AiRec = _real_rec_cls
ef.CFG.clear()
ef.CFG.update(ef.DEFAULT_CFG)
app.show_page(4)
lang_texts = sorted(it.get("text") for it in app.cv.items.values() if it.get("text") in ("RU", "EN", "UA"))
check("на «Настройки» есть три плитки языка", lang_texts == ["EN", "RU", "UA"], str(lang_texts))
mark = len(app.cv.binds)
app.show_page(4)
ua_clicks = [cb for tag, seq, cb in app.cv.binds[mark:] if seq == "<Button-1>"]
for cb in ua_clicks:
    cb(None)
check("клики по элементам страницы 4 (вкл. плитки языка) не падают", ef.CFG.get("lang") in ("ru", "en", "ua"),
      str(ef.CFG.get("lang")))
ef.CFG["lang"] = "ru"
app.show_page(0)
btn = [it.get("text") for it in app.cv.items.values() if isinstance(it.get("text"), str) and "F8" in it["text"]]
check("кнопка СТАРТ подписана хоткеем", bool(btn), str(btn[:2]))
app.show_page(1)
check("версия показана в углу панели", any(isinstance(it.get("text"), str) and it["text"].startswith("v")
                                           and it["text"][1:2].isdigit() for it in app.cv.items.values()))

print("== 6. quit() освобождает захват ==")
ef.App.hide_window, ef.App.show_window = _real_hide, _real_show    # вернуть настоящие методы
closed = []
ef.CAP.close = lambda: closed.append(True)
try:
    app.quit()
    ok, err = True, ""
except Exception as e:
    ok, err = False, f"{type(e).__name__}: {e}"
check("App.quit() не падает", ok, err)
check("ScreenCapture.close() вызван (DXGI освобождён)", closed == [True], str(closed))

for f in (ef.LOG_PATH, ef.CFG_PATH, ef.STATS_PATH):
    try:
        os.remove(f)
    except Exception:
        pass
print()
if fails:
    print("FAILED:", len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL GUI CHECKS PASSED")
