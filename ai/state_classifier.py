# -*- coding: utf-8 -*-
"""Классификатор состояний экрана (v1.24): правила + подтверждение временем.

Начальный набор состояний из ТЗ. Реализация — ПРАВИЛА на дешёвых признаках:
* легаси-подсказки основного приложения (инвентарь открыт, мини-игра, ожидание) —
  это уже проверенные годы работы сигналы, AI их НЕ заменяет, а дополняет;
* классы детектора (если установлена модель) и OCR-тексты;
* флаг screen_transition из детектора изменений.

Состояние меняется только после ai_state_confirm подтверждений подряд; смена
возвращается однократно (changed=True). Ничего не распозналось — честный
`unknown`. Опциональный обучаемый классификатор можно подключить позже тем же
контрактом update(...).
"""

STATES = ("unknown", "normal_gameplay", "inventory_open", "fishing_waiting",
          "fishing_minigame", "fishing_catch_result", "notification_visible",
          "loading_or_transition")

# легаси state-key (STATE["title_key"]) -> состояние
_LEGACY_MAP = {
    "st_starting": "unknown", "st_idle": "unknown",
    "st_bite": "fishing_waiting", "st_cast": "fishing_waiting",
    "st_mg": "fishing_minigame", "st_minigame": "fishing_minigame",
    "st_catch": "fishing_catch_result", "st_equip": "inventory_open",
    "st_inv": "inventory_open", "st_wait": "fishing_waiting",
}

# слова OCR, по которым опознаётся уведомление (проверенные строки интерфейса)
_NOTIFY_HINTS = ("упустили", "улов поднят", "наживка", "you missed", "loot picked", "bait")


class StateClassifier(object):
    def __init__(self, confirm=3):
        self.confirm = max(1, int(confirm))
        self.state = "unknown"
        self.confidence = 0.0
        self._cand = "unknown"
        self._n = 0

    def update(self, legacy_hints=None, det_classes=None, ocr_texts=None,
               change=None, now=None):
        """Один кадр -> (state, confidence, changed). Подтверждение — N кадров."""
        hints = dict(legacy_hints or {})
        classes = set(det_classes or [])
        texts = " ".join(ocr_texts or []).lower()

        cand, conf = "unknown", 0.0
        if change is not None and change.transition:
            cand, conf = "loading_or_transition", 0.9
        elif hints.get("minigame"):
            cand, conf = "fishing_minigame", 0.95
        elif hints.get("catch_result"):
            cand, conf = "fishing_catch_result", 0.9
        elif hints.get("inventory") or classes & {"inventory_window"}:
            conf = 0.95 if hints.get("inventory") else 0.6
            cand = "inventory_open"
        elif hints.get("waiting"):
            cand, conf = "fishing_waiting", 0.9
        elif texts and any(w in texts for w in _NOTIFY_HINTS):
            cand, conf = "notification_visible", 0.6
        elif hints.get("running"):
            cand, conf = "normal_gameplay", 0.7
        elif classes:
            cand, conf = "unknown", 0.3

        if cand == self._cand:
            self._n = min(self._n + 1, 2 * self.confirm)
        else:
            self._cand, self._n = cand, 1
        changed = False
        if self._n >= self.confirm and self._cand != self.state:
            self.state = self._cand
            changed = True
        # уверенность стабильного состояния растёт с числом подтверждений
        k = min(1.0, self._n / float(self.confirm))
        self.confidence = round(conf * (0.6 + 0.4 * k), 3) if self.state == self._cand else \
            round(conf * 0.5 * k, 3)
        return self.state, self.confidence, changed
