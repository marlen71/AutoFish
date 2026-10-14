# -*- coding: utf-8 -*-
"""AI-зрение Eternal FishMod (v1.24): локальный анализ кадра, наблюдение.

Импорт пакета ЛЁГКИЙ: __init__ не тянет ни cv2, ни onnxruntime — тяжёлые
модули загружаются лениво внутри VisionPipeline/detector/ocr. Основное
приложение может импортировать ai.config даже без установленных зависимостей.

Правило безопасности: всё, что публикует этот пакет, — НАБЛЮДЕНИЯ. Ни один
компонент пакета не имеет права двигать мышь или посылать клавиши.
"""
from .config import AI_DEFAULTS, ai_cfg, ai_models_dir   # noqa: F401
from .event_bus import EventBus, VisionEvent             # noqa: F401
from .frame_router import Frame, FrameRouter             # noqa: F401

__all__ = ["AI_DEFAULTS", "ai_cfg", "ai_models_dir", "EventBus", "VisionEvent",
           "Frame", "FrameRouter"]
__version__ = "1.24.0"
