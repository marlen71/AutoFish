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
    vx: float = 0.
    vy: float = 0.
    raw: Box | None = None

    def projected(self, now, horizon=.06):
        age = min(max(0., now-self.seen), horizon)
        b = self.box
        dx = max(-(b.x2-b.x1)*.5, min((b.x2-b.x1)*.5, self.vx*age))
        dy = max(-(b.y2-b.y1)*.25, min((b.y2-b.y1)*.25, self.vy*age))
        return Box(b.x1+dx,b.y1+dy,b.x2+dx,b.y2+dy,b.confidence)


class Tracker:
    def __init__(self, hold=.18, tau=0.0, acquire=0.0):
        self.hold, self.tau, self.acquire = hold, tau, acquire
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
            interval = captured-t.seen
            raw = t.raw or t.box
            if .005 <= interval <= .5:
                vx = ((b.x1+b.x2)-(raw.x1+raw.x2))/2/interval
                vy = ((b.y1+b.y2)-(raw.y1+raw.y2))/2/interval
                t.vx = .5*t.vx+.5*max(-3000,min(3000,vx))
                t.vy = .5*t.vy+.5*max(-3000,min(3000,vy))
            else:
                t.vx = t.vy = 0.
            t.raw = b
            alpha = 1.0 if self.tau <= 0 else 1-math.exp(-max(.001, captured-t.seen)/self.tau)
            coords = [getattr(t.box, v)+(getattr(b, v)-getattr(t.box, v))*alpha
                      for v in ('x1','y1','x2','y2')]
            t.box = Box(*coords, b.confidence)
            t.seen = captured
            used_tracks.add(k)
            used_boxes.add(i)
        for i, b in enumerate(boxes):
            if i not in used_boxes and b.confidence >= self.acquire:
                self.tracks[self.next_id] = Track(self.next_id, b, captured)
                self.next_id += 1

    def visible(self, now):
        self.tracks = {k: t for k, t in self.tracks.items() if now-t.seen <= self.hold}
        return list(self.tracks.values())

    def display(self, now, captured, max_age=.2):
        """Only boxes confirmed by the latest result; no unmatched ghost trails."""
        return [t for t in self.visible(now) if t.seen == captured and now-t.seen <= max_age]

    def render(self, now, captured, max_age=.35, prediction=.06):
        return [(t, t.projected(now, prediction), t.seen != captured)
                for t in self.visible(now) if now-t.seen <= max_age]

    def choose(self, origin, radius, mode, now, locked=None, max_age=.12, head=.13, body=.42, prediction=0., confirmed_at=None):
        def point(t):
            b=(t.raw or t.box) if confirmed_at is not None else t.projected(now,prediction)
            return b.point(mode,head,body)
        eligible = [t for t in self.visible(now) if now-t.seen <= max_age
                    and (confirmed_at is None or t.seen == confirmed_at)
                    and math.dist(point(t),origin) <= radius]
        for t in eligible:
            if t.id == locked:
                return t
        return min(eligible, key=lambda t: math.dist(point(t),origin), default=None)
