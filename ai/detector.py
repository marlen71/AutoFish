# -*- coding: utf-8 -*-
"""Детектор объектов (v1.24): адаптер локальной ONNX-модели + честный Null.

Контракт постобработки layout "nms5" (его же требуют от экспортируемых моделей,
см. docs/AI_VISION.md и datasets/README.md):
  выход модели: float32 [1, M, 5 + C]
  строка:       [cx, cy, w, h, obj, class_0 ... class_{C-1}]
  все пять служебных значений прогоняются через sigmoid; cx/cy/w/h — в долях
  кадра (0..1); итоговая уверенность = obj * max(class); далее NMS.

БЕЗ модели (или без onnxruntime) работает NullDetector: detect() -> [] и статус
с причиной. Это не «молчаливая деградация»: статус виден в GUI/журнале.
ВАЖНО: универсальная предобученная модель НЕ распознаёт объекты Skyrim — классы
появляются только после обучения на своих скриншотах (datasets/README.md).
"""
import threading
import time

import cv2
import numpy as np

from .model_manager import DETECTOR_CLASSES_DOC
from .runtime import ModelRuntime


class Detection(object):
    __slots__ = ("class_id", "class_name", "confidence", "bbox", "frame_id", "ts", "model")

    def __init__(self, class_id, class_name, confidence, bbox, frame_id, ts, model=""):
        self.class_id = int(class_id)
        self.class_name = str(class_name)
        self.confidence = float(confidence)
        self.bbox = [float(v) for v in bbox]        # x, y, w, h в пикселях кадра
        self.frame_id = int(frame_id)
        self.ts = float(ts)
        self.model = str(model)

    def as_event_fields(self):
        x, y, w, h = self.bbox
        return {"bbox": [x, y, x + w, y + h], "confidence": self.confidence}

    def __repr__(self):
        return "Detection(%s %.2f %s)" % (self.class_name, self.confidence,
                                          [int(v) for v in self.bbox])


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _nms(boxes, scores, thr=0.45):
    """NMS на numpy/cv2: boxes [N,4] (x, y, w, h) -> индексы выживших."""
    if not len(boxes):
        return []
    idx = cv2.dnn.NMSBoxes([[b[0], b[1], b[2], b[3]] for b in boxes],
                           [float(s) for s in scores], 0.0, thr)
    try:
        return [int(i) for i in np.array(idx).flatten()]
    except Exception:
        return list(range(len(boxes)))               # NMS не критичен для наблюдения


class BaseDetector(object):
    name = "none"

    def detect(self, frame_bgr, frame_id=-1, ts=None):
        raise NotImplementedError

    @property
    def status(self):
        return "none"


class NullDetector(BaseDetector):
    """Нет модели / битая модель: статус с причиной, детекций ноль."""

    def __init__(self, reason):
        self.reason = reason
        self.name = "null"

    @property
    def status(self):
        return self.reason

    def detect(self, frame_bgr, frame_id=-1, ts=None):
        return []


class OnnxDetector(BaseDetector):
    """Адаптер OnnxRuntime-детектора (CPU). Ленивая загрузка через ModelRuntime."""

    def __init__(self, entry, runtime, conf=0.45, nms_thr=0.45):
        self.entry = entry
        self.rt = runtime
        self.conf = float(conf)
        self.nms_thr = float(nms_thr)
        self.name = entry.describe() if entry else "onnx"
        self.classes = entry.classes if (entry and entry.classes) else list(DETECTOR_CLASSES_DOC)
        self._lock = threading.Lock()

    @property
    def status(self):
        return self.rt.status

    @property
    def loaded(self):
        return self.rt.loaded

    def ensure_loaded(self):
        return self.rt.load()

    # ------------------------------------------------------------- конвейер
    def _preprocess(self, bgr):
        """letterbox до входа модели, BGR->RGB, NCHW. Возвращает (blob, pad, gain)."""
        ih, iw = self.rt.input_shape()[2], self.rt.input_shape()[3]
        H, W = bgr.shape[:2]
        gain = min(iw / float(W), ih / float(H))
        nw, nh = max(1, int(round(W * gain))), max(1, int(round(H * gain)))
        resized = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((ih, iw, 3), 114, np.uint8)
        px, py = (iw - nw) // 2, (ih - nh) // 2
        canvas[py:py + nh, px:px + nw] = resized
        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        blob = rgb.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
        return np.ascontiguousarray(blob), (px, py), gain

    def detect(self, frame_bgr, frame_id=-1, ts=None):
        ts = time.time() if ts is None else ts
        if not self.rt.loaded and not self.rt.load():
            return []
        blob, (px, py), gain = self._preprocess(frame_bgr)
        out = self.rt.infer(blob)
        if out is None or not out:
            return []
        pred = np.asarray(out[0])
        if pred.ndim == 3:
            pred = pred[0]
        if pred.ndim != 2 or pred.shape[1] < 6:
            return []
        obj = _sigmoid(pred[:, 4])
        cls = _sigmoid(pred[:, 5:]) if pred.shape[1] > 5 else obj[:, None]
        best_cls = cls.argmax(axis=1)
        best_score = cls.max(axis=1) * obj
        keep = np.where(best_score >= self.conf)[0]
        if not len(keep):
            return []
        ih, iw = self.rt.input_shape()[2], self.rt.input_shape()[3]
        # сигмоидные координаты живут во ВХОДНОМ пространстве модели (letterbox):
        # пиксели входа -> вычет пада -> деление на gain -> пиксели кадра
        boxes_wh = _sigmoid(pred[keep, 2:4]) * np.array([iw, ih], np.float32)
        centers = _sigmoid(pred[keep, 0:2]) * np.array([iw, ih], np.float32)
        cx = (centers[:, 0] - px) / gain
        cy = (centers[:, 1] - py) / gain
        ww = np.maximum(2.0, boxes_wh[:, 0] / gain)
        hh = np.maximum(2.0, boxes_wh[:, 1] / gain)
        boxes = np.stack([cx - ww / 2, cy - hh / 2, ww, hh], axis=1)
        order = _nms(boxes, best_score[keep], self.nms_thr)
        dets = []
        for i in order:
            k = int(keep[i])
            cid = int(best_cls[k])
            nm = self.classes[cid] if 0 <= cid < len(self.classes) else ("class_%d" % cid)
            dets.append(Detection(cid, nm, float(best_score[k]),
                                  [float(v) for v in boxes[i]], frame_id, ts, self.name))
        return dets


def make_detector(manager, conf=0.45, threads=0):
    """(detector, status): модель валидна -> OnnxDetector, иначе NullDetector."""
    entry = manager.entry("detector")
    v = manager.validate(entry)
    if entry is None:
        return NullDetector("no_model"), "no_model"
    if v != "ok":
        return NullDetector(v), v
    rt = ModelRuntime(entry.path, threads=threads)
    det = OnnxDetector(entry, rt, conf=conf)
    return det, "ready"
