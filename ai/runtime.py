# -*- coding: utf-8 -*-
"""Локальный runtime ONNX (v1.24): только CPU, лениво, с прогревом и замером.

onnxruntime — НЕобязательная зависимость: если пакет не установлен, load()
возвращает False со статусом "no_onnxruntime", и всё приложение продолжает
работать на легаси-зрении. Модели не скачиваются никогда.
"""
import threading
import time

import numpy as np


class ModelRuntime(object):
    """Обёртка InferenceSession: загрузка/валидация входа/инференс/выгрузка."""

    def __init__(self, model_path, threads=0):
        self.path = str(model_path)
        self.threads = int(threads)
        self._sess = None
        self._in_name = None
        self._in_shape = None
        self._lock = threading.Lock()
        self.status = "new"          # new|ok|no_onnxruntime|load_error|unloaded
        self.error = ""
        self.load_ms = 0.0
        self.last_ms = 0.0
        self.ema_ms = 0.0
        self.runs = 0

    @property
    def loaded(self):
        return self._sess is not None

    def input_shape(self):
        return tuple(self._in_shape) if self._in_shape else None

    def load(self):
        """Ленивая загрузка. True — сессия готова к infer()."""
        with self._lock:
            if self._sess is not None:
                return True
            try:
                import onnxruntime as ort
            except Exception:
                self.status, self.error = "no_onnxruntime", "pip install onnxruntime"
                return False
            t0 = time.perf_counter()
            try:
                so = ort.SessionOptions()
                so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                if self.threads > 0:                    # настраиваемые потоки CPU
                    so.intra_op_num_threads = self.threads
                    so.inter_op_num_threads = 1
                sess = ort.InferenceSession(self.path, so, providers=["CPUExecutionProvider"])
                inp = sess.get_inputs()[0]
                self._in_name = inp.name
                shape = [int(d) if isinstance(d, int) and d > 0 else 1 for d in inp.shape]
                self._in_shape = [1, 3, 64, 64] if len(shape) != 4 else shape
                # прогрев: первая инструкция всегда медленная — не смешиваем с рабочей
                dummy = np.zeros(self._in_shape, np.float32)
                sess.run(None, {self._in_name: dummy})
                self._sess = sess
                self.status = "ok"
                self.load_ms = (time.perf_counter() - t0) * 1000.0
                return True
            except Exception as e:                       # битая/нечитаемая модель — не смертельно
                self.status, self.error = "load_error", "%s: %s" % (type(e).__name__, e)
                return False

    def infer(self, blob):
        """Прогон NCHW-float32 блока; возвращает выходы или None (нет модели)."""
        if self._sess is None:
            return None
        t0 = time.perf_counter()
        try:
            out = self._sess.run(None, {self._in_name: np.ascontiguousarray(blob, np.float32)})
        except Exception as e:
            self.status, self.error = "load_error", "%s: %s" % (type(e).__name__, e)
            self._sess = None                            # сессия битая — перезагрузит следующий load()
            return None
        dt = (time.perf_counter() - t0) * 1000.0
        self.last_ms = dt
        self.ema_ms = dt if not self.ema_ms else self.ema_ms * 0.8 + dt * 0.2
        self.runs += 1
        return out

    def unload(self):
        with self._lock:
            self._sess = None
            self.status = "unloaded"
