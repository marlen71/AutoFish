"""Desktop launcher for Assist; also used by the packaged executable."""
import sys
import traceback
from pathlib import Path


def launch():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title('НейроАссист / Assist')
    root.geometry('640x720')
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Assist', font=('Segoe UI', 22, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='Экранные боксы и помощь в наведении').pack(anchor='w', pady=(0, 16))
    model = tk.StringVar()
    ttk.Label(frame, text='Модель YOLO (.pt), обученная на персонажах игры:').pack(anchor='w')
    row = ttk.Frame(frame)
    row.pack(fill='x', pady=6)
    ttk.Entry(row, textvariable=model).pack(side='left', fill='x', expand=True)

    def browse():
        filename = filedialog.askopenfilename(parent=root, title='Выберите модель', filetypes=[('YOLO weights', '*.pt')])
        if filename:
            model.set(filename)

    ttk.Button(row, text='Обзор…', command=browse).pack(side='right', padx=(8, 0))
    values = {}
    for label, name, default in [('Классы персонажей (через запятую)', 'classes', '0'),
                                 ('Монитор', 'monitor', '1'),
                                 ('Радиус FOV', 'fov', '100'),
                                 ('Плавность (больше = медленнее)', 'smooth', '10')]:
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=3)
        ttk.Label(row, text=label).pack(side='left')
        values[name] = tk.StringVar(value=default)
        ttk.Entry(row, textvariable=values[name], width=15).pack(side='right')
    ttk.Label(frame, text='F8 — включить • F6 — голова/туловище • ПКМ — доводка\nF10 — выход • +/− — плавность • [ / ] — радиус').pack(anchor='w', pady=12)
    ttk.Label(frame, text='Модель не включена. Используйте только доверенные .pt файлы.').pack(anchor='w')
    chosen = []

    def start():
        if not Path(model.get()).is_file() or Path(model.get()).suffix.lower() != '.pt':
            messagebox.showerror('Assist', 'Выберите существующий файл модели .pt', parent=root)
            return
        try:
            if int(values['monitor'].get()) < 1 or int(values['fov'].get()) < 1 or float(values['smooth'].get()) < 1:
                raise ValueError()
            for item in values['classes'].get().split(','):
                int(item)
        except ValueError:
            messagebox.showerror('Assist', 'Проверьте числовые настройки.', parent=root)
            return
        chosen.extend(['--model', model.get()])
        for name, value in values.items():
            chosen.extend(['--' + name, value.get()])
        root.destroy()

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

    ttk.Button(frame, text='Запустить Assist', command=start).pack(fill='x', pady=12)
    ttk.Separator(frame).pack(fill='x', pady=4)
    propose = tk.BooleanVar(value=True)
    ttk.Checkbutton(frame, text='Фоновая предразметка (без своей модели скачает YOLO11n)', variable=propose).pack(anchor='w')
    ttk.Button(frame, text='Сбор кадров и предложений боксов', command=collect_frames).pack(fill='x', pady=6)
    ttk.Label(frame, text='Собирает изображения локально. Не обучает модель автоматически.').pack(anchor='w')

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
