# -*- coding: utf-8 -*-
"""OCR интерфейса (v1.24): RapidOCR (ONNX, локально) — опционально.

RapidOCR НЕ входит в обязательные зависимости: если пакет не установлен,
StubOcr честно возвращает статус "not_installed" и пустой результат. Тексты
нормализуются (пробелы/регистр не меняют смысл события), повторяющиеся надписи
в том же регионе дедуплицируются по кулдауну.

OCR событийно-региональный: приоритет — регионы, которые изменились (по сигналу
change_detector) или содержат найденные интерфейсные элементы. Полный экран на
максимальной частоте НЕ распознаётся никогда.
"""
import re
import threading
import time

_WS = re.compile(r"\s+")


class OcrResult(object):
    __slots__ = ("text", "confidence", "bbox", "region")

    def __init__(self, text, confidence, bbox=None, region=""):
        self.text = _WS.sub(" ", str(text)).strip()
        self.confidence = float(confidence)
        self.bbox = [float(v) for v in bbox] if bbox else None
        self.region = str(region)


class BaseOcr(object):
    name = "none"

    def recognize(self, bgr, region=""):
        return []

    @property
    def status(self):
        return "none"


class StubOcr(BaseOcr):
    """OCR не установлен: статус с причиной, текстов ноль. Приложение работает."""

    def __init__(self, reason="not_installed"):
        self.reason = reason
        self.name = "stub"

    @property
    def status(self):
        return self.reason

    def recognize(self, bgr, region=""):
        return []


class RapidOcr(BaseOcr):
    """Адаптер rapidocr_onnxruntime (полностью локальный инференс, CPU)."""

    def __init__(self):
        self.name = "rapidocr"
        self._eng = None
        self._lock = threading.Lock()
        self._err = ""

    @property
    def status(self):
        return "ok" if self._eng is not None else (self._err or "lazy")

    def _engine(self):
        if self._eng is not None:
            return self._eng
        with self._lock:
            if self._eng is None:
                try:
                    from rapidocr_onnxruntime import RapidOCR
                    self._eng = RapidOCR()
                except Exception as e:
                    self._err = "no_rapidocr: %s" % (str(e) or type(e).__name__)
                    return None
        return self._eng

    def recognize(self, bgr, region=""):
        eng = self._engine()
        if eng is None or bgr is None or bgr.size == 0:
            return []
        try:
            raw, _elapse = eng(bgr)
        except Exception:
            return []
        out = []
        for item in raw or []:
            try:
                box, (txt, conf) = item[0], item[1]
                xs = [float(p[0]) for p in box]
                ys = [float(p[1]) for p in box]
                out.append(OcrResult(txt, float(conf),
                                     [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)],
                                     region))
            except Exception:
                continue
        return out


class RegionOcr(object):
    """Региональный OCR с дедупликацией повторов и приоритетом changed-регионов."""

    def __init__(self, engine=None, dedup_sec=8.0):
        self.eng = engine if engine is not None else StubOcr()
        self.dedup_sec = float(dedup_sec)
        self._seen = {}                        # (region, text) -> ts
        self.last_ms = 0.0
        self.runs = 0

    @property
    def status(self):
        return self.eng.status

    def run(self, frame, regions, prefer=()):
        """regions: {имя: (x, y, w, h)}; prefer — имена changed-регионов первыми.

        Возвращает OcrResult[], отфильтрованный по кулдауну повторов."""
        if self.eng is None or isinstance(self.eng, StubOcr):
            return []
        order = [n for n in regions if n in set(prefer)] + \
                [n for n in regions if n not in set(prefer)]
        res = []
        t0 = time.perf_counter()
        for nm in order:
            crop = frame.region(regions[nm]) if frame is not None else None
            if crop is None:
                continue
            for r in self.eng.recognize(crop, nm):
                if not r.text:
                    continue
                key = (r.region, r.text.lower())
                now = time.time()
                if now - self._seen.get(key, 0.0) < self.dedup_sec:
                    continue
                self._seen[key] = now
                res.append(r)
        self.last_ms = (time.perf_counter() - t0) * 1000.0
        self.runs += 1
        return res


def make_ocr():
    """(ocr, статус): пакет установлен -> RapidOcr, иначе StubOcr."""
    probe = RapidOcr()
    eng = probe._engine()                          # ленивая проверка импорта
    if eng is None:
        return StubOcr(probe._err or "not_installed"), probe._err or "not_installed"
    return RegionOcr(RapidOcr()), "ok"
