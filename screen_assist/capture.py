"""Windows capture backends. Every frame includes an explicit screen-space origin."""
import time
import threading

_DXGI_LOCK=threading.Lock()


def region_for(monitor, mode='full', size=960):
    width, height = monitor['width'], monitor['height']
    if mode == 'full':
        return (0, 0, width, height)
    side = min(int(size), width, height)
    x, y = (width-side)//2, (height-side)//2
    return (x, y, x+side, y+side)


class ScreenCapture:
    def __init__(self, args, monitor):
        import mss
        self.args, self.monitor = args, monitor
        self.mss = mss.mss()
        self.camera = None
        self.owns_dxgi_lock = False
        self.name, self.warning = 'MSS', ''
        self.region = region_for(monitor, args.capture_region, args.crop_size)
        self.cached, self.cached_at = None, 0.
        if args.capture_backend != 'mss':
            try:
                # MSS and DXGI don't promise the same output numbering. Never silently
                # choose a different screen when auto-probing a multi-monitor machine.
                if args.capture_backend == 'auto' and len(self.mss.monitors) != 2:
                    raise RuntimeError('Multiple monitors: auto uses MSS; select DXGI output explicitly')
                if not _DXGI_LOCK.acquire(blocking=False):
                    raise RuntimeError('DXGI is closing/in use; this session uses MSS')
                self.owns_dxgi_lock = True
                import dxcam
                self.camera = dxcam.create(output_idx=args.dxgi_output, output_color='BGR')
                self.name = 'DXGI'
            except Exception as exc:
                self._release_camera()
                self.warning = f'DXGI fallback: {exc}'
                self.name = 'MSS'

    def _mss_frame(self):
        import numpy as np
        x1,y1,x2,y2 = self.region
        region = dict(left=self.monitor['left']+x1, top=self.monitor['top']+y1,
                      width=x2-x1, height=y2-y1)
        return np.asarray(self.mss.grab(region))[:, :, :3].copy()

    def grab(self):
        started = time.perf_counter()
        frame = None
        frame_time = started
        self.last_backend = 'MSS'
        if self.camera is not None:
            try:
                raw = self.camera.grab()
                if raw is not None:
                    if raw.shape[:2] != (self.monitor['height'],self.monitor['width']):
                        raise RuntimeError('DXGI resolution does not match selected monitor')
                    x1,y1,x2,y2 = self.region
                    self.cached = raw[y1:y2,x1:x2,:3].copy()
                    self.cached_at = started
                    frame = self.cached
                    self.last_backend = 'DXGI'
                elif self.cached is not None and started-self.cached_at <= .08:
                    # DXGI returns None for an unchanged desktop; bound cache reuse.
                    frame = self.cached
                    self.last_backend = 'DXGI cached <=80ms'
                    frame_time = self.cached_at
                else:
                    frame = self._mss_frame()
                    self.last_backend = 'MSS refresh (DXGI unchanged)'
            except Exception as exc:
                self.warning = f'DXGI runtime fallback: {exc}'
                self._release_camera()
                self.name = 'MSS'
        if frame is None:
            frame = self._mss_frame()
        return frame, frame_time, self.region[:2], (time.perf_counter()-started)*1000

    def _release_camera(self):
        if self.camera is not None:
            try:
                self.camera.release()
            except Exception:
                pass
            self.camera = None
        if self.owns_dxgi_lock:
            self.owns_dxgi_lock = False
            _DXGI_LOCK.release()

    def invalidate(self):
        self.cached,self.cached_at=None,0.

    def close(self):
        self._release_camera()
        self.mss.close()
