#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Интеграционный тест детектора с НАСТОЯЩЕЙ ONNX-моделью (v1.24).

Модель крошечная и СИНТЕТИЧЕСКАЯ (генерируется на месте через onnx.helper):
её цель — проверить весь конвейер (манифест -> sha256 -> Runtime -> препроцесс ->
инференс CPU -> постобработка nms5 -> координаты кадра -> NMS), а НЕ распознавание
игры. Игра-специфичные модели требуют датасета (datasets/README.md).

Если onnx/onnxruntime не установлены — тест ЧЕСТНО сообщит и пропустит сценарий
(приложение в этом режиме живёт на легаси-зрении).
Запуск: python tests/test_ai_detector_onnx.py"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

try:
    import onnx
    from onnx import helper, TensorProto
    import onnxruntime
except Exception as e:
    print("SKIP: onnx/onnxruntime не установлены (%s) — приложение работает на легаси." % e)
    sys.exit(0)

from ai.detector import make_detector
from ai.model_manager import ModelManager
from ai.runtime import ModelRuntime

fails = []


def check(label, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + label + ("  " + extra if extra else ""))
    if not cond:
        fails.append(label)


def build_tiny_onnx(path, rows=4, ncls=3, inchw=(1, 3, 64, 64)):
    """Модель-константа: выход [1, rows, 5+ncls]. Строка 0: obj~1, class0~0.98,
    box=(0.5, 0.5, 0.5, 0.5) после sigmoid(0) — детекция детерминирована bias."""
    total = 5 + ncls
    bias = np.full((1, rows, total), -6.0, np.float32)   # по умолчанию всё «пусто»
    bias[0, 0, 0:4] = 0.0                                # box = sigmoid(0) = 0.5
    bias[0, 0, 4] = 6.0                                  # obj = sigmoid(6) ~ 0.998
    bias[0, 0, 5] = 4.0                                  # class_0 ~ 0.982
    X = helper.make_tensor_value_info("images", TensorProto.FLOAT, list(inchw))
    Y = helper.make_tensor_value_info("out", TensorProto.FLOAT, [1, rows, total])
    # выход — константа (синтетика для конвейера): вход обязателен по контракту,
    # но содержимо не используется. Real-модель: conv-детектор с тем же выходом.
    const = helper.make_tensor("detections", TensorProto.FLOAT, [1, rows, total],
                               bias.flatten().tolist())
    node = helper.make_node("Constant", [], ["out"], value=const)
    g = helper.make_graph([node], "tiny", [X], [Y])
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 13)])
    m.ir_version = 9
    onnx.checker.check_model(m)
    onnx.save(m, path)


print("== 1. Синтетическая ONNX-модель: манифест, сумма, Runtime ==")
tmp = tempfile.mkdtemp()
try:
    onnx_path = os.path.join(tmp, "tiny_detector.onnx")
    build_tiny_onnx(onnx_path)
    sha = hashlib.sha256(open(onnx_path, "rb").read()).hexdigest()
    with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "models": {"detector": {
            "file": "tiny_detector.onnx", "sha256": sha, "version": "0.0.1-test",
            "input": [1, 3, 64, 64], "layout": "nms5",
            "classes": ["fishing_rod", "bait_icon", "inventory_window"]}}}, f)
    mm = ModelManager(tmp)
    det, status = make_detector(mm, conf=0.45)
    check("менеджер нашёл и принял модель (ленивая загрузка)", status == "ready",
          str(status))
    check("load(): сессия поднялась на CPUExecutionProvider",
          det.ensure_loaded() is True and det.status == "ok" and
          det.rt.input_shape() == (1, 3, 64, 64), det.status)

    print("== 2. Инференс: детекция в координатах кадра (letterbox туда-обратно) ==")
    frame = np.full((540, 960, 3), 40, np.uint8)         # «экран» 960x540
    t0 = time.perf_counter()
    dets = det.detect(frame, frame_id=101)
    dt_ms = (time.perf_counter() - t0) * 1000.0
    check("ровно одна детекция выше порога", len(dets) == 1, str([repr(d) for d in dets]))
    d = dets[0]
    check("класс из реестра манифеста", d.class_name == "fishing_rod" and d.class_id == 0)
    cx, cy = d.bbox[0] + d.bbox[2] / 2, d.bbox[1] + d.bbox[3] / 2
    check("центр box сходится с sigmoid(0.5)*W/H (letterbox учтён)",
          abs(cx - 480) < 8 and abs(cy - 270) < 8, "c=(%.1f, %.1f)" % (cx, cy))
    check("уверенность детерминирована", abs(d.confidence - 0.982 * 0.9975) < 0.01,
          "%.3f" % d.confidence)
    check("метаданные детекции заполнены", d.frame_id == 101 and d.model != ""
          and d.ts > 0)
    check("замер инференса ведётся", det.rt.ema_ms > 0.0 and det.rt.runs >= 1,
          "%.2f мс (runs=%d)" % (det.rt.ema_ms, det.rt.runs))

    print("== 3. Порог уверенности: завышенный отрезает всё ==")
    strict, _ = make_detector(mm, conf=0.999)
    strict.ensure_loaded()
    check("conf=0.999 -> 0 детекций (obj*cls ~ 0.98 < 0.999)",
          len(strict.detect(frame)) == 0)

    print("== 4. Битая модель: статус bad_checksum, приложение не падает ==")
    with open(onnx_path, "ab") as f:
        f.write(b"corrupted")
    mm2 = ModelManager(tmp)
    det2, status2 = make_detector(mm2, conf=0.45)
    check("контрольная сумма отбила битый файл", status2 == "bad_checksum" and
          det2.detect(frame) == [], "%s %s" % (status2, det2.status))

    print("== 5. Производительность CPU (эталонная среда, не поле) ==")
    tmp2 = tempfile.mkdtemp()
    build_tiny_onnx(os.path.join(tmp2, "tiny_detector.onnx"))
    sha2 = hashlib.sha256(open(os.path.join(tmp2, "tiny_detector.onnx"), "rb").read()).hexdigest()
    with open(os.path.join(tmp2, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "models": {"detector": {
            "file": "tiny_detector.onnx", "sha256": sha2, "version": "0.0.1-test",
            "input": [1, 3, 64, 64], "layout": "nms5",
            "classes": ["fishing_rod", "bait_icon", "inventory_window"]}}}, f)
    det3, _ = make_detector(ModelManager(tmp2), conf=0.45)
    det3.ensure_loaded()
    blob_frame = np.full((1080, 1920, 3), 60, np.uint8)
    n, t0 = 0, time.perf_counter()
    while time.perf_counter() - t0 < 1.5:
        det3.detect(blob_frame, frame_id=n)
        n += 1
    wall = time.perf_counter() - t0
    print("     полный экран 1920x1080: %d инференсов за %.2f с -> %.1f к/с (по %.1f мс)"
          % (n, wall, n / wall, det3.rt.ema_ms))
    check("конвейер держит хотя бы 10 к/с на синтетике 64x64 (бенчмарк-минимум)",
          n / wall >= 10.0, "%.1f к/с" % (n / wall))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    if "tmp2" in dir():
        shutil.rmtree(tmp2, ignore_errors=True)

print()
if fails:
    print("FAILED:", len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL ONNX-DETECTOR CHECKS PASSED")
