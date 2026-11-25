"""Dark/red Assist panels, independent of the fishing application."""
from .settings import DEFAULTS, CHOICES, validate

ENGINE = {'model','classes','monitor','confidence','track_confidence','device','imgsz','cpu_threads'}


def theme(root):
    from tkinter import ttk
    root.configure(bg='#202024')
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', background='#202024', foreground='#ececec', font=('Segoe UI', 10))
    style.configure('TFrame', background='#202024')
    style.configure('Card.TLabelframe', background='#202024', bordercolor='#424249')
    style.configure('Card.TLabelframe.Label', foreground='#d63a3a', font=('Segoe UI', 11, 'bold'))
    style.configure('TEntry', fieldbackground='#303036', foreground='white', insertcolor='white')
    style.configure('TCombobox', fieldbackground='#303036', foreground='white', arrowcolor='white')
    style.map('TCombobox', fieldbackground=[('readonly','#303036')], foreground=[('readonly','white')])
    style.configure('TButton', padding=(12,8), background='#38383f', foreground='white', borderwidth=0)
    style.map('TButton', background=[('active','#51515b')])
    style.configure('Accent.TButton', background='#b82a2a', font=('Segoe UI',10,'bold'))
    style.map('Accent.TButton', background=[('active','#d63a3a')])
    style.configure('TCheckbutton', background='#202024', foreground='#ececec')
    style.map('TCheckbutton', background=[('active','#202024')])
    style.configure('TNotebook', background='#202024', borderwidth=0)
    style.configure('TNotebook.Tab', background='#303036', padding=(12,9))
    style.map('TNotebook.Tab', background=[('selected','#b82a2a')], foreground=[('selected','white')])


class SettingsForm:
    def __init__(self, parent, values, live=False):
        import tkinter as tk
        from tkinter import ttk, filedialog
        self.vars = {k: (tk.BooleanVar(value=values.get(k,v)) if isinstance(v,bool)
                         else tk.StringVar(value=str(values.get(k,v)))) for k,v in DEFAULTS.items()}
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill='both', expand=True, pady=10)
        self.tabs = {}
        self.widgets = {}
        for key, name in [('aim','Наведение'),('esp','ESP'),('trigger','Триггер'),('engine','Детектор'),('data','Данные')]:
            tab = ttk.Frame(self.notebook, padding=16)
            self.notebook.add(tab, text=name)
            self.tabs[key] = tab

        def row(tab, key, label):
            panel = self.tabs[tab]
            line = ttk.Frame(panel)
            line.pack(fill='x', pady=5)
            ttk.Label(line, text=label).pack(side='left')
            var = self.vars[key]
            if isinstance(DEFAULTS[key],bool):
                widget = ttk.Checkbutton(line, variable=var)
            elif key in CHOICES:
                widget = ttk.Combobox(line, textvariable=var, values=CHOICES[key], state='readonly', width=17)
            else:
                widget = ttk.Entry(line, textvariable=var, width=20 if key != 'model' else 40)
            widget.pack(side='right')
            self.widgets[key] = widget
            if live and key in ENGINE:
                widget.configure(state='disabled')
            return line

        for key, label in [('aim_enabled','Помощь в наведении'),('aim_activation','Активация: rmb = ПКМ / auto = автоматически'),
                           ('aim_point','Точка: head = голова / body = туловище'),('fov','Радиус захвата, пиксели'),
                           ('smooth','Smooth (больше = медленнее)'),('speed','Ограничение скорости, пикс./с'),
                           ('aim_age','Макс. возраст цели, секунды'),('origin','Центр: center / положение курсора: cursor')]:
            row('aim',key,label)
        ttk.Label(self.tabs['aim'], text='F8 — общий старт/стоп • F6 — голова/туловище\n'
                  'F7 — auto/ПКМ • Insert — меню • F10 — аварийный выход\n'
                  'Автоввод действует только в окне, активном при нажатии F8.\n'
                  'Голова и туловище — приблизительные точки внутри бокса.', wraplength=650).pack(anchor='w',pady=16)
        for key,label in [('esp_enabled','Показывать боксы по всему экрану'),('show_fov','Показывать круг захвата'),
                          ('esp_age','Удержание бокса, секунды'),('prediction_ms','Компенсация движения, мс (0 = выкл.)'),
                          ('box_smooth_ms','Фильтр боксов, мс (0 = без задержки)')]:
            row('esp',key,label)
        ttk.Label(self.tabs['esp'], text='У ESP нет радиуса в метрах — виден весь монитор.\n'
                  'Мелкие цели: увеличьте размер входа во вкладке «Детектор».\n'
                  'Пунктирный бокс — краткий пропуск детекции, не новая находка.\n'
                  'Прогноз ограничен, но может ошибаться при резкой смене направления.',wraplength=650).pack(anchor='w',pady=16)
        for key,label in [('trigger_enabled','Автоматическое нажатие ЛКМ (по умолчанию выключено)'),
                          ('trigger_radius','Допуск от точки цели, пиксели'),('trigger_delay_ms','Непрерывное удержание на цели, мс'),
                          ('trigger_interval_ms','Минимум между кликами, мс')]:
            row('trigger',key,label)
        ttk.Label(self.tabs['trigger'], text='F9 — триггер вкл./выкл. Работает при общем F8 ON, в активном\n'
                  'окне игры, с условиями режима auto/ПКМ. Наведение можно выключить\n'
                  'отдельно. Только свежий подтверждённый бокс под прицелом;\n'
                  'при открытом меню, смене окна и потере цели клики прекращаются.\n'
                  'Различения команд нет. Используйте только там, где это разрешено.',wraplength=650).pack(anchor='w',pady=16)
        row('engine','model','Веса .pt')
        def browse():
            file = filedialog.askopenfilename(parent=parent, filetypes=[('YOLO weights','*.pt')])
            if file:
                self.vars['model'].set(file)
        if not live:
            ttk.Button(self.tabs['engine'],text='Выбрать модель…',command=browse).pack(anchor='e')
        for key,label in [('classes','Классы игроков (0; свой self исключён)'),('monitor','Монитор'),('device','Устройство: auto / cpu / 0 = GPU'),
                          ('imgsz','Размер входа (больше = лучше мелкие цели)'),('confidence','Порог НОВОЙ цели'),
                          ('track_confidence','Порог УДЕРЖАНИЯ знакомой цели'),('cpu_threads','Потоки CPU')]:
            row('engine',key,label)
        if not live:
            bar=ttk.Frame(self.tabs['engine']);bar.pack(fill='x',pady=8)
            def preset(size, conf, low):
                for key,value in [('imgsz',size),('confidence',conf),('track_confidence',low)]:
                    self.vars[key].set(str(value))
            for name,size,conf,low in [('Быстро',416,.25,.14),('Баланс',640,.22,.12),('Мелкие цели',960,.18,.10)]:
                ttk.Button(bar,text=name,command=lambda s=size,c=conf,l=low:preset(s,c,l)).pack(side='left',padx=3)
        ttk.Label(self.tabs['engine'], text=('Детектор меняется после остановки и повторного запуска.' if live else
                  'auto проверит доступный GPU; 0 требует совместимого CUDA PyTorch.\n'
                  'Большой вход на CPU может УВЕЛИЧИТЬ отставание. Начните с 512/640.\n'
                  'Низкий порог повышает число ложных боксов. Веса берите из доверенных источников.'),wraplength=650).pack(anchor='w',pady=10)

    def get(self):
        return validate({k:v.get() for k,v in self.vars.items()})
