"""Pure geometry for screen-space detection and aim assistance."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Box:
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float = 1.0

    def point(self, mode: str, head_ratio: float = .13, body_ratio: float = .42):
        ratio = head_ratio if mode == 'head' else body_ratio
        return ((self.x1 + self.x2) / 2, self.y1 + (self.y2 - self.y1) * ratio)


def select_target(boxes, origin, radius, mode, head_ratio=.13, body_ratio=.42):
    """Nearest aim point inside a circular FOV; no off-screen/world data."""
    candidates = [b.point(mode, head_ratio, body_ratio) for b in boxes]
    candidates = [p for p in candidates if math.dist(p, origin) <= radius]
    return min(candidates, key=lambda p: math.dist(p, origin), default=None)


def smooth_step(origin, target, smooth, dt, max_speed):
    """Frame-rate independent exponential approach, capped in pixels/second."""
    alpha = 1 - math.exp(-max(0, dt) * 60 / max(1, smooth))
    dx, dy = ((target[i] - origin[i]) * alpha for i in (0, 1))
    length = math.hypot(dx, dy)
    cap = max_speed * max(0, dt)
    if length > cap and length:
        dx, dy = dx * cap / length, dy * cap / length
    return dx, dy
