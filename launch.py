#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Eternal FishMod — launcher / обёртка приложения.

Делает ровно то, что нужно перед запуском бота:
  [1/4] проверяет версию Python;
  [2/4] проверяет зависимости (opencv-python, numpy, dxcam/bettercam, pydirectinput,
        keyboard, tkinter) и при нехватке ставит их через pip (reqs из requirements.txt);
  [3/4] проверяет права администратора (SendInput/DXGI не работают поверх игры от админа)
        и умеет перезапустить себя через UAC («runas»);
  [4/4] запускает eternal_fishmod.py отдельным процессом и следит за ним.

Запуск:
    python launch.py                — обычный запуск
    python launch.py --yes          — ставить недостающие библиотеки без вопроса
    python launch.py --no-install   — ничего не ставить, только проверить
    python launch.py --restart      — перезапускать бота, если он упал (кроме Ctrl+C/паники)
    python launch.py --admin        — сразу попросить повышенные права (через UAC)
    python launch.py --lang en      — язык сообщений лаунчера (ru|en|ua; по умолчанию берётся
                                      из fishmod_config.json, иначе en)

Сообщения лаунчера переведены (ru/en/ua); полный перевод интерфейса самого бота — в
eternal_fishmod.py (STRINGS), язык меняется на лету на странице «Настройки».
"""
import os
import sys
import json
import time
import ctypes
import codecs
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(HERE, "eternal_fishmod.py")
REQS = os.path.join(HERE, "requirements.txt")
CFG = os.path.join(HERE, "fishmod_config.json")
VERSION_FILE = os.path.join(HERE, "VERSION")
APP = "Eternal FishMod"

IS_WIN = os.name == "nt"
ANSI_OK = False
if IS_WIN:
    try:                                    # включает VT-последовательности в консоли Win10+
        h = ctypes.windll.kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if ctypes.windll.kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            ANSI_OK = bool(ctypes.windll.kernel32.SetConsoleMode(h, mode.value | 0x0004))
    except Exception:
        ANSI_OK = False
if not ANSI_OK and not IS_WIN:
    ANSI_OK = sys.stdout.isatty()


# ------------------------------------------------------------------ консоль
# Никаких падений из-за кодировки: если вывод перенаправлен в файл/pipe с
# однобайтовой кодовой страницей (cp866/cp1251), пиктограммы вроде ✓ или 🖥
# иначе утонули бы в UnicodeEncodeError — то есть в «сыром» трейсбеке, что
# противоречит обещанию «человеческих» сообщений лаунчера.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass


def paint(text, code):
    return f"\033[{code}m{text}\033[0m" if ANSI_OK else text


def c_ok(t_):
    return paint(t_, "32")


def c_err(t_):
    return paint(t_, "31")


def c_warn(t_):
    return paint(t_, "33")


def c_dim(t_):
    return paint(t_, "90")


def c_hi(t_):
    return paint(t_, "1")


# --------------------------------------------------------------------------- локализация лаунчера
LS = {
 "ru": {
  "step_py": "Проверяем Python…",
  "py_ok": "Python {v} — подходит (нужен 3.8+)",
  "py_bad": "Нужен Python 3.8 или новее, найден {v}. Установи с python.org и поставь галочку «Add to PATH».",
  "step_libs": "Проверяем библиотеки…",
  "lib_ok": "Все зависимости на месте",
  "lib_missing": "Не хватает: {names}",
  "lib_optional": "Не найдено (не страшно): {names}",
  "ask_install": "Установить недостающие сейчас? [Y/n]",
  "installing": "Ставим через pip: {args}",
  "install_done": "Готово, библиотеки установлены",
  "install_fail": "pip завершился с ошибкой (код {code}). Поставь вручную: pip install -r requirements.txt",
  "no_install": "Автоустановка выключена (--no-install) — ставим вручную: pip install -r requirements.txt",
  "step_admin": "Проверяем права администратора…",
  "admin_ok": "Права администратора есть",
  "admin_no": "Нет прав администратора. Если игра запущена от админа, клики (SendInput) и захват экрана могут не работать.",
  "admin_ask": "Запустить лаунчер от администратора? [Y/n]",
  "admin_denied": "Понятно, продолжаем без админа. Если бот «не видит» игру — запусти этот файл от администратора.",
  "admin_uac": "Отказ в UAC — запускаемся с обычными правами.",
  "admin_no_win": "Определение прав доступно только на Windows — пропускаем.",
  "step_run": "Запускаем бота…",
  "note_lang": "Подсказка: язык интерфейса бота (RU/EN/UA) меняется на странице «Настройки».",
  "banner1": "полупрозрачный помощник по рыбалке · Skyrim RP",
  "version": "версия",
  "started": "Бот запущен (pid {pid}). F8 — старт/стоп, F10 — аварийный стоп.",
  "exited": "Бот завершился, код {code}",
  "restarting": "Перезапускаем через {sec} с (Ctrl+C — выход)…",
  "bye": "Всё, выходим.",
  "no_main": "Не найден {f} рядом с launch.py — распакуй архив целиком.",
  "traceback": "Ошибка лаунчера: {type}: {msg}",
  "help_epilog": "Подробнее — README.md",
  "pip_note": "Примечание: ставим в текущий интерпретатор {exe}",
  "tk_hint": "tkinter не найден — переустанови Python с галочкой «tcl/tk and IDLE».",
  "capture_ok": "Захват DXGI доступен: {b}",
  "capture_no": "Ни dxcam, ни bettercam не импортируются — без DXGI-захвата бот работать не сможет; ставлю обе библиотеки сейчас.",
  "capture_gdi": "бот сможет работать на встроенном резерве GDI (ctypes, без зависимостей) — он чуть медленнее и не видит защищённые от захвата окна. После установки DXGI-библиотек перезапусти бота.",
 },
 "en": {
  "step_py": "Checking Python…",
  "py_ok": "Python {v} — fine (3.8+ required)",
  "py_bad": "Python 3.8+ is required, found {v}. Install it from python.org and tick “Add to PATH”.",
  "step_libs": "Checking libraries…",
  "lib_ok": "All dependencies are present",
  "lib_missing": "Missing: {names}",
  "lib_optional": "Not found (optional): {names}",
  "ask_install": "Install what is missing now? [Y/n]",
  "installing": "Installing with pip: {args}",
  "install_done": "Done, libraries installed",
  "install_fail": "pip failed (exit code {code}). Install manually: pip install -r requirements.txt",
  "no_install": "Auto-install is off (--no-install) — run: pip install -r requirements.txt",
  "step_admin": "Checking administrator rights…",
  "admin_ok": "Running as administrator",
  "admin_no": "Not running as administrator. If the game runs elevated, SendInput clicks and screen capture may not work.",
  "admin_ask": "Relaunch this launcher as administrator? [Y/n]",
  "admin_denied": "OK, continuing without admin rights.",
  "admin_uac": "UAC was declined — starting with normal privileges.",
  "admin_no_win": "Admin check is only meaningful on Windows — skipping.",
  "step_run": "Starting the bot…",
  "note_lang": "Hint: the bot's UI language (RU/EN/UA) is switched on the “Settings” page.",
  "banner1": "semi-automatic fishing helper · Skyrim RP",
  "version": "version",
  "started": "Bot started (pid {pid}). F8 = start/stop, F10 = panic stop.",
  "exited": "Bot exited, code {code}",
  "restarting": "Restarting in {sec} s (Ctrl+C to quit)…",
  "bye": "Bye.",
  "no_main": "{f} not found next to launch.py — unpack the whole archive.",
  "traceback": "Launcher error: {type}: {msg}",
  "help_epilog": "Docs: README.md",
  "pip_note": "Note: installing into the current interpreter {exe}",
  "tk_hint": "tkinter is missing — reinstall Python with the “tcl/tk and IDLE” component.",
  "capture_ok": "DXGI capture available: {b}",
  "capture_no": "Neither dxcam nor bettercam imports — without DXGI capture the bot cannot run; installing both libraries now.",
  "capture_gdi": "the bot can run on its built-in GDI fallback (ctypes, no dependencies) — a bit slower, and it cannot see capture-protected windows. Restart the bot after installing the DXGI libraries.",
 },
 "ua": {
  "step_py": "Перевіряємо Python…",
  "py_ok": "Python {v} — підходить (потрібен 3.8+)",
  "py_bad": "Потрібен Python 3.8 або новіший, знайдено {v}. Встанови з python.org і постав галочку «Add to PATH».",
  "step_libs": "Перевіряємо бібліотеки…",
  "lib_ok": "Усі залежності на місці",
  "lib_missing": "Не вистачає: {names}",
  "lib_optional": "Не знайдено (не критично): {names}",
  "ask_install": "Встановити недостаюче зараз? [Y/n]",
  "installing": "Ставимо через pip: {args}",
  "install_done": "Готово, бібліотеки встановлено",
  "install_fail": "pip завершився з помилкою (код {code}). Встанови вручну: pip install -r requirements.txt",
  "no_install": "Автоустановку вимкнено (--no-install) — вручну: pip install -r requirements.txt",
  "step_admin": "Перевіряємо права адміністратора…",
  "admin_ok": "Права адміністратора є",
  "admin_no": "Немає прав адміністратора. Якщо гра запущена від адміна, кліки (SendInput) та захват екрана можуть не працювати.",
  "admin_ask": "Запустити лаунчер від адміністратора? [Y/n]",
  "admin_denied": "Зрозуміло, продовжуємо без адміна.",
  "admin_uac": "Відмова в UAC — запускаємо зі звичайними правами.",
  "admin_no_win": "Визначення прав доступне лише у Windows — пропускаємо.",
  "step_run": "Запускаємо бота…",
  "note_lang": "Підказка: мову інтерфейсу бота (RU/EN/UA) змінюють на сторінці «Налаштування».",
  "banner1": "напівавтомат риболовлі · Skyrim RP",
  "version": "версія",
  "started": "Бота запущено (pid {pid}). F8 — старт/стоп, F10 — аварійний стоп.",
  "exited": "Бот завершився, код {code}",
  "restarting": "Перезапуск через {sec} с (Ctrl+C — вихід)…",
  "bye": "Усе, виходимо.",
  "no_main": "Не знайдено {f} поруч із launch.py — розпакуй архів повністю.",
  "traceback": "Помилка лаунчера: {type}: {msg}",
  "help_epilog": "Докладніше — README.md",
  "pip_note": "Зауваж: ставимо у поточний інтерпретатор {exe}",
  "tk_hint": "tkinter не знайдено — перевстанови Python з компонентом «tcl/tk and IDLE».",
  "capture_ok": "Захват DXGI доступний: {b}",
  "capture_no": "Ні dxcam, ні bettercam не імпортується — без DXGI-захвата бот не працюватиме; ставлю обидві бібліотеки зараз.",
  "capture_gdi": "бот зможе працювати на вбудованому резервi GDI (ctypes, без залежностей) — трішки повільніший і не бачить вікон, захищених від захоплення. Пiсля встановлення DXGI-бiблiотек перезапусти бота.",
 },
}


def load_lang():
    for f in (lambda: json.load(open(CFG, encoding="utf-8")).get("lang"),):
        try:
            v = f()
            if v in LS:
                return v
        except Exception:
            pass
    for i, a in enumerate(sys.argv):
        if a == "--lang" and i + 1 < len(sys.argv) and sys.argv[i + 1] in LS:
            return sys.argv[i + 1]
        if a.startswith("--lang=") and a.split("=", 1)[1] in LS:
            return a.split("=", 1)[1]
    return "en"


LANG = load_lang()


def L(key, **kw):
    txt = LS[LANG].get(key) or LS["en"].get(key) or key
    try:
        return txt.format(**kw)
    except Exception:
        return txt


def say(text, code=None):
    try:
        print(paint(text, code) if code else text, flush=True)
    except Exception:
        try:
            print(text.encode("ascii", "ignore").decode("ascii"), flush=True)
        except Exception:
            pass


def step(n, total, text):
    say("")
    say(c_hi(paint(f"[{n}/{total}]", "36")) + " " + text)


def hr(char="─", n=72):
    say(c_dim(char * n))


def read_version():
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            v = f.read().strip()
            if v:
                return v
    except Exception:
        pass
    try:                                    # запасной вариант — константа из главного файла
        import re
        with open(MAIN, "r", encoding="utf-8") as f:
            m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', f.read(), re.M)
            if m:
                return m.group(1)
    except Exception:
        pass
    return "0.0.0"


# --------------------------------------------------------------------------- проверки
def check_python():
    v = "%d.%d.%d" % sys.version_info[:3]
    if sys.version_info < (3, 8):
        say(c_err(L("py_bad", v=v)))
        return False
    say(c_ok("✓ ") + L("py_ok", v=v))
    return True


REQUIRED = [                                   # (имя в requirements, модуль для import, обязательно?)
    ("opencv-python", "cv2", True),
    ("numpy", "numpy", True),
    ("pydirectinput", "pydirectinput", True),
    ("keyboard", "keyboard", True),
    ("tkinter", "tkinter", False),             # обязателен по сути, но ставится не pip'ом
]
OPTIONAL_CAPTURE = ["dxcam", "bettercam"]     # резервный GDI-захват вшит
                                               # в бота (ctypes): никаких pip-зависимостей


def check_libs(auto_install, yes):
    import importlib
    missing, opt_missing = [], []
    for pkg, mod, _hard in REQUIRED:
        if mod == "tkinter":
            try:
                importlib.import_module("tkinter")
            except Exception:
                say(c_warn("⚠ ") + L("tk_hint"))
                missing.append(pkg)
            continue
        try:
            m_ = importlib.import_module(mod)
            v = getattr(m_, "__version__", None) or getattr(m_, "VERSION", None)
            say(c_ok("✓ ") + c_dim(f"{pkg:<16} ") + (str(v) if v else "ok"))
        except Exception:
            missing.append(pkg)
    cap = None
    for mod in OPTIONAL_CAPTURE:
        try:
            importlib.import_module(mod)
            cap = mod
            say(c_ok("✓ ") + c_dim(f"{mod:<16} ") + paint(L("capture_ok", b=mod), "32"))
            break
        except Exception:
            opt_missing.append(mod)
    if cap is None:
        say(c_warn("⚠ ") + L("capture_no"))
        if IS_WIN:
            # Ставим ОБЕ DXGI-библиотеки: они дублируют друг друга, и если одна не
            # заведётся (драйвер, гибридная GPU, свежая версия Python), бот возьмёт вторую.
            for mod in OPTIONAL_CAPTURE:
                if mod not in missing:
                    missing.append(mod)
    if not missing:
        if not opt_missing or cap:
            say(c_ok("✓ ") + L("lib_ok"))
        return True
    say(c_err("✗ ") + L("lib_missing", names=", ".join(missing)))
    if not auto_install:
        say(c_warn("→ ") + L("no_install"))
        return False
    if not yes:
        try:
            ans = input(L("ask_install") + " ").strip().lower()
        except Exception:
            ans = "y"
        if ans in ("n", "нет", "ні"):
            say(c_warn("→ ") + L("no_install"))
            return False
    args = [sys.executable, "-m", "pip", "install", "-r", REQS] if os.path.exists(REQS) else \
           [sys.executable, "-m", "pip", "install"] + missing
    say(c_dim(L("pip_note", exe=sys.executable)))
    say(c_hi(L("installing", args=" ".join(args[3:]))))
    hr("·")
    t0 = time.time()
    r = subprocess.run(args)
    hr("·")
    if r.returncode != 0:
        r2 = subprocess.run(args + ["--user"])       # вторая попытка — в каталог пользователя
        if r2.returncode != 0:
            say(c_err("✗ ") + L("install_fail", code=r.returncode))
            return False
    say(c_ok("✓ ") + L("install_done") + c_dim(f"  ({time.time() - t0:.0f} s)"))
    for pkg, mod, _ in REQUIRED:
        try:
            importlib.invalidate_caches()
            importlib.import_module(mod)
        except Exception:
            if mod == "tkinter":
                continue
            say(c_err("✗ ") + f"{pkg}: " + "import still fails")
            return False
    return True


def is_admin():
    if not IS_WIN:
        return None
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return None


def relaunch_as_admin(extra):
    """Перезапуск этого лаунчера с повышенными правами (UAC). Возвращает True, если удалось."""
    params = " ".join(f'"{a}"' if " " in a else a for a in [os.path.abspath(__file__)] + extra + ["--already-elevated"])
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, HERE, 1)
        return int(rc) > 32
    except Exception:
        return False


def check_admin(force_ask=True):
    if "--already-elevated" in sys.argv:
        say(c_ok("✓ ") + L("admin_ok"))
        return True
    adm = is_admin()
    if adm is None:
        say(c_dim("· ") + L("admin_no_win"))
        return True
    if adm:
        say(c_ok("✓ ") + L("admin_ok"))
        return True
    say(c_warn("⚠ ") + L("admin_no"))
    if not force_ask:
        return True
    try:
        ans = input(L("admin_ask") + " ").strip().lower()
    except Exception:
        ans = "y"
    if ans in ("", "y", "yes", "да", "так"):
        if relaunch_as_admin(sys.argv[1:]):
            say(c_ok("✓ ") + "UAC — " + paint("OK", "32") + "; " + APP + " " + c_dim("restart"))
            say(c_ok(L("bye")))
            sys.exit(0)
        say(c_warn("⚠ ") + L("admin_uac"))
    else:
        say(c_dim("· ") + L("admin_denied"))
    return True


# --------------------------------------------------------------------------- запуск
def run_bot(restart):
    if not os.path.exists(MAIN):
        say(c_err("✗ ") + L("no_main", f="eternal_fishmod.py"))
        return 2
    code = ["-X", "utf8", MAIN]
    while True:
        step(4, 4, L("step_run"))
        t0 = time.time()
        try:
            p = subprocess.Popen([sys.executable] + code, cwd=HERE)
        except OSError as e:
            say(c_err("✗ ") + f"{e}")
            return 1
        say(c_ok("▶ ") + L("started", pid=p.pid))
        hr()
        try:
            rc = p.wait()
        except KeyboardInterrupt:
            say("")
            try:
                p.terminate()
                for _ in range(50):
                    if p.poll() is not None:
                        break
                    time.sleep(0.1)
                else:
                    p.kill()
            except Exception:
                pass
            say(c_warn("■ ") + L("bye"))
            return 0
        say(c_dim("· ") + L("exited", code=rc) + c_dim(f"  ({time.time() - t0:.0f} s)"))
        if not restart or rc == 0:
            return rc
        for s in (5, 4, 3, 2, 1):
            say(c_warn("↻ ") + L("restarting", sec=s))
            time.sleep(1)


def banner(ver):
    logo = [
        r"  ______           _         _____ _     _   ",
        r" |  ____|         | |       |  ___| |   | |  ",
        r" | |__ _  _____  _| |_ ___  | |_  | |   | |_ ",
        r" |  __| |/ / _ \|_   _/ _ \ |  _| | |   | __|",
        r" | |  |   <  __/  | ||  __/ | |   | |___| |_ ",
        r" |_|  |_|\_\___|  |_| \___| |_|   |_____|\__|",
    ]
    for ln in logo:
        say(paint(ln, "31"))
    say(c_dim(" " * 12) + paint(APP, "1") + " " + c_dim(f"v{ver}") + "  ·  " + L("banner1"))
    say(c_dim(" " * 12) + c_dim(L("version") + ": ") + paint(ver, "33") +
        c_dim("   ·   https://github.com/marlen71/AutoFish"))
    hr("═")


def main():
    ver = read_version()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        try:
            sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "replace")
        except Exception:
            pass
    banner(ver)
    yes = ("--yes" in sys.argv or "-y" in sys.argv or "--auto-install" in sys.argv)
    auto_install = "--no-install" not in sys.argv
    restart = "--restart" in sys.argv
    try:
        step(1, 4, L("step_py"))
        if not check_python():
            return 3
        step(2, 4, L("step_libs"))
        if not check_libs(auto_install, yes):
            if not yes:
                try:
                    input("\nEnter — exit / Выход")
                except Exception:
                    pass
            return 4
        step(3, 4, L("step_admin"))
        check_admin(force_ask=IS_WIN and "--no-admin-ask" not in sys.argv)
        return run_bot(restart)
    except KeyboardInterrupt:
        say("")
        say(c_warn("■ ") + L("bye"))
        return 130
    except Exception as e:
        say("")
        say(c_err("✗ ") + L("traceback", type=type(e).__name__, msg=e))
        say(c_dim("→ ") + L("help_epilog"))
        if "--debug" in sys.argv:
            import traceback
            traceback.print_exc()
        return 1
    finally:
        if ANSI_OK:
            try:
                sys.stdout.write("\033[0m")
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
