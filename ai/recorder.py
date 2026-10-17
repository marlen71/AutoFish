# -*- coding: utf-8 -*-
"""Запись игровых сессий для обучения ИИ (v1.25) — «ИИ учится на твоих действиях».

Пока ТЫ играешь руками (открываешь инвентарь, кликаешь предметы, играешь
мини-игру), рекордер складывает по тикам:
  frames/f%06d.jpg   — кадры экрана (прореженные, сжатые, с лимитом объёма);
  actions.jsonl      — по строке на кадр: время, файл, ИГРОВОЙ курсор (если
                       увиден детектором), кнопки мыши; отдельными строками —
                       клики (с координатой!) и нажатия клавиш;
  imitation.jsonl    — разбор мини-игры (зона/рыба/срыв) + состояние ЛКМ:
                       это пары «состояние -> действие человека», материал
                       для будущей политики мини-игры;
  meta.json          — конфигурация и итоговые счётчики сессии.

Зависимости — ТОЛЬКО инъекции: источник кадров, опрос кнопок/курсора, детектор
игрового курсора и анализатор мини-игры передаёт основное приложение. Поэтому
модуль тестируется без Windows и не тянет вечный цикл захвата.

ВСЁ, что делает рекордер — пишет файлы. Он не двигает мышь и не жмёт клавиши.
"""
import json
import os
import threading
import time

import cv2


