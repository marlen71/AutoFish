#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты записи сессий и сборки датасета (v1.25):
* SessionRecorder на фейках: кадры, клики с координатой, клавиши, игровой
  курсор, imitation-строки, лимиты (max_frames/диск), чистый стоп;
* export_session: клик -> YOLO-метка, эвристика классов, фон, data.yaml,
  review.csv. Запуск: python tests/test_ai_recorder.py"""
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cv2
import numpy as np

from ai.dataset_export import export_session
from ai.frame_router import Frame
from ai.recorder import SessionRecorder, load_session

fails = []


def check(label, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + label + ("  " + extra if extra else ""))
    if not cond:
        fails.append(label)


def mkframe(fid, cursor_at=None, size=(120, 160)):
    img = np.full((size[1], size[0], 3), 40, np.uint8)
    if cursor_at:
        cv2.fillPoly(img, [np.array([[cursor_at[0], cursor_at[1] - 9],
                                     [cursor_at[0] + 7, cursor_at[1]],
                                     [cursor_at[0], cursor_at[1] + 9]], np.int32)],
                     (255, 255, 255))
    return Frame(fid, time.time(), img,
                 {"left": 0, "top": 0, "width": size[0], "height": size[1]},
                 1.0, 1.0, "test", 5.0)


print("== 1. SessionRecorder: кадры, клики, клавиши, игровой курсор ==")
tmp = tempfile.mkdtemp()
try:
    seq = {"i": 0}
    clicks_at = {2: (60, 40)}                       # на 3-м тике ЛКМ в (60, 40)

    def frame_source():
        i = seq["i"]
        seq["i"] += 1
        return mkframe(i, cursor_at=(60 + i, 40))

    def input_poll():
        i = seq["i"] - 1                       # опрос идёт ПОСЛЕ frame_source()
        return {"lmb": i in clicks_at, "rmb": False, "x": 60 + i, "y": 40}

    def cursor_fn(bgr):
        # тот же принцип, что _game_cursor: белая стрелка на тёмном
        g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        m = (g > 225).astype(np.uint8)
        n, _l, st, _c = cv2.connectedComponentsWithStats(m, 8)
        for k in range(1, n):
            x, y, w, h, area = st[k]
            if 3 <= w <= 20 and 5 <= h <= 30 and area >= 10:
                return (int(x + w / 2), int(y + h / 2))
        return None

    keys = [(time.time(), "tab")]

    def analyzer(bgr):
        return {"zone": (10, 50, 30), "fish": 25, "slip": 0.02}

    rec = SessionRecorder(frame_source, input_poll, tmp, fps=10, max_frames=4,
                          cursor_fn=cursor_fn, analyzer_fn=analyzer,
                          key_events=lambda: keys, nap=lambda s: None)
    rec.start()
    t_end = time.time() + 5
    while time.time() < t_end and rec.frames < 4:
        time.sleep(0.02)
    st = rec.stop()
    check("записано ровно max_frames кадров", st["frames"] == 4 and
          st["reason"] in ("max_frames", "user"), str(st))
    check("jpg-файлы на диске", len(os.listdir(os.path.join(rec.frames_dir))) == 4)
    meta, acts, imi = load_session(rec.dir)
    fr_rows = [a for a in acts if a["type"] == "frame"]
    click_rows = [a for a in acts if a["type"] == "click"]
    check("строка на кадр с координатой ОС и игровым курсором",
          len(fr_rows) == 4 and all(a["gc"] for a in fr_rows) and
          all(a["os"] for a in fr_rows), str(fr_rows[0])[:100])
    check("клик зафиксирован на нужном кадре с координатой",
          len(click_rows) == 1 and click_rows[0]["frame"] == 2 and
          click_rows[0]["x"] == 62 and click_rows[0]["y"] == 40, str(click_rows))
    check("клавиша записана", any(a["type"] == "key" and a["name"] == "tab" for a in acts))
    check("imitation: зона/рыба/ЛКМ на каждом кадре", len(imi) == 4 and
          imi[2]["lmb"] is True and imi[0]["fish"] == 25, str(imi[:1]))
    check("meta.json финализирован", meta.get("final") is True and meta["frames"] == 4)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("== 2. Лимит диска: сессия останавливается сама ==")
tmp = tempfile.mkdtemp()
try:
    seq2 = {"i": 0}

    def fs2():
        seq2["i"] += 1
        return Frame(seq2["i"], time.time(),
                     np.full((200, 300, 3), 80, np.uint8),  # «тяжёлые» кадры
                     {"left": 0, "top": 0, "width": 300, "height": 200}, 1.0, 1.0,
                     "test", 5.0)

    rec2 = SessionRecorder(fs2, lambda: {"lmb": False, "rmb": False, "x": None, "y": None},
                           tmp, fps=10, max_mb=1, nap=lambda s: None)  # 1 МБ = быстрый автостоп
    rec2.start()
    t_end = time.time() + 5
    while time.time() < t_end and rec2.stopped_reason == "":
        time.sleep(0.02)
    st = rec2.stop()
    check("автостоп по лимиту диска", st["reason"] == "disk", str(st))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("== 3. export_session: клики -> YOLO-метки, классы, фон, data.yaml ==")
tmp = tempfile.mkdtemp()
tmp_out = tempfile.mkdtemp()
try:
    sess = os.path.join(tmp, "rec_test")
    os.makedirs(os.path.join(sess, "frames"))
    W, H = 160, 120
    # кадр 0: фон; кадр 1: клик по КРАСНОЙ строке (menu_row); кадр 2: клик в левой панели
    f0 = np.full((H, W, 3), 40, np.uint8)
    f1 = np.full((H, W, 3), 40, np.uint8)
    cv2.rectangle(f1, (40, 40), (140, 58), (40, 40, 200), -1)      # красная полоса
    f2 = np.full((H, W, 3), 60, np.uint8)
    f2[20:60, 10:50] = 120                                          # «иконка» слева
    for i, img in enumerate((f0, f1, f2)):
        cv2.imwrite(os.path.join(sess, "frames", "f%06d.jpg" % i), img)
    rows = [
        {"type": "frame", "t": 1, "frame": 0, "file": "f000000.jpg", "w": W, "h": H},
        {"type": "frame", "t": 2, "frame": 1, "file": "f000001.jpg", "w": W, "h": H},
        {"type": "click", "btn": "l", "t": 2, "frame": 1, "x": 90, "y": 49},
        {"type": "frame", "t": 3, "frame": 2, "file": "f000002.jpg", "w": W, "h": H},
        {"type": "click", "btn": "l", "t": 3, "frame": 2, "x": 30, "y": 40},
    ]
    with open(os.path.join(sess, "actions.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    with open(os.path.join(sess, "meta.json"), "w") as f:
        json.dump({"frames": 3}, f)
    r = export_session(sess, tmp_out, crop=48, val_split=0.0, bg_frac=1.0)
    check("сводка: 2 объекта, 1 фон, 3 кадра", r["objects"] == 2 and
          r["background"] == 1 and r["frames"] == 3, str(r))
    imgs = sorted(os.listdir(os.path.join(tmp_out, "images", "train")))
    lbls = sorted(os.listdir(os.path.join(tmp_out, "labels", "train")))
    check("images/labels пары на месте", len(imgs) == 3 and len(lbls) == 3,
          "%s %s" % (imgs, lbls))
    lab_red = open(os.path.join(tmp_out, "labels", "train", "obj_000001.txt")).read()
    parts = lab_red.split()
    check("YOLO-метка нормализована в [0,1] и класс=0 (menu_row по красноте)",
          len(parts) == 5 and parts[0] == "0" and
          all(0.0 <= float(v) <= 1.0 for v in parts[1:]), lab_red)
    lab_inv = open(os.path.join(tmp_out, "labels", "train", "obj_000002.txt")).read()
    check("клик в левой панели -> класс 1 (inventory_item)", lab_inv.split()[0] == "1",
          lab_inv)
    bg_lbl = open(os.path.join(tmp_out, "labels", "train", "bg_000000.txt")).read()
    check("фон — ПУСТАЯ метка", bg_lbl.strip() == "")
    yaml = open(os.path.join(tmp_out, "data.yaml")).read()
    check("data.yaml с классами по порядку", "menu_row" in yaml and
          "inventory_item" in yaml and "click_target" in yaml)
    rev = open(os.path.join(tmp_out, "review.csv"), encoding="utf-8").read()
    check("review.csv для ручной сверки", rev.count(";") >= 4, rev.strip()[:80])
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmp_out, ignore_errors=True)

print()
if fails:
    print("FAILED:", len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL RECORDER CHECKS PASSED")
