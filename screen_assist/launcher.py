"""Assist desktop dashboard; independent from FishMod."""
import sys
import traceback
from pathlib import Path
from .settings import load, save, cli
from .menu import SettingsForm, theme


def launch():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    root = tk.Tk()
    root.title('Assist — управление')
    root.geometry(f"820x{min(790, root.winfo_screenheight()-70)}")
    root.minsize(760, 620)
    theme(root)
    outer = ttk.Frame(root, padding=20)
    outer.pack(fill='both', expand=True)
    ttk.Label(outer, text='ASSIST', font=('Segoe UI', 25, 'bold'), foreground='#d63a3a').pack(anchor='w')
    ttk.Label(outer, text='Экранный детектор • наведение • локальное обучение').pack(anchor='w')
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
            with log_path.open('w', encoding='utf-8') as log:
                process = subprocess.Popen(command, stdout=log, stderr=log)
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
