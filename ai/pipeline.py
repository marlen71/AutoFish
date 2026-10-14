# -*- coding: utf-8 -*-
"""VisionPipeline (v1.24): один воркер, наблюдение, никаких нажатий.

Потокобезопасность и отказоустойчивость:
* ОДИН демо-поток потребляет САМЫЙ СВЕЖИЙ кадр из FrameRouter (backpressure);
* отказ любого модуля (детектор/OCR/изменения) не роняет цикл: модуль помечается
  деградировавшим, счётчик ошибок растёт, остальные продолжают;
* статусы: startup -> running | degraded | stopped (+ off, если ai_enabled=False);
* GUI НЕ получает колбэки из воркера: он сам опрашивает get_status() в своём
  такте, поэтому все обновления Tk происходят в главном потоке;
* мышь/клавиатура конвейером НЕ трогаются вообще — по построению.

«Медленный вторичный анализ» (ТЗ §5.5/§8): расширенный прогон выполняется по
триггеру неизвестного события и в этом же воркере — поток мини-игры не трогается.
"""
import threading
import time

from . import config as aicfg
from .change_detector import ChangeDetector
from .diagnostics import Diagnostics
from .event_bus import EventBus
from .event_fusion import EventFusion
from .detector import make_detector
from .frame_router import FrameRouter
from .model_manager import ModelManager
from .ocr import make_ocr
from .state_classifier import StateClassifier


def _ema(old, new, k=0.2):
    return new if not old else old * (1.0 - k) + new * k


