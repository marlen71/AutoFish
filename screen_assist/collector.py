"""Opt-in screen collection with optional background unverified suggestions."""
import ctypes
import datetime as dt
import hashlib
from collections import deque
from io import BytesIO
import json
import sys
import time
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def collect(parent, monitor=1, weights='yolo11n.pt', classes=(0,), propose=True):
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    if sys.platform != 'win32':
        messagebox.showerror('Assist', 'Сбор кадров поддерживается на Windows.', parent=parent)
        return
    import mss
    from PIL import Image
    from .proposals import ProposalWorker, similar

    capture = mss.mss()
    if not 1 <= monitor < len(capture.monitors):
        capture.close()
        messagebox.showerror('Assist', 'Неверный номер монитора.', parent=parent)
        return
    mon = capture.monitors[monitor]
    folder = Path.cwd() / 'Assist_captures' / dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    folder.mkdir(parents=True, exist_ok=False)
    metadata = dict(format_version=2, created_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                    monitor=mon, background_interval_seconds=2, buffer_interval_seconds=.25, limit=500, annotated=False,
                    note='Raw screenshots only; review privacy and annotate before training.', frames=[])
    worker = ProposalWorker(folder, weights, classes) if propose else None
    recent = deque(maxlen=20)
    state = dict(recording=False, last=0., hash=None, closed=False, keys={}, post_until=0., last_save=0.)
    buffer = deque(maxlen=3)
    win = tk.Toplevel(parent)
    win.title('Assist — сбор кадров')
    win.geometry('660x440')
    status = tk.StringVar(value='Пауза. F8 — запись/пауза, F10 — остановить и показать окно.')
    frame = ttk.Frame(win, padding=16)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Сбор данных для обучения', font=('Segoe UI', 16, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='НейроАссист: кадры до/после ЛКМ + фон раз в 2 сек. Лимит 500.\n'
              'Захватывается ВЕСЬ выбранный монитор: чат, рабочий стол, окна.\n'
              'Ничего не отправляется автоматически. Проверяйте кадры перед отправкой.').pack(anchor='w', pady=10)
    ttk.Label(frame, textvariable=status, wraplength=540).pack(anchor='w', pady=8)
    ttk.Label(frame, text=str(folder), wraplength=540).pack(anchor='w')

    inference_status = tk.StringVar()
    ttk.Label(frame, textvariable=inference_status, wraplength=620).pack(anchor='w', pady=6)

    def manifest():
        temporary = folder / 'session.tmp'
        temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(folder / 'session.json')

    def pause():
        state['recording'] = False
        buffer.clear()
        state['post_until'] = 0.
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
            state['last'] = time.monotonic() + 2  # allow time to return to game
            state['keys'][0x01] = bool(user.GetAsyncKeyState(0x01) & 0x8000)
            win.iconify()

    def export():
        pause()
        if worker and worker.pending:
            messagebox.showinfo('Предразметка', 'Дождитесь завершения очереди предразметки и повторите экспорт.', parent=win)
            return
        if not metadata['frames']:
            messagebox.showinfo('Assist', 'Пока нет кадров. Нажмите F8 и вернитесь в игру.', parent=win)
            return
        destination = filedialog.asksaveasfilename(parent=win, defaultextension='.zip',
                         initialfile=f'Assist_data_{folder.name}.zip', filetypes=[('ZIP', '*.zip')])
        if not destination:
            return
        try:
            with ZipFile(destination, 'w', ZIP_DEFLATED) as archive:
                for path in sorted(folder.rglob('*')):
                    if path.is_file() and path.suffix != '.tmp':
                        archive.write(path, f'{folder.name}/{path.relative_to(folder).as_posix()}')
            messagebox.showinfo('Assist', 'ZIP сохранён. Проверьте изображения перед отправкой.\n'
                                'Это исходные кадры, не обученная модель.', parent=win)
        except Exception as exc:
            messagebox.showerror('Assist', str(exc), parent=win)

    def close():
        state['recording'] = False
        state['closed'] = True
        if worker:
            worker.stop.set()
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

    def save_sample(sample, reason):
        if len(metadata['frames']) >= metadata['limit']:
            return
        raw, info = sample
        with Image.open(BytesIO(raw)) as image:
            signature = image.convert('L').resize((32, 18)).tobytes()
        if any(similar(signature, previous) for previous in recent):
            return
        digest = hashlib.sha256(raw).hexdigest()
        if digest == state['hash']:
            return
        name = f"frame_{len(metadata['frames']):05d}.jpg"
        (folder / name).write_bytes(raw)
        metadata['frames'].append(dict(file=name, reason=reason, **info))
        state['hash'] = digest
        recent.append(signature)
        manifest()
        if worker:
            worker.submit(folder / name)

    def tick():
        if state['closed']:
            return
        try:
            if worker:
                inference_status.set(f'{worker.message} | Готово: {worker.done}, очередь: {worker.pending}, без предложений: {worker.skipped}')
            else:
                inference_status.set('Предразметка выключена. Кадры для ручной разметки.')
            if pressed(0x77):
                toggle()
            if pressed(0x79):
                pause()
            now = time.monotonic()
            click = pressed(0x01)
            if state['recording'] and now >= state['last']:
                if click:
                    for sample in buffer:
                        save_sample(sample, 'before_left_click')
                    state['post_until'] = now + .75
                if now - state['last'] >= .25:
                    state['last'] = now
                    shot = capture.grab(mon)
                    stream = BytesIO()
                    Image.frombytes('RGB', shot.size, shot.rgb).save(stream, format='JPEG', quality=85)
                    from ctypes import wintypes
                    pos = wintypes.POINT()
                    user.GetCursorPos(ctypes.byref(pos))
                    sample = (stream.getvalue(), dict(
                        captured_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                        width=shot.width, height=shot.height,
                        cursor=[pos.x-mon['left'], pos.y-mon['top']],
                        assumed_crosshair=[shot.width/2, shot.height/2],
                        left_down=bool(user.GetAsyncKeyState(1) & 0x8000),
                        right_down=bool(user.GetAsyncKeyState(2) & 0x8000)))
                    buffer.append(sample)
                    if now <= state['post_until'] or now - state['last_save'] >= 2:
                        save_sample(sample, 'click_window' if now <= state['post_until'] else 'background')
                        state['last_save'] = now
                if len(metadata['frames']) >= metadata['limit']:
                    pause()
            win.after(25, tick)
        except Exception as exc:
            state['recording'] = False
            buffer.clear()
            win.deiconify()
            messagebox.showerror('Assist — сбор остановлен', str(exc), parent=win)
            win.after(100, tick)

    manifest()
    win.after(100, tick)
    parent.wait_window(win)
