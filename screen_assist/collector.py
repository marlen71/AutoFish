"""Opt-in local screenshot collection; no inference, labels or uploads."""
import ctypes
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def collect(parent, monitor=1):
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    if sys.platform != 'win32':
        messagebox.showerror('Assist', 'Сбор кадров поддерживается на Windows.', parent=parent)
        return
    import mss
    from mss.tools import to_png

    capture = mss.mss()
    if not 1 <= monitor < len(capture.monitors):
        capture.close()
        messagebox.showerror('Assist', 'Неверный номер монитора.', parent=parent)
        return
    mon = capture.monitors[monitor]
    folder = Path.cwd() / 'Assist_captures' / dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    folder.mkdir(parents=True, exist_ok=False)
    metadata = dict(format_version=1, created_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                    monitor=mon, interval_seconds=2, limit=500, annotated=False,
                    note='Raw screenshots only; review privacy and annotate before training.', frames=[])
    state = dict(recording=False, last=0., hash=None, closed=False, keys={})
    win = tk.Toplevel(parent)
    win.title('Assist — сбор кадров')
    win.geometry('580x310')
    status = tk.StringVar(value='Пауза. F8 — запись/пауза, F10 — остановить и показать окно.')
    frame = ttk.Frame(win, padding=16)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Сбор данных для обучения', font=('Segoe UI', 16, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='Без модели и без автонаводки. 1 кадр / 2 сек., максимум 500.\n'
              'Захватывается ВЕСЬ выбранный монитор: чат, рабочий стол, окна.\n'
              'Ничего не отправляется автоматически. Проверяйте кадры перед отправкой.').pack(anchor='w', pady=10)
    ttk.Label(frame, textvariable=status, wraplength=540).pack(anchor='w', pady=8)
    ttk.Label(frame, text=str(folder), wraplength=540).pack(anchor='w')

    def manifest():
        (folder / 'session.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')

    def pause():
        state['recording'] = False
        manifest()
        win.deiconify()
        win.lift()
        status.set(f"Пауза. Сохранено кадров: {len(metadata['frames'])}. F8 — продолжить.")

    def toggle():
        if state['recording']:
            pause()
        elif len(metadata['frames']) >= metadata['limit']:
            status.set('Достигнут лимит 500 кадров. Сохраните ZIP или начните новую сессию.')
        else:
            state['recording'] = True
            state['last'] = time.monotonic()  # allow time to return to game
            win.iconify()

    def export():
        pause()
        if not metadata['frames']:
            messagebox.showinfo('Assist', 'Пока нет кадров. Нажмите F8 и вернитесь в игру.', parent=win)
            return
        destination = filedialog.asksaveasfilename(parent=win, defaultextension='.zip',
                         initialfile=f'Assist_data_{folder.name}.zip', filetypes=[('ZIP', '*.zip')])
        if not destination:
            return
        try:
            with ZipFile(destination, 'w', ZIP_DEFLATED) as archive:
                for path in sorted(folder.iterdir()):
                    if path.is_file():
                        archive.write(path, f'{folder.name}/{path.name}')
            messagebox.showinfo('Assist', 'ZIP сохранён. Проверьте изображения перед отправкой.\n'
                                'Это исходные кадры, не обученная модель.', parent=win)
        except Exception as exc:
            messagebox.showerror('Assist', str(exc), parent=win)

    def close():
        state['recording'] = False
        state['closed'] = True
        manifest()
        capture.close()
        win.destroy()

    ttk.Button(frame, text='Запись / пауза (F8)', command=toggle).pack(fill='x', pady=6)
    ttk.Button(frame, text='Пауза и сохранить ZIP…', command=export).pack(fill='x')
    win.protocol('WM_DELETE_WINDOW', close)
    user = ctypes.windll.user32

    def pressed(key):
        down = bool(user.GetAsyncKeyState(key) & 0x8000)
        before = state['keys'].get(key, False)
        state['keys'][key] = down
        return down and not before

    def tick():
        if state['closed']:
            return
        try:
            if pressed(0x77):
                toggle()
            if pressed(0x79):
                pause()
            now = time.monotonic()
            if state['recording'] and now - state['last'] >= 2:
                state['last'] = now
                shot = capture.grab(mon)
                rgb = shot.rgb
                digest = hashlib.sha256(rgb).hexdigest()
                if digest != state['hash']:
                    name = f"frame_{len(metadata['frames']):05d}.png"
                    to_png(rgb, shot.size, output=str(folder / name))
                    metadata['frames'].append(dict(file=name, captured_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                                                   width=shot.width, height=shot.height))
                    state['hash'] = digest
                    manifest()
                if len(metadata['frames']) >= metadata['limit']:
                    pause()
            win.after(100, tick)
        except Exception as exc:
            pause()
            messagebox.showerror('Assist — сбор остановлен', str(exc), parent=win)
            win.after(100, tick)

    manifest()
    win.after(100, tick)
    parent.wait_window(win)
