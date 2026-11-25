"""Read-only live preview. This module never imports mouse/trigger code."""
import json
import sys
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from .detector import Detector
from .menu import theme


def open_diagnostics(parent,settings):
    import tkinter as tk
    from tkinter import ttk,filedialog
    from PIL import Image,ImageTk
    if sys.platform!='win32':
        raise RuntimeError('Live capture diagnostics requires Windows')
    import mss
    with mss.mss() as capture:
        if not 1<=settings['monitor']<len(capture.monitors):
            raise ValueError('Invalid monitor')
        mon = dict(capture.monitors[settings['monitor']])
    win = tk.Toplevel(parent)
    win.title('Assist — диагностика без ввода')
    win.geometry('800x690')
    theme(win)
    outer = ttk.Frame(win,padding=20); outer.pack(fill='both',expand=True)
    ttk.Label(outer,text='PIPELINE INSPECTOR',font=('Segoe UI',18,'bold'),foreground='#d63a3a').pack(anchor='w')
    ttk.Label(outer,text='Только захват и боксы. Движение мыши и клики здесь отсутствуют.').pack(anchor='w',pady=8)
    preview = ttk.Label(outer,text='Прогрев модели…',anchor='center')
    preview.pack(fill='both',expand=True)
    status = tk.StringVar(value='Загрузка…')
    ttk.Label(outer,textvariable=status,wraplength=740).pack(anchor='w',pady=12)
    win.update_idletasks()
    try:
        import ctypes
        from ctypes import wintypes
        user=ctypes.windll.user32
        user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT]
        user.GetAncestor.restype=wintypes.HWND
        user.SetWindowDisplayAffinity.argtypes=[wintypes.HWND,wintypes.DWORD]
        excluded=bool(user.SetWindowDisplayAffinity(user.GetAncestor(win.winfo_id(),2),0x11))
    except Exception:
        excluded=False
    detector=Detector(SimpleNamespace(**settings),mon,preview=True)
    detector.activate(True)
    state=dict(closed=False,last_image=None)

    def report():
        metrics,_=detector.diagnostics()
        requested={key:settings[key] for key in ('capture_backend','capture_region','crop_size','monitor','dxgi_output',
                                                  'inference_backend','onnx_provider','device','imgsz')}
        return dict(schema='assist-pipeline-v2',model=Path(settings['model']).name,requested=requested,
                    metrics=metrics,warning=detector.warning,error=detector.error,
                    note='Preview JPEG overhead included in total. No input injection.')

    def export():
        path=filedialog.asksaveasfilename(parent=win,initialfile='assist_diagnostics.json',defaultextension='.json',filetypes=[('JSON','*.json')])
        if path:
            try:
                Path(path).write_text(json.dumps(report(),ensure_ascii=False,indent=2),encoding='utf-8')
            except OSError as exc:
                status.set(str(exc))

    def close():
        state['closed']=True
        detector.stop.set(); detector.enabled.set()
        win.destroy()

    bar=ttk.Frame(outer);bar.pack(fill='x')
    ttk.Button(bar,text='Сохранить отчёт JSON…',command=export).pack(side='right')
    ttk.Button(bar,text='Закрыть проверку',command=close).pack(side='left')
    win.bind('<Escape>',lambda event:close())
    win.protocol('WM_DELETE_WINDOW',close)
    def tick():
        if state['closed']:
            return
        metrics,jpeg=detector.diagnostics()
        text=detector.error or detector.status
        if metrics:
            text+='\n'+' | '.join(f'{label}: {metrics.get(key,0):.1f} ms' for label,key in
                                  [('Захват','capture_ms'),('Подготовка','pre_ms'),('Сеть','infer_ms'),('NMS','post_ms'),('Всего','total_ms')])
            text+=f"\nЦелей: {metrics['detections']} | {metrics['frame_width']}×{metrics['frame_height']} | pipeline ~{metrics['frame_fps']:.1f} FPS"
            text+=f"\nОкно {metrics['samples']} кадров: P50 {metrics['p50_ms']:.1f} ms / P95 {metrics['p95_ms']:.1f} ms"
        if detector.warning:
            text+='\n'+detector.warning
        if not excluded:
            text+='\nОкно не исключено из захвата: переместите его на другой монитор.'
        status.set(text)
        if jpeg is not None and jpeg is not state['last_image']:
            preview.photo=ImageTk.PhotoImage(Image.open(BytesIO(jpeg)))
            preview.configure(image=preview.photo,text='')
            state['last_image']=jpeg
        win.after(250,tick)
    win.after(250,tick)
    parent.wait_window(win)
