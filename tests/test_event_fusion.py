#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты слияния сигналов (v1.24): детектор изменений, классификатор состояний,
трекер, событийная склейка (кулдауны, неизвестные события), OCR-нормализация,
диагностика и менеджер моделей. Запуск: python tests/test_event_fusion.py"""
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

from ai.change_detector import ChangeDetector
from ai.diagnostics import Diagnostics
from ai.event_fusion import EventFusion
from ai.model_manager import ModelManager
from ai.ocr import OcrResult, RegionOcr, StubOcr
from ai.state_classifier import StateClassifier
from ai.tracker import Tracker

fails = []


def check(label, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + label + ("  " + extra if extra else ""))
    if not cond:
        fails.append(label)


def frame(seed, size=(160, 120)):
    img = np.full((size[1], size[0], 3), 40, np.uint8)
    if seed:
        img[20:60, 30:80] = (seed * 37 % 200, 90, 160)
    return img


print("== 1. Детектор изменений: первое лицо, засветка, реальные изменения ==")
cdA = ChangeDetector(persistence=1)
check("первый кадр не даёт событий", cdA.update(frame(0)).first)
r_same = cdA.update(frame(0))
check("статичный кадр — изменений нет", not r_same.first and r_same.fraction < 0.03)
r_ch = cdA.update(frame(3))
check("появление объекта замечено (клетки + доля)", r_ch.fraction >= 0.03 and len(r_ch.cells) >= 1,
      "frac=%.3f cells=%d" % (r_ch.fraction, len(r_ch.cells)))
cdB = ChangeDetector(persistence=1)
cdB.update(frame(0))
r_shift = cdB.update(frame(0) + 25)                    # ровная засветка всего экрана
check("ровный сдвиг яркости — НЕ изменение и НЕ переход", r_shift.fraction < 0.03
      and not r_shift.transition, "%.3f" % r_shift.fraction)
cdC = ChangeDetector(persistence=1)
cdC.update(frame(0))
big = np.full((120, 160, 3), 200, np.uint8)
big[:60] = (30, 30, 200)                               # макро-блоки, как у реальной
big[:, :80] = (200, 30, 30)                            # смены сцены/оверлея
r_big = cdC.update(big)
check("структурная смена почти всего экрана = transition", r_big.transition,
      "frac=%.3f" % r_big.fraction)

print("== 2. Классификатор состояний: подтверждение временем ==")
sc = StateClassifier(confirm=3)
res = [sc.update({"minigame": True}) for _ in range(3)]
check("мини-игра подтверждена только на 3-м кадре",
      res[0][0] != "fishing_minigame" and res[2][0] == "fishing_minigame" and res[2][2] is True,
      str(res))
res2 = sc.update({"minigame": False, "inventory": True})
check("смена кандидата сбрасывает счётчик (не мгновенная)",
      res2[0] == "fishing_minigame" and res2[2] is False, str(res2))
sc2 = StateClassifier(confirm=1)
check("без подсказок — честный unknown", sc2.update({})[0] == "unknown")

print("== 3. Трекер: устойчивые id, появление ==")
from ai.detector import Detection
tr = Tracker()
d1 = [Detection(1, "fishing_rod", 0.9, [10, 10, 30, 40], 1, time.time())]
t1 = tr.update(d1)
d2 = [Detection(1, "fishing_rod", 0.9, [12, 11, 30, 40], 2, time.time())]
t2 = tr.update(d2)
check("объект сохранил id после сдвига", t2 and t2[0].tid == t1[0].tid)
check("appeared() даёт только новорождённые", len(tr.appeared(d2)) == 0 and
      len(tr.appeared([Detection(2, "bait_icon", 0.8, [70, 70, 20, 20], 3, time.time())])) == 1)

print("== 4. Слияние: события состояний, кулдауны, неизвестное ==")
fu = EventFusion()
evs = fu.update(1, [], [], None, ("inventory_open", 0.95, True), {})
check("ui.inventory_opened опубликован один раз", len(evs) == 1 and
      evs[0].type == "ui.inventory_opened", str([e.type for e in evs]))
evs2 = fu.update(2, [], [], None, ("inventory_open", 0.95, False), {})
check("повторный кадр того же состояния — БЕЗ событий", evs2 == [])
ch = type("C", (), {})()
ch.first, ch.fraction, ch.transition, ch.cells, ch.motion = \
    False, 0.10, False, [(4, 4, 48, 48, 20.0)], (1.0, 0.0)
evs3 = fu.update(3, [], [], ch, ("unknown", 0.2, False), {})
check("неизвестное изменение -> game.unknown_visual_change с неопределённостью",
      len(evs3) == 1 and evs3[0].type == "game.unknown_visual_change"
      and evs3[0].confidence < 1.0 and evs3[0].metadata.get("want_snapshot") is True,
      str([e.type for e in evs3]))
evs4 = fu.update(4, [], [], ch, ("unknown", 0.2, False), {})
check("кулдаун: то же неизвестное не сыплется каждый кадр", evs4 == [])
chT = type("C", (), {})()
chT.first, chT.fraction, chT.transition, chT.cells, chT.motion = \
    False, 0.6, True, [], (0.0, 0.0)
evs5 = fu.update(5, [], [], chT, ("loading_or_transition", 0.9, True), {})
check("полносменный кадр -> game.screen_transition",
      any(e.type == "game.screen_transition" for e in evs5), str([e.type for e in evs5]))
evs6 = fu.update(6, [], [], None, ("inventory_open", 0.9, False), {"focus": False})
check("потеря фокуса окна -> game.window_lost_focus",
      any(e.type == "game.window_lost_focus" for e in evs6), str([e.type for e in evs6]))

print("== 5. OCR: нормализация и дедупликация повторов ==")


class FakeEng:
    def recognize(self, bgr, region=""):
        return [OcrResult("  Вы   упустили  рыбу  ", 0.9, [0, 0, 10, 10], region)]


ro = RegionOcr(FakeEng(), dedup_sec=60.0)
f_ = type("F", (), {})()
f_.region = lambda rect: np.zeros((40, 120, 3), np.uint8)
res1 = ro.run(f_, {"toast": (0, 0, 120, 40)})
res2 = ro.run(f_, {"toast": (0, 0, 120, 40)})
check("текст нормализован (пробелы схлопнуты)", res1 and res1[0].text == "Вы упустили рыбу",
      res1[0].text if res1 else "-")
check("повтор того же текста в том же регионе дедуплицирован", res2 == [])
stub = StubOcr("not_installed")
check("StubOcr честно пуст", stub.recognize(np.zeros((10, 10, 3), np.uint8)) == []
      and stub.status == "not_installed")

print("== 6. Диагностика: jsonl, лимиты снимков ==")
tmp = tempfile.mkdtemp()
try:
    dg = Diagnostics(tmp, snapshots=True, max_files=5, max_mb=50)
    evd = {"event_id": "x", "type": "game.unknown_visual_change", "frame_id": 5}
    dg.log_event(evd)
    check("событие дописано в events.jsonl",
          os.path.exists(os.path.join(tmp, "events.jsonl")) and
          "unknown_visual_change" in open(os.path.join(tmp, "events.jsonl")).read())
    for i in range(8):
        dg.snapshot(np.zeros((4, 4, 3), np.uint8), {"frame_id": i})
        time.sleep(0.02)                               # уникальные имена по мс
    snaps = os.listdir(os.path.join(tmp, "snapshots"))
    check("снимки ограничены max_files (ротация старых)", len(snaps) == 5, str(len(snaps)))
    check("отчёт диагностики показывает счётчики", dg.report()["snapshots"] == 5,
          str(dg.report()))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("== 7. Менеджер моделей: нет манифеста / битая сумма / хорошая ==")
tmp = tempfile.mkdtemp()
try:
    mm0 = ModelManager(tmp)
    check("без манифеста — честный статус, детекций нет",
          mm0.manifest_status == "no_manifest" and mm0.entry("detector") is None)
    blob = bytes(range(256)) * 64
    open(os.path.join(tmp, "m.onnx"), "wb").write(blob)
    import hashlib
    good = hashlib.sha256(blob).hexdigest()
    with open(os.path.join(tmp, "manifest.json"), "w") as f:
        json.dump({"version": 1, "models": {"detector": {
            "file": "m.onnx", "sha256": good, "version": "1.0.0",
            "input": [1, 3, 64, 64], "layout": "nms5", "classes": ["fishing_rod"]}}}, f)
    mm1 = ModelManager(tmp)
    e1 = mm1.entry("detector")
    check("манифест читается, сумма сходится", e1 is not None and mm1.validate(e1) == "ok")
    with open(os.path.join(tmp, "manifest.json"), "w") as f:
        json.dump({"version": 1, "models": {"detector": {
            "file": "m.onnx", "sha256": "00" * 32, "version": "1.0.0",
            "input": [1, 3, 64, 64], "layout": "nms5", "classes": ["fishing_rod"]}}}, f)
    mm2 = ModelManager(tmp)
    check("чужая/битая модель ловится по sha256", mm2.validate(mm2.entry("detector")) == "bad_checksum")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
if fails:
    print("FAILED:", len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL EVENT-FUSION CHECKS PASSED")
