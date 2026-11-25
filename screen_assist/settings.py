"""Validated settings shared by the launcher and the live menu."""
import json
import math
from pathlib import Path

DEFAULTS = dict(model='', classes='0', monitor=1, confidence=.22, track_confidence=.12,
                device='auto', imgsz=512, cpu_threads=4, box_smooth_ms=0., aim_age=.2,
                esp_age=.35, prediction_ms=60., fov=130, smooth=10., speed=900.,
                head_ratio=.13, body_ratio=.42, origin='center', aim_enabled=True,
                aim_activation='rmb', aim_point='head', esp_enabled=True, show_fov=True,
                trigger_enabled=False, trigger_radius=6., trigger_delay_ms=100., trigger_interval_ms=220.,
                capture_backend='auto', capture_region='full', crop_size=960, dxgi_output=0,
                inference_backend='auto', onnx_provider='auto')
RANGES = dict(monitor=(1,32), confidence=(.05,1), track_confidence=(.01,1), cpu_threads=(1,8),
              box_smooth_ms=(0,150), aim_age=(.03,.3), esp_age=(.05,.6), prediction_ms=(0,100),
              fov=(10,2000), smooth=(1,100), speed=(10,10000), head_ratio=(0,1), body_ratio=(0,1),
              trigger_radius=(1,30), trigger_delay_ms=(30,1000), trigger_interval_ms=(100,2000),
              crop_size=(256,2048), dxgi_output=(0,8))
CHOICES = dict(device=['auto','cpu','0'], imgsz=[320,416,512,640,960,1280], origin=['center','cursor'],
               aim_activation=['rmb','auto'], aim_point=['head','body'],
               capture_backend=['auto','dxgi','mss'], capture_region=['full','center'],
               inference_backend=['auto','pytorch','onnx'], onnx_provider=['auto','directml','cuda','cpu'])
PATH = Path.cwd() / 'assist_settings.json'


def validate(values):
    result = dict(DEFAULTS)
    for key, default in DEFAULTS.items():
        value = values.get(key, default)
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise ValueError(f'{key}: expected boolean')
        elif isinstance(default, int):
            number = float(value)
            if not math.isfinite(number) or number != int(number):
                raise ValueError(f'{key}: expected integer')
            value = int(number)
        elif isinstance(default, float):
            value = float(value)
            if not math.isfinite(value):
                raise ValueError(f'{key}: expected finite number')
        else:
            value = str(value).strip()
        if key in RANGES and not RANGES[key][0] <= value <= RANGES[key][1]:
            raise ValueError(f'{key}: {RANGES[key][0]} .. {RANGES[key][1]}')
        if key in CHOICES and value not in CHOICES[key]:
            raise ValueError(f'{key}: {CHOICES[key]}')
        result[key] = value
    ids = [int(c) for c in result['classes'].split(',')]
    if not ids or any(c < 0 for c in ids):
        raise ValueError('classes: non-negative class IDs required')
    if result['track_confidence'] > result['confidence']:
        raise ValueError('Порог удержания должен быть не выше порога новой цели.')
    return result


def load(path=PATH):
    if not path.exists():
        return dict(DEFAULTS)
    return validate(json.loads(path.read_text(encoding='utf-8')))


def save(values, path=PATH):
    settings = validate(values)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def cli(values):
    result = []
    for key, value in validate(values).items():
        flag = key.replace('_', '-')
        if isinstance(value, bool):
            result.append('--' + ('' if value else 'no-') + flag)
        else:
            result.extend(['--'+flag, str(value)])
    return result
