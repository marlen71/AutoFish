"""Nonblocking click state machine. Never sleeps or reads game memory."""
import math


def activation_allowed(enabled, menu_open, focused, mode, rmb):
    return bool(enabled and not menu_open and focused and (mode == 'auto' or (mode == 'rmb' and rmb)))


def candidate_under_crosshair(tracks, origin, mode, now, captured, radius, max_age=.12, head=.13, body=.42, min_conf=0.):
    from .aim_control import safe_point
    eligible=[]
    for track in tracks:
        box=track.raw or track.box
        point=safe_point(box,mode,head,body)
        if (track.seen == captured and 0<=now-track.seen<=max_age and box.confidence>=min_conf and point
                and box.x1<=origin[0]<=box.x2 and box.y1<=origin[1]<=box.y2
                and math.dist(point,origin)<=radius):
            eligible.append((math.dist(point,origin),track))
    return min(eligible,key=lambda item:item[0])[1] if eligible else None


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
