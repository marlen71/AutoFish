"""Nonblocking click state machine. Never sleeps or reads game memory."""
import math


def activation_allowed(enabled, menu_open, focused, mode, rmb):
    return bool(enabled and not menu_open and focused and (mode == 'auto' or (mode == 'rmb' and rmb)))


def candidate_under_crosshair(tracks, origin, mode, now, captured, radius, max_age=.12, head=.13, body=.42, min_conf=0.):
    eligible = [t for t in tracks if t.seen == captured and now-t.seen <= max_age and t.box.confidence >= min_conf
                and t.box.x1 <= origin[0] <= t.box.x2 and t.box.y1 <= origin[1] <= t.box.y2
                and math.dist(t.box.point(mode, head, body), origin) <= radius]
    return min(eligible, key=lambda t: math.dist(t.box.point(mode, head, body), origin), default=None)


class Trigger:
    def __init__(self):
        self.candidate = None
        self.since = 0.
        self.next_click = 0.
        self.pressed = False
        self.release_at = 0.

    def step(self, now, candidate, allowed, manual_left=False, delay=.1, interval=.22):
        if self.pressed:
            if not allowed or candidate != self.candidate or now >= self.release_at:
                self.pressed = False
                if not allowed or candidate != self.candidate:
                    self.candidate = None
                return 'up'
            return None
        if not allowed or candidate is None or manual_left:
            self.candidate = None
            return None
        if candidate != self.candidate:
            self.candidate, self.since = candidate, now
        if now-self.since >= delay and now >= self.next_click:
            self.pressed = True
            self.release_at = now+.025
            self.next_click = now+interval
            return 'down'
        return None

    def cancel(self):
        was_pressed = self.pressed
        self.pressed = False
        self.candidate = None
        return 'up' if was_pressed else None
