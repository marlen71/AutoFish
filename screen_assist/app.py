"""Assist — standalone Windows screen overlay. Run: python Assist.py --help"""
import argparse
import ctypes
import sys
import time
from pathlib import Path

from .core import smooth_step
from .tracking import Tracker
from .detector import Detector


def arguments():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', required=True, help='Local YOLO detection .pt weights')
    p.add_argument('--classes', default='0', help='Comma-separated player class IDs')
    p.add_argument('--monitor', type=int, default=1)
    p.add_argument('--confidence', type=float, default=.35)
    p.add_argument('--device', choices=['cpu', '0'], default='cpu')
    p.add_argument('--imgsz', type=int, choices=[416, 512, 640], default=512)
    p.add_argument('--aim-age', type=float, default=.2, help='Maximum target age in seconds')
    p.add_argument('--fov', type=int, default=100, help='Aim radius in screen pixels')
    p.add_argument('--smooth', type=float, default=10, help='Higher = slower')
    p.add_argument('--speed', type=float, default=900, help='Maximum pixels/second')
    p.add_argument('--head-ratio', type=float, default=.13)
    p.add_argument('--body-ratio', type=float, default=.42)
    p.add_argument('--origin', choices=['center', 'cursor'], default='center')
    a = p.parse_args()
    if not Path(a.model).is_file():
        p.error('--model must be an existing local weights file')
    if not (0 < a.confidence <= 1 and a.fov > 0 and a.smooth >= 1 and a.speed > 0 and .03 <= a.aim_age <= .3):
        p.error('Invalid confidence, fov, smooth or speed')
    if not (0 <= a.head_ratio <= 1 and 0 <= a.body_ratio <= 1):
        p.error('Point ratios must be between 0 and 1')
    try:
        a.classes = [int(x) for x in a.classes.split(',')]
    except ValueError:
        p.error('--classes must contain integer IDs')
    return a


