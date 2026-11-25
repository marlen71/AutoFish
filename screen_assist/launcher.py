"""Assist desktop dashboard; independent from FishMod."""
import sys
import traceback
from pathlib import Path
from .settings import load, save, cli
from . import __version__
from .menu import SettingsForm, theme


def launch():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    root = tk.Tk()
    root.title('Assist — AI Workspace')
    root.geometry(f"{min(1080,root.winfo_screenwidth()-40)}x{min(820, root.winfo_screenheight()-70)}")
    root.minsize(940, 620)
    theme(root)
    outer = ttk.Frame(root, padding=20)
    outer.pack(fill='both', expand=True)
    ttk.Label(outer, text=f'ASSIST  {__version__}', font=('Segoe UI', 25, 'bold'), foreground='#d63a3a').pack(anchor='w')
    ttk.Label(outer, text='AI WORKSPACE   /   Захват → модель → трекинг → контролируемый ввод').pack(anchor='w')
    try:
        settings = load()
    except Exception as exc:
        from .settings import DEFAULTS
        settings = dict(DEFAULTS)
        messagebox.showwarning('Настройки сброшены', str(exc), parent=root)
    bundled = Path(__file__).resolve().parent.parent / 'game_detector_final.pt'
    if not Path(settings['model']).is_file() and bundled.is_file():
        settings['model'] = str(bundled)
    form = SettingsForm(outer, settings)
    values = form.vars
    model = values['model']
    chosen = []
    overview = form.tabs['diagnostics']
    ttk.Label(overview,text='Новый конвейер. Сначала проверьте изображение.',font=('Segoe UI',13,'bold')).pack(anchor='w',pady=(0,12))
    ttk.Label(overview,text='01  Захват DXGI или резервный MSS\n\n02  PyTorch (.pt) или ONNX Runtime (.onnx)\n\n03  Трекинг с ограниченной компенсацией задержки\n\n04  Наведение и триггер только после явного F8',wraplength=570).pack(anchor='w',pady=12)
    ttk.Label(overview,text='Проверка ниже не двигает мышь и не нажимает кнопки.\n'
              'Full сохраняет весь экран. Center ограничивает и ESP.\n'
              'Логи и кадры остаются локально.',foreground='#aaaab8',wraplength=570).pack(anchor='w',pady=12)
    def diagnose():
        try:
            settings=form.get()
            if not Path(settings['model']).is_file():
                raise ValueError('Сначала выберите модель в разделе «Модель».')
            from .diagnostics import open_diagnostics
            root.withdraw()
            open_diagnostics(root,settings)
        except Exception as exc:
            messagebox.showerror('Диагностика',str(exc),parent=root)
        finally:
            root.deiconify()
    ttk.Button(overview,text='Проверить захват и модель — без ввода',style='Accent.TButton',command=diagnose).pack(fill='x',pady=12)
    export_status=tk.StringVar(value='Для DirectML сначала экспортируйте свои веса в ONNX.')
    exporting={}
    def export_model():
        import subprocess,os
        if exporting.get('process') and exporting['process'].poll() is None:
            return
        try:
            settings=form.get()
            source=Path(settings['model'])
            if not source.is_file() or source.suffix.lower()!='.pt':
                raise ValueError('Выберите доверенную .pt detection-модель.')
            output=filedialog.asksaveasfilename(parent=root,initialfile=source.stem+'.onnx',defaultextension='.onnx',filetypes=[('ONNX','*.onnx')])
            if not output:
                return
            log_path=Path.cwd()/'assist_export.log'
            command=[sys.executable]
            if not getattr(sys,'frozen',False):
                command.append(str(Path(__file__).resolve().parent.parent/'Assist.py'))
            command+=['--export-onnx',str(source),output,'--size',str(settings['imgsz'])]
            env=dict(os.environ,ASSIST_JOB_LOG=str(log_path))
            with log_path.open('w',encoding='utf-8') as log:
                process=subprocess.Popen(command,stdout=log,stderr=log,env=env)
            exporting['process']=process
            export_status.set('Экспорт выполняется отдельно. Лог: assist_export.log')
            def check():
                if process.poll() is None:
                    root.after(1000,check)
                elif process.returncode==0:
                    form.vars['model'].set(output)
                    form.vars['inference_backend'].set('auto')
                    export_status.set('ONNX готов и выбран. Теперь запустите проверку без ввода.')
                else:
                    export_status.set('Ошибка экспорта. Пришлите assist_export.log; .pt сохранён.')
            root.after(1000,check)
        except Exception as exc:
            messagebox.showerror('Экспорт ONNX',str(exc),parent=root)
    ttk.Button(overview,text='Экспорт выбранной .pt → ONNX',command=export_model).pack(fill='x',pady=5)
    ttk.Label(overview,textvariable=export_status,wraplength=570,foreground='#aaaab8').pack(anchor='w',pady=10)
    frame = form.tabs['data']
    propose = tk.BooleanVar(value=True)

    def start():
        try:
            settings = form.get()
            if not Path(settings['model']).is_file():
                raise ValueError('Выберите существующую модель во вкладке «Детектор».')
            save(settings)
            chosen.extend(cli(settings))
            root.destroy()
        except Exception as exc:
            messagebox.showerror('Assist', str(exc), parent=root)

    def collect_frames():
        try:
            monitor = int(values['monitor'].get())
            if monitor < 1:
                raise ValueError('Номер монитора должен быть больше 0.')
            from .collector import collect
            root.withdraw()
            collect(root, monitor, weights=model.get().strip() or 'yolo11n.pt',
                    classes=tuple(int(x) for x in values['classes'].get().split(',')),
                    propose=propose.get())
        except Exception as exc:
            messagebox.showerror('Assist — сбор кадров', str(exc), parent=root)
        finally:
            root.deiconify()

    ttk.Label(frame, text='ЛОКАЛЬНЫЙ ДАТАСЕТ', font=('Segoe UI',14,'bold')).pack(anchor='w',pady=8)
    ttk.Checkbutton(frame, text='Фоновая предразметка', variable=propose).pack(anchor='w')
    ttk.Button(frame, text='Собирать кадры и предложения', command=collect_frames).pack(fill='x',pady=8)
    ttk.Label(frame, text='Захватывается весь монитор, включая чат и личные окна.\nНичего не отправляется автоматически.').pack(anchor='w',pady=8)
    def review_frames():
        try:
            from .review import review
            review(root)
        except Exception as exc:
            messagebox.showerror('Разметка', str(exc), parent=root)

    training = {}
    training_status = tk.StringVar(value='Обучение: CPU по умолчанию. GTX 1080 Ti требует совместимой CUDA-сборки.')
    gpu = tk.BooleanVar(value=False)

    def train_frames():
        import subprocess
        import datetime
        if training.get('process') and training['process'].poll() is None:
            messagebox.showinfo('Обучение', 'Обучение уже запущено.', parent=root)
            return
        folder = filedialog.askdirectory(parent=root, title='Сессия с проверенным annotations.json')
        if not folder:
            return
        if not (Path(folder) / 'annotations.json').is_file():
            messagebox.showerror('Обучение', 'Сначала проверьте и разметьте кадры.', parent=root)
            return
        if not messagebox.askyesno('Обучение', 'Начать 20 эпох? Закройте игру. Нужен интернет для начальных весов.\n'
                                 'CPU может работать много часов. Модель не заменится автоматически.', parent=root):
            return
        logs = Path.cwd() / 'Assist_training'
        logs.mkdir(exist_ok=True)
        log_path = logs / ('train_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S') + '.log')
        command = [sys.executable]
        if not getattr(sys, 'frozen', False):
            command.append(str(Path(__file__).resolve().parent.parent / 'Assist.py'))
        command += ['--train', folder, '--device', '0' if gpu.get() else 'cpu']
        try:
            import os
            with log_path.open('w', encoding='utf-8') as log:
                process = subprocess.Popen(command, stdout=log, stderr=log,env=dict(os.environ,ASSIST_JOB_LOG=str(log_path)))
            training['process'] = process
        except Exception as exc:
            messagebox.showerror('Обучение', str(exc), parent=root)
            return
        training_status.set(f'Идёт обучение. Лог: {log_path.name}')

        def check():
            code = process.poll()
            if code is None:
                root.after(2000, check)
            else:
                training_status.set('Завершено.' if code == 0 else 'Ошибка — откройте лог обучения.')
                messagebox.showinfo('Обучение', ('Кандидат сохранён в Assist_training.' if code == 0 else 'Ошибка обучения.')
                                    + f'\nЛог: {log_path}', parent=root)
        root.after(2000, check)

    ttk.Button(frame, text='Проверить и разметить кадры', command=review_frames).pack(fill='x', pady=6)
    ttk.Checkbutton(frame, text='Обучать на GPU 0 (только с совместимым PyTorch/CUDA)', variable=gpu).pack(anchor='w')
    ttk.Button(frame, text='Дообучить отдельную модель по проверенным кадрам', command=train_frames).pack(fill='x', pady=6)
    ttk.Label(frame, textvariable=training_status, wraplength=590).pack(anchor='w')
    bar = ttk.Frame(outer)
    bar.pack(fill='x', pady=(10,0))
    ttk.Label(bar, text='После запуска: F8 в окне игры • Insert — настройки • F10 — выход', wraplength=500).pack(side='left')
    ttk.Button(bar, text='Запустить Assist', style='Accent.TButton', command=start).pack(side='right')
    root.mainloop()
    if not chosen:
        return
    sys.argv = [sys.argv[0], *chosen]
    try:
        from .app import main
        main()
    except (Exception, SystemExit) as exc:
        error_root = tk.Tk()
        error_root.withdraw()
        messagebox.showerror('Assist — ошибка запуска', str(exc) or traceback.format_exc(), parent=error_root)
        error_root.destroy()
