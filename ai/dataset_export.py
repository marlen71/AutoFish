# -*- coding: utf-8 -*-
"""Сборка YOLO-датасета из записанных сессий (v1.25).

Идея: ТВОИ КЛИКИ — готовые метки. На кадре клика вырезаем область вокруг
координаты (это объект, по которому ты кликнул) и пишем YOLO-метку; остальные
кадры идут фоном (пустые метки) — они учат модель «здесь ничего нет».

Автоклассы (эвристика по кадру, потом правишь руками в review.csv):
  menu_row        — клик по строке контекстного меню (красная/белая полоса);
  inventory_item  — клик в левой панели инвентаря;
  click_target    — остальное.
Формат: images/{train,val}, labels/{train,val}, data.yaml, review.csv.
"""
import os
import random

import cv2
import numpy as np

DEFAULT_CROP = 96
CLASSES = ("menu_row", "inventory_item", "click_target")


def _crop_class(bgr, fx, fy):
    """Эвристика класса по содержимому вокруг точки клика."""
    H, W = bgr.shape[:2]
    x0, y0 = max(0, fx - 40), max(0, fy - 40)
    x1, y1 = min(W, fx + 40), min(H, fy + 40)
    crop = bgr[y0:y1, x0:x1]
    if crop.size:
        r = crop[:, :, 2].astype(np.int16)
        g = crop[:, :, 1].astype(np.int16)
        b = crop[:, :, 0].astype(np.int16)
        red = ((r > 110) & (r - np.maximum(g, b) > 60)).mean()
        if red > 0.15:                                   # красная строка меню
            return "menu_row"
    if fx < W * 0.40:                                    # левая панель = инвентарь
        return "inventory_item"
    return "click_target"


def export_session(session_dir, out_dir, crop=DEFAULT_CROP, val_split=0.2,
                   bg_frac=0.25, seed=7):
    """Сессия -> YOLO-датасет. Возвращает сводку (dict)."""
    from .recorder import load_session
    meta, acts, _imi = load_session(session_dir)
    frames_dir = os.path.join(session_dir, "frames")
    if not os.path.isdir(frames_dir):
        raise FileNotFoundError("в сессии нет frames/ — записей кадра не было")
    click_rows = [a for a in acts if a.get("type") == "click" and a.get("x") is not None
                  and a.get("frame") is not None]
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        os.makedirs(os.path.join(out_dir, sub), exist_ok=True)
    rnd = random.Random(seed)
    n_obj, n_bg, review = 0, 0, []
    half = crop / 2.0
    # --- объекты: кадры с кликами ---
    by_type = {}
    for a in click_rows:
        by_type.setdefault(a["frame"], []).append(a)
    for fid, rows in by_type.items():
        fpath = os.path.join(frames_dir, "f%06d.jpg" % fid)
        img = cv2.imread(fpath)
        if img is None:
            continue
        H, W = img.shape[:2]
        sub = "val" if rnd.random() < val_split else "train"
        lines = []
        for a in rows:
            fx = min(W - 1, max(0, int(a["x"] * (W / float(a.get("w") or W)))))
            fy = min(H - 1, max(0, int(a["y"] * (H / float(a.get("h") or H)))))
            x0, y0 = int(max(0, fx - half)), int(max(0, fy - half))
            x1, y1 = int(min(W, fx + half)), int(min(H, fy + half))
            if x1 - x0 < 8 or y1 - y0 < 8:
                continue
            cls = _crop_class(img, fx, fy)
            ci = CLASSES.index(cls)
            # координаты объекта в вырезанном кропе, нормировка 0..1
            cx = (fx - x0) / float(x1 - x0)
            cy = (fy - y0) / float(y1 - y0)
            nw = min(1.0, crop / float(x1 - x0))
            nh = min(1.0, crop / float(y1 - y0))
            lines.append("%d %.4f %.4f %.4f %.4f" % (ci, cx, cy, nw, nh))
            review.append({"frame": fid, "x": fx, "y": fy, "class": cls,
                           "file": "%s_%06d" % (sub, n_obj)})
            n_obj += 1
        name = "obj_%06d.jpg" % fid
        cv2.imwrite(os.path.join(out_dir, "images", sub, name), img)
        with open(os.path.join(out_dir, "labels", sub,
                               name.replace(".jpg", ".txt")), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
    # --- фон: кадры без кликов (пустые метки), с потолком доли ---
    fr_rows = [a for a in acts if a.get("type") == "frame"]
    bgs = [a for a in fr_rows if a["frame"] not in by_type]
    rnd.shuffle(bgs)
    cap = int(len(fr_rows) * bg_frac) if fr_rows else 0
    for a in bgs[:cap]:
        fpath = os.path.join(frames_dir, a.get("file", ""))
        img = cv2.imread(fpath)
        if img is None:
            continue
        sub = "val" if rnd.random() < val_split else "train"
        name = "bg_%06d.jpg" % a["frame"]
        cv2.imwrite(os.path.join(out_dir, "images", sub, name), img)
        open(os.path.join(out_dir, "labels", sub, name.replace(".jpg", ".txt")),
             "w").close()
        n_bg += 1
    with open(os.path.join(out_dir, "data.yaml"), "w", encoding="utf-8") as f:
        f.write("path: %s\ntrain: images/train\nval: images/val\nnames:\n" %
                os.path.abspath(out_dir))
        for i, c in enumerate(CLASSES):
            f.write("  %d: %s\n" % (i, c))
    if review:
        with open(os.path.join(out_dir, "review.csv"), "w", encoding="utf-8") as f:
            f.write("file;frame;x;y;class\n")
            for r in review:
                f.write("%(file)s;%(frame)d;%(x)d;%(y)d;%(class)s\n" % r)
    return {"objects": n_obj, "background": n_bg, "frames": len(fr_rows),
            "clicks": len(click_rows), "out": os.path.abspath(out_dir),
            "classes": list(CLASSES)}
