"""Bounded background pseudo-label worker. Suggestions are never ground truth."""
import json
import queue
import threading
from pathlib import Path


def similar(a, b, threshold=2.0):
    return b is not None and len(a) == len(b) and sum(abs(x-y) for x, y in zip(a, b)) / max(1, len(a)) < threshold


def priority(confidences):
    # Empty and uncertain frames first; this is a heuristic, not calibrated uncertainty.
    return 1.0 if not confidences else 1.0 - min(confidences)


class ProposalWorker:
    def __init__(self, folder, weights='yolo11n.pt', classes=(0,)):
        self.folder = Path(folder) / 'suggestions'
        self.folder.mkdir(exist_ok=True)
        self.weights = str(weights)
        self.classes = list(classes)
        self.queue = queue.Queue(maxsize=8)
        self.stop = threading.Event()
        self.message = 'Загрузка модели…'
        self.done = 0
        self.skipped = 0
        self.failed = False
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def submit(self, path):
        if self.failed or self.stop.is_set():
            self.skipped += 1
            return
        try:
            self.queue.put_nowait(Path(path))
        except queue.Full:
            self.skipped += 1  # Screenshot remains available for manual annotation.

    def run(self):
        try:
            from ultralytics import YOLO
            from PIL import Image
            import torch
            torch.set_num_threads(2)
            model = YOLO(self.weights, task='detect')
            self.message = 'Предразметка работает (CPU)'
            while not self.stop.is_set():
                try:
                    path = self.queue.get(timeout=.2)
                except queue.Empty:
                    continue
                try:
                    with Image.open(path) as image:
                        result = model.predict(image.convert('RGB'), classes=self.classes, conf=.2,
                                               imgsz=640, device='cpu', verbose=False)[0]
                    boxes, confidence = [], []
                    if result.boxes is not None:
                        for xy, cls, conf in zip(result.boxes.xyxy.cpu().tolist(),
                                                 result.boxes.cls.cpu().tolist(), result.boxes.conf.cpu().tolist()):
                            # Self is recognized only by an explicit class name, never COCO class ID 1.
                            name = str(model.names[int(cls)]).lower()
                            boxes.append([1 if name in ('self', 'own_player') else 0, *xy])
                            confidence.append(conf)
                    record = dict(reviewed=False, boxes=boxes, confidence=confidence,
                                  priority=priority(confidence), model=self.weights,
                                  warning='Unverified suggestions; do not train without review')
                    target = self.folder / (path.stem + '.json')
                    temporary = target.with_suffix('.tmp')
                    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
                    temporary.replace(target)
                    self.done += 1
                finally:
                    self.queue.task_done()
        except Exception as exc:
            self.failed = True
            self.message = f'Предразметка отключена: {exc}. Кадры продолжают сохраняться.'
            while True:
                try:
                    self.queue.get_nowait()
                    self.queue.task_done()
                except queue.Empty:
                    break

    @property
    def pending(self):
        return self.queue.unfinished_tasks