def main():
    if sys.platform != 'win32':
        raise SystemExit('This overlay requires Windows 10 2004+ / Windows 11.')
    a = arguments()
    import tkinter as tk
    import mss
    from ctypes import wintypes

    user = ctypes.windll.user32
    # Physical coordinates must match MSS, including on high-DPI monitors.
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user.GetAsyncKeyState.restype = ctypes.c_short
    user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.DWORD, ctypes.c_size_t]
    capture = mss.mss()
    if not 1 <= a.monitor < len(capture.monitors):
        raise SystemExit('Invalid --monitor index')
    mon = dict(capture.monitors[a.monitor])
    capture.close()
    root = tk.Tk()
    root.title('Assist')
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.configure(bg='#010101')
    root.attributes('-transparentcolor', '#010101')
    root.geometry(f"{mon['width']}x{mon['height']}{mon['left']:+d}{mon['top']:+d}")
    canvas = tk.Canvas(root, bg='#010101', highlightthickness=0)
    canvas.pack(fill='both', expand=True)
    root.update()
    hwnd = user.GetAncestor(root.winfo_id(), 2)
    # Layered, click-through, non-activating tool window.
    user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    style = user.GetWindowLongW(hwnd, -20)
    user.SetWindowLongW(hwnd, -20, style | 0x80000 | 0x20 | 0x8000000 | 0x80)
    # Otherwise our own boxes would enter the next detector frame.
    if not user.SetWindowDisplayAffinity(hwnd, 0x11):
        root.destroy()
        capture.close()
        raise SystemExit('Cannot exclude overlay from capture; Windows 10 2004+ required.')
    detector = Detector(a, mon)
    tracker = Tracker(hold=.3)
    state = dict(enabled=False, mode='head', last=time.perf_counter(), keys={}, rx=0., ry=0.,
                 sequence=0, locked=None, latency=0.)

    def down(key):
        return bool(user.GetAsyncKeyState(key) & 0x8000)

    def pressed(key):
        current = down(key)
        old = state['keys'].get(key, False)
        state['keys'][key] = current
        return current and not old

    def tick():
        try:
            if down(0x79):  # F10, also checked after inference
                root.destroy()
                return
            if pressed(0x77):
                state['enabled'] = not state['enabled']
                detector.activate(state['enabled'])
                tracker.tracks.clear()
                state['locked'] = None
                state['rx'] = state['ry'] = 0.
            if pressed(0x75):
                state['mode'] = 'body' if state['mode'] == 'head' else 'head'
                state['locked'] = None
                state['rx'] = state['ry'] = 0.
            if pressed(0xBB):
                a.smooth = min(100, a.smooth + 1)
            if pressed(0xBD):
                a.smooth = max(1, a.smooth - 1)
            if pressed(0xDD):
                a.fov = min(1000, a.fov + 10)
            if pressed(0xDB):
                a.fov = max(10, a.fov - 10)
            canvas.delete('all')
            ox, oy = mon['width'] / 2, mon['height'] / 2
            if a.origin == 'cursor':
                pos = wintypes.POINT()
                user.GetCursorPos(ctypes.byref(pos))
                ox, oy = pos.x - mon['left'], pos.y - mon['top']
            now = time.perf_counter()
            if detector.error:
                raise RuntimeError(detector.error)
            snapshot = detector.read()
            if state['enabled'] and snapshot and snapshot[0] != state['sequence']:
                state['sequence'], captured, boxes, state['latency'] = snapshot
                tracker.update(boxes, captured)
            if state['enabled']:
                for track in tracker.visible(now):
                    b = track.box
                    canvas.create_rectangle(b.x1, b.y1, b.x2, b.y2, outline='#00ff88', width=2)
                    px, py = b.point(state['mode'], a.head_ratio, a.body_ratio)
                    canvas.create_oval(px-3, py-3, px+3, py+3, fill='#00ff88')
                canvas.create_oval(ox-a.fov, oy-a.fov, ox+a.fov, oy+a.fov, outline='#aaaaaa')
            dt = min(now - state['last'], .05)
            state['last'] = now
            if not down(0x02):
                state['locked'] = None
            track = tracker.choose((ox, oy), a.fov, state['mode'], now, state['locked'],
                                   max_age=a.aim_age, head=a.head_ratio, body=a.body_ratio) if state['enabled'] else None
            target = track.box.point(state['mode'], a.head_ratio, a.body_ratio) if track else None
            if down(0x79):
                root.destroy()
                return
            if target and down(0x02) and state['enabled']:
                if state['locked'] != track.id:
                    state['rx'] = state['ry'] = 0.
                state['locked'] = track.id
                dx, dy = smooth_step((ox, oy), target, a.smooth, dt, a.speed)
                dx += state['rx']
                dy += state['ry']
                ix, iy = round(dx), round(dy)
                state['rx'], state['ry'] = dx-ix, dy-iy
                user.mouse_event(0x0001, ix & 0xffffffff, iy & 0xffffffff, 0, 0)
                canvas.create_line(ox, oy, *target, fill='#ffcc00')
            else:
                state['rx'] = state['ry'] = 0.
                state['locked'] = None
            stale = bool(snapshot and now-snapshot[1] > a.aim_age)
            canvas.create_text(16, 16, anchor='nw', fill='white', text=(
                f"{'ON' if state['enabled'] else 'OFF'} | {state['mode']} | smooth {a.smooth:g} | FOV {a.fov}\n"
                f'F8 toggle | F6 head/body | +/- smooth | [ ] FOV | F10 exit\n'
                f'Inference {state["latency"]*1000:.0f} ms | {detector.status}'
                + (' | STALE: try input 416' if stale else '')))
            root.after(16, tick)
        except Exception as exc:
            print(f'Stopped safely: {exc}', file=sys.stderr)
            from tkinter import messagebox
            messagebox.showerror('Assist — остановлен', str(exc), parent=root)
            root.destroy()

    try:
        root.after(16, tick)
        root.mainloop()
    finally:
        detector.stop.set()
        detector.enabled.set()


if __name__ == '__main__':
    main()
