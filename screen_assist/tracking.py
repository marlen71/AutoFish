"""Short-lived screen-space tracks, not world visibility or persistent identities."""
from dataclasses import dataclass
import math
from .core import Box


def iou(a, b):
    area = max(0, min(a.x2, b.x2)-max(a.x1, b.x1)) * max(0, min(a.y2, b.y2)-max(a.y1, b.y1))
    union = (a.x2-a.x1)*(a.y2-a.y1)+(b.x2-b.x1)*(b.y2-b.y1)-area
    return area/union if union > 0 else 0.


@dataclass
class Track:
    id: int
    box: Box
    seen: float


class Tracker:
    def __init__(self, hold=.18, tau=0.0):
        self.hold, self.tau = hold, tau
        self.tracks = {}
        self.next_id = 1

    def update(self, boxes, captured):
        self.tracks = {k: t for k, t in self.tracks.items() if captured-t.seen <= self.hold}
        pairs = sorted(((iou(t.box, b), k, i) for k, t in self.tracks.items()
                        for i, b in enumerate(boxes)), reverse=True)
        used_tracks, used_boxes = set(), set()
        for score, k, i in pairs:
            if score < .2 or k in used_tracks or i in used_boxes:
                continue
            t, b = self.tracks[k], boxes[i]
            alpha = 1.0 if self.tau <= 0 else 1-math.exp(-max(.001, captured-t.seen)/self.tau)
            coords = [getattr(t.box, v)+(getattr(b, v)-getattr(t.box, v))*alpha
                      for v in ('x1','y1','x2','y2')]
            t.box = Box(*coords, b.confidence)
            t.seen = captured
            used_tracks.add(k)
            used_boxes.add(i)
        for i, b in enumerate(boxes):
            if i not in used_boxes:
                self.tracks[self.next_id] = Track(self.next_id, b, captured)
                self.next_id += 1

    def visible(self, now):
        self.tracks = {k: t for k, t in self.tracks.items() if now-t.seen <= self.hold}
        return list(self.tracks.values())

    def display(self, now, captured, max_age=.2):
        """Only boxes confirmed by the latest result; no unmatched ghost trails."""
        return [t for t in self.visible(now) if t.seen == captured and now-t.seen <= max_age]

    def choose(self, origin, radius, mode, now, locked=None, max_age=.12, head=.13, body=.42):
        eligible = [t for t in self.visible(now) if now-t.seen <= max_age
                    and math.dist(t.box.point(mode, head, body), origin) <= radius]
        for t in eligible:
            if t.id == locked:
                return t
        return min(eligible, key=lambda t: math.dist(t.box.point(mode, head, body), origin), default=None)
