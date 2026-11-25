"""One capture/inference worker, latest result only; Tk never runs inference."""
import threading
import time
from .core import Box


class Detector:
    def __init__(self, args, monitor):
        self.args, self.monitor = args, monitor
        self.enabled = threading.Event()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.latest = None
        self.sequence = 0
        self.error = None
        self.status = 'Loading model...'
        self.generation = 0
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def activate(self, active):
        with self.lock:
            self.generation += 1
            self.latest = None
            if active:
                self.enabled.set()
            else:
                self.enabled.clear()

    def read(self):
        with self.lock:
            return self.latest

    def run(self):
        try:
            import mss
            import numpy as np
            import torch
            from ultralytics import YOLO
            a = self.args
            torch.set_num_threads(a.cpu_threads)
            model = YOLO(a.model, task='detect')
            names = model.names
            classes = [c for c in a.classes if str(names.get(c, '')).lower() not in ('self', 'own_player')]
            if not classes or any(c not in names for c in classes):
                raise ValueError(f'Invalid player classes {a.classes}; model classes: {names}')
            self.status = f'{a.device} | input {a.imgsz} | {a.cpu_threads} CPU threads'
            # Fuse once before capture, not on the first enabled frame.
            model.fuse(verbose=False)
            with mss.mss() as capture:
                while not self.stop.is_set():
                    if not self.enabled.wait(.1):
                        continue
                    if self.stop.is_set():
                        break
                    with self.lock:
                        generation = self.generation
                    captured = time.perf_counter()
                    frame = np.asarray(capture.grab(self.monitor))[:, :, :3].copy()
                    result = model.predict(frame, classes=classes, conf=a.confidence, imgsz=a.imgsz,
                                           device=a.device, verbose=False)[0]
                    boxes = []
                    if result.boxes is not None:
                        for xy, conf in zip(result.boxes.xyxy.cpu().tolist(), result.boxes.conf.cpu().tolist()):
                            x1,y1,x2,y2 = xy
                            b = Box(max(0,x1), max(0,y1), min(self.monitor['width'],x2), min(self.monitor['height'],y2), conf)
                            if b.x2 > b.x1 and b.y2 > b.y1:
                                boxes.append(b)
                    with self.lock:
                        if generation == self.generation and self.enabled.is_set():
                            self.sequence += 1
                            self.latest = (self.sequence, captured, boxes, time.perf_counter()-captured)
        except Exception as exc:
            self.error = str(exc)
