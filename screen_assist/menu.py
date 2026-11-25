"""Dark/red Assist panels, independent of the fishing application."""
from .settings import DEFAULTS, CHOICES, validate

ENGINE = {'model','classes','monitor','confidence','track_confidence','device','imgsz','cpu_threads',
          'capture_backend','capture_region','crop_size','dxgi_output','inference_backend','onnx_provider'}


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
    style.configure('Nav.TButton', anchor='w', padding=(16,13), background='#202024')
    style.configure('NavActive.TButton', anchor='w', padding=(16,13), background='#b82a2a')
    style.map('NavActive.TButton', background=[('active','#d63a3a')])
    style.configure('TNotebook', background='#202024', borderwidth=0)
    style.configure('TNotebook.Tab', background='#303036', padding=(12,9))
    style.map('TNotebook.Tab', background=[('selected','#b82a2a')], foreground=[('selected','white')])


class SettingsForm:
    def __init__(self, parent, values, live=False):
        import tkinter as tk
        from tkinter import ttk, filedialog
        self.vars = {k: (tk.BooleanVar(value=values.get(k,v)) if isinstance(v,bool)
                         else tk.StringVar(value=str(values.get(k,v)))) for k,v in DEFAULTS.items()}
        shell = ttk.Frame(parent)
        shell.pack(fill='both',expand=True,pady=12)
        sidebar = ttk.Frame(shell,width=175)
        sidebar.pack(side='left',fill='y',padx=(0,18))
        ttk.Label(sidebar,text='WORKSPACE',foreground='#888896',font=('Segoe UI',9,'bold')).pack(anchor='w',pady=(8,16))
        deck = ttk.Frame(shell)
        deck.pack(side='right',fill='both',expand=True)
        deck.rowconfigure(0,weight=1); deck.columnconfigure(0,weight=1)
        self.tabs,self.widgets,self.pages,self.nav,self.canvases = {},{},{},{},{}
        self.current = 'diagnostics'
        def show(key):
            self.current=key
            self.pages[key].tkraise()
            for name,button in self.nav.items():
                button.configure(style='NavActive.TButton' if name==key else 'Nav.TButton')
        for key,name in [('diagnostics','01  Обзор'),('capture','02  Захват'),('engine','03  Модель'),
                         ('aim','04  Наведение'),('esp','05  ESP'),('trigger','06  Триггер'),('data','07  Данные')]:
            outer = ttk.Frame(deck)
            outer.grid(row=0,column=0,sticky='nsew')
            self.pages[key]=outer
            canvas = tk.Canvas(outer,bg='#202024',highlightthickness=0)
            self.canvases[key]=canvas
            scroll = ttk.Scrollbar(outer,orient='vertical',command=canvas.yview)
            canvas.configure(yscrollcommand=scroll.set)
            scroll.pack(side='right',fill='y'); canvas.pack(side='left',fill='both',expand=True)
            tab = ttk.Frame(canvas,padding=(6,8,16,18))
            window = canvas.create_window((0,0),window=tab,anchor='nw')
            tab.bind('<Configure>',lambda event,c=canvas:c.configure(scrollregion=c.bbox('all')))
            canvas.bind('<Configure>',lambda event,c=canvas,w=window:c.itemconfigure(w,width=event.width))
            ttk.Label(tab,text=name[4:].upper(),font=('Segoe UI',17,'bold')).pack(anchor='w',pady=(0,20))
            self.tabs[key]=tab
            button=ttk.Button(sidebar,text=name,style='Nav.TButton',command=lambda k=key:show(k))
            button.pack(fill='x',pady=3); self.nav[key]=button
        ttk.Label(sidebar,text='ASSIST  /  REBUILD\nЭкранный AI backend\nБез игровых модулей',foreground='#888896',wraplength=160).pack(side='bottom',anchor='w',pady=20)
        self.show = show
        def wheel(event):
            units = -int(event.delta/120) if getattr(event,'delta',0) else (-1 if event.num==4 else 1)
            self.canvases[self.current].yview_scroll(units,'units')
        parent.winfo_toplevel().bind('<MouseWheel>',wheel,add='+')
        show('diagnostics')

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
                widget = ttk.Entry(line, textvariable=var, width=18 if key != 'model' else 30)
            widget.pack(side='right')
            self.widgets[key] = widget
            if live and key in ENGINE:
                widget.configure(state='disabled')
            return line

        for key,label in [('capture_backend','Захват: auto / dxgi / mss'),('monitor','Монитор MSS (с 1)'),
                          ('dxgi_output','Выход DXGI (с 0, вручную для нескольких экранов)'),
                          ('capture_region','Область: full / center'),('crop_size','Сторона центрального crop, пиксели')]:
            row('capture',key,label)
        ttk.Label(self.tabs['capture'],text='Full — ESP по всему выбранному экрану. Center — только квадрат\n'
                  'вокруг центра; это ограничивает ESP, а не просто радиус наведения.\n'
                  'Auto пробует DXGI на одном мониторе, иначе использует MSS.\n'
                  'При нескольких мониторах DXGI output выбирается отдельно.\n'
                  'Ошибка DXGI переключает захват на MSS и показывается в диагностике.',
                  wraplength=560).pack(anchor='w',pady=16)
        for key, label in [('aim_enabled','Помощь в наведении'),('aim_activation','Активация: rmb = ПКМ / auto = автоматически'),
                           ('aim_point','Точка: head = голова / body = туловище'),('fov','Радиус захвата, пиксели'),
                           ('smooth','Smooth (больше = медленнее)'),('speed','Ограничение скорости, пикс./с'),
                           ('aim_age','Макс. возраст цели, секунды'),('origin','Центр: center / положение курсора: cursor')]:
            row('aim',key,label)
        ttk.Label(self.tabs['aim'], text='F8 — общий старт/стоп • F6 — голова/туловище\n'
                  'F7 — auto/ПКМ • Insert — меню • F10 — аварийный выход\n'
                  'Автоввод действует только в окне, активном при нажатии F8.\n'
                  'Голова и туловище — приблизительные точки внутри бокса.', wraplength=560).pack(anchor='w',pady=16)
        for key,label in [('esp_enabled','Показывать боксы по всему экрану'),('show_fov','Показывать круг захвата'),
                          ('esp_age','Удержание бокса, секунды'),('prediction_ms','Компенсация движения, мс (0 = выкл.)'),
                          ('box_smooth_ms','Фильтр боксов, мс (0 = без задержки)')]:
            row('esp',key,label)
        ttk.Label(self.tabs['esp'], text='У ESP нет радиуса в метрах. Область задаётся в «Захват».\n'
                  'Мелкие цели: увеличьте размер входа во вкладке «Детектор».\n'
                  'Пунктирный бокс — краткий пропуск детекции, не новая находка.\n'
                  'Прогноз ограничен, но может ошибаться при резкой смене направления.',wraplength=560).pack(anchor='w',pady=16)
        for key,label in [('trigger_enabled','Автоматическое нажатие ЛКМ (по умолчанию выключено)'),
                          ('trigger_radius','Допуск от точки цели, пиксели'),('trigger_delay_ms','Непрерывное удержание на цели, мс'),
                          ('trigger_interval_ms','Минимум между кликами, мс')]:
            row('trigger',key,label)
        ttk.Label(self.tabs['trigger'], text='F9 — триггер вкл./выкл. Работает при общем F8 ON, в активном\n'
                  'окне игры, с условиями режима auto/ПКМ. Наведение можно выключить\n'
                  'отдельно. Только свежий подтверждённый бокс под прицелом;\n'
                  'при открытом меню, смене окна и потере цели клики прекращаются.\n'
                  'Различения команд нет. Используйте только там, где это разрешено.',wraplength=560).pack(anchor='w',pady=16)
        row('engine','model','Модель .pt / .onnx')
        def browse():
            file = filedialog.askopenfilename(parent=parent, filetypes=[('Detection model','*.pt *.onnx'),('PyTorch','*.pt'),('ONNX','*.onnx')])
            if file:
                self.vars['model'].set(file)
        if not live:
            ttk.Button(self.tabs['engine'],text='Выбрать модель…',command=browse).pack(anchor='e')
        for key,label in [('inference_backend','Backend: auto / pytorch / onnx'),('onnx_provider','ONNX: auto / directml / cuda / cpu'),('classes','Классы игроков (0; свой self исключён)'),('device','PyTorch: auto / cpu / 0 = GPU'),
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
                  'Низкий порог повышает число ложных боксов. Веса берите из доверенных источников.'),wraplength=560).pack(anchor='w',pady=10)

    def get(self):
        return validate({k:v.get() for k,v in self.vars.items()})
