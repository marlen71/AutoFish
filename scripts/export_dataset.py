#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сессия(и) записи -> YOLO-датасет. CLI над ai.dataset_export.

    python scripts/export_dataset.py                        # последняя сессия
    python scripts/export_dataset.py --session sessions/rec_XXXX --out my_ds
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ai.dataset_export import export_session          # noqa: E402


def latest_session(base):
    d = os.path.join(base, "sessions")
    if not os.path.isdir(d):
        return None
    cands = sorted((os.path.join(d, n) for n in os.listdir(d)
                    if n.startswith("rec_") and os.path.isdir(os.path.join(d, n))),
                   key=os.path.getmtime)
    return cands[-1] if cands else None


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="", help="каталог сессии (по умолчанию — последняя)")
    ap.add_argument("--out", default="", help="куда писать датасет")
    ap.add_argument("--crop", type=int, default=96)
    ap.add_argument("--val-split", type=float, default=0.2)
    args = ap.parse_args()
    sess = args.session or latest_session(ROOT)
    if not sess:
        print("Сессий нет: сначала запиши свою игру (страница «AI-ЗРЕНИЕ» → «Записать сессию»).")
        return 1
    out = args.out or os.path.join(ROOT, "dataset_out")
    r = export_session(sess, out, crop=args.crop, val_split=args.val_split)
    print("Кадров: %(frames)d | кликов-меток: %(clicks)d | объектов: %(objects)d | фон: %(background)d"
          % r)
    print("Классы: %s" % ", ".join(r["classes"]))
    print("Датасет: %s (проверь review.csv и поправь классы при нужде)" % r["out"])
    print("Дальше: docs/LEARNING.md — обучение YOLO и подключение модели.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
