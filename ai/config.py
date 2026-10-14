# -*- coding: utf-8 -*-
"""AI-конфиг Eternal FishMod (v1.24).

Единственный источник значений по умолчанию для всех ai_* ключей конфига.
Основное приложение делает ``DEFAULT_CFG.update(AI_DEFAULTS)`` — старые конфиги
мигрируют аддитивно (недостающие ключи получают дефолты), поведение без AI не
меняется: ai_enabled=False, ai_mode="legacy".

ЗДЕСЬ НЕТ зависимостей (ни cv2, ни onnxruntime) — модуль безопасно импортировать
из самого верха основного файла.
"""
import os

# Ключи автоматически подхватываются системой конфига основного приложения
# (DEFAULT_CFG -> load_cfg/save_cfg). Ни один существующий ключ не трогается.
AI_DEFAULTS = {
    # мастер-выключатель: конвейер наблюдения запускается только со стартом рыбалки
    "ai_enabled": False,
    # стратегия поиска удочки при экипировке: legacy (шаблоны) | ai (детектор ONNX,
    # фолбэк на шаблоны) | hybrid (шаблоны первыми, детектор спасает при промахе)
    "ai_mode": "legacy",
    # конвейер полного анализа (медленный путь FrameRouter)
    "ai_fullscreen": True,
    # лёгкий детектор изменений (OpenCV, между инференциями)
    "ai_change_detect": True,
    # OCR текста интерфейса (RapidOCR onnxruntime; устанавливается отдельно)
    "ai_ocr_enabled": False,
    "ai_ocr_fps": 1.0,                   # распознаваний текста в секунду (не чаще)
    # полный экран: 2-5 к/с — стартовый ориентир ТЗ на CPU
    "ai_detect_fps": 2.0,
    "ai_conf": 0.45,                     # порог уверенности детектора
    # состояние считается сменившимся после стольких подтверждений подряд
    "ai_state_confirm": 3,
    # потоки ONNX Runtime (0 = решает runtime сам)
    "ai_threads": 0,
    # снимки НЕИЗВЕСТНЫХ событий (для разметки датасета); хранилище ограничено
    "ai_snapshots": True,
    "ai_snap_max_mb": 200,
    "ai_snap_max_files": 40,
    # каталог моделей ("" = ai/models рядом с ботом). Модели НИКОГДА не скачиваются
    # автоматически — только вручную, по инструкции docs/AI_VISION.md
    "ai_model_dir": "",
}


def ai_cfg(cfg):
    """Валидированный срез ai_* ключей из общего CFG (значения-мусор -> дефолт)."""
    d = AI_DEFAULTS
    out = {k: cfg.get(k, v) for k, v in d.items()}
    out["ai_mode"] = out["ai_mode"] if out["ai_mode"] in ("legacy", "ai", "hybrid") else "legacy"
    for k in ("ai_detect_fps", "ai_ocr_fps", "ai_conf"):
        try:
            out[k] = float(out[k])
        except (TypeError, ValueError):
            out[k] = float(d[k])
    out["ai_detect_fps"] = min(10.0, max(0.2, out["ai_detect_fps"]))
    out["ai_ocr_fps"] = min(5.0, max(0.1, out["ai_ocr_fps"]))
    out["ai_conf"] = min(0.95, max(0.05, out["ai_conf"]))
    for k in ("ai_state_confirm", "ai_threads", "ai_snap_max_files"):
        try:
            out[k] = int(out[k])
        except (TypeError, ValueError):
            out[k] = int(d[k])
    out["ai_state_confirm"] = min(10, max(1, out["ai_state_confirm"]))
    out["ai_threads"] = min(16, max(0, out["ai_threads"]))
    try:
        out["ai_snap_max_mb"] = max(20, int(out["ai_snap_max_mb"]))
    except (TypeError, ValueError):
        out[k] = int(d["ai_snap_max_mb"])
    for k in ("ai_enabled", "ai_fullscreen", "ai_change_detect", "ai_ocr_enabled", "ai_snapshots"):
        out[k] = bool(out[k])
    return out


def ai_models_dir(base_dir):
    """Каталог моделей: CFG["ai_model_dir"] или ai/models рядом с ботом."""
    return base_dir if base_dir else os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
