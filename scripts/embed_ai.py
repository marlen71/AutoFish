#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Синхронизация встроенного AI-пакета (v1.24.1).

eternal_fishmod.py обязан работать как ОДИН файл (так его ставят пользователи),
поэтому источники пакета ai/ вшиты в него сжатым payload'ом между маркерами
[AI-EMBED-BEGIN] / [AI-EMBED-END]. Правила:

* править код нужно в каталоге ai/ (не в payload!);
* после любого изменения ai/ запусти:  python scripts/embed_ai.py
* проверка синхронности (CI/тесты):    python scripts/embed_ai.py --check

Приоритет в рантайме: если рядом с ботом есть каталог ai/ — используется он
(режим разработки), иначе модули собираются из встроенного payload (деплой
одним файлом). Так дублирование не расходится: тест test_legacy_compatibility
сравнивает payload с диском при каждом прогоне.
"""
import base64
import io
import json
import os
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(ROOT, "eternal_fishmod.py")
AI_DIR = os.path.join(ROOT, "ai")
BEGIN = "# [AI-EMBED-BEGIN]"
END = "# [AI-EMBED-END]"


def collect():
    """{имя модуля: источник} по всем ai/*.py (ai/__init__.py -> 'ai')."""
    mods = {}
    for name in sorted(os.listdir(AI_DIR)):
        if not name.endswith(".py"):
            continue
        key = "ai" if name == "__init__.py" else "ai." + name[:-3]
        with io.open(os.path.join(AI_DIR, name), encoding="utf-8") as f:
            mods[key] = f.read()
    return mods


def pack(mods):
    blob = zlib.compress(json.dumps(mods, ensure_ascii=False).encode("utf-8"), 9)
    return base64.b64encode(blob).decode("ascii")


def region(payload_b64, loader_src):
    lines = [payload_b64[i:i + 96] for i in range(0, len(payload_b64), 96)]
    body = "_AI_EMBED_B64 = (\n" + "".join('    "%s"\n' % l for l in lines) + ")\n"
    return (BEGIN + " (генерируется scripts/embed_ai.py — не править руками)\n"
            + body + loader_src + END)


LOADER = '''\
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
'''


def build():
    mods = collect()
    payload = pack(mods)
    with io.open(MAIN, encoding="utf-8") as f:
        src = f.read()
    i = src.find(BEGIN)
    j = src.find(END)
    if i < 0 or j < 0 or j < i:
        print("ОШИБКА: маркеры %s/%s не найдены в eternal_fishmod.py" % (BEGIN, END))
        sys.exit(2)
    new = region(payload, LOADER)
    src = src[:i] + new + src[j + len(END):]
    with io.open(MAIN, "w", encoding="utf-8") as f:
        f.write(src)
    print("OK: payload обновлён (%d модулей ai/, %d КБ base64)"
          % (len(mods), len(payload) // 1024))


def check():
    import re
    with io.open(MAIN, encoding="utf-8") as f:
        src = f.read()
    i, j = src.find(BEGIN), src.find(END)
    if i < 0 or j < 0:
        print("ОШИБКА: маркеры не найдены")
        return 1
    seg = src[i:j]
    m = re.search(r"_AI_EMBED_B64 = \((.*?)\n\)", seg, re.S)
    if not m:
        print("ОШИБКА: блок _AI_EMBED_B64 не найден")
        return 1
    payload = "".join(re.findall(r'"([^"]*)"', m.group(1)))
    embedded = json.loads(zlib.decompress(base64.b64decode(payload)).decode("utf-8"))
    disk = collect()
    if embedded == disk:
        print("OK: встроенный payload == ai/ на диске (%d модулей)" % len(disk))
        return 0
    diff = [k for k in set(embedded) | set(disk) if embedded.get(k) != disk.get(k)]
    print("РАСХОЖДЕНИЕ ai/ и payload: %s — запусти python scripts/embed_ai.py" % sorted(diff))
    return 1


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    build()
