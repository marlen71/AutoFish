"""Latest-result engine. Capture/inference are replaceable; no input injection here."""
import threading
import time
from collections import deque
from .core import Box
from .inference import resolve_device  # compatibility for existing integrations/tests


class Detector:
    def __init__(self,args,monitor,preview=False):
        self.args,self.monitor,self.preview = args,monitor,preview
        self.enabled,self.stop = threading.Event(),threading.Event()
        self.lock = threading.Lock()
        self.latest,self.metrics,self.preview_jpeg = None,{},None
        self.sequence,self.generation = 0,0
        self.error,self.status,self.warning = None,'Loading model...', ''
        self.thread = threading.Thread(target=self.run,daemon=True)
        self.thread.start()

    def activate(self,active):
        with self.lock:
            self.generation += 1
            self.latest = None
            self.preview_jpeg = None
            self.enabled.set() if active else self.enabled.clear()

    def read(self):
        with self.lock:
            return self.latest

    def diagnostics(self):
        with self.lock:
            return dict(self.metrics),self.preview_jpeg

    def run(self):
        capture = None
        try:
            from .capture import ScreenCapture
            from .inference import create_backend
            backend = create_backend(self.args)
            self.status = 'Opening screen capture...'
            capture = ScreenCapture(self.args,self.monitor)
            self.status = f'{capture.name} | {backend.name}'
            self.warning = ' | '.join(v for v in (capture.warning,backend.warning) if v)
            last_generation,last_source,last_finished=None,None,None
            samples=deque(maxlen=120)
            while not self.stop.is_set():
                if not self.enabled.wait(.1):
                    continue
                if self.stop.is_set():
                    break
                with self.lock:
                    generation = self.generation
                if generation != last_generation:
                    capture.invalidate()
                    samples.clear()
                    last_source=None
                    last_finished=None
                    last_generation=generation
                cycle_start = time.perf_counter()
                frame,captured,origin,capture_ms = capture.grab()
                if captured == last_source:
                    # Reusing a DXGI desktop cache must not reset track velocity or
                    # spend another inference on the exact same source timestamp.
                    self.stop.wait(.004)
                    continue
                last_source=captured
                boxes,timings = backend.predict(frame)
                x,y = origin
                mapped = []
                for b in boxes:
                    box = Box(max(0,b.x1+x),max(0,b.y1+y),min(self.monitor['width'],b.x2+x),
                              min(self.monitor['height'],b.y2+y),b.confidence)
                    if box.x2>box.x1 and box.y2>box.y1:
                        mapped.append(box)
                jpeg = None
                if self.preview:
                    import cv2
                    image = frame.copy()
                    for b in boxes:
                        cv2.rectangle(image,(round(b.x1),round(b.y1)),(round(b.x2),round(b.y2)),(70,220,140),2)
                    scale = min(640/image.shape[1],360/image.shape[0],1.)
                    image = cv2.resize(image,None,fx=scale,fy=scale)
                    ok,encoded = cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,80])
                    if ok:
                        jpeg = encoded.tobytes()
                finished=time.perf_counter()
                elapsed = finished-cycle_start
                fps=1/max(finished-last_finished,.000001) if last_finished else 0.
                last_finished=finished
                samples.append(elapsed*1000)
                ordered=sorted(samples)
                p50=ordered[(len(ordered)-1)//2]
                p95=ordered[min(len(ordered)-1,int((len(ordered)-1)*.95+.5))]
                metrics = dict(timings,p50_ms=p50,p95_ms=p95,samples=len(samples),capture_ms=capture_ms,total_ms=elapsed*1000,source_age_ms=(time.perf_counter()-captured)*1000,
                               frame_fps=fps,detections=len(mapped),
                               capture=capture.last_backend,inference=backend.name,region=self.args.capture_region,
                               frame_width=frame.shape[1],frame_height=frame.shape[0])
                self.status = f'{capture.last_backend} | {backend.name}'
                self.warning = ' | '.join(v for v in (capture.warning,backend.warning) if v)
                with self.lock:
                    if generation==self.generation and self.enabled.is_set():
                        self.sequence+=1
                        self.latest = (self.sequence,captured,mapped,elapsed)
                        self.metrics,self.preview_jpeg = metrics,jpeg
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'
        finally:
            if capture:
                capture.close()
