"""Desktop launcher for Assist; also used by the packaged executable."""
import sys
import traceback
from pathlib import Path


def launch():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title('Assist')
    root.geometry('560x440')
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

    ttk.Button(frame, text='Запустить Assist', command=start).pack(fill='x', pady=12)
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
