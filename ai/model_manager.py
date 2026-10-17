# -*- coding: utf-8 -*-
"""Менеджер моделей (v1.24): обнаружение, контрольные суммы, статусы.

Модели поставляются ТОЛЬКО вручную (docs/AI_VISION.md): кладёшь .onnx в каталог
моделей и вписываешь его в ai/models/manifest.json c sha256. Менеджер:
* читает манифест (нет манифеста/файла — честный статус, приложение работает);
* проверяет sha256 один раз на файл (кэш по mtime+size);
* НЕ скачивает ничего, НИКОГДА.

Формат манифеста:
{
  "version": 1,
  "models": {
    "detector": {"file": "rod_detector.onnx", "sha256": "<hex>", "version": "1.0.0",
                 "input": [1, 3, 640, 640], "layout": "nms5",
                 "classes": ["inventory_window", "fishing_rod", ...]}
  }
}
"""
import hashlib
import json
import os
import threading

DETECTOR_CLASSES_DOC = [
    # Целевые категории из ТЗ. Это РЕЕСТР КЛАССОВ, а не обещание: распознаются те
    # классы, которые реально есть в установленной обученной модели.
    "inventory_window", "fishing_rod", "bait_icon", "item_icon", "interaction_prompt",
    "status_indicator", "notification_panel", "minigame_bar", "minigame_fish", "unknown",
]


class ModelEntry(object):
    __slots__ = ("name", "file", "sha256", "version", "input", "layout", "classes", "path")

    def __init__(self, name, d, models_dir):
        self.name = name
        self.file = str(d.get("file", ""))
        self.sha256 = str(d.get("sha256", "")).lower()
        self.version = str(d.get("version", ""))
        self.input = [int(v) for v in (d.get("input") or [])]
        self.layout = str(d.get("layout", "nms5"))
        self.classes = [str(c) for c in (d.get("classes") or [])]
        self.path = os.path.join(models_dir, self.file) if self.file else ""

    def describe(self):
        return "%s v%s (%s)" % (self.file, self.version or "?", self.layout)


class ModelManager(object):
    """Читает manifest.json, проверяет целостность; безопасность к потокам."""

    def __init__(self, models_dir):
        self.dir = str(models_dir)
        self.manifest_path = os.path.join(self.dir, "manifest.json")
        self._lock = threading.Lock()
        self._sums = {}                        # path -> (mtime, size, ok)
        self.manifest_status = "ok"            # ok|no_manifest|bad_json
        self.raw = {}
        self._read_manifest()

    def _read_manifest(self):
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.raw = data
                return
        except FileNotFoundError:
            self.manifest_status = "no_manifest"
        except Exception:
            self.manifest_status = "bad_json"
        self.raw = {}

    def entry(self, name="detector"):
        """ModelEntry из манифеста или None (со статусом причины)."""
        models = self.raw.get("models") if isinstance(self.raw, dict) else None
        if not isinstance(models, dict) or name not in models:
            return None
        try:
            return ModelEntry(name, models[name], self.dir)
        except Exception:
            return None

    def validate(self, entry):
        """ok | missing_file | bad_checksum. Сумма считается один раз на файл."""
        if entry is None or not entry.file:
            return "missing_file"
        if not os.path.isfile(entry.path):
            return "missing_file"
        try:
            st = os.stat(entry.path)
            key = (st.st_mtime, st.st_size)
            with self._lock:
                cached = self._sums.get(entry.path)
            if cached is not None and cached[0] == key:
                return "ok" if cached[1] else "bad_checksum"
            h = hashlib.sha256()
            with open(entry.path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            ok = (not entry.sha256) or h.hexdigest() == entry.sha256
            with self._lock:
                self._sums[entry.path] = (key, ok)
            return "ok" if ok else "bad_checksum"
        except Exception:
            return "missing_file"
