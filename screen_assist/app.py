"""Assist screen-only overlay. python Assist.py --help"""
import argparse
import ctypes
import os
import sys
import time
from pathlib import Path
from .aim_control import AimController, safe_point
from .tracking import Tracker
from .detector import Detector
from .trigger import Trigger, candidate_under_crosshair, activation_allowed
from .settings import DEFAULTS, CHOICES, validate, save


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    for key, default in DEFAULTS.items():
        kwargs = dict(default=default)
        if isinstance(default, bool):
            kwargs['action'] = argparse.BooleanOptionalAction
        else:
            kwargs['type'] = type(default)
            if key in CHOICES:
                kwargs['choices'] = CHOICES[key]
        parser.add_argument('--'+key.replace('_','-'), **kwargs)
    args = parser.parse_args()
    try:
        values = validate(vars(args))
        if not Path(values['model']).is_file():
            raise ValueError('Select an existing --model .pt file')
    except (ValueError, TypeError) as exc:
        parser.error(str(exc))
    return argparse.Namespace(**values)


def main():
    if sys.platform != 'win32':
        raise SystemExit('Windows 10 2004+ / Windows 11 required.')
    a = arguments()
    import tkinter as tk
    from tkinter import ttk, messagebox
    import mss
    from ctypes import wintypes
    from .menu import SettingsForm, theme, ENGINE
    user = ctypes.windll.user32
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user.GetAsyncKeyState.restype = ctypes.c_short
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    with mss.mss() as capture:
        if not 1 <= a.monitor < len(capture.monitors):
            raise ValueError('Invalid monitor')
        mon = dict(capture.monitors[a.monitor])
    root = tk.Tk()
    root.title('Assist overlay')
    root.overrideredirect(True)
    root.attributes('-topmost',True)
    root.configure(bg='#010101')
    root.attributes('-transparentcolor','#010101')
    root.geometry(f"{mon['width']}x{mon['height']}{mon['left']:+d}{mon['top']:+d}")
    canvas = tk.Canvas(root,bg='#010101',highlightthickness=0)
    canvas.pack(fill='both',expand=True)
    root.update()
    hwnd = user.GetAncestor(root.winfo_id(),2)
    user.SetWindowLongW(hwnd,-20,user.GetWindowLongW(hwnd,-20)|0x80000|0x20|0x8000000|0x80)
    if not user.SetWindowDisplayAffinity(hwnd,0x11):
        root.destroy()
        raise RuntimeError('Cannot exclude overlay from capture.')
    detector = Detector(a,mon)
    tracker = Tracker(hold=max(.3,a.esp_age),tau=a.box_smooth_ms/1000,acquire=a.confidence)
    trigger = Trigger()
    aim_controller = AimController()
    state = dict(enabled=False,keys={},sequence=0,
                 locked=None,latency=0.,game_hwnd=None,menu=False,stats_at=0.)

    def down(key):
        return bool(user.GetAsyncKeyState(key)&0x8000)

    def pressed(key):
        current = down(key)
        previous = state['keys'].get(key,False)
        state['keys'][key] = current
        return current and not previous

    def release_trigger():
        if trigger.cancel() == 'up':
            user.mouse_event(0x0004,0,0,0,0)

    def reset_input():
        aim_controller.reset()
        release_trigger()
        state['locked'] = None

    panel = tk.Toplevel(root)
    panel.withdraw()
    panel.title('Assist — настройки (Insert)')
    panel.geometry(f"{min(1080,root.winfo_screenwidth()-40)}x{min(800,root.winfo_screenheight()-70)}")
    theme(panel)
    content = ttk.Frame(panel,padding=18)
    content.pack(fill='both',expand=True)
    ttk.Label(content,text='ASSIST  /  LIVE',font=('Segoe UI',22,'bold'),foreground='#d63a3a').pack(anchor='w')
    form = SettingsForm(content,vars(a),live=True)
    live_stats = tk.StringVar(value='Ожидание F8 в окне игры…')
    ttk.Label(form.tabs['diagnostics'],text='LIVE PIPELINE',font=('Segoe UI',15,'bold'),foreground='#d63a3a').pack(anchor='w',pady=12)
    ttk.Label(form.tabs['diagnostics'],textvariable=live_stats,wraplength=570).pack(anchor='w',pady=12)
    ttk.Label(form.tabs['diagnostics'],text='Для предпросмотра без ввода и экспорта ONNX: F10 → стартовое меню.\nЗахват и модель меняются после перезапуска.',wraplength=570).pack(anchor='w')
    ttk.Label(form.tabs['data'],text='Сбор, разметка и обучение доступны в стартовом меню.\n'
              'Для смены модели/устройства: F10 и повторный запуск BAT.').pack(anchor='w')

    def hide_menu():
        panel.withdraw()
        state['menu'] = False
        tracker.tracks.clear()
        detector.activate(state['enabled'])
        reset_input()

    def apply_menu():
        try:
            settings = form.get()
            for key,value in settings.items():
                if key not in ENGINE:
                    setattr(a,key,value)
            tracker.hold = max(.3,a.esp_age)
            tracker.tau = a.box_smooth_ms/1000
            save(vars(a))
            hide_menu()
        except Exception as exc:
            messagebox.showerror('Настройки',str(exc),parent=panel)

    def toggle_menu():
        reset_input()
        if state['menu']:
            hide_menu()
        else:
            for key,value in vars(a).items():
                if key in form.vars:
                    form.vars[key].set(value)
            state['menu'] = True
            detector.activate(False)
            tracker.tracks.clear()
            panel.deiconify()
            panel.lift()
            panel.update_idletasks()
            user.SetWindowDisplayAffinity(user.GetAncestor(panel.winfo_id(),2),0x11)

    buttons = ttk.Frame(content)
    buttons.pack(fill='x',pady=8)
    ttk.Button(buttons,text='Применить и сохранить',style='Accent.TButton',command=apply_menu).pack(side='right')
    ttk.Button(buttons,text='Закрыть без применения',command=hide_menu).pack(side='left')
    panel.protocol('WM_DELETE_WINDOW',hide_menu)

    def tick():
        try:
            if down(0x79):
                root.destroy()
                return
            if pressed(0x2D):
                toggle_menu()
            if pressed(0x77):
                reset_input()
                if state['enabled']:
                    state['enabled'] = False
                else:
                    foreground = user.GetForegroundWindow()
                    pid = wintypes.DWORD()
                    user.GetWindowThreadProcessId(foreground,ctypes.byref(pid))
                    if foreground and pid.value != os.getpid() and not state['menu']:
                        state['game_hwnd'] = foreground
                        state['enabled'] = True
                detector.activate(state['enabled'])
                tracker.tracks.clear()
            point_key, mode_key, trigger_key = pressed(0x75), pressed(0x76), pressed(0x78)
            if not state['menu']:
                if point_key:
                    a.aim_point = 'body' if a.aim_point == 'head' else 'head'
                    reset_input()
                if mode_key:
                    a.aim_activation = 'auto' if a.aim_activation == 'rmb' else 'rmb'
                    reset_input()
                if trigger_key:
                    a.trigger_enabled = not a.trigger_enabled
                    release_trigger()
                if pressed(0xBB):
                    a.smooth = min(100,a.smooth+1)
                if pressed(0xBD):
                    a.smooth = max(1,a.smooth-1)
                if pressed(0xDD):
                    a.fov = min(2000,a.fov+10)
                if pressed(0xDB):
                    a.fov = max(10,a.fov-10)
            canvas.delete('all')
            ox,oy = mon['width']/2+a.crosshair_x,mon['height']/2+a.crosshair_y
            if a.origin == 'cursor':
                pos = wintypes.POINT()
                user.GetCursorPos(ctypes.byref(pos))
                ox,oy = pos.x-mon['left'],pos.y-mon['top']
            if detector.error:
                raise RuntimeError(detector.error)
            snapshot = detector.read()
            if state['enabled'] and snapshot and snapshot[0] != state['sequence']:
                state['sequence'],captured,boxes,state['latency'] = snapshot
                tracker.update(boxes,captured)
            now = time.perf_counter()
            captured = snapshot[1] if snapshot else None
            prediction = a.prediction_ms/1000
            if state['enabled']:
                if a.esp_enabled:
                    for track,b,coasting in tracker.render(now,captured,a.esp_age,prediction):
                        color = '#75a68c' if coasting else '#00ee99'
                        x1,y1,x2,y2 = max(0,b.x1),max(0,b.y1),min(mon['width'],b.x2),min(mon['height'],b.y2)
                        if x2 <= x1 or y2 <= y1:
                            continue
                        canvas.create_rectangle(x1,y1,x2,y2,outline=color,width=2,dash=(4,3) if coasting else ())
                        point=safe_point(track.raw or track.box,a.aim_point,a.head_ratio,a.body_ratio) if not coasting else None
                        if point:
                            px,py=point
                            canvas.create_oval(px-2,py-2,px+2,py+2,fill='#f0b94b',outline='#f0b94b')
                if a.capture_region == 'center':
                    from .capture import region_for
                    x1,y1,x2,y2=region_for(mon,a.capture_region,a.crop_size)
                    canvas.create_rectangle(x1,y1,x2,y2,outline='#c6935d',dash=(6,4))
                if a.show_fov:
                    canvas.create_oval(ox-a.fov,oy-a.fov,ox+a.fov,oy+a.fov,outline='#8e8e96')
            canvas.create_line(ox-5,oy,ox+5,oy,fill='#f0b94b')
            canvas.create_line(ox,oy-5,ox,oy+5,fill='#f0b94b')
            focused = user.GetForegroundWindow() == state['game_hwnd']
            active = state['enabled'] and focused and not state['menu']
            activated = activation_allowed(state['enabled'],state['menu'],focused,a.aim_activation,down(0x02))
            activated = activated and 0<=ox<mon['width'] and 0<=oy<mon['height']
            if not activated:
                reset_input()
            track = tracker.choose((ox,oy),a.fov,a.aim_point,now,state['locked'],max_age=a.aim_age,
                                   head=a.head_ratio,body=a.body_ratio,prediction=0.,confirmed_at=captured) if activated and a.aim_enabled else None
            if track:
                state['locked'] = track.id
                confirmed_box=track.raw or track.box
                target = safe_point(confirmed_box,a.aim_point,a.head_ratio,a.body_ratio)
                ix,iy=aim_controller.step(state['sequence'],track.seen,track.id,confirmed_box,(ox,oy),target,now,
                                          smooth=a.smooth,speed=a.speed,gain=a.aim_gain,limit=a.aim_step_limit,
                                          deadzone=a.aim_deadzone,confirm_frames=a.aim_confirm_frames,max_age=a.aim_age)
                # Recheck focus immediately before injection.
                if (ix or iy) and user.GetForegroundWindow() == state['game_hwnd'] and not down(0x79):
                    user.mouse_event(1,ix&0xffffffff,iy&0xffffffff,0,0)
                if target:
                    canvas.create_rectangle(confirmed_box.x1,confirmed_box.y1,confirmed_box.x2,confirmed_box.y2,
                                            outline='#ffcc00',width=1)
                    canvas.create_line(ox,oy,*target,fill='#ffcc00')
                    canvas.create_oval(target[0]-3,target[1]-3,target[0]+3,target[1]+3,outline='#ffcc00')
            else:
                aim_controller.reset()
                state['locked'] = None
            candidate = candidate_under_crosshair(tracker.visible(now),(ox,oy),a.aim_point,now,captured,
                                                  a.trigger_radius,max_age=min(.12,a.aim_age),
                                                  head=a.head_ratio,body=a.body_ratio,min_conf=a.confidence) if activated else None
            click_allowed = activated and a.trigger_enabled and not down(0x79) and user.GetForegroundWindow() == state['game_hwnd']
            event = trigger.step(now,candidate.id if candidate else None,click_allowed,manual_left=down(1),
                                 delay=a.trigger_delay_ms/1000,interval=a.trigger_interval_ms/1000)
            if event:
                user.mouse_event(2 if event == 'down' else 4,0,0,0,0)
            age = (now-captured)*1000 if captured else 0.
            label = 'OFF — F8 в окне игры' if not state['enabled'] else ('ON' if active else 'PAUSE — меню/другое окно')
            metrics,_ = detector.diagnostics()
            stages = ' | '.join(f'{name} {metrics.get(key,0):.1f} ms' for name,key in [('Capture','capture_ms'),('Prep','pre_ms'),('Net','infer_ms'),('Post','post_ms')])
            if now-state['stats_at']>=.25:
                state['stats_at']=now
                live_stats.set(f'{detector.status}\n\n{stages}\n\nTotal {state["latency"]*1000:.1f} ms | age {age:.0f} ms\n{detector.warning}')
            text = (f'ASSIST | {label} | {a.aim_point} | {a.aim_activation} | Trigger {"ON" if a.trigger_enabled else "OFF"}\n'
                    f'Insert меню | F6 точка | F7 auto/ПКМ | F8 старт/стоп | F9 триггер | F10 выход\n'
                    f'Pipeline {state["latency"]*1000:.0f} ms | age {age:.0f} ms | {detector.status}\n{stages}')
            if detector.warning:
                text += '\n'+detector.warning[:200]
            if snapshot and age > a.aim_age*1000:
                text += '\nSTALE: наведение остановлено — уменьшите вход или используйте совместимый GPU'
            canvas.create_text(16,16,anchor='nw',fill='white',text=text)
            root.after(16,tick)
        except Exception as exc:
            reset_input()
            messagebox.showerror('Assist — остановлен',str(exc),parent=root)
            root.destroy()

    try:
        root.after(16,tick)
        root.mainloop()
    finally:
        release_trigger()
        detector.stop.set()
        detector.enabled.set()


if __name__ == '__main__':
    main()
