using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace RMFish
{
    internal static class Theme
    {
        public static readonly Color Background = Color.FromArgb(10, 18, 22);
        public static readonly Color Sidebar = Color.FromArgb(14, 25, 29);
        public static readonly Color Card = Color.FromArgb(20, 34, 38);
        public static readonly Color Raised = Color.FromArgb(26, 43, 46);
        public static readonly Color Border = Color.FromArgb(43, 64, 65);
        public static readonly Color Text = Color.FromArgb(231, 243, 239);
        public static readonly Color Muted = Color.FromArgb(144, 169, 166);
        public static readonly Color Accent = Color.FromArgb(94, 224, 177);
        public static readonly Color AccentDark = Color.FromArgb(12, 47, 36);
        public static readonly Color Warn = Color.FromArgb(237, 192, 114);

        public static GraphicsPath Round(Rectangle rect, int radius)
        {
            int d = Math.Min(radius * 2, Math.Min(rect.Width, rect.Height));
            GraphicsPath path = new GraphicsPath();
            path.AddArc(rect.X, rect.Y, d, d, 180, 90);
            path.AddArc(rect.Right - d, rect.Y, d, d, 270, 90);
            path.AddArc(rect.Right - d, rect.Bottom - d, d, d, 0, 90);
            path.AddArc(rect.X, rect.Bottom - d, d, d, 90, 90);
            path.CloseFigure();
            return path;
        }
    }

    internal class SoftCard : Panel
    {
        public Color Fill = Theme.Card;
        public Color Stroke = Theme.Border;
        public int Radius = 14;
        public SoftCard()
        {
            DoubleBuffered = true;
            SetStyle(ControlStyles.SupportsTransparentBackColor, true);
            BackColor = Theme.Background;
        }
        protected override void OnPaintBackground(PaintEventArgs e)
        {
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (SolidBrush background = new SolidBrush(Parent == null ? Theme.Background : Parent.BackColor))
                e.Graphics.FillRectangle(background, ClientRectangle);
            Rectangle box = new Rectangle(0, 0, Math.Max(1, Width - 1), Math.Max(1, Height - 1));
            using (GraphicsPath path = Theme.Round(box, Radius))
            using (SolidBrush brush = new SolidBrush(Fill))
            using (Pen pen = new Pen(Stroke, 1))
            {
                e.Graphics.FillPath(brush, path);
                e.Graphics.DrawPath(pen, path);
            }
        }
    }

    internal class SoftButton : Button
    {
        public Color Fill = Theme.Raised;
        public Color Ink = Theme.Text;
        public Color Border = Theme.Border;
        public bool Selected;
        public bool AlignLeft;
        private bool hovered;
        public SoftButton()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            Cursor = Cursors.Hand;
            Font = new Font("Segoe UI", 9.5f, FontStyle.Bold);
            TabStop = true;
        }
        protected override void OnMouseEnter(EventArgs e) { hovered = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hovered = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnPaintBackground(PaintEventArgs e) { }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            SoftCard parentCard = Parent as SoftCard;
            e.Graphics.Clear(parentCard != null ? parentCard.Fill : Parent == null ? Theme.Background : Parent.BackColor);
            Color fill = Enabled ? Fill : Color.FromArgb(30, 42, 43);
            if (Enabled && (hovered || Selected)) fill = ControlPaint.Light(fill, 0.10f);
            Color ink = Enabled ? Ink : Color.FromArgb(101, 118, 115);
            using (GraphicsPath path = Theme.Round(new Rectangle(0, 0, Math.Max(1, Width - 1), Math.Max(1, Height - 1)), 10))
            using (SolidBrush brush = new SolidBrush(fill))
            using (Pen pen = new Pen(Selected ? Theme.Accent : Border))
            {
                e.Graphics.FillPath(brush, path);
                e.Graphics.DrawPath(pen, path);
            }
            Rectangle textRect = new Rectangle(AlignLeft ? 16 : 3, 0, Width - (AlignLeft ? 20 : 6), Height);
            TextFormatFlags flags = TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis |
                (AlignLeft ? TextFormatFlags.Left : TextFormatFlags.HorizontalCenter);
            TextRenderer.DrawText(e.Graphics, Text, Font, textRect, ink, flags);
            if (Focused && ShowFocusCues)
                ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(ClientRectangle, -5, -5), ink, fill);
        }
    }

    internal sealed class Logo : Control
    {
        public Logo() { DoubleBuffered = true; Size = new Size(44, 44); }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (GraphicsPath path = Theme.Round(new Rectangle(0, 0, Width - 1, Height - 1), 11))
            using (SolidBrush bg = new SolidBrush(Color.FromArgb(22, 67, 57)))
            using (Pen edge = new Pen(Color.FromArgb(53, 126, 102)))
            {
                e.Graphics.FillPath(bg, path);
                e.Graphics.DrawPath(edge, path);
            }
            using (Pen hook = new Pen(Theme.Accent, 3))
            {
                hook.StartCap = LineCap.Round;
                hook.EndCap = LineCap.Round;
                e.Graphics.DrawLine(hook, 27, 10, 27, 28);
                e.Graphics.DrawArc(hook, 14, 19, 13, 14, 0, 175);
                e.Graphics.DrawLine(hook, 14, 26, 17, 28);
            }
        }
    }

    internal sealed class StageCard : SoftCard
    {
        private bool isActive;
        public StageCard(string number, string title, string detail)
        {
            MainForm.AddLabel(this, number, 16, 11, 40, 21, 8.5f, Theme.Accent, FontStyle.Bold);
            MainForm.AddLabel(this, title, 16, 36, 220, 25, 11f, Theme.Text, FontStyle.Bold);
            MainForm.AddLabel(this, detail, 16, 67, 220, 23, 8.5f, Theme.Muted, FontStyle.Regular);
        }
        public void SetActive(bool active)
        {
            if (isActive == active) return;
            isActive = active;
            Stroke = active ? Theme.Accent : Theme.Border;
            Fill = active ? Color.FromArgb(21, 49, 43) : Theme.Card;
            Invalidate(true);
        }
    }

    public sealed class MainForm : Form
    {
        private readonly string baseDirectory, stopFile, settingsPath;
        private readonly FishingEngine engine;
        private readonly Panel[] pages = new Panel[4];
        private readonly SoftButton[] navigation = new SoftButton[4];
        private readonly System.Windows.Forms.Timer refreshTimer = new System.Windows.Forms.Timer();
        private readonly System.Windows.Forms.Timer probeTimer = new System.Windows.Forms.Timer();
        private Label statusDot, statusTitle, statusDetail, castValue, reelValue, timeValue, detectionLabel, probeLabel, hotkeyLabel;
        private SoftButton startButton, stopButton;
        private StageCard castStage, waitStage, reelStage;
        private NumericUpDown pollInput, clickInput, timeoutInput;
        private CheckBox minimizeInput;
        private TextBox logBox;
        private bool hotF8, hotF9, hotF10;
        private string lastLogText = "";
        private const int HotF8 = 101, HotF9 = 102, HotF10 = 103;

        public MainForm(string directory)
        {
            baseDirectory = directory;
            stopFile = Path.Combine(directory, "STOP.txt");
            string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (String.IsNullOrEmpty(local)) local = directory;
            settingsPath = Path.Combine(local, "RMFish", "settings.ini");
            engine = new FishingEngine(new WindowsGamePort(stopFile));

            Text = "RMFish — авторыбалка для RMRP";
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(1050, 700);
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            BackColor = Theme.Background;
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

            BuildSidebar();
            BuildDashboard();
            BuildSettings();
            BuildGuide();
            BuildDiagnostics();
            LoadSettings();
            ShowPage(0);

            refreshTimer.Interval = 150;
            refreshTimer.Tick += delegate { RefreshView(); };
            refreshTimer.Start();
            probeTimer.Interval = 3000;
            probeTimer.Tick += delegate { probeTimer.Stop(); ProbeScreen(); };
            Shown += delegate { RegisterKeys(); RefreshView(); };
            FormClosing += delegate { refreshTimer.Stop(); probeTimer.Stop(); engine.RequestStop(); UnregisterKeys(); };
            FormClosed += delegate
            {
                refreshTimer.Dispose();
                probeTimer.Dispose();
                engine.Dispose();
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
            page.Location = new Point(210, 0);
            page.Size = new Size(840, 700);
            page.BackColor = Theme.Background;
            Controls.Add(page);
            pages[index] = page;
            return page;
        }

        private void BuildSidebar()
        {
            Panel sidebar = new Panel();
            sidebar.SetBounds(0, 0, 210, 700);
            sidebar.BackColor = Theme.Sidebar;
            Controls.Add(sidebar);
            Logo logo = new Logo();
            logo.Location = new Point(22, 25);
            sidebar.Controls.Add(logo);
            AddLabel(sidebar, "RMFish", 78, 21, 115, 29, 17f, Theme.Text, FontStyle.Bold);
            AddLabel(sidebar, "RMRP  /  AUTOFISH", 79, 50, 120, 19, 7.5f, Theme.Muted, FontStyle.Bold);
            AddLabel(sidebar, "МЕНЮ", 24, 116, 140, 20, 8f, Theme.Muted, FontStyle.Bold);
            string[] names = { "Панель", "Настройки", "Как запустить", "Диагностика" };
            for (int i = 0; i < names.Length; i++)
            {
                int pageIndex = i;
                SoftButton nav = Button(sidebar, names[i], 20, 143 + i * 49, 170, 40, false);
                nav.AlignLeft = true;
                nav.Fill = Theme.Sidebar;
                nav.Border = Theme.Sidebar;
                nav.Font = new Font("Segoe UI", 9.5f, FontStyle.Regular);
                nav.Click += delegate { ShowPage(pageIndex); };
                navigation[i] = nav;
            }
            SoftCard shortcut = Card(sidebar, 20, 527, 170, 107);
            shortcut.Fill = Color.FromArgb(19, 40, 38);
            AddLabel(shortcut, "БЫСТРОЕ УПРАВЛЕНИЕ", 13, 10, 150, 19, 7.4f, Theme.Muted, FontStyle.Bold);
            AddLabel(shortcut, "F8     Старт / стоп", 13, 37, 150, 22, 9f, Theme.Text, FontStyle.Bold);
            AddLabel(shortcut, "F10   Аварийный стоп", 13, 65, 150, 22, 8.5f, Theme.Text, FontStyle.Regular);
            hotkeyLabel = AddLabel(sidebar, "", 22, 646, 165, 38, 8f, Theme.Muted, FontStyle.Regular);
        }

        private void BuildDashboard()
        {
            Panel page = CreatePage(0);
            AddLabel(page, "ПАНЕЛЬ УПРАВЛЕНИЯ", 32, 19, 350, 21, 8.5f, Theme.Accent, FontStyle.Bold);
            AddLabel(page, "Рыбалка под контролем", 30, 42, 600, 40, 21f, Theme.Text, FontStyle.Bold);
            AddLabel(page, "Заброс, ожидание клёва и вываживание — в одном цикле.", 32, 82, 700, 24, 9.5f, Theme.Muted, FontStyle.Regular);

            SoftCard status = Card(page, 32, 121, 776, 134);
            statusDot = AddLabel(status, "●", 20, 16, 22, 24, 11f, Theme.Muted, FontStyle.Bold);
            AddLabel(status, "ТЕКУЩИЙ СТАТУС", 43, 17, 250, 23, 8f, Theme.Muted, FontStyle.Bold);
            statusTitle = AddLabel(status, "Готов к запуску", 21, 42, 470, 30, 15f, Theme.Text, FontStyle.Bold);
            statusDetail = AddLabel(status, "Выберите удочку и наживку в игре.", 22, 76, 475, 42, 9f, Theme.Muted, FontStyle.Regular);
            startButton = Button(status, "▶   Старт", 509, 43, 119, 46, true);
            stopButton = Button(status, "■   Стоп", 638, 43, 116, 46, false);
            startButton.Click += delegate { StartFishing(); };
            stopButton.Click += delegate { engine.RequestStop(); };

            AddLabel(page, "ЭТАПЫ РЫБАЛКИ", 32, 274, 250, 24, 8.5f, Theme.Muted, FontStyle.Bold);
            AddLabel(page, "АВТОМАТИЧЕСКИЙ ЦИКЛ", 612, 274, 196, 24, 8f, Theme.Muted, FontStyle.Bold);
            castStage = new StageCard("01", "Заброс", "Крючок в зелёной зоне");
            waitStage = new StageCard("02", "Ожидание клёва", "Следим за шкалой");
            reelStage = new StageCard("03", "Вываживание", "Кликаем, пока она видна");
            castStage.SetBounds(32, 306, 250, 103);
            waitStage.SetBounds(295, 306, 250, 103);
            reelStage.SetBounds(558, 306, 250, 103);
            page.Controls.Add(castStage); page.Controls.Add(waitStage); page.Controls.Add(reelStage);

            SoftCard stats = Card(page, 32, 425, 776, 99);
            AddLabel(stats, "ЗАБРОСОВ", 23, 12, 190, 20, 8f, Theme.Muted, FontStyle.Bold);
            AddLabel(stats, "ВЫВАЖИВАНИЙ", 278, 12, 190, 20, 8f, Theme.Muted, FontStyle.Bold);
            AddLabel(stats, "ВРЕМЯ СЕССИИ", 532, 12, 190, 20, 8f, Theme.Muted, FontStyle.Bold);
            castValue = AddLabel(stats, "0", 22, 35, 180, 42, 22f, Theme.Text, FontStyle.Bold);
            reelValue = AddLabel(stats, "0", 277, 35, 180, 42, 22f, Theme.Text, FontStyle.Bold);
            timeValue = AddLabel(stats, "00:00", 531, 35, 210, 42, 22f, Theme.Text, FontStyle.Bold);
            stats.Paint += delegate(object sender, PaintEventArgs e)
            {
                using (Pen pen = new Pen(Theme.Border))
                {
                    e.Graphics.DrawLine(pen, 253, 20, 253, 78);
                    e.Graphics.DrawLine(pen, 508, 20, 508, 78);
                }
            };

            SoftCard note = Card(page, 32, 540, 776, 112);
            note.Fill = Color.FromArgb(18, 44, 39);
            AddLabel(note, "ПЕРЕД СТАРТОМ", 20, 15, 240, 21, 8f, Theme.Accent, FontStyle.Bold);
            AddLabel(note, "Удочку и наживку выберите вручную", 20, 40, 520, 25, 11f, Theme.Text, FontStyle.Bold);
            AddLabel(note, "Инвентарь  →  бамбуковая удочка  →  ловить рыбу  →  хлебный мякиш", 20, 69, 600, 22, 8.5f, Theme.Muted, FontStyle.Regular);
            SoftButton guide = Button(note, "Инструкция  →", 618, 38, 138, 39, false);
            guide.Click += delegate { ShowPage(2); };
            AddLabel(page, "Клики только при активном окне GTA5  ·  F8 — старт / стоп  ·  F10 — аварийный стоп", 32, 662, 776, 22, 8f, Theme.Muted, FontStyle.Regular);
        }

        private static NumericUpDown Number(Control parent, int x, int y, int min, int max, int step)
        {
            NumericUpDown number = new NumericUpDown();
            number.SetBounds(x, y, 112, 30);
            number.Minimum = min; number.Maximum = max; number.Increment = step;
            number.BackColor = Theme.Raised; number.ForeColor = Theme.Text;
            number.BorderStyle = BorderStyle.FixedSingle;
            number.Font = new Font("Segoe UI", 10f);
            number.TextAlign = HorizontalAlignment.Center;
            parent.Controls.Add(number);
            return number;
        }

        private void BuildSettings()
        {
            Panel page = CreatePage(1);
            AddLabel(page, "ПАРАМЕТРЫ", 32, 19, 350, 21, 8.5f, Theme.Accent, FontStyle.Bold);
            AddLabel(page, "Настройки", 30, 42, 600, 40, 21f, Theme.Text, FontStyle.Bold);
            AddLabel(page, "Меняйте скорость и ограничения под свою игру.", 32, 82, 700, 24, 9.5f, Theme.Muted, FontStyle.Regular);
            SoftCard settings = Card(page, 32, 122, 776, 355);
            AddLabel(settings, "Частота проверки экрана", 22, 19, 450, 25, 10.5f, Theme.Text, FontStyle.Bold);
            AddLabel(settings, "Интервал между снимками, мс (меньше — быстрее).", 22, 46, 560, 24, 9f, Theme.Muted, FontStyle.Regular);
            pollInput = Number(settings, 627, 29, 20, 200, 5);
            AddLabel(settings, "Интервал ЛКМ при вываживании", 22, 91, 500, 25, 10.5f, Theme.Text, FontStyle.Bold);
            AddLabel(settings, "Время между нажатиями, мс.", 22, 118, 520, 24, 9f, Theme.Muted, FontStyle.Regular);
            clickInput = Number(settings, 627, 101, 35, 250, 5);
            AddLabel(settings, "Максимальное ожидание шкалы", 22, 163, 500, 25, 10.5f, Theme.Text, FontStyle.Bold);
            AddLabel(settings, "В секундах; 0 — ждать без ограничения.", 22, 190, 520, 24, 9f, Theme.Muted, FontStyle.Regular);
            timeoutInput = Number(settings, 627, 173, 0, 3600, 30);
            minimizeInput = new CheckBox();
            minimizeInput.Text = "Сворачивать RMFish при запуске";
            minimizeInput.SetBounds(22, 245, 500, 29);
            minimizeInput.Font = new Font("Segoe UI", 10f, FontStyle.Bold);
            minimizeInput.ForeColor = Theme.Text;
            minimizeInput.BackColor = Color.Transparent;
            minimizeInput.FlatStyle = FlatStyle.Flat;
            minimizeInput.FlatAppearance.BorderColor = Theme.Muted;
            settings.Controls.Add(minimizeInput);
            AddLabel(settings, "Вернитесь в игру после нажатия «Старт».", 44, 276, 560, 22, 9f, Theme.Muted, FontStyle.Regular);

            SoftButton save = Button(page, "Сохранить настройки", 32, 497, 220, 44, true);
            save.Click += delegate { SaveSettings(true); };
            AddLabel(page, "Новые параметры применяются при следующем запуске.", 269, 501, 530, 34, 9f, Theme.Muted, FontStyle.Regular);
            SoftCard safety = Card(page, 32, 561, 776, 90);
            safety.Fill = Color.FromArgb(43, 38, 28);
            safety.Stroke = Color.FromArgb(99, 83, 54);
            AddLabel(safety, "БЕЗОПАСНОСТЬ", 18, 12, 210, 20, 8f, Theme.Warn, FontStyle.Bold);
            AddLabel(safety, "Потеря фокуса GTA5 останавливает клики. Клавиша F10 и STOP.bat останавливают программу.", 18, 37, 735, 38, 9f, Theme.Text, FontStyle.Regular);
        }

        private void BuildGuide()
        {
            Panel page = CreatePage(2);
            AddLabel(page, "ПЕРВЫЙ ЗАПУСК", 32, 19, 350, 21, 8.5f, Theme.Accent, FontStyle.Bold);
            AddLabel(page, "Как начать рыбалку", 30, 42, 650, 40, 21f, Theme.Text, FontStyle.Bold);
            AddLabel(page, "Первую подготовку выполняем вручную — это надёжнее в RMRP.", 32, 82, 740, 24, 9.5f, Theme.Muted, FontStyle.Regular);
            string[] titles = { "Встаньте в зоне рыбалки", "Подготовьте удочку и наживку", "Запустите RMFish и вернитесь в игру", "Остановите, когда понадобится" };
            string[] details = {
                "Откройте GTA5 / RMRP и подойдите к воде в отмеченной зоне.",
                "Нажмите I → бамбуковая удочка → «Ловить рыбу» → «Хлебный мякиш».",
                "Нажмите «Старт» или F8. Вернитесь в GTA5: программа ждёт видимую шкалу.",
                "F8 — обычный стоп, F10 — аварийный. Также можно запустить STOP.bat."
            };
            for (int i = 0; i < titles.Length; i++)
            {
                SoftCard step = Card(page, 32, 122 + i * 92, 776, 80);
                AddLabel(step, "0" + (i + 1), 18, 15, 48, 45, 15f, Theme.Accent, FontStyle.Bold);
                AddLabel(step, titles[i], 75, 11, 665, 25, 10.5f, Theme.Text, FontStyle.Bold);
                AddLabel(step, details[i], 75, 39, 670, 26, 9f, Theme.Muted, FontStyle.Regular);
            }
            SoftCard tip = Card(page, 32, 508, 776, 139);
            tip.Fill = Color.FromArgb(18, 44, 39);
            AddLabel(tip, "ВАЖНО", 20, 12, 230, 20, 8f, Theme.Accent, FontStyle.Bold);
            AddLabel(tip, "Используйте формат 16:9, лучше 1920×1080, и оконный режим без рамки. Окно игры должно быть полностью видно.", 20, 37, 735, 43, 9f, Theme.Text, FontStyle.Regular);
            AddLabel(tip, "Счётчик показывает завершённые фазы вываживания, а не подтверждённую поимку. Наличие наживки не проверяется.", 20, 83, 735, 42, 9f, Theme.Muted, FontStyle.Regular);
        }

        private void BuildDiagnostics()
        {
            Panel page = CreatePage(3);
            AddLabel(page, "ПРОВЕРКА ЭКРАНА", 32, 19, 350, 21, 8.5f, Theme.Accent, FontStyle.Bold);
            AddLabel(page, "Диагностика", 30, 42, 600, 40, 21f, Theme.Text, FontStyle.Bold);
            AddLabel(page, "Проверка только считывает изображение и не нажимает мышь.", 32, 82, 730, 24, 9.5f, Theme.Muted, FontStyle.Regular);
            SoftCard probe = Card(page, 32, 122, 776, 159);
            AddLabel(probe, "ПОСЛЕДНЯЯ ПРОВЕРКА F9", 20, 15, 300, 20, 8f, Theme.Accent, FontStyle.Bold);
            probeLabel = AddLabel(probe, "Переключитесь в GTA5 и нажмите F9 или запустите проверку через 3 секунды.", 20, 42, 720, 52, 9.5f, Theme.Text, FontStyle.Regular);
            SoftButton check = Button(probe, "Проверить через 3 сек", 20, 103, 210, 38, false);
            check.Click += delegate
            {
                probeLabel.Text = "Переключитесь в GTA5: снимок будет сделан через 3 секунды…";
                probeTimer.Stop(); probeTimer.Start();
            };
            AddLabel(page, "ДАННЫЕ РАБОЧЕГО КАДРА", 32, 300, 400, 20, 8f, Theme.Muted, FontStyle.Bold);
            SoftCard detected = Card(page, 32, 326, 776, 64);
            detectionLabel = AddLabel(detected, "Кадр ещё не проверен.", 18, 10, 735, 44, 9f, Theme.Text, FontStyle.Regular);
            AddLabel(page, "ЖУРНАЛ СОБЫТИЙ", 32, 408, 400, 20, 8f, Theme.Muted, FontStyle.Bold);
            SoftCard logPanel = Card(page, 32, 434, 776, 218);
            logBox = new TextBox();
            logBox.SetBounds(18, 16, 739, 184);
            logBox.Multiline = true;
            logBox.ReadOnly = true;
            logBox.ScrollBars = ScrollBars.Vertical;
            logBox.BorderStyle = BorderStyle.None;
            logBox.BackColor = Theme.Card;
            logBox.ForeColor = Theme.Muted;
            logBox.Font = new Font("Consolas", 9f);
            logBox.TabStop = false;
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
                    navigation[i].Fill = i == index ? Color.FromArgb(23, 55, 47) : Theme.Sidebar;
                    navigation[i].Ink = i == index ? Theme.Accent : Theme.Muted;
                    navigation[i].Invalidate();
                }
            }
        }

        private EngineOptions GetOptions()
        {
            return new EngineOptions
            {
                PollMilliseconds = (int)pollInput.Value,
                ReelClickMilliseconds = (int)clickInput.Value,
                WaitTimeoutSeconds = (int)timeoutInput.Value,
                MinimizeOnStart = minimizeInput.Checked
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
                        if (pair[0] == "minimize" && Boolean.TryParse(pair[1], out flag)) options.MinimizeOnStart = flag;
                    }
                }
            }
            catch (Exception ex) { engine.Log("Не удалось прочитать настройки: " + ex.Message); }
            options = options.CopyValidated();
            pollInput.Value = options.PollMilliseconds;
            clickInput.Value = options.ReelClickMilliseconds;
            timeoutInput.Value = options.WaitTimeoutSeconds;
            minimizeInput.Checked = options.MinimizeOnStart;
        }

        private bool SaveSettings(bool inform)
        {
            try
            {
                EngineOptions options = GetOptions().CopyValidated();
                Directory.CreateDirectory(Path.GetDirectoryName(settingsPath));
                string text = "poll_ms=" + options.PollMilliseconds + "\r\nreel_click_ms=" + options.ReelClickMilliseconds +
                    "\r\nwait_seconds=" + options.WaitTimeoutSeconds + "\r\nminimize=" + options.MinimizeOnStart + "\r\n";
                File.WriteAllText(settingsPath, text, Encoding.UTF8);
                if (inform) MessageBox.Show(this, "Настройки сохранены. Они применятся при следующем запуске.", "RMFish", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return true;
            }
            catch (Exception ex)
            {
                engine.Log("Не удалось сохранить настройки: " + ex.Message);
                if (inform) MessageBox.Show(this, "Не удалось сохранить настройки: " + ex.Message, "RMFish", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return false;
            }
        }

        private void StartFishing()
        {
            if (engine.Snapshot().Running) return;
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
            if (engine.Start(options))
            {
                if (options.MinimizeOnStart) WindowState = FormWindowState.Minimized;
                RefreshView();
            }
        }

        private void RefreshView()
        {
            EngineSnapshot state = engine.Snapshot();
            statusTitle.Text = state.Title;
            statusDetail.Text = state.Detail;
            statusDot.ForeColor = !state.Running ? Theme.Muted : state.Phase == FishingPhase.Paused ? Theme.Warn : Theme.Accent;
            startButton.Enabled = !state.Running;
            stopButton.Enabled = state.Running;
            castStage.SetActive(state.Running && state.Phase == FishingPhase.Casting);
            waitStage.SetActive(state.Running && state.Phase == FishingPhase.WaitingBite);
            reelStage.SetActive(state.Running && state.Phase == FishingPhase.Reeling);
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
                logBox.Text = text;
                logBox.SelectionStart = logBox.TextLength;
                logBox.ScrollToCaret();
            }
        }

        private void ProbeScreen()
        {
            try
            {
                using (WindowsGamePort port = new WindowsGamePort(null))
                {
                    GameBounds bounds;
                    string reason;
                    if (!port.TryGetForeground(out bounds, out reason))
                    {
                        probeLabel.Text = reason;
                        engine.Log("Диагностика: " + reason);
                        return;
                    }
                    PixelFrame frame = port.Capture(bounds);
                    string result = String.Format("{0}×{1}. {2}", bounds.Width, bounds.Height, Vision.Describe(frame));
                    probeLabel.Text = result;
                    engine.Log("F9: " + result);
                }
            }
            catch (Exception ex)
            {
                probeLabel.Text = "Ошибка снимка: " + ex.Message;
                engine.Log(probeLabel.Text);
            }
        }

        private void RegisterKeys()
        {
            const uint NoRepeat = 0x4000;
            hotF8 = WindowsNative.RegisterHotKey(Handle, HotF8, NoRepeat, 0x77);
            hotF9 = WindowsNative.RegisterHotKey(Handle, HotF9, NoRepeat, 0x78);
            hotF10 = WindowsNative.RegisterHotKey(Handle, HotF10, NoRepeat, 0x79);
            if (hotF8 && hotF9 && hotF10)
                hotkeyLabel.Text = "F9  ·  проверка экрана\nВерсия 1.27 beta";
            else
            {
                hotkeyLabel.Text = "Некоторые горячие клавиши заняты.";
                engine.Log(String.Format("Горячие клавиши: F8 {0}, F9 {1}, F10 {2}. Занятые клавиши замените кнопками и STOP.bat.",
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
                if (id == HotF9) { ProbeScreen(); return; }
                if (id == HotF10) { engine.RequestStop(); return; }
            }
            base.WndProc(ref m);
        }
    }
}