class SessionRecorder(object):
    def __init__(self, frame_source, input_poll, out_dir,
                 fps=5.0, quality=80, max_width=960, max_mb=500,
                 cursor_fn=None, analyzer_fn=None, key_events=None,
                 nap=time.sleep, max_frames=0):
        """frame_source() -> ai.frame_router.Frame | None
        input_poll() -> {"lmb": bool, "rmb": bool, "x": int|None, "y": int|None}
                        (координаты — ЭКРАННЫЕ физические пиксели)
        cursor_fn(bgr) -> (x, y) | None — детектор игрового курсора
        analyzer_fn(bgr) -> {"zone":…, "fish":…, "slip":…} | None — мини-игра
        key_events() -> [(t, name)] — накопленные нажатия клавиш (дренируются)."""
        self._src = frame_source
        self._poll = input_poll
        self._cursor_fn = cursor_fn
        self._analyzer_fn = analyzer_fn
        self._keys = key_events or (lambda: [])
        self._nap = nap
        self.fps = min(15.0, max(1.0, float(fps)))
        self.quality = min(95, max(40, int(quality)))
        self.max_width = min(1920, max(480, int(max_width)))
        self.max_mb = max(0, int(max_mb))
        self.max_frames = max(0, int(max_frames))     # 0 = без ограничения
        self.dir = os.path.join(str(out_dir), "rec_%s" % time.strftime("%Y%m%d_%H%M%S"))
        self.frames_dir = os.path.join(self.dir, "frames")
        self._stop = threading.Event()
        self._thr = None
        self._lock = threading.Lock()
        self.frames = 0
        self.actions = 0
        self.clicks = 0
        self.bytes = 0
        self.cursor_hits = 0
        self.imi_rows = 0
        self.stopped_reason = ""                      # ""|user|disk|max_frames|error
        self.error = ""
        self.t_start = 0.0

    # ------------------------------------------------------------------ статус
    def status(self):
        with self._lock:
            return {"recording": self._thr is not None and self._thr.is_alive()
                    and not self._stop.is_set(),
                    "dir": self.dir, "frames": self.frames, "actions": self.actions,
                    "clicks": self.clicks, "mb": round(self.bytes / 1048576.0, 1),
                    "cursor_hits": self.cursor_hits, "imi": self.imi_rows,
                    "reason": self.stopped_reason, "error": self.error}

    def start(self):
        with self._lock:
            if self._thr is not None and self._thr.is_alive():
                return False
            self._stop.clear()
            os.makedirs(self.frames_dir, exist_ok=True)
            self.t_start = time.time()
            self._wmeta(final=False)
            self._thr = threading.Thread(target=self._loop, daemon=True, name="ai-rec")
            self._thr.start()
            return True

    def stop(self, reason="user", timeout=5.0):
        self._stop.set()
        thr = self._thr
        if thr is not None and thr.is_alive():
            thr.join(timeout)
        self._thr = None
        with self._lock:
            if not self.stopped_reason:
                self.stopped_reason = reason
            self._wmeta(final=True)
        return self.status()

    # ------------------------------------------------------------------ запись
    def _wline(self, name, row):
        try:
            with open(os.path.join(self.dir, name), "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.actions += 1
        except Exception as e:
            self.error = "%s: %s" % (type(e).__name__, e)

    def _wmeta(self, final):
        try:
            with open(os.path.join(self.dir, "meta.json"), "w", encoding="utf-8") as f:
                json.dump({"t_start": self.t_start, "t_end": time.time(),
                           "final": bool(final), "fps": self.fps,
                           "quality": self.quality, "max_width": self.max_width,
                           "frames": self.frames, "actions": self.actions,
                           "clicks": self.clicks, "bytes": self.bytes,
                           "cursor_hits": self.cursor_hits, "imi_rows": self.imi_rows,
                           "stopped_reason": self.stopped_reason,
                           "error": self.error}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.error = "%s: %s" % (type(e).__name__, e)

    def _save_frame(self, fr):
        img = fr.image
        H, W = img.shape[:2]
        if W > self.max_width:
            k = self.max_width / float(W)
            img = cv2.resize(img, (self.max_width, max(1, int(H * k))),
                             interpolation=cv2.INTER_AREA)
        name = "f%06d.jpg" % self.frames
        path = os.path.join(self.frames_dir, name)
        ok = cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
        if not ok:
            return None
        try:
            self.bytes += os.path.getsize(path)
        except OSError:
            pass
        return name

    def _loop(self):
        prev_lmb = prev_rmb = False
        period = 1.0 / self.fps
        try:
            while not self._stop.is_set():
                t0 = time.perf_counter()
                fr = self._src()
                if fr is not None and getattr(fr, "image", None) is not None:
                    fname = self._save_frame(fr)
                    if fname is None:
                        self.stopped_reason = "error"
                        break
                    fid = self.frames
                    self.frames += 1
                    inp = self._poll() or {}
                    # координаты в СИСТЕМЕ КАДРА (физические px монитора захвата)
                    mx = my = None
                    try:
                        if inp.get("x") is not None:
                            mx = int(inp["x"] - fr.mon.get("left", 0))
                            my = int(inp["y"] - fr.mon.get("top", 0))
                    except Exception:
                        mx = my = None
                    gc = self._cursor_fn(fr.image) if self._cursor_fn else None
                    if gc:
                        self.cursor_hits += 1
                    self._wline("actions.jsonl", {
                        "type": "frame", "t": time.time(), "frame": fid, "file": fname,
                        "w": int(fr.image.shape[1]), "h": int(fr.image.shape[0]),
                        "lmb": bool(inp.get("lmb")), "rmb": bool(inp.get("rmb")),
                        "os": [mx, my] if mx is not None else None,
                        "gc": [int(gc[0]), int(gc[1])] if gc else None})
                    # клики — момент нажатия (edge), с координатой: это БУДУЩИЕ метки
                    lmb, rmb = bool(inp.get("lmb")), bool(inp.get("rmb"))
                    if lmb and not prev_lmb:
                        self.clicks += 1
                        self._wline("actions.jsonl", {
                            "type": "click", "btn": "l", "t": time.time(),
                            "frame": fid, "x": mx, "y": my})
                    if rmb and not prev_rmb:
                        self.clicks += 1
                        self._wline("actions.jsonl", {
                            "type": "click", "btn": "r", "t": time.time(),
                            "frame": fid, "x": mx, "y": my})
                    prev_lmb, prev_rmb = lmb, rmb
                    for kt, kname in (self._keys() or []):
                        self._wline("actions.jsonl", {
                            "type": "key", "t": kt, "name": str(kname), "frame": fid})
                    # мини-игра: состояние -> действие человека (для будущей политики)
                    if self._analyzer_fn:
                        try:
                            r = self._analyzer_fn(fr.image) or {}
                        except Exception:
                            r = {}
                        if r.get("zone") or r.get("fish") is not None:
                            self.imi_rows += 1
                            self._wline("imitation.jsonl", {
                                "t": time.time(), "frame": fid,
                                "zone": r.get("zone"), "fish": r.get("fish"),
                                "slip": round(float(r.get("slip") or 0.0), 4),
                                "lmb": lmb})
                    if self.max_frames and self.frames >= self.max_frames:
                        self.stopped_reason = "max_frames"
                        break
                    if self.max_mb and self.bytes >= self.max_mb * 1048576:
                        self.stopped_reason = "disk"
                        break
                remain = period - (time.perf_counter() - t0)
                if remain > 0:
                    self._nap(remain)
        except Exception as e:
            self.error = "%s: %s" % (type(e).__name__, e)
            self.stopped_reason = "error"
        finally:
            with self._lock:
                if not self.stopped_reason:
                    self.stopped_reason = "user"
                self._wmeta(final=True)


def load_session(session_dir):
    """Прочитать сессию: (meta, actions[], imitation[]) — для экспорта/анализа."""
    meta, acts, imi = {}, [], []
    try:
        with open(os.path.join(session_dir, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        pass
    for nm, dst in (("actions.jsonl", acts), ("imitation.jsonl", imi)):
        try:
            with open(os.path.join(session_dir, nm), encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        dst.append(json.loads(line))
        except FileNotFoundError:
            pass
        except Exception:
            continue
    return meta, acts, imi
