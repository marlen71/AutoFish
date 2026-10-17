# -*- coding: utf-8 -*-
"""Шина событий AI-зрения (v1.24) + типизированная схема события.

Все модули зрения публикуют нормализованные VisionEvent; потребители (журнал,
GUI, будущие адаптеры) подписываются на шину. Гарантии шины:
* потокобезопасная публикация/подписка;
* изоляция ошибок: упавший подписчик не роняет шину и других подписчиков;
* отбраковка устаревших событий (stale) по возрасту;
* дедупликация (тип + frame_id) — одно событие не публикуется дважды;
* ограниченная история для диагностики.

События — ТОЛЬКО наблюдения. Ничто на шине не имеет права двигать мышь или
клацать кнопки: решения принимает легаси-контроллер основного приложения.
"""
import collections
import threading
import time
import uuid

# Предложенный в ТЗ набор типов; реальные эмиттеры см. event_fusion.py.
# Коды — ASCII-идентификаторы; человекочитаемые строки даёт локализация приложения.
EVENT_TYPES = (
    "ui.inventory_opened", "ui.inventory_closed", "ui.item_detected",
    "ui.notification_detected",
    "fishing.bite_detected", "fishing.minigame_started", "fishing.fish_detected",
    "fishing.fish_slipping", "fishing.catch_confirmed", "fishing.bait_missing",
    "game.window_lost_focus", "game.screen_transition", "game.unknown_visual_change",
)


class VisionEvent(object):
    """Нормализованное событие зрения. Валидно, если confidence в [0, 1]."""

    __slots__ = ("event_id", "type", "timestamp", "frame_id", "confidence",
                 "bbox", "source", "metadata")

    def __init__(self, type, timestamp=None, frame_id=-1, confidence=0.0,
                 bbox=None, source="ai", metadata=None, event_id=None):
        if not isinstance(type, str) or not type:
            raise ValueError("event type must be a non-empty string")
        c = float(confidence if confidence is not None else 0.0)
        if not (0.0 <= c <= 1.0):
            raise ValueError("confidence must be within [0, 1]")
        self.event_id = event_id or uuid.uuid4().hex
        self.type = type
        self.timestamp = float(timestamp if timestamp is not None else time.time())
        self.frame_id = int(frame_id)
        self.confidence = c
        self.bbox = [float(v) for v in bbox] if bbox else None
        self.source = str(source)
        self.metadata = dict(metadata) if metadata else {}

    def to_dict(self):
        return {"event_id": self.event_id, "type": self.type,
                "timestamp": self.timestamp, "frame_id": self.frame_id,
                "confidence": self.confidence, "bbox": self.bbox,
                "source": self.source, "metadata": self.metadata}

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict):
            raise ValueError("event must be a dict")
        return cls(type=d["type"], timestamp=d.get("timestamp"),
                   frame_id=d.get("frame_id", -1), confidence=d.get("confidence", 0.0),
                   bbox=d.get("bbox"), source=d.get("source", "ai"),
                   metadata=d.get("metadata"), event_id=d.get("event_id"))

    def __repr__(self):
        return "VisionEvent(%s conf=%.2f f=%s)" % (self.type, self.confidence, self.frame_id)


class EventBus(object):
    """Потокобезопасная шина с историей, дедупликацией и изоляцией подписчиков."""

    def __init__(self, history=256, stale_sec=10.0):
        self._subs = []                       # [(fn, types|None)]
        self._lock = threading.Lock()
        self._hist = collections.deque(maxlen=history)
        self._recent = {}                     # (type, frame_id) -> ts  (дедупликация)
        self.stale_sec = float(stale_sec)
        self.published = 0
        self.dropped_stale = 0
        self.dropped_dup = 0
        self.subscriber_errors = 0

    def subscribe(self, fn, types=None):
        """fn(event) вызывается на publish(); types=None — все события."""
        with self._lock:
            self._subs.append((fn, tuple(types) if types else None))

    def publish(self, ev):
        """Публикация: stale -> отбраковка, дубликат -> отбраковка, иначе всем."""
        now = time.time()
        if self.stale_sec > 0 and now - ev.timestamp > self.stale_sec:
            self.dropped_stale += 1
            return False
        key = (ev.type, ev.frame_id)
        with self._lock:
            last = self._recent.get(key)
            if last is not None and now - last < 0.9 * self.stale_sec:
                self.dropped_dup += 1
                return False
            self._recent[key] = now
            self._hist.append(ev)
            subs = list(self._subs)
        self.published += 1
        for fn, types in subs:
            if types is not None and ev.type not in types:
                continue
            try:
                fn(ev)
            except Exception:
                self.subscriber_errors += 1   # изоляция: упавший подписчик не мешает другим
        return True

    def history(self, n=50):
        with self._lock:
            return list(self._hist)[-n:]

    def stats(self):
        with self._lock:
            return {"published": self.published, "dropped_stale": self.dropped_stale,
                    "dropped_dup": self.dropped_dup,
                    "subscriber_errors": self.subscriber_errors,
                    "subscribers": len(self._subs)}
