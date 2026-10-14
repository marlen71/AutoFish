#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка «якорных» файлов запуска: start.bat, start_admin.bat, start.vbs.

Пойма ровно ту болячку, из-за которой двойной клик по start.bat выдавал
«'el' is not recognized as an internal or external command» и код 9009:
cmd.exe читает .bat посимвольно и хранит байтовые смещения строк, а wscript.exe
читает .vbs как ANSI. Кириллица внутри таких файлов и/или LF-переводы съезжают,
и выполняться начинают обрезки соседних строк. Отсюда инварианты:

  * только ASCII, ровно CRLF, без BOM;
  * блоки ( ... ) сбалансированы, все goto ведут на существующие метки;
  * в echo-строках нет `< > & |` и одиночных `!` (delayed expansion их съедает);
  * флаги, которые .bat/.vbs передают в launch.py, там действительно распознаны;
  * собранная .vbs командная строка синтаксически корректна (проверяем мини-
    интерпретатором конкатенаций, без Windows под рукой).

Запуск: python tests/test_launcher_files.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

fails = []


def check(label, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + label + ("  " + extra if extra else ""))
    if not cond:
        fails.append(label)


def raw(name):
    with open(os.path.join(ROOT, name), "rb") as f:
        return f.read()


def text(name):
    return raw(name).decode("utf-8", "replace")


def lines_of(name):
    """Строки без переводов; 'text' уже без BOM-шума."""
    return text(name).replace("\r\n", "\n").split("\n")


# ------------------------------------------------------------------ 1. кодировка/переводы
print("== 1. start.bat / start_admin.bat / start.vbs: ASCII + CRLF + без BOM ==")
LAUNCHERS = ["start.bat", "start_admin.bat", "start.vbs"]
for name in LAUNCHERS:
    path = os.path.join(ROOT, name)
    check("%s существует" % name, os.path.exists(path))
    if not os.path.exists(path):
        continue
    b = raw(name)
    non_ascii = sorted({c for c in b if c > 127})
    lone_lf = b.count(b"\n") - b.count(b"\r\n")
    lone_cr = b.count(b"\r") - b.count(b"\r\n")
    check("%s: ни одного не-ASCII байта" % name, not non_ascii,
          "%d байт(а): %s" % (len(non_ascii), [hex(c) for c in non_ascii[:5]]) if non_ascii else "")
    check("%s: переводы строк только CRLF" % name, lone_lf == 0 and lone_cr == 0,
          "lone LF=%d, lone CR=%d" % (lone_lf, lone_cr))
    check("%s: без BOM" % name, b[:3] != b"\xef\xbb\xbf" and b[:2] not in (b"\xff\xfe", b"\xfe\xff"))
    if name.endswith(".bat"):
        check("%s: первая строка — @echo off" % name, lines_of(name)[0].strip() == "@echo off")
        check("%s: есть setlocal и endlocal (не мусорим в окружение)" % name,
              any(l.strip().startswith("setlocal") for l in lines_of(name))
              and any("endlocal" in l for l in lines_of(name)))
        check("%s: консоль переведена в UTF-8 (chcp 65001) либо это делегат" % name,
              any(re.search(r"^\s*chcp\s+65001", l) for l in lines_of(name))
              or 'call "%~dp0start.bat"' in text(name))
        check("%s: напоминание про ASCII/CRLF в шапке" % name,
              "PURE ASCII" in text(name).upper() and "CRLF" in text(name).upper())
    else:
        check("%s: Option Explicit включён" % name, any("Option Explicit" in l for l in lines_of(name)))

# ------------------------------------------------------------------ 2. .gitattributes
print("== 2. .gitattributes держит CRLF для .bat/.vbs при любом клонировании ==")
ga = text(".gitattributes") if os.path.exists(os.path.join(ROOT, ".gitattributes")) else ""
check(".gitattributes существует", bool(ga))
for pat in ("*.bat", "*.cmd", "*.vbs"):
    check("%s -> text eol=crlf" % pat,
          bool(re.search(re.escape(pat) + r"\s+text\s+eol=crlf", ga)))
check("есть правило 'text=auto' по умолчанию", bool(re.search(r"^\*\s+text=auto", ga, re.M)))

# ------------------------------------------------------------------ 3. синтаксис батников
print("== 3. start.bat / start_admin.bat: блоки, метки, опасные символы ==")