class VisionPipeline(object):
    def __init__(self, frame_source, hints_source=None, base_dir=".",
                 cfg_getter=None, status_cb=None, log_cb=None):
        """frame_source() -> ai.frame_router.Frame (кадр + метаданные) или None.
        hints_source() -> дешёвые легаси-подсказки (dict).
        cfg_getter() -> свежий срез ai_cfg (настройки применяются на лету).
        status_cb(dict) / log_cb(str) — необязательные уведомления."""
        self._src = frame_source
        self._hints = hints_source or (lambda: {})
        self._cfg_getter = cfg_getter or (lambda: dict(aicfg.AI_DEFAULTS))
        self._base = base_dir
        self._status_cb = status_cb
        self._log = log_cb or (lambda s: None)
        self.router = FrameRouter()
        self.bus = EventBus()
        self.diag = Diagnostics(base_dir)
        self.change = ChangeDetector()
        self.classifier = StateClassifier()
        self.fusion = EventFusion()
        self.manager = ModelManager(aicfg.ai_models_dir(None))
        self.detector, self.det_status = make_detector(self.manager)
        self.ocr, self.ocr_status = make_ocr()
        self._stop = threading.Event()
        self._thr = None
        self._state = "startup"
        self._lock = threading.Lock()
        self._last_pub = 0.0
        self.stats = {"frames": 0, "det_ms": 0.0, "ocr_ms": 0.0, "change_ms": 0.0,
                      "events": 0, "module_errors": 0, "unknown": 0, "transitions": 0}

    # ------------------------------------------------------------- жизненный цикл
    def start(self):
        if self._thr is not None and self._thr.is_alive():
            return
        self._stop.clear()
        self._thr = threading.Thread(target=self._loop, daemon=True, name="ai-vision")
        self._thr.start()

    def stop(self, timeout=3.0):
        self._stop.set()
        if self._thr is not None and self._thr.is_alive():
            self._thr.join(timeout)
        self._thr = None
        self._set_state("stopped")
        self._publish(True)

    def submit(self, frame, fast=False):
        """Точка входа кадров из легаси-захвата (адаптер в eternal_fishmod)."""
        self.router.submit(frame, fast=fast)

    # ------------------------------------------------------------------- статусы
    def _set_state(self, st):
        with self._lock:
            self._state = st

    def _publish(self, force=False):
        now = time.time()
        if not force and now - self._last_pub < 0.7:
            return
        self._last_pub = now
        if self._status_cb:
            try:
                self._status_cb(self.get_status())
            except Exception:
                pass

    @property
    def state(self):
        with self._lock:
            return self._state

    def get_status(self):
        """Снимок статуса для GUI (вызывается из Tk-потока). Только данные."""
        rs = self.router.stats()
        bs = self.bus.stats()
        with self._lock:
            st = self._state
        return {"state": st, "detector": self.det_status, "ocr": self.ocr_status,
                "model": self.detector.name, "det_rt": self.detector.status,
                "det_ms": round(self.stats["det_ms"], 1),
                "ocr_ms": round(self.stats["ocr_ms"], 1),
                "change_ms": round(self.stats["change_ms"], 1),
                "frames": self.stats["frames"], "dropped": rs.get("dropped_stale", 0),
                "dup": rs.get("dropped_dup", 0), "events": self.stats["events"],
                "unknown": self.stats["unknown"], "errors": self.stats["module_errors"],
                "transitions": self.stats["transitions"], "bus": bs,
                "diag": self.diag.report(),
                "state_screen": self.classifier.state,
                "state_conf": self.classifier.confidence}

    def detect_once(self, bgr, frame_id=-1):
        """Синхронный прогон детектора для легаси (экипировка, режим ai/hybrid).

        InferenceSession у onnxruntime потокобезопасен; ленивую загрузку ловим
        замком. Без модели -> [] (легаси уходит в шаблоны)."""
        try:
            if not self.detector.loaded and not self.detector.ensure_loaded():
                return []
            return self.detector.detect(bgr, frame_id)
        except Exception:
            self.stats["module_errors"] += 1
            return []

    # -------------------------------------------------------------------- воркер
    def _module(self, fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except Exception:
            self.stats["module_errors"] += 1
            return None

    def _loop(self):
        self._set_state("degraded" if self.det_status != "ready" else "running")
        self._publish(True)
        last_det = last_ocr = 0.0
        while not self._stop.is_set():
            frame = self.router.next_slow(0.4)
            if frame is None:
                continue
            self.stats["frames"] += 1
            ai = self._cfg_getter() or {}

            hints = self._module(self._hints) or {}
            ch = None
            if ai.get("ai_change_detect", True):
                t0 = time.perf_counter()
                ch = self._module(self.change.update, frame.image)
                self.stats["change_ms"] = _ema(self.stats["change_ms"],
                                               (time.perf_counter() - t0) * 1000.0)

            dets, ocr = [], []
            now = time.time()
            det_every = 1.0 / max(0.2, float(ai.get("ai_detect_fps", 2.0)))
            if now - last_det >= det_every:
                last_det = now
                t0 = time.perf_counter()
                d = self._module(self.detector.detect, frame.image, frame.frame_id)
                self.stats["det_ms"] = _ema(self.stats["det_ms"],
                                            (time.perf_counter() - t0) * 1000.0)
                if d:
                    dets = d
            if ai.get("ai_ocr_enabled") and \
                    now - last_ocr >= 1.0 / max(0.1, float(ai.get("ai_ocr_fps", 1.0))):
                last_ocr = now
                t0 = time.perf_counter()
                H, W = frame.image.shape[:2]
                regions = {"left_panel": (0, 0, int(W * 0.4), int(H * 0.9))}
                prefer = [c[:4] and "left_panel" for c in
                          (ch.cells if (ch is not None and ch.cells) else [])][:1]
                r = self._module(self.ocr.run, frame, regions,
                                 [p for p in prefer if p])
                self.stats["ocr_ms"] = _ema(self.stats["ocr_ms"],
                                            (time.perf_counter() - t0) * 1000.0)
                if r:
                    ocr = r

            st = self._module(self.classifier.update, hints,
                              [d.class_name for d in dets],
                              [r.text for r in ocr], ch)
            if st is None:
                st = ("unknown", 0.0, False)
            evs = self._module(self.fusion.update, frame.frame_id, dets, ocr, ch,
                               st, hints) or []
            for ev in evs:
                ev.metadata["frame_age"] = round(frame.age, 3)
                self.stats["events"] += 1
                self.bus.publish(ev)
                self.diag.log_event(ev.to_dict())
                if ev.type == "game.unknown_visual_change":
                    self.stats["unknown"] += 1
                    if ev.metadata.get("want_snapshot") and self.diag.snapshots_enabled:
                        self.diag.snapshot(frame.image, ev.to_dict())
                if ev.type == "game.screen_transition":
                    self.stats["transitions"] += 1

            want = "running" if self.detector.status == "ok" else "degraded"
            with self._lock:
                if self._state in ("running", "degraded") and self._state != want:
                    self._state = want
            self._publish()
