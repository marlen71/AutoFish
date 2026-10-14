#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты схемы событий и шины AI (v1.24): валидация, дедупликация, изоляция,
отбраковка устаревших событий, история. Запуск: python tests/test_ai_events.py"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai.event_bus import EventBus, VisionEvent

fails = []


def check(label, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + label + ("  " + extra if extra else ""))
    if not cond:
        fails.append(label)


print("== 1. VisionEvent: валидация и сериализация ==")
ev = VisionEvent("ui.inventory_opened", confidence=0.97, frame_id=1842,
                 bbox=[1, 2, 3, 4], source="onnx_detector")
d = ev.to_dict()
check("поля схемы ТЗ на месте", d["type"] == "ui.inventory_opened" and d["frame_id"] == 1842
      and abs(d["confidence"] - 0.97) < 1e-9 and d["bbox"] == [1.0, 2.0, 3.0, 4.0]
      and d["source"] == "onnx_detector" and "event_id" in d and "timestamp" in d, str(sorted(d)))
ev2 = VisionEvent.from_dict(d)
check("to_dict/from_dict туда-обратно", ev2.event_id == ev.event_id and ev2.type == ev.type
      and ev2.confidence == ev.confidence and ev2.bbox == ev.bbox)
bad = 0
for kw in ({"type": ""}, {"type": "x", "confidence": 1.5}, {"type": "x", "confidence": -0.1},
           {"type": 42}):
    try:
        VisionEvent(**kw)
    except (ValueError, TypeError):
        bad += 1
check("мусор отвергается (пустой тип/уверенность вне [0,1]/не-строка)", bad == 4, str(bad))

print("== 2. EventBus: публикация, фильтр типов, история ==")
bus = EventBus()
got, got_filtered = [], []
bus.subscribe(got.append)
bus.subscribe(got_filtered.append, types=("ui.item_detected",))
check("публикация доходит всем подписчикам", bus.publish(ev) is True and
      got and got_filtered == [])
e_item = VisionEvent("ui.item_detected", confidence=0.8, frame_id=2)
bus.publish(e_item)
check("фильтр типов: подписчик получил только свой тип", got_filtered and
      got_filtered[0].type == "ui.item_detected")
check("история ограничена и заполняется", len(bus.history(10)) == 2, str(len(bus.history(10))))

print("== 3. EventBus: изоляция ошибок подписчиков ==")


def boom(_ev):
    raise RuntimeError("subscriber died")


bus2 = EventBus()
ok_list = []
bus2.subscribe(boom)
bus2.subscribe(ok_list.append)
bus2.publish(VisionEvent("game.screen_transition", confidence=0.5, frame_id=3))
check("упавший подписчик не мешает другим", len(ok_list) == 1)
check("ошибка подписчика посчитана", bus2.stats()["subscriber_errors"] == 1,
      str(bus2.stats()))

print("== 4. EventBus: устаревшие события и дедупликация ==")
bus3 = EventBus(stale_sec=1.0)
old = VisionEvent("game.unknown_visual_change", timestamp=time.time() - 30,
                  confidence=0.5, frame_id=9)
check("устаревшее событие отброшено", bus3.publish(old) is False and
      bus3.dropped_stale == 1)
f1 = VisionEvent("fishing.minigame_started", confidence=0.9, frame_id=77)
f2 = VisionEvent("fishing.minigame_started", confidence=0.9, frame_id=77)   # тот же кадр
seen = []
bus3.subscribe(seen.append)
check("первое событие типа+кадра проходит", bus3.publish(f1) is True)
check("дубль (тип+кадр) отброшен", bus3.publish(f2) is False and bus3.dropped_dup == 1
      and len(seen) == 1)
f3 = VisionEvent("fishing.minigame_started", confidence=0.9, frame_id=78)   # новый кадр
check("новый кадр — новое событие", bus3.publish(f3) is True)

print("== 5. Событие с bbox=None и пустой metadata ==")
e0 = VisionEvent("fishing.bite_detected", confidence=0.0, frame_id=-1)
check("минимальное событие валидно и сериализуемо",
      VisionEvent.from_dict(e0.to_dict()).type == "fishing.bite_detected")

print()
if fails:
    print("FAILED:", len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL AI-EVENTS CHECKS PASSED")
