using System;
using System.Diagnostics;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace RMFish
{
    public sealed class MainForm : Form
    {
        private readonly string baseDirectory, stopFile, settingsPath, noticePath, gearPath;
        private readonly object calibrationGate = new object();
        private readonly List<GearPoint> gearSamples = new List<GearPoint>();
        // 0: idle, 1: capture notice with F9, 2: record gear with F9,
        // 3: finish/save the captured sample on the UI or worker thread.
        private int calibrationMode;
        private bool autoRelocate, rodRight = true, captureRodRight;
        private readonly FishingEngine engine;
        private readonly Func<bool> accessAllowed;
        private readonly SafetyKeyMonitor safetyKeys;
        private readonly BackgroundProbe probeWorker;
        private readonly Stopwatch hotkeyClock = Stopwatch.StartNew();
        private readonly CooldownGate probeGate = new CooldownGate(300);
        private readonly CooldownGate stopLogGate = new CooldownGate(300);
        private volatile bool safetyFailed, closing;
        private readonly Panel[] pages = new Panel[4];
        private readonly SoftButton[] navigation = new SoftButton[4];
        private readonly System.Windows.Forms.Timer refreshTimer = new System.Windows.Forms.Timer();
        private readonly System.Windows.Forms.Timer probeTimer = new System.Windows.Forms.Timer();
        private Label statusTitle, statusDetail, castValue, reelValue, timeValue, detectionLabel, probeLabel, hotkeyLabel;
        private Label powerCaption, speedValue, settingsFeedback;
        private PowerButton powerButton;
        private SoftButton stopButton, sideStopButton, copyLogButton;
        private StageStrip stages;
        private SpeedSlider speedSlider;
        private Image brandImage;
        private DarkNumberInput pollInput, clickInput, timeoutInput, sessionInput;
        private CheckBox minimizeInput;
        private DarkLogBox logBox;
        private bool hotF8, hotF9, hotF10;
        private string lastLogText = "";
        private const int HotF8 = 101, HotF9 = 102, HotF10 = 103;

        public MainForm(string directory) : this(directory, null, null) { }

        // The second path lets GUI tests isolate settings from a real profile.
        internal MainForm(string directory, string settingsRoot) : this(directory, settingsRoot, null) { }

        // The loader can supply an independent, fail-closed subscription gate.
        // A standalone RMFish build passes no gate and retains its prior behavior.
        internal MainForm(string directory, string settingsRoot, Func<bool> authorization)
        {
            accessAllowed = authorization;
            baseDirectory = directory;
            stopFile = Path.Combine(directory, "STOP.txt");
            string local = settingsRoot;
            if (String.IsNullOrEmpty(local)) local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (String.IsNullOrEmpty(local)) local = directory;
            settingsPath = Path.Combine(local, "RMFish", "settings.ini");
            noticePath = Path.Combine(local, "RMFish", "fish-notice.dat");
            gearPath = Path.Combine(local, "RMFish", "fish-gear.dat");
            engine = new FishingEngine(new WindowsGamePort(stopFile));
            safetyKeys = new SafetyKeyMonitor(
                delegate(int key) { return (WindowsNative.GetAsyncKeyState(key) & 0x8000) != 0; },
                HandleEmergency, RequestProbe, HandleSafetyFault);
            probeWorker = new BackgroundProbe(ProbeScreen,
                delegate(Exception ex) { ReportProbe("Ошибка снимка: " + ex.Message, "Диагностика: "); });

            Text = "RMFish — авторыбалка для RMRP";
            StartPosition = FormStartPosition.CenterScreen;
            // A slim branded frame replaces the native Windows caption. Keep
            // the existing 980×630 content area below a 36px title bar.
            FormBorderStyle = FormBorderStyle.None;
            ClientSize = new Size(982, 668);
            MaximizeBox = false;
            MinimizeBox = true;
            ShowInTaskbar = true;
            DoubleBuffered = true;
            BackColor = Theme.Accent;
            ForeColor = Theme.Text;
            Font = new Font("Segoe UI", 9f);
            AutoScaleMode = AutoScaleMode.Font;
            string iconPath = Path.Combine(baseDirectory, "assets", "rmfish.ico");
            try
            {
                // The release EXE has its icon embedded; the source/BAT mode
                // keeps it in assets. Neither mode requires an external file.
                if (File.Exists(iconPath)) Icon = new Icon(iconPath);
                else Icon = System.Drawing.Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            }
            catch (Exception) { }

            BuildWindowChrome();
            BuildSidebar();
            BuildDashboard();
            BuildSettings();
            BuildGuide();
            BuildDiagnostics();
            ConnectSpeedControls();
            LoadSettings();
            ShowPage(0);

            refreshTimer.Interval = 150;
            refreshTimer.Tick += delegate { RefreshView(); };
            refreshTimer.Start();
            probeTimer.Interval = 3000;
            probeTimer.Tick += delegate { probeTimer.Stop(); RequestProbe(); };
            Shown += delegate
            {
                RegisterKeys();
                try { safetyKeys.Start(); }
                catch (Exception ex) { HandleSafetyFault(ex); }
                RefreshView();
            };
            FormClosing += delegate
            {
                closing = true;
                CancelCalibration();
                refreshTimer.Stop(); probeTimer.Stop(); engine.RequestStop();
                safetyKeys.Dispose(); UnregisterKeys();
            };
            FormClosed += delegate
            {
                refreshTimer.Dispose();
                probeTimer.Dispose();
                engine.Dispose();
                if (brandImage != null) { brandImage.Dispose(); brandImage = null; }
            };
        }

        internal static Label AddLabel(Control parent, string text, int x, int y, int width, int height,
                                       float size, Color color, FontStyle style)
        {
            Label label = new Label();
            label.Text = text;
            label.Location = new Point(x, y);
            label.Size = new Size(width, height);
            label.Font = new Font("Segoe UI", size, style);
            label.ForeColor = color;
            label.BackColor = Color.Transparent;
            label.AutoSize = false;
            label.TextAlign = ContentAlignment.MiddleLeft;
            parent.Controls.Add(label);
            return label;
        }

        private static SoftCard Card(Control parent, int x, int y, int width, int height)
        {
            SoftCard panel = new SoftCard();
            panel.SetBounds(x, y, width, height);
            parent.Controls.Add(panel);
            return panel;
        }

        private static SoftButton Button(Control parent, string text, int x, int y, int width, int height, bool primary)
        {
            SoftButton button = new SoftButton();
            button.Text = text;
            button.AccessibleName = text;
            button.SetBounds(x, y, width, height);
            if (primary)
            {
                button.Fill = Theme.Accent;
                button.Ink = Theme.AccentDark;
                button.Border = Theme.Accent;
            }
            parent.Controls.Add(button);
            return button;
        }

        private Panel CreatePage(int index)
        {
            Panel page = new Panel();
            page.Name = "page" + index;
            page.Location = new Point(191, 37);
            page.Size = new Size(790, 630);
            page.BackColor = Theme.Background;
            Controls.Add(page);
            pages[index] = page;
            return page;
        }

        private static Image LoadBrandImage(string directory)
        {
            try
            {
                // The published EXE embeds the image. Source mode reads the
                // same asset from the checkout; neither requires a network.
                using (Stream embedded = typeof(MainForm).Assembly.GetManifestResourceStream("RMFish.BrandLogo.png"))
                {
                    if (embedded != null)
                        using (Image image = Image.FromStream(embedded)) return new Bitmap(image);
                }
                string path = Path.Combine(directory, "assets", "rmfish-logo.png");
                if (File.Exists(path))
                    using (Image image = Image.FromFile(path)) return new Bitmap(image);
            }
            catch (Exception) { /* A missing/corrupt image must not disable the safety UI. */ }
            return null;
        }

        private void BuildWindowChrome()
        {
            WindowHeader header = new WindowHeader(Icon);
            header.Name = "windowHeader";
            header.SetBounds(1, 1, 980, 36);
            Controls.Add(header);
            WindowButton minimize = new WindowButton(WindowAction.Minimize);
            minimize.Name = "minimizeWindow";
            minimize.SetBounds(898, 1, 40, 33);
            minimize.Click += delegate { WindowState = FormWindowState.Minimized; };
            header.Controls.Add(minimize);
            WindowButton close = new WindowButton(WindowAction.Close);
            close.Name = "closeWindow";
            close.SetBounds(939, 1, 40, 33);
            close.Click += delegate { Close(); };
            header.Controls.Add(close);
        }

        private void BuildSidebar()
        {
            Panel sidebar = new Panel();
            sidebar.Name = "sidebar";
            sidebar.SetBounds(1, 37, 190, 630);
            sidebar.BackColor = Theme.Sidebar;
            sidebar.Paint += delegate(object sender, PaintEventArgs e)
            {
                using (Pen line = new Pen(Theme.Border)) e.Graphics.DrawLine(line, 189, 0, 189, sidebar.Height);
            };
            Controls.Add(sidebar);
            brandImage = LoadBrandImage(baseDirectory);
            if (brandImage != null)
            {
                PictureBox logo = new PictureBox();
                logo.Name = "brandLogo";
                logo.AccessibleName = "Логотип RMFish";
                logo.SetBounds(16, 13, 158, 74);
                logo.BackColor = Theme.Sidebar;
                logo.SizeMode = PictureBoxSizeMode.Zoom;
                logo.Image = brandImage;
                sidebar.Controls.Add(logo);
            }
            else AddLabel(sidebar, "RMFish", 23, 25, 145, 45, 20f, Theme.Accent, FontStyle.Bold);
            AddLabel(sidebar, "RMRP  /  АВТОРЫБАЛКА", 21, 90, 155, 18, 7.3f, Theme.Muted, FontStyle.Bold);
            AddLabel(sidebar, "МЕНЮ", 20, 126, 140, 19, 7.5f, Theme.Muted, FontStyle.Bold);
            string[] names = { "Рыбалка", "Настройки", "Инструкция", "Диагностика" };
            MenuIcon[] icons = { MenuIcon.Fish, MenuIcon.Settings, MenuIcon.Guide, MenuIcon.Journal };
            for (int i = 0; i < names.Length; i++)
            {
                int pageIndex = i;
                SoftButton nav = Button(sidebar, names[i], 15, 151 + i * 48, 160, 39, false);
                nav.Name = "navigation" + i;
                nav.AlignLeft = true;
                nav.IconKind = icons[i];
                nav.Fill = Theme.Raised;
                nav.Border = Theme.Raised;
                nav.Font = new Font("Segoe UI", 9f, FontStyle.Bold);
                nav.Click += delegate { ShowPage(pageIndex); };
                navigation[i] = nav;
            }
            // Always reachable even when settings, instructions or diagnostics
            // are open. Hotkey monitoring remains independent of this button.
            sideStopButton = Button(sidebar, "■  СТОП", 15, 352, 160, 36, false);
            sideStopButton.Name = "sideStopButton";
            sideStopButton.AccessibleName = "Остановить рыбалку";
            sideStopButton.Ink = Theme.Warn;
            sideStopButton.Enabled = false;
            sideStopButton.Click += delegate { engine.RequestStop(); RefreshView(); };
            SoftCard shortcut = Card(sidebar, 15, 402, 160, 145);
            shortcut.Fill = Color.FromArgb(10, 32, 33);
            AddLabel(shortcut, "БЫСТРЫЙ СТОП", 12, 10, 136, 19, 7.7f, Theme.Accent, FontStyle.Bold);
            AddLabel(shortcut, "F10  ·  аварийный", 12, 33, 139, 21, 8.3f, Theme.Text, FontStyle.Bold);
            AddLabel(shortcut, "Esc  ·  держать 2 сек", 12, 57, 139, 20, 8f, Theme.Muted, FontStyle.Regular);
            AddLabel(shortcut, "ЛКМ + ПКМ  ·  2 сек", 12, 80, 139, 20, 8f, Theme.Muted, FontStyle.Regular);
            AddLabel(shortcut, "Проверьте F10 в игре", 12, 111, 139, 21, 7.8f, Theme.Text, FontStyle.Regular);
            hotkeyLabel = AddLabel(sidebar, "F8  ·  старт / стоп\nF9  ·  проверка экрана\nВерсия 1.28 beta.1", 19, 560, 154, 55, 8f, Theme.Muted, FontStyle.Regular);
        }

        private void BuildDashboard()
        {
            Panel page = CreatePage(0);
            AddLabel(page, "АВТОРЫБАЛКА", 30, 17, 390, 30, 16.5f, Theme.Text, FontStyle.Bold);
            AddLabel(page, "RMRP  /  ПАНЕЛЬ УПРАВЛЕНИЯ", 31, 47, 440, 18, 7.8f, Theme.Muted, FontStyle.Bold);
            stopButton = Button(page, "■  СТОП   F10", 632, 23, 128, 38, false);
            stopButton.Name = "stopButton";
            stopButton.Enabled = false;
            stopButton.AccessibleName = "Остановить рыбалку";
            stopButton.Click += delegate { engine.RequestStop(); RefreshView(); };

            powerButton = new PowerButton();
            powerButton.Name = "powerButton";
            powerButton.SetBounds(347, 64, 96, 96);
            powerButton.AccessibleName = "Запустить рыбалку";
            powerButton.Click += delegate
            {
                if (engine.Snapshot().Running) engine.RequestStop();
                else StartFishing();
                RefreshView();
            };
            page.Controls.Add(powerButton);
            powerCaption = AddLabel(page, "ВКЛЮЧИТЬ", 277, 157, 236, 25, 11f, Theme.Text, FontStyle.Bold);
            powerCaption.TextAlign = ContentAlignment.MiddleCenter;
            statusTitle = AddLabel(page, "Готов к запуску", 145, 181, 500, 20, 9f, Theme.Accent, FontStyle.Bold);
            statusTitle.Name = "statusTitle";
            statusTitle.TextAlign = ContentAlignment.MiddleCenter;
            statusDetail = AddLabel(page, "Выберите удочку и наживку в игре.", 30, 203, 730, 29, 8.5f, Theme.Muted, FontStyle.Regular);
            statusDetail.Name = "statusDetail";
            statusDetail.TextAlign = ContentAlignment.MiddleCenter;

            stages = new StageStrip();
            stages.Name = "stages";
            stages.SetBounds(30, 235, 730, 75);
            page.Controls.Add(stages);

            SoftCard equipment = Card(page, 30, 318, 730, 83);
            equipment.Name = "equipmentInstructions";
            RodArt rod = new RodArt();
            rod.SetBounds(12, 7, 130, 69);
            equipment.Controls.Add(rod);
            equipment.Paint += delegate(object sender, PaintEventArgs e)
            {
                using (Pen line = new Pen(Theme.Border)) e.Graphics.DrawLine(line, 149, 14, 149, 68);
            };
            AddLabel(equipment, "ПОДГОТОВКА  ·  ВЫБЕРИТЕ ВРУЧНУЮ В ИГРЕ", 166, 8, 510, 20, 7.7f, Theme.Muted, FontStyle.Bold);
            AddLabel(equipment, "Снасть: бамбуковая удочка", 166, 28, 430, 22, 9.1f, Theme.Text, FontStyle.Bold);
            AddLabel(equipment, "Наживка: хлебный мякиш", 166, 50, 430, 22, 9.1f, Theme.Text, FontStyle.Regular);
            SoftButton guide = Button(equipment, "Как?  →", 625, 26, 84, 33, false);
            guide.Click += delegate { ShowPage(2); };

            Label castsLabel = AddLabel(page, "ЗАБРОСОВ", 38, 411, 230, 20, 8f, Theme.Muted, FontStyle.Bold);
            Label reelsLabel = AddLabel(page, "ВЫВАЖИВАНИЙ", 280, 411, 230, 20, 8f, Theme.Muted, FontStyle.Bold);
            Label timeLabel = AddLabel(page, "ВРЕМЯ СЕССИИ", 522, 411, 230, 20, 8f, Theme.Muted, FontStyle.Bold);
            castsLabel.TextAlign = reelsLabel.TextAlign = timeLabel.TextAlign = ContentAlignment.MiddleCenter;
            castValue = AddLabel(page, "0", 38, 431, 230, 35, 19f, Theme.Text, FontStyle.Bold);
            reelValue = AddLabel(page, "0", 280, 431, 230, 35, 19f, Theme.Text, FontStyle.Bold);
            timeValue = AddLabel(page, "00:00", 522, 431, 230, 35, 19f, Theme.Text, FontStyle.Bold);
            castValue.Name = "castValue"; reelValue.Name = "reelValue"; timeValue.Name = "timeValue";
            castValue.TextAlign = reelValue.TextAlign = timeValue.TextAlign = ContentAlignment.MiddleCenter;
            Label statsNote = AddLabel(page, "Счётчики показывают фазы, а не подтверждённый улов.", 30, 467, 730, 19, 7.8f, Theme.Muted, FontStyle.Regular);
            statsNote.TextAlign = ContentAlignment.MiddleCenter;
            page.Paint += delegate(object sender, PaintEventArgs e)
            {
                using (Pen line = new Pen(Theme.Border))
                {
                    e.Graphics.DrawLine(line, 274, 418, 274, 463);
                    e.Graphics.DrawLine(line, 516, 418, 516, 463);
                    e.Graphics.DrawLine(line, 30, 563, 760, 563);
                }
            };

            AddLabel(page, "Интервал ЛКМ", 30, 499, 190, 23, 9.2f, Theme.Text, FontStyle.Bold);
            speedSlider = new SpeedSlider();
            speedSlider.Name = "speedSlider";
            speedSlider.SetBounds(227, 494, 355, 32);
            page.Controls.Add(speedSlider);
            speedValue = AddLabel(page, "35 мс", 605, 499, 155, 23, 9.2f, Theme.Accent, FontStyle.Bold);
            speedValue.TextAlign = ContentAlignment.MiddleRight;
            AddLabel(page, "Вываживание: слева медленнее, справа быстрее. Применится при следующем запуске.", 30, 530, 730, 22, 8.2f, Theme.Muted, FontStyle.Regular);
            AddLabel(page, "F10 — аварийный стоп  ·  Esc или ЛКМ + ПКМ удерживать 2 секунды", 30, 571, 730, 19, 8.5f, Theme.Text, FontStyle.Bold);
            AddLabel(page, "Перед стартом проверьте F10 в игре и журнал в разделе «Диагностика».", 30, 593, 730, 19, 8.1f, Theme.Muted, FontStyle.Regular);
        }

        private static DarkNumberInput Number(Control parent, int x, int y, int min, int max, int step, string label)
        {
            DarkNumberInput number = new DarkNumberInput(min, max, step);
            number.SetBounds(x, y, 112, 30);
            number.SetAccessibleLabel(label);
            parent.Controls.Add(number);
            return number;
        }

        private void BuildSettings()
        {
            Panel page = CreatePage(1);
            AddLabel(page, "ПАРАМЕТРЫ", 30, 16, 350, 20, 8.5f, Theme.Accent, FontStyle.Bold);
            AddLabel(page, "Настройки", 28, 38, 600, 38, 20f, Theme.Text, FontStyle.Bold);
            AddLabel(page, "Меняйте скорость и ограничения под свою игру.", 30, 78, 700, 22, 9.2f, Theme.Muted, FontStyle.Regular);
            SoftCard settings = Card(page, 30, 109, 730, 340);
            AddLabel(settings, "Частота проверки экрана", 21, 12, 440, 25, 10f, Theme.Text, FontStyle.Bold);
            AddLabel(settings, "Интервал между снимками, мс (меньше — быстрее).", 21, 36, 520, 24, 8.7f, Theme.Muted, FontStyle.Regular);
            pollInput = Number(settings, 585, 20, 20, 200, 5, "Частота проверки экрана, миллисекунды");
            pollInput.Name = "pollInput";
            AddLabel(settings, "Интервал ЛКМ при вываживании", 21, 72, 470, 25, 10f, Theme.Text, FontStyle.Bold);
            AddLabel(settings, "Время между нажатиями, мс.", 21, 96, 510, 24, 8.7f, Theme.Muted, FontStyle.Regular);
            clickInput = Number(settings, 585, 80, 35, 250, 5, "Интервал ЛКМ при вываживании, миллисекунды");
            clickInput.Name = "clickInput";
            AddLabel(settings, "Максимальное ожидание шкалы", 21, 132, 470, 25, 10f, Theme.Text, FontStyle.Bold);
            AddLabel(settings, "В секундах; 0 — без отдельного лимита ожидания.", 21, 156, 520, 24, 8.7f, Theme.Muted, FontStyle.Regular);
            timeoutInput = Number(settings, 585, 140, 0, 3600, 30, "Максимальное ожидание шкалы, секунды");
            timeoutInput.Name = "timeoutInput";
            AddLabel(settings, "Лимит всей сессии, сек", 21, 192, 470, 25, 10f, Theme.Text, FontStyle.Bold);
            AddLabel(settings, "Автостоп даже на паузе; по умолчанию 120 секунд.", 21, 216, 520, 24, 8.7f, Theme.Muted, FontStyle.Regular);
            sessionInput = Number(settings, 585, 200, 1, 1800, 30, "Лимит всей сессии, секунды");
            sessionInput.Name = "sessionInput";
            minimizeInput = new DarkToggle();
            minimizeInput.Name = "minimizeInput";
            minimizeInput.Text = "Сворачивать RMFish при запуске";
            minimizeInput.SetBounds(21, 261, 490, 28);
            minimizeInput.Font = new Font("Segoe UI", 9.7f, FontStyle.Bold);
            minimizeInput.ForeColor = Theme.Text;
            settings.Controls.Add(minimizeInput);
            AddLabel(settings, "Вернитесь в игру после нажатия «Включить».", 69, 292, 520, 22, 8.7f, Theme.Muted, FontStyle.Regular);

            SoftButton save = Button(page, "Сохранить настройки", 30, 466, 220, 42, true);
            save.Name = "saveSettings";
            save.Click += delegate { SaveSettings(true); };
            settingsFeedback = AddLabel(page, "Изменения — при следующем запуске.", 266, 469, 260, 35, 8.5f, Theme.Muted, FontStyle.Regular);
            settingsFeedback.Name = "settingsFeedback";
            SoftButton relocate = Button(page, "Автоотход…", 551, 466, 209, 42, false);
            relocate.Name = "relocationSettings";
            relocate.Click += delegate { ShowRelocationSetup(); };
            SoftCard safety = Card(page, 30, 527, 730, 80);
            safety.Fill = Color.FromArgb(42, 39, 29);
            safety.Stroke = Color.FromArgb(98, 82, 54);
            AddLabel(safety, "БЕЗОПАСНОСТЬ", 18, 9, 210, 20, 8f, Theme.Warn, FontStyle.Bold);
            AddLabel(safety, "F10, Esc на 2 сек или обе кнопки мыши на 2 сек — аварийный стоп. Проверьте F10 в игре до старта.", 18, 31, 690, 39, 8.8f, Theme.Text, FontStyle.Regular);
        }

        private void BuildGuide()
        {
            Panel page = CreatePage(2);
            AddLabel(page, "ПЕРВЫЙ ЗАПУСК", 30, 16, 350, 20, 8.5f, Theme.Accent, FontStyle.Bold);
            AddLabel(page, "Как начать рыбалку", 28, 38, 650, 38, 20f, Theme.Text, FontStyle.Bold);
            AddLabel(page, "Перед работой проверьте остановку и подготовьте снасти вручную.", 30, 78, 710, 22, 9.2f, Theme.Muted, FontStyle.Regular);
            string[] titles = { "Проверьте F10 до запуска", "Подготовьте удочку и наживку", "Запустите RMFish и вернитесь в игру", "Остановите, когда понадобится" };
            string[] details = {
                "В игре нажмите F10 при остановленном боте. В «Диагностике» должно быть «F10 получен».",
                "В зоне рыбалки: I → бамбуковая удочка → «Ловить рыбу» → «Хлебный мякиш».",
                "Нажмите «Включить» или F8. Вернитесь в GTA5: программа ждёт видимую шкалу.",
                "F10 — стоп; запасной вариант: удерживайте Esc или обе кнопки мыши 2 секунды."
            };
            for (int i = 0; i < titles.Length; i++)
            {
                SoftCard step = Card(page, 30, 110 + i * 82, 730, 72);
                AddLabel(step, "0" + (i + 1), 18, 13, 47, 44, 14f, Theme.Accent, FontStyle.Bold);
                AddLabel(step, titles[i], 74, 8, 630, 24, 10f, Theme.Text, FontStyle.Bold);
                AddLabel(step, details[i], 74, 34, 630, 30, 8.6f, Theme.Muted, FontStyle.Regular);
            }
            SoftCard tip = Card(page, 30, 454, 730, 153);
            tip.Fill = Color.FromArgb(13, 42, 39);
            AddLabel(tip, "ВАЖНО", 19, 11, 230, 20, 8f, Theme.Accent, FontStyle.Bold);
            AddLabel(tip, "Используйте формат 16:9, лучше 1920×1080, и оконный режим без рамки. Окно игры должно быть полностью видно.", 19, 34, 690, 43, 8.8f, Theme.Text, FontStyle.Regular);
            AddLabel(tip, "Программа не проверяет предметы и улов. Счётчики показывают фазы, а не успешную поимку. Сначала остановите бота перед проверкой F9.", 19, 83, 690, 55, 8.8f, Theme.Muted, FontStyle.Regular);
        }

        private void BuildDiagnostics()
        {
            Panel page = CreatePage(3);
            AddLabel(page, "ПРОВЕРКА ЭКРАНА", 30, 16, 350, 20, 8.5f, Theme.Accent, FontStyle.Bold);
            AddLabel(page, "Диагностика", 28, 38, 600, 38, 20f, Theme.Text, FontStyle.Bold);
            AddLabel(page, "Перед F9 остановите рыбалку. Нажмите F10 в игре и проверьте журнал.", 30, 78, 710, 22, 9.1f, Theme.Muted, FontStyle.Regular);
            SoftCard probe = Card(page, 30, 109, 730, 144);
            AddLabel(probe, "ПОСЛЕДНЯЯ ПРОВЕРКА F9", 19, 11, 300, 20, 8f, Theme.Accent, FontStyle.Bold);
            probeLabel = AddLabel(probe, "Переключитесь в GTA5 и нажмите F9 или запустите проверку через 3 секунды.", 19, 35, 690, 45, 9.1f, Theme.Text, FontStyle.Regular);
            SoftButton check = Button(probe, "Проверить через 3 сек", 19, 91, 210, 37, false);
            check.Click += delegate
            {
                probeLabel.Text = "Переключитесь в GTA5: снимок будет сделан через 3 секунды…";
                probeTimer.Stop(); probeTimer.Start();
            };
            AddLabel(page, "ДАННЫЕ РАБОЧЕГО КАДРА", 30, 267, 400, 20, 8f, Theme.Muted, FontStyle.Bold);
            SoftCard detected = Card(page, 30, 292, 730, 59);
            detectionLabel = AddLabel(detected, "Кадр ещё не проверен.", 18, 7, 690, 44, 8.9f, Theme.Text, FontStyle.Regular);
            AddLabel(page, "ЖУРНАЛ СОБЫТИЙ", 30, 366, 400, 20, 8f, Theme.Muted, FontStyle.Bold);
            copyLogButton = Button(page, "Копировать", 632, 359, 128, 28, false);
            copyLogButton.Name = "copyLog";
            copyLogButton.Font = new Font("Segoe UI", 8.2f, FontStyle.Bold);
            copyLogButton.Click += delegate
            {
                try
                {
                    if (!String.IsNullOrEmpty(lastLogText)) Clipboard.SetText(lastLogText);
                    copyLogButton.Text = "Скопировано";
                }
                catch (Exception ex) { engine.Log("Не удалось скопировать журнал: " + ex.Message); }
            };
            SoftCard logPanel = Card(page, 30, 391, 730, 216);
            logBox = new DarkLogBox();
            logBox.Name = "eventLog";
            logBox.SetBounds(18, 15, 694, 185);
            logPanel.Controls.Add(logBox);
        }

        private void ShowPage(int index)
        {
            for (int i = 0; i < pages.Length; i++)
            {
                if (pages[i] != null) pages[i].Visible = i == index;
                if (navigation[i] != null)
                {
                    navigation[i].Selected = i == index;
                    navigation[i].Fill = i == index ? Theme.Accent : Theme.Raised;
                    navigation[i].Border = i == index ? Theme.Accent : Theme.Raised;
                    navigation[i].Ink = i == index ? Theme.AccentDark : Theme.Muted;
                    navigation[i].Invalidate();
                }
            }
        }

        private void ConnectSpeedControls()
        {
            speedSlider.ValueChanged += delegate
            {
                if (clickInput.Value != speedSlider.Value) clickInput.Value = speedSlider.Value;
                speedValue.Text = speedSlider.Value + " мс";
            };
            clickInput.ValueChanged += delegate
            {
                speedSlider.Value = (int)clickInput.Value;
                speedValue.Text = clickInput.Value + " мс";
            };
        }

        private EngineOptions GetOptions()
        {
            // F8 can start while an editable field still has focus.
            pollInput.CommitEdit(); clickInput.CommitEdit();
            timeoutInput.CommitEdit(); sessionInput.CommitEdit();
            return new EngineOptions
            {
                PollMilliseconds = (int)pollInput.Value,
                ReelClickMilliseconds = (int)clickInput.Value,
                WaitTimeoutSeconds = (int)timeoutInput.Value,
                SessionLimitSeconds = (int)sessionInput.Value,
                MinimizeOnStart = minimizeInput.Checked,
                AutoRelocate = autoRelocate
            };
        }

        private void LoadSettings()
        {
            EngineOptions options = new EngineOptions();
            try
            {
                if (File.Exists(settingsPath))
                {
                    foreach (string line in File.ReadAllLines(settingsPath, Encoding.UTF8))
                    {
                        string[] pair = line.Split(new char[] { '=' }, 2);
                        if (pair.Length != 2) continue;
                        int number;
                        bool flag;
                        if (pair[0] == "poll_ms" && Int32.TryParse(pair[1], out number)) options.PollMilliseconds = number;
                        if (pair[0] == "reel_click_ms" && Int32.TryParse(pair[1], out number)) options.ReelClickMilliseconds = number;
                        if (pair[0] == "wait_seconds" && Int32.TryParse(pair[1], out number)) options.WaitTimeoutSeconds = number;
                        if (pair[0] == "session_seconds" && Int32.TryParse(pair[1], out number)) options.SessionLimitSeconds = number;
                        if (pair[0] == "minimize" && Boolean.TryParse(pair[1], out flag)) options.MinimizeOnStart = flag;
                        if (pair[0] == "auto_relocate" && Boolean.TryParse(pair[1], out flag)) autoRelocate = flag;
                        if (pair[0] == "rod_right_button" && Boolean.TryParse(pair[1], out flag)) rodRight = flag;
                    }
                }
            }
            catch (Exception ex) { engine.Log("Не удалось прочитать настройки: " + ex.Message); }
            options = options.CopyValidated();
            pollInput.Value = options.PollMilliseconds;
            clickInput.Value = options.ReelClickMilliseconds;
            timeoutInput.Value = options.WaitTimeoutSeconds;
            sessionInput.Value = options.SessionLimitSeconds;
            minimizeInput.Checked = options.MinimizeOnStart;
        }

        private bool SaveSettings(bool inform)
        {
            try
            {
                EngineOptions options = GetOptions().CopyValidated();
                Directory.CreateDirectory(Path.GetDirectoryName(settingsPath));
                string text = "poll_ms=" + options.PollMilliseconds + "\r\nreel_click_ms=" + options.ReelClickMilliseconds +
                    "\r\nwait_seconds=" + options.WaitTimeoutSeconds + "\r\nsession_seconds=" + options.SessionLimitSeconds +
                    "\r\nminimize=" + options.MinimizeOnStart + "\r\nauto_relocate=" + autoRelocate +
                    "\r\nrod_right_button=" + rodRight + "\r\n";
                File.WriteAllText(settingsPath, text, Encoding.UTF8);
                if (inform)
                {
                    settingsFeedback.Text = "Сохранено. Изменения применятся при следующем запуске.";
                    settingsFeedback.ForeColor = Theme.Accent;
                }
                return true;
            }
            catch (Exception ex)
            {
                engine.Log("Не удалось сохранить настройки: " + ex.Message);
                if (inform)
                {
                    settingsFeedback.Text = "Не удалось сохранить настройки. Подробности — в диагностике.";
                    settingsFeedback.ForeColor = Theme.Warn;
                }
                return false;
            }
        }

        private void ShowRelocationSetup()
        {
            if (engine.Snapshot().Running)
            {
                MessageBox.Show(this, "Сначала остановите рыбалку и дождитесь завершения рабочего потока.", "Автоотход",
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            if (CancelCalibration())
            {
                engine.Log("Запись образцов отменена.");
                MessageBox.Show(this, "Запись образцов отменена. Откройте настройки ещё раз для новой записи.", "Автоотход");
                return;
            }
            using (RelocationSetupForm dialog = new RelocationSetupForm(autoRelocate, rodRight, File.Exists(noticePath), File.Exists(gearPath)))
            {
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                autoRelocate = dialog.AutoEnabled; rodRight = dialog.RodRightButton;
                SaveSettings(false);
                if (dialog.Command == "notice")
                {
                    if (MessageBox.Show(this,
                        "Остановите рыбалку. Переключитесь в GTA5 и дождитесь именно сообщения об окончании рыбы над миникартой. Пока сообщение видно, нажмите F9; затем в открывшемся окне выделите всю надпись. F10 отменяет запись.",
                        "Образец уведомления", MessageBoxButtons.OKCancel, MessageBoxIcon.Information) != DialogResult.OK) return;
                    lock (calibrationGate) calibrationMode = 1;
                    engine.Log("Ожидаем F9 на уведомлении об окончании рыбы. F10 отменяет запись.");
                }
                else if (dialog.Command == "gear")
                {
                    string button = rodRight ? "правой" : "левой";
                    if (MessageBox.Show(this,
                        "Запись выполняется вручную в игре, без автоматических кликов.\n\n1. Откройте инвентарь I/Ш, наведите курсор на удочку и нажмите F9. После сигнала нажмите на удочку " + button + " кнопкой.\n\n2. Наведите на «Ловить рыбу», нажмите F9 и после сигнала нажмите ЛКМ.\n\n3. Наведите на «Хлебный мякиш», нажмите F9 и после сигнала нажмите ЛКМ.\n\nНе меняйте размер окна. Подводите курсор к узнаваемому значку/тексту, не к пустому месту. F10 отменяет запись.",
                        "Запись инвентаря", MessageBoxButtons.OKCancel, MessageBoxIcon.Information) != DialogResult.OK) return;
                    lock (calibrationGate) { gearSamples.Clear(); captureRodRight = rodRight; calibrationMode = 2; }
                    engine.Log("Запись инвентаря: наведите на удочку и нажмите F9. F10 отменяет запись.");
                }
            }
        }

        private bool CancelCalibration()
        {
            lock (calibrationGate)
            {
                bool wasActive = calibrationMode != 0;
                calibrationMode = 0; gearSamples.Clear();
                return wasActive;
            }
        }

        private bool AccessAllowed()
        {
            try { return accessAllowed == null || accessAllowed(); }
            catch { return false; }
        }

        // A loader must keep the single-instance mutex until a blocked worker
        // has really exited, even if its window has already closed.
        internal bool FinishWorkerShutdown()
        {
            if (!engine.WaitForStop(0)) return false;
            engine.Dispose();
            return true;
        }

        // Safe to call from the loader's independent lease-monitor thread,
        // including while the UI is busy. This is a stop request; native calls
        // cannot be forcibly interrupted, exactly like the emergency hotkeys.
        internal void RevokeAuthorization(string reason)
        {
            engine.RequestStop(reason);
            engine.Log(reason);
            try
            {
                if (IsHandleCreated && !IsDisposed && !Disposing)
                    BeginInvoke((MethodInvoker)delegate { if (!IsDisposed) RefreshView(); });
            }
            catch (InvalidOperationException) { }
        }

        private void StartFishing()
        {
            if (closing || engine.Snapshot().Running) return;
            lock (calibrationGate)
            {
                if (calibrationMode != 0)
                {
                    engine.Log("Сначала завершите запись образцов или отмените её с F10.");
                    return;
                }
            }
            // Record intent before checking the lease: a concurrent revocation
            // increments StopVersion and must win over this start attempt.
            long stopVersion = engine.StopVersion;
            if (!AccessAllowed())
            {
                engine.Log("Доступ не подтверждён. Откройте продукт снова через RMacro.");
                RefreshView();
                return;
            }
            // A stop arriving during settings/file IO cancels this attempt.
            if (safetyFailed)
            {
                MessageBox.Show(this, "Аварийный монитор недоступен. Перезапустите RMFish и проверьте F10 до начала работы.",
                    "RMFish", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }
            if (safetyKeys.StopHeld || (WindowsNative.GetAsyncKeyState(SafetyKeyMonitor.F10) & 0x8000) != 0)
            {
                engine.Log("Отпустите аварийную клавишу или кнопки мыши перед запуском.");
                return;
            }
            try
            {
                // STOP.bat deliberately leaves a sentinel. A new explicit Start
                // clears it; a running worker never clears it on its own.
                if (File.Exists(stopFile)) File.Delete(stopFile);
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, "Не удалось удалить STOP.txt: " + ex.Message + "\nРаспакуйте программу в доступную для записи папку.", "RMFish", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }
            EngineOptions options = GetOptions();
            SaveSettings(false);
            try
            {
                if (options.AutoRelocate)
                {
                    if (!File.Exists(noticePath) || !File.Exists(gearPath))
                        throw new InvalidOperationException("Для автоотхода сначала запишите уведомление и элементы инвентаря в настройках.");
                    options.Notice = NoticeTemplate.Load(noticePath);
                    options.Gear = GearMacro.Load(gearPath);
                    if (options.Gear.Point(0).RightButton != rodRight)
                        throw new InvalidOperationException("Способ нажатия на удочку изменился. Запишите инвентарь заново.");
                }
                if (engine.Start(options, stopVersion))
                {
                    // A fault or held emergency key must win over Start.
                    if (!AccessAllowed())
                        engine.RequestStop("Запуск отменён: доступ к продукту больше не подтверждён.");
                    else if (safetyFailed || safetyKeys.StopHeld || engine.StopVersion != stopVersion ||
                        (WindowsNative.GetAsyncKeyState(SafetyKeyMonitor.F10) & 0x8000) != 0)
                        engine.RequestStop("Запуск отменён: аварийная остановка или ошибка контроля клавиш.");
                    else if (options.MinimizeOnStart) WindowState = FormWindowState.Minimized;
                }
                else engine.Log("Запуск отменён: рабочий поток ещё останавливается или получен сигнал стоп.");
                RefreshView();
            }
            catch (Exception ex)
            {
                engine.RequestStop("Ошибка запуска.");
                engine.Log("Ошибка запуска: " + ex.Message);
                RefreshView();
                MessageBox.Show(this, "Не удалось запустить рыбалку: " + ex.Message,
                    "RMFish", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private void RefreshView()
        {
            EngineSnapshot state = engine.Snapshot();
            statusTitle.Text = safetyFailed && !state.Running ? "Ошибка контроля клавиш" : state.Title;
            statusDetail.Text = safetyFailed && !state.Running ?
                "Запуск заблокирован. Перезапустите RMFish и проверьте F10 до начала работы." : state.Detail;
            statusTitle.ForeColor = safetyFailed || state.Stopping || state.Phase == FishingPhase.Paused ? Theme.Warn :
                state.Running ? Theme.Accent : Theme.Muted;
            bool authorized = AccessAllowed();
            if (!authorized && !state.Running)
            {
                statusTitle.Text = "Доступ не подтверждён";
                statusDetail.Text = "Откройте продукт снова через RMacro после проверки подписки.";
                statusTitle.ForeColor = Theme.Warn;
            }
            powerButton.Enabled = state.Running ? !state.Stopping : !safetyFailed && authorized;
            powerButton.Working = state.Running && !state.Stopping;
            powerCaption.Text = state.Stopping ? "ОСТАНОВКА…" : state.Running ? "ОСТАНОВИТЬ" :
                !authorized || safetyFailed ? "ЗАПУСК ЗАБЛОКИРОВАН" : "ВКЛЮЧИТЬ";
            powerButton.AccessibleName = state.Running ? "Остановить рыбалку" : "Запустить рыбалку";
            powerButton.AccessibleDescription = statusDetail.Text;
            stopButton.Enabled = state.Running && !state.Stopping;
            sideStopButton.Enabled = state.Running && !state.Stopping;
            stages.ActiveIndex = !state.Running || state.Stopping ? -1 :
                state.Phase == FishingPhase.Casting ? 0 : state.Phase == FishingPhase.WaitingBite ? 1 :
                state.Phase == FishingPhase.Reeling ? 2 : -1;
            castValue.Text = state.Casts.ToString();
            reelValue.Text = state.Reels.ToString();
            timeValue.Text = state.Elapsed.TotalHours >= 1 ?
                String.Format("{0:00}:{1:00}:{2:00}", (int)state.Elapsed.TotalHours, state.Elapsed.Minutes, state.Elapsed.Seconds) :
                String.Format("{0:00}:{1:00}", (int)state.Elapsed.TotalMinutes, state.Elapsed.Seconds);
            detectionLabel.Text = state.Detection;
            string text = String.Join("\r\n", engine.Events());
            if (text != lastLogText)
            {
                lastLogText = text;
                logBox.SetContent(text);
                copyLogButton.Text = "Копировать";
            }
        }

        private void HandleEmergency(EmergencySignal signal, bool first)
        {
            bool wasRunning = engine.Snapshot().Running;
            string reason = signal == EmergencySignal.F10 ? "Аварийная остановка: F10." :
                signal == EmergencySignal.EscapeHeld ? "Аварийная остановка: Esc удерживался 2 секунды." :
                "Аварийная остановка: обе кнопки мыши удерживались 2 секунды.";
            // This callback also runs on the independent polling thread: it
            // never waits for the WinForms UI to process a hotkey message.
            engine.RequestStop(reason);
            if (CancelCalibration() && first) engine.Log("Запись образцов отменена аварийной остановкой.");
            if (!first) return;
            if (signal == EmergencySignal.F10)
            {
                if (stopLogGate.TryClaim(hotkeyClock.ElapsedMilliseconds))
                    engine.Log(wasRunning ? reason : "F10 получен. Проверьте, что игра была в фокусе во время нажатия.");
            }
            else if (wasRunning) engine.Log(reason);
        }

        private void HandleSafetyFault(Exception ex)
        {
            safetyFailed = true;
            engine.RequestStop("Ошибка контроля аварийной остановки. Запуск заблокирован.");
            engine.Log("Ошибка контроля аварийных клавиш: " + ex.Message + ". Перезапустите RMFish.");
            try
            {
                if (IsHandleCreated && !IsDisposed && !Disposing)
                    BeginInvoke((MethodInvoker)delegate { if (!IsDisposed) RefreshView(); });
            }
            catch (InvalidOperationException) { }
        }

        private void RequestProbe()
        {
            if (closing) return;
            // Both WM_HOTKEY and the independent poller can see one keypress.
            if (!probeGate.TryClaim(hotkeyClock.ElapsedMilliseconds)) return;
            try
            {
                // Capture must never block the emergency-key or UI thread.
                if (!probeWorker.TryStart())
                    ReportProbe("Предыдущая проверка ещё выполняется. Если она зависла, перезапустите RMFish.", "Диагностика: ");
            }
            catch (Exception ex) { ReportProbe("Не удалось запустить проверку: " + ex.Message, "Диагностика: "); }
        }

        // BackgroundProbe owns this operation and its thread-affine capture.
        private void ProbeScreen()
        {
            using (WindowsGamePort port = new WindowsGamePort(null))
            {
                GameBounds bounds;
                string reason;
                if (!port.TryGetForeground(out bounds, out reason))
                {
                    ReportProbe(reason, "Диагностика: ");
                    return;
                }
                int mode;
                lock (calibrationGate) mode = calibrationMode;
                if (mode != 0 && engine.Snapshot().Running)
                {
                    CancelCalibration();
                    ReportProbe("Запись отменена: рыбалка уже работает.", "Автоотход: ");
                    return;
                }
                if (mode == 1) { CaptureNoticeSample(port, bounds); return; }
                if (mode == 2) { CaptureGearSample(port, bounds); return; }
                if (mode == 3) { ReportProbe("Дождитесь завершения текущей записи.", "Автоотход: "); return; }
                PixelFrame frame = port.Capture(bounds);
                if (!port.IsForeground(bounds))
                {
                    ReportProbe("Фокус игры изменился во время снимка. Проверьте ещё раз.", "Диагностика: ");
                    return;
                }
                string result = String.Format("{0}×{1}. {2}", bounds.Width, bounds.Height, Vision.Describe(frame));
                ReportProbe(result, "F9: ");
            }
        }

        private void CaptureNoticeSample(WindowsGamePort port, GameBounds bounds)
        {
            PixelFrame frame = port.CaptureArea(bounds, NoticeTemplate.RegionLeft, NoticeTemplate.RegionTop,
                NoticeTemplate.RegionRight, NoticeTemplate.RegionBottom);
            if (!port.IsForeground(bounds)) throw new InvalidOperationException("Фокус изменился. Дождитесь уведомления и нажмите F9 ещё раз.");
            lock (calibrationGate)
            {
                if (calibrationMode != 1) return;
                calibrationMode = 3;
            }
            try
            {
                BeginInvoke((MethodInvoker)delegate
                {
                    try
                    {
                        if (closing) return;
                        lock (calibrationGate) { if (calibrationMode != 3) return; }
                        using (NoticeSelectionForm dialog = new NoticeSelectionForm(frame))
                        {
                            if (dialog.ShowDialog(this) != DialogResult.OK || dialog.Result == null) return;
                            lock (calibrationGate) { if (calibrationMode != 3) return; }
                            dialog.Result.Save(noticePath);
                            engine.Log("Образец текста уведомления сохранён. Проверьте его с реальным сообщением перед использованием.");
                        }
                    }
                    catch (Exception ex) { engine.Log("Не удалось сохранить образец: " + ex.Message); }
                    finally { lock (calibrationGate) { if (calibrationMode == 3) calibrationMode = 0; } }
                });
            }
            catch
            {
                lock (calibrationGate) { if (calibrationMode == 3) calibrationMode = 0; }
                throw;
            }
        }

        private void CaptureGearSample(WindowsGamePort port, GameBounds bounds)
        {
            WindowsNative.Point cursor, after;
            if (!WindowsNative.GetCursorPos(out cursor)) throw new InvalidOperationException("Не удалось определить положение курсора.");
            int x = (int)Math.Round((cursor.X - bounds.X) * (double)PixelFrame.ReferenceWidth / bounds.Width);
            int y = (int)Math.Round((cursor.Y - bounds.Y) * (double)PixelFrame.ReferenceHeight / bounds.Height);
            if (x < GearPoint.HalfWidth || x >= PixelFrame.ReferenceWidth - GearPoint.HalfWidth ||
                y < GearPoint.HalfHeight || y >= PixelFrame.ReferenceHeight - GearPoint.HalfHeight)
                throw new InvalidOperationException("Наведите курсор на элемент внутри окна игры.");
            int index; bool right;
            lock (calibrationGate)
            {
                if (calibrationMode != 2) return;
                index = gearSamples.Count; right = index == 0 && captureRodRight;
            }
            PixelFrame frame = port.CaptureArea(bounds, x - GearPoint.HalfWidth, y - GearPoint.HalfHeight,
                x + GearPoint.HalfWidth, y + GearPoint.HalfHeight);
            if (!port.IsForeground(bounds) || !WindowsNative.GetCursorPos(out after) ||
                Math.Abs(after.X - cursor.X) > 1 || Math.Abs(after.Y - cursor.Y) > 1)
                throw new InvalidOperationException("Фокус или курсор изменился. Наведите его на элемент и нажмите F9 ещё раз.");
            GearPoint point = GearPoint.Create(frame, x, y, right);
            GearMacro finished = null;
            lock (calibrationGate)
            {
                if (calibrationMode != 2 || gearSamples.Count != index) return;
                gearSamples.Add(point);
                if (gearSamples.Count == 3)
                {
                    finished = new GearMacro(gearSamples[0], gearSamples[1], gearSamples[2]);
                    calibrationMode = 3;
                }
            }
            try { System.Media.SystemSounds.Asterisk.Play(); } catch (Exception) { }
            if (finished != null)
            {
                try
                {
                    lock (calibrationGate) { if (calibrationMode != 3) return; }
                    finished.Save(gearPath);
                    ReportProbe("Три элемента инвентаря сохранены. Проверьте настройки перед запуском.", "Автоотход: ");
                }
                finally { lock (calibrationGate) { if (calibrationMode == 3) calibrationMode = 0; gearSamples.Clear(); } }
            }
            else
            {
                string next = index == 0 ? "Теперь нажмите на удочку, наведите на «Ловить рыбу» и нажмите F9." :
                    "Теперь нажмите «Ловить рыбу», наведите на «Хлебный мякиш» и нажмите F9.";
                ReportProbe("Сохранён шаг " + (index + 1) + ". " + next, "Автоотход: ");
            }
        }

        private void ReportProbe(string text, string logPrefix)
        {
            if (closing) return;
            engine.Log(logPrefix + text);
            try
            {
                if (IsHandleCreated && !IsDisposed && !Disposing)
                    BeginInvoke((MethodInvoker)delegate
                    {
                        if (!closing && !IsDisposed && !Disposing) probeLabel.Text = text;
                    });
            }
            catch (InvalidOperationException) { }
        }

        private void RegisterKeys()
        {
            const uint NoRepeat = 0x4000;
            hotF8 = WindowsNative.RegisterHotKey(Handle, HotF8, NoRepeat, 0x77);
            hotF9 = WindowsNative.RegisterHotKey(Handle, HotF9, NoRepeat, 0x78);
            hotF10 = WindowsNative.RegisterHotKey(Handle, HotF10, NoRepeat, 0x79);
            if (hotF8 && hotF9 && hotF10)
                hotkeyLabel.Text = "F8  ·  старт / стоп\nF9  ·  проверка экрана\nВерсия 1.28 beta.1";
            else
            {
                hotkeyLabel.Text = "Часть клавиш занята.\nПроверьте F10 в игре.";
                engine.Log(String.Format("Регистрация: F8 {0}, F9 {1}, F10 {2}. Резервная проверка F9/F10 включена; проверьте стоп в игре.",
                    hotF8 ? "готова" : "занята", hotF9 ? "готова" : "занята", hotF10 ? "готова" : "занята"));
            }
        }

        private void UnregisterKeys()
        {
            if (hotF8) WindowsNative.UnregisterHotKey(Handle, HotF8);
            if (hotF9) WindowsNative.UnregisterHotKey(Handle, HotF9);
            if (hotF10) WindowsNative.UnregisterHotKey(Handle, HotF10);
            hotF8 = hotF9 = hotF10 = false;
        }

        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            // Borderless windows must retain the familiar keyboard close path.
            if (keyData == (Keys.Alt | Keys.F4)) { Close(); return true; }
            return base.ProcessCmdKey(ref msg, keyData);
        }

        protected override void WndProc(ref Message m)
        {
            const int WM_HOTKEY = 0x0312;
            if (m.Msg == WM_HOTKEY)
            {
                int id = m.WParam.ToInt32();
                if (id == HotF8)
                {
                    if (engine.Snapshot().Running) engine.RequestStop();
                    else StartFishing();
                    return;
                }
                if (id == HotF9) { RequestProbe(); return; }
                if (id == HotF10) { HandleEmergency(EmergencySignal.F10, true); return; }
            }
            base.WndProc(ref m);
        }
    }
}
