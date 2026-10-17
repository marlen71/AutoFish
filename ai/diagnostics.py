# -*- coding: utf-8 -*-
"""Диагностика AI-зрения (v1.24): журнал событий + снимки неизвестного.

* events.jsonl — построчные события (вращение по размеру, 3 файла);
* снимки ТОЛЬКО неизвестных/запрошенных событий, включаются настройкой;
  лимиты: max_files, max_mb и защита «на диске меньше 300 МБ — выключаемся»;
* по умолчанию кадры НЕ сохраняются массово.
"""
import json
import os
import shutil
import threading
import time


class Diagnostics(object):
    def __init__(self, out_dir, snapshots=True, max_files=40, max_mb=200):
        self.dir = str(out_dir)
        self.snapshots_enabled = bool(snapshots)
        self.max_files = max(5, int(max_files))
        self.max_mb = max(20, int(max_mb))
        self._lock = threading.Lock()
        self.events_written = 0
        self.snapshots_written = 0
        self.disabled_reason = ""
        try:
            os.makedirs(self.dir, exist_ok=True)
        except Exception:
            self.disabled_reason = "dir_unavailable"
        self._snap_dir = os.path.join(self.dir, "snapshots")

    # ------------------------------------------------------------------ события
    def _ev_path(self):
        return os.path.join(self.dir, "events.jsonl")

    def log_event(self, ev_dict):
        """Дописать событие в jsonl; ротация при >2 МБ (events.jsonl.1/.2)."""
        if self.disabled_reason:
            return False
        try:
            with self._lock:
                p = self._ev_path()
                try:
                    if os.path.getsize(p) > 2 * 1024 * 1024:   # ротация: .1 -> .2
                        if os.path.exists(p + ".1"):
                            os.replace(p + ".1", p + ".2")
                        os.replace(p, p + ".1")
                except OSError:
                    pass
                with open(p, "a", encoding="utf-8") as f:
                    f.write(json.dumps(ev_dict, ensure_ascii=False) + "\n")
                self.events_written += 1
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ снимки
    def snapshot(self, frame_bgr, ev_dict):
        """Снимок НЕИЗВЕСТНОГО события (png) с жёсткими лимитами хранилища."""
        if not self.snapshots_enabled or self.disabled_reason:
            return None
        if frame_bgr is None or frame_bgr.size == 0:
            return None
        try:
            if shutil.disk_usage(self.dir).free < 300 * 1024 * 1024:
                self.disabled_reason = "low_disk"
                return None
            os.makedirs(self._snap_dir, exist_ok=True)
            name = "unk_%s_%s_%s.png" % (time.strftime("%H%M%S"),
                                         ("%04d" % (int(time.time() * 1000) % 10000)),
                                         str(ev_dict.get("frame_id", "x")))
            path = os.path.join(self._snap_dir, name)
            import cv2
            cv2.imwrite(path, frame_bgr)
            self.snapshots_written += 1
            self._enforce_limits()
            return path
        except Exception:
            return None

    def _enforce_limits(self):
        try:
            files = sorted((os.path.join(self._snap_dir, f) for f in
                            os.listdir(self._snap_dir) if f.endswith(".png")),
                           key=os.path.getmtime)
            while len(files) > self.max_files:
                os.remove(files.pop(0))
            total = sum(os.path.getsize(f) for f in files if os.path.exists(f))
            while total > self.max_mb * 1024 * 1024 and files:
                p = files.pop(0)
                total -= os.path.getsize(p)
                os.remove(p)
        except Exception:
            pass

    def report(self):
        """Короткий статус для GUI/журнала (без чтения тяжёлых файлов)."""
        snaps = 0
        try:
            snaps = len([f for f in os.listdir(self._snap_dir) if f.endswith(".png")])
        except Exception:
            pass
        return {"events": self.events_written, "snapshots": snaps,
                "disabled": self.disabled_reason}
