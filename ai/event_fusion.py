# -*- coding: utf-8 -*-
"""Слияние сигналов зрения в события (v1.24).

На вход: детекции, OCR, изменения кадра, подтверждённое состояние и легаси-подсказки.
На выходе: список VisionEvent с кулдаунами (никаких копий одного события каждый
кадр). НЕИЗВЕСТНОЕ изменение -> game.unknown_visual_change с честной
неопределённостью; выдумывать описания запрещено.
"""
import time

from .event_bus import VisionEvent

# кулдауны повторных событий, сек
_COOLDOWN = {
    "ui.item_detected": 5.0,
    "ui.notification_detected": 5.0,
    "game.screen_transition": 3.0,
    "game.unknown_visual_change": 4.0,
    "game.window_lost_focus": 10.0,
    "fishing.minigame_started": 2.0,
}


class EventFusion(object):
    def __init__(self, source="ai_fusion"):
        self.source = source
        self._last = {}                        # type -> ts последней публикации
        self._state = "unknown"                # предыдущее стабильное состояние

    def _ready(self, type, now, cd=None):
        cd = float(cd if cd is not None else _COOLDOWN.get(type, 2.0))
        if now - self._last.get(type, 0.0) < cd:
            return False
        self._last[type] = now
        return True

    def update(self, frame_id, detections, ocr_results, change, state_conf,
               legacy_hints=None, now=None):
        """-> [VisionEvent]. state_conf = (state, confidence, changed)."""
        now = time.time() if now is None else now
        hints = dict(legacy_hints or {})
        state, conf, changed = state_conf
        evs = []

        # --- смены подтверждённого состояния (однократно на переход) ---
        if changed:
            trans = {"inventory_open": ("ui.inventory_opened", "ui.inventory_closed"),
                     "fishing_minigame": ("fishing.minigame_started", None),
                     }
            pair = trans.get(state)
            if pair and pair[0] and self._ready(pair[0], now, 1.0):
                evs.append(VisionEvent(pair[0], now, frame_id, conf, source=self.source))
            prev = self._state
            self._state = state
            if state != "inventory_open" and prev == "inventory_open" and \
                    self._ready("ui.inventory_closed", now, 1.0):
                evs.append(VisionEvent("ui.inventory_closed", now, frame_id,
                                       max(0.3, conf), source=self.source))
        elif state != "unknown":
            self._state = state

        # --- детекции объектов ---
        for d in detections or []:
            if d.class_name in ("fishing_rod", "bait_icon") and self._ready(
                    "ui.item_detected", now, 4.0):
                ev = VisionEvent("ui.item_detected", now, frame_id, d.confidence,
                                 bbox=[d.bbox[0], d.bbox[1],
                                       d.bbox[0] + d.bbox[2], d.bbox[1] + d.bbox[3]],
                                 source=self.source,
                                 metadata={"class": d.class_name, "model": d.model})
                evs.append(ev)
            if d.class_name == "notification_panel" and self._ready(
                    "ui.notification_detected", now):
                evs.append(VisionEvent("ui.notification_detected", now, frame_id,
                                       d.confidence, source=self.source,
                                       metadata={"class": d.class_name}))

        # --- OCR-тексты (уведомления опознаём ТОЛЬКО по известным словам) ---
        txts = [r.text for r in (ocr_results or []) if r.text]
        if txts and state == "notification_visible" and self._ready(
                "ui.notification_detected", now):
            evs.append(VisionEvent("ui.notification_detected", now, frame_id,
                                   0.6, source=self.source, metadata={"ocr": txts[:4]}))

        # --- изменения кадра ---
        if change is not None and not change.first:
            if change.transition and self._ready("game.screen_transition", now):
                evs.append(VisionEvent("game.screen_transition", now, frame_id,
                                       0.85, source=self.source,
                                       metadata={"fraction": change.fraction}))
            elif change.fraction >= 0.03 and state in ("unknown",) and \
                    not detections and self._ready("game.unknown_visual_change", now):
                # НЕИЗВЕСТНОЕ событие: неопределённость = 1 - доля объяснённого;
                # снапшот запрашивается конвейером отдельно (metadata.want_snapshot)
                evs.append(VisionEvent("game.unknown_visual_change", now, frame_id,
                                       round(max(0.05, 1.0 - change.fraction), 3),
                                       bbox=(change.cells[0][:4] if change.cells else None),
                                       source=self.source,
                                       metadata={"fraction": change.fraction,
                                                 "cells": len(change.cells),
                                                 "motion": change.motion,
                                                 "want_snapshot": True}))

        # --- фокус окна (дешёвая легаси-подсказка) ---
        if hints.get("focus") is False and self._ready("game.window_lost_focus", now):
            evs.append(VisionEvent("game.window_lost_focus", now, frame_id, 0.9,
                                   source=self.source))
        return evs