def strip_quotes(line):
    out, q = [], False
    for ch in line:
        if ch == '"':
            q = not q
            continue
        if not q:
            out.append(ch)
    return "".join(out)


def bat_problems(name):
    """(проблемы) — наивная, но строгая проверка того, что реально ломает cmd.exe."""
    bad = []
    ls = lines_of(name)
    depth = 0
    labels = {l.strip()[1:].lower() for l in ls if l.strip().startswith(":") and len(l.strip()) > 1}
    for i, l in enumerate(ls, 1):
        s = l.strip()
        if not s or s.lower().startswith("rem ") or s.lower() == "rem":
            continue
        body = strip_quotes(s)
        # «echo <текст>»: спецсимволы вне кавычек cmd сожрёт
        if body.lower().startswith("echo ") or body.lower() == "echo.":
            if re.search(r"[<>|&]", body[5:]):
                bad.append("строка %d: echo содержит <, >, | или & — cmd обрывает команду" % i)
            txt = body[5:]
            if re.sub(r"![A-Za-z_][A-Za-z0-9_]*!", "", txt).count("!") % 2:
                bad.append("строка %d: одиночный '!' — delayed expansion съест его с соседним" % i)
        depth += body.count("(") - body.count(")")
        if depth < 0:
            bad.append("строка %d: закрывающая ) без открывающей (" % i)
            depth = 0
        m = re.search(r"\bgoto\s+:?([A-Za-z0-9_]+)", body, re.I)
        if m and m.group(1).lower() not in labels and m.group(1).lower() != "eof":
            bad.append("строка %d: goto :%s — такой метки нет" % (i, m.group(1)))
    if depth != 0:
        bad.append("несбалансированные ( ... ): остаток %d" % depth)
    return bad, labels


for name in ("start.bat", "start_admin.bat"):
    problems, labels = bat_problems(name)
    check("%s: синтаксис блоков/меток/спецсимволов чист" % name, not problems, "; ".join(problems[:4]))
    check("%s: есть метки для всех goto" % name,
          all(l in labels for l in ("launch", "run", "finish")) if name == "start.bat"
          else "run" in labels, str(sorted(labels)))
    t = text(name)
    check("%s: аргументы пользователя пробрасываются (%%*)" % name, "%*" in t)
    if name == "start.bat":          # именно здесь живёт запуск; start_admin — делегат
        check("%s: запуск через launch.py (весь перевод — на Python-стороне)" % name,
              "launch.py" in t and "-X utf8" in t)
        check("%s: окно не закрывается после ошибки (pause на ветке ненулевого кода)" % name,
              "pause" in t)
        check("%s: python ищется прогоном интерпретатора, а не 'where python'" % name,
              re.search(r"-c \"import sys\"", t) is not None)
        check("%s: launch.py ищется рядом с .bat" % name, 'if exist "%~dp0launch.py"' in t)

check("start_admin.bat: проверяет повышенные права (net session)",
      "net session" in text("start_admin.bat"))
check("start_admin.bat: поднимает UAC через -Verb RunAs",
      "-Verb RunAs" in text("start_admin.bat"))
check("start_admin.bat: переиспользует start.bat, а не дублирует запуск",
      re.search(r'call\s+"%~dp0start\.bat"', text("start_admin.bat")) is not None)
check("start_admin.bat: говорит лаунчеру, что права уже есть (--already-elevated)",
      "--already-elevated" in text("start_admin.bat"))

# ------------------------------------------------------------------ 4. .vbs
print("== 4. start.vbs: собираемая командная строка ==")
vbs = lines_of("start.vbs")


def vbs_eval(expr, env):
    """Мини-интерпретатор конкатенаций VBScript: литералы, Chr(34), переменные из env."""
    out = []
    for part in re.split(r"&(?=(?:[^\"']|\"[^\"]*\")*$)", expr):
        p = part.strip()
        if not p:
            continue
        if p == "Chr(34)":
            out.append('"')
        elif p.startswith('"') and p.endswith('"'):
            out.append(p[1:-1].replace('""', '"'))
        elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", p):
            out.append(env.get(p, ""))
        else:
            out.append("")
    return "".join(out)


