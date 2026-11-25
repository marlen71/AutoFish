"""One capture/inference worker, latest result only; Tk never runs inference."""
import threading
import time
from .core import Box


def resolve_device(requested, cuda_available):
    if requested == 'cpu':
        return 'cpu', False
    if cuda_available:
        return '0', False
    return 'cpu', requested == '0'


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
            requested = [int(c) for c in a.classes.split(',')] if isinstance(a.classes,str) else a.classes
            classes = [c for c in requested if str(names.get(c, '')).lower() not in ('self', 'own_player')]
            if not classes or any(c not in names for c in classes):
                raise ValueError(f'Invalid player classes {a.classes}; model classes: {names}')
            device, fallback = resolve_device(a.device, torch.cuda.is_available())
            low_conf = min(a.confidence,a.track_confidence)
            # Fuse once before capture, not on the first enabled frame.
            model.fuse(verbose=False)
            warmup = np.zeros((a.imgsz,a.imgsz,3), dtype=np.uint8)
            try:
                model.predict(warmup,classes=classes,conf=low_conf,imgsz=a.imgsz,device=device,verbose=False)
            except Exception:
                if device == 'cpu':
                    raise
                device = 'cpu'
                fallback = True
                model.to('cpu')
                model.predictor = None
                model.predict(warmup,classes=classes,conf=low_conf,imgsz=a.imgsz,device=device,verbose=False)
            self.status = f'{device} | input {a.imgsz}' + (' | GPU unavailable: CPU fallback (Install_GPU_1080Ti.bat)' if fallback else '')
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
                    result = model.predict(frame, classes=classes, conf=low_conf, imgsz=a.imgsz,
                                           device=device, verbose=False)[0]
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
