# -*- coding: utf-8 -*-
"""Простой трекер детекций (v1.24): жадное сопоставление по IoU + стабильные id.

Нужен, чтобы события вида «иконка появилась/исчезла/сдвинулась» не сыпались
каждый кадр: трекер помнит объекты между кадрами и даёт им устойчивые id.
"""
import time


def _iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x0, y0 = max(ax, bx), max(ay, by)
    x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    return inter / float(aw * ah + bw * bh - inter + 1e-6)


class Tracked(object):
    __slots__ = ("tid", "class_name", "bbox", "confidence", "hits", "misses", "last_ts")

    def __init__(self, tid, det):
        self.tid = tid
        self.class_name = det.class_name
        self.bbox = list(det.bbox)
        self.confidence = det.confidence
        self.hits = 1
        self.misses = 0
        self.last_ts = det.ts


class Tracker(object):
    def __init__(self, iou_thr=0.30, max_misses=5):
        self.iou_thr = float(iou_thr)
        self.max_misses = int(max_misses)
        self._objects = []
        self._next_id = 1

    def update(self, detections, now=None):
        """Свежие детекции -> активные Tracked (с пропавшими до max_misses)."""
        now = time.time() if now is None else now
        alive = [t for t in self._objects if t.misses <= self.max_misses]
        free = list(range(len(alive)))
        for det in detections:
            best, bi = self.iou_thr, -1
            for i in free:
                t = alive[i]
                if t.class_name != det.class_name:
                    continue
                v = _iou(t.bbox, det.bbox)
                if v > best:
                    best, bi = v, i
            if bi >= 0:
                t = alive[bi]
                t.bbox, t.confidence = list(det.bbox), det.confidence
                t.hits += 1
                t.misses = 0
                t.last_ts = now
                free.remove(bi)
            else:
                alive.append(Tracked(self._next_id, det))
                self._next_id += 1
        for i in free:
            alive[i].misses += 1
        self._objects = alive
        return [t for t in alive if t.misses == 0]

    def appeared(self, detections):
        """Треки, увиденные впервые (hits == 1) — кандидаты на «новый объект»."""
        cur = self.update(detections)
        return [t for t in cur if t.hits == 1]