env = {"folder": r"C:\Games\AutoFish"}
assigns = [l.strip() for l in vbs if re.match(r"^\s*line\s*=", l)]
check("start.vbs: есть присваивания командной строки", len(assigns) >= 2, "%d шт." % len(assigns))
for a in assigns:
    built = vbs_eval(a.split("=", 1)[1].strip(), env)
    ok_line = (built.startswith(("pythonw ", "py -3w "))
               and built.count('"') == 2
               and r'\launch.py"' in built
               and "--yes" in built and "--no-admin-ask" in built)
    check("команда собрана корректно: %s" % built, ok_line)
check("start.vbs: окно скрытое (sh.Run ..., 0, ...)",
      re.search(r"sh\.Run\s+\w+\s*,\s*0\s*,", text("start.vbs")) is not None)
check("start.vbs: есть On Error Resume Next + разбор ошибки (не тихий провал)",
      "On Error Resume Next" in text("start.vbs") and "MsgBox" in text("start.vbs"))
check("start.vbs: проваленный pythonw подменяется py -3w",
      "py -3w" in text("start.vbs"))
check("start.vbs: кавычки сбалансированы в каждой строке",
      all(l.count('"') % 2 == 0 for l in vbs),
      str([i + 1 for i, l in enumerate(vbs) if l.count('"') % 2][:6]))

# ------------------------------------------------------------------ 5. launch.py понимает флаги
print("== 5. лаунчер: флаги из .bat/.vbs распознаются, падений из-за кодировки нет ==")
lp = text("launch.py")
for flag in ("--yes", "--restart", "--no-install", "--admin", "--lang",
             "--already-elevated", "--no-admin-ask"):
    check("launch.py знает %s" % flag, flag in lp)
check("launch.py не падает на не-совместимой кодировке консоли (errors=replace)",
      "reconfigure(errors=" in lp or "errors=\"replace\"" in lp)
check("launch.py под Windows ищет администратора и делает UAC-релонч",
      "ShellExecuteW" in lp and "runas" in lp)
check("launch.py печатает версию приложения", "__version__" in lp or "APP_VERSION" in lp)
reqs = text("requirements.txt")
for pkg in ("dxcam", "mss", "opencv", "numpy", "pydirectinput", "keyboard"):
    check("requirements.txt: %s" % pkg, pkg in reqs)
check("requirements.txt: bettercam упомянут как альтернатива dxcam", "bettercam" in reqs)

# ------------------------------------------------------------------ 6. README документирует правило
print("== 6. README объясняет, почему .bat только ASCII ==")
rd = text("README.md")
check("README: правило ASCII/CRLF для .bat описано",
      re.search(r"ASCII", rd) is not None and "CRLF" in rd)
check("README: описан код 9009/«не является внутренней или внешней командой»",
      "9009" in rd or "внутренней или внешней" in rd)

# ------------------------------------------------------------------ 7. состав релизного архива
print("== 7. В релизном архиве — только то, чем пользуются ==")
rs = text("scripts/release.py")
m = re.search(r"INCLUDE_FILES = \[(.*?)\]", rs, re.S)
files = [x.strip().strip('\"\'') for x in (m.group(1) if m else "").replace("\n", " ").split(",") if x.strip()]
needed = {"eternal_fishmod.py", "launch.py", "start.bat", "start_admin.bat", "start.vbs",
          "requirements.txt", "README.md", "VERSION"}
check("архив: всё необходимое для запуска на месте", needed.issubset(set(files)), str(sorted(needed - set(files))))
extra = [f for f in files if f not in needed]
check("архив: без девелоперского мусора", not extra, str(extra))
mdir = re.search(r"INCLUDE_DIRS = \[(.*?)\]", rs, re.S)
dirs = (mdir.group(1) if mdir else "")
check("архив: scripts/ и .github/ в него не попадают", '"scripts"' not in dirs and ".github" not in dirs,
      " ".join(dirs.split()))
check("архив: templates/ с откалиброванными картинками едет", "templates" in dirs)
tpl = os.path.join(ROOT, "templates")
check("templates/ непустой (иначе бот не найдёт удочку)", os.path.isdir(tpl) and len(os.listdir(tpl)) >= 1,
      str(sorted(os.listdir(tpl))[:6]) if os.path.isdir(tpl) else "нет папки")

print()
if fails:
    print("FAILED:", len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL LAUNCHER FILE CHECKS PASSED")
