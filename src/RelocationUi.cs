using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace RMFish
{
    // This dialog only stores the user's choice; no game input is sent here.
    internal sealed class RelocationSetupForm : Form
    {
        private readonly CheckBox enabled, rightButton, confirmedTurn;
        private readonly NumericUpDown turnUnits;
        public string Command { get; private set; }
        public bool AutoEnabled { get { return enabled.Checked; } }
        public bool RodRightButton { get { return rightButton.Checked; } }
        public int TurnUnits { get { return (int)turnUnits.Value; } }
        public bool TurnConfirmed { get { return turnUnits.Value > 0 && confirmedTurn.Checked; } }

        public RelocationSetupForm(bool autoEnabled, bool rodRight, bool hasNotice, bool hasGear)
            : this(autoEnabled, rodRight, hasNotice, hasGear, 0, false) { }

        public RelocationSetupForm(bool autoEnabled, bool rodRight, bool hasNotice, bool hasGear, int units, bool turnConfirmed)
        {
            Text = "RMFish — автоотход"; StartPosition = FormStartPosition.CenterParent;
            FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false; MinimizeBox = false;
            ClientSize = new Size(620, 570); BackColor = Theme.Background; ForeColor = Theme.Text;
            Font = new Font("Segoe UI", 9f);
            Label title = new Label(); title.Text = "Автоотход при окончании рыбы"; title.SetBounds(18, 14, 570, 28);
            title.Font = new Font("Segoe UI", 12f, FontStyle.Bold); Controls.Add(title);
            enabled = new CheckBox(); enabled.Name = "relocationEnabled";
            enabled.Text = "Включить автоотход (по умолчанию выключен)";
            enabled.Checked = autoEnabled; enabled.SetBounds(20, 50, 570, 27); Controls.Add(enabled);
            Label warning = new Label(); warning.SetBounds(20, 83, 580, 70);
            warning.ForeColor = Theme.Warn;
            warning.Text = "Только под наблюдением: пробел → поворот на 180° → W 7 с → поворот на 180° → W 7 с. Точный возврат не гарантируется. Фокус или F10 прервёт маршрут без повтора.";
            Controls.Add(warning);
            Label steps = new Label(); steps.SetBounds(20, 153, 580, 52);
            steps.Text = "Нужны образец уведомления, три элемента инвентаря и проверенный поворот при текущем разрешении и чувствительности мыши.";
            Controls.Add(steps);
            Button notice = MakeButton("1. Уведомление по F9 · " + (hasNotice ? "готово" : "нет"), 20, 205, 330);
            notice.Name = "recordNotice";
            notice.Click += delegate { Command = "notice"; DialogResult = DialogResult.OK; Close(); };
            Button noticeFile = MakeButton("Из файла…", 360, 205, 170);
            noticeFile.Name = "importNotice";
            noticeFile.Click += delegate { Command = "notice-file"; DialogResult = DialogResult.OK; Close(); };
            rightButton = new CheckBox(); rightButton.Name = "rodRightButton";
            rightButton.Text = "Удочку открывать правой кнопкой мыши";
            rightButton.Checked = rodRight; rightButton.SetBounds(20, 248, 570, 28); Controls.Add(rightButton);
            Button gear = MakeButton("2. Инвентарь по F9 · " + (hasGear ? "готово" : "нет"), 20, 282, 330);
            gear.Name = "recordGear";
            gear.Click += delegate { Command = "gear"; DialogResult = DialogResult.OK; Close(); };
            Button gearFiles = MakeButton("Из файлов…", 360, 282, 170);
            gearFiles.Name = "importGear";
            gearFiles.Click += delegate { Command = "gear-files"; DialogResult = DialogResult.OK; Close(); };
            Label turnLabel = new Label(); turnLabel.SetBounds(20, 327, 580, 25);
            turnLabel.Text = "3. Поворот на 180° · относительные шаги мыши (0 — не настроен)";
            Controls.Add(turnLabel);
            turnUnits = new NumericUpDown(); turnUnits.Name = "turnUnits";
            turnUnits.Minimum = 0; turnUnits.Maximum = 10000; turnUnits.Increment = 100;
            turnUnits.Value = Math.Max(0, Math.Min(10000, units)); turnUnits.SetBounds(20, 358, 115, 28);
            Controls.Add(turnUnits);
            Button testTurn = MakeButton("Пробный поворот через 3 сек", 146, 354, 250);
            testTurn.Name = "testTurn"; testTurn.Enabled = turnUnits.Value > 0;
            testTurn.Click += delegate { Command = "turn"; DialogResult = DialogResult.OK; Close(); };
            confirmedTurn = new CheckBox(); confirmedTurn.Name = "confirmedTurn";
            confirmedTurn.Text = "Я проверил в игре: это именно 180°";
            confirmedTurn.SetBounds(20, 397, 570, 28);
            confirmedTurn.Checked = turnUnits.Value > 0 && turnConfirmed;
            confirmedTurn.Enabled = turnUnits.Value > 0; Controls.Add(confirmedTurn);
            turnUnits.ValueChanged += delegate
            {
                confirmedTurn.Checked = false;
                confirmedTurn.Enabled = turnUnits.Value > 0;
                testTurn.Enabled = turnUnits.Value > 0;
            };
            Label hint = new Label(); hint.SetBounds(20, 431, 580, 62); hint.ForeColor = Theme.Muted;
            hint.Text = "Введите величину и проверьте поворот на безопасном месте. Подберите её повторными тестами и подтвердите только при точных 180°. При смене чувствительности настройте заново.";
            Controls.Add(hint);
            Button save = MakeButton("Сохранить и закрыть", 20, 515, 190);
            save.Name = "saveRelocation";
            save.Click += delegate { Command = "save"; DialogResult = DialogResult.OK; Close(); };
            Button cancel = MakeButton("Отмена", 218, 515, 115);
            cancel.DialogResult = DialogResult.Cancel;
            CancelButton = cancel;
        }

        private Button MakeButton(string text, int x, int y, int width)
        {
            Button button = new Button(); button.Text = text; button.SetBounds(x, y, width, 35);
            button.FlatStyle = FlatStyle.Flat; button.BackColor = Theme.Raised; button.ForeColor = Theme.Text;
            button.FlatAppearance.BorderColor = Theme.Border; Controls.Add(button); return button;
        }
    }

    // This is only the mode selector. The worker independently refuses to
    // run the unfinished mode, even if a setting file is edited by hand.
    internal sealed class WindowModeForm : Form
    {
        private readonly RadioButton active, minimized;
        public GameWindowMode SelectedMode { get { return minimized.Checked ? GameWindowMode.MinimizedExperimental : GameWindowMode.Active; } }

        public WindowModeForm(GameWindowMode current)
        {
            Text = "Режим окна игры"; StartPosition = FormStartPosition.CenterParent;
            FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false; MinimizeBox = false;
            ClientSize = new Size(560, 260); BackColor = Theme.Background; ForeColor = Theme.Text;
            Font = new Font("Segoe UI", 9f);
            Label title = new Label(); title.Text = "Выберите режим"; title.SetBounds(18, 13, 510, 26);
            title.Font = new Font("Segoe UI", 12f, FontStyle.Bold); Controls.Add(title);
            active = new RadioButton(); active.Name = "activeGameMode"; active.Text = "Обычный: GTA5 видна и активна";
            active.SetBounds(20, 52, 510, 29); active.Checked = current == GameWindowMode.Active; Controls.Add(active);
            minimized = new RadioButton(); minimized.Name = "minimizedGameMode";
            minimized.Text = "Свёрнутая игра — в разработке"; minimized.SetBounds(20, 88, 510, 29);
            minimized.Checked = current == GameWindowMode.MinimizedExperimental; Controls.Add(minimized);
            Label warning = new Label(); warning.ForeColor = Theme.Warn; warning.SetBounds(20, 128, 520, 63);
            warning.Text = "Режим свёрнутой GTA пока не работает: его выбор блокирует запуск рыбалки. Системный ввод нельзя безопасно отправить в свёрнутую игру обычным способом.";
            Controls.Add(warning);
            Button save = new Button(); save.Name = "saveGameMode"; save.Text = "Сохранить"; save.SetBounds(20, 211, 140, 32);
            save.DialogResult = DialogResult.OK; Controls.Add(save); AcceptButton = save;
            Button cancel = new Button(); cancel.Text = "Отмена"; cancel.SetBounds(170, 211, 100, 32);
            cancel.DialogResult = DialogResult.Cancel; Controls.Add(cancel); CancelButton = cancel;
        }
    }

    // A file is useful for click calibration only if its pixels still have the
    // original game-client coordinates. A cropped icon cannot supply those.
    // This checks dimensions, not the image's content: the user must still
    // confirm that the image really is the whole, unscaled game client.
    internal static class CalibrationImage
    {
        internal const long MaximumFileBytes = 50L * 1024L * 1024L;
        internal const long MaximumPixels = 16000000L;

        public static PixelFrame Load(string path)
        {
            using (FileStream file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                if (file.Length < 1 || file.Length > MaximumFileBytes)
                    throw new InvalidDataException("Файл пустой или больше 50 МБ.");
                using (Image source = Image.FromStream(file, false, true))
                {
                    if (!source.RawFormat.Equals(ImageFormat.Png) && !source.RawFormat.Equals(ImageFormat.Jpeg) &&
                        !source.RawFormat.Equals(ImageFormat.Bmp))
                        throw new InvalidDataException("Выберите PNG, JPEG или BMP.");
                    int width = source.Width, height = source.Height;
                    if (width < 1280 || height < 720 || width > 10000 || height > 10000 ||
                        (long)width * height > MaximumPixels || Math.Abs(width / (double)height - 16.0 / 9.0) > 0.035)
                        throw new InvalidDataException("Нужен полный снимок окна GTA5 без обрезки и изменения размера: 16:9, от 1280×720, не более 16 мегапикселей. Отдельный значок не содержит координат.");
                    using (Bitmap copy = new Bitmap(width, height, PixelFormat.Format32bppArgb))
                    {
                        using (Graphics graphics = Graphics.FromImage(copy))
                        {
                            graphics.CompositingMode = System.Drawing.Drawing2D.CompositingMode.SourceCopy;
                            graphics.DrawImageUnscaled(source, 0, 0);
                        }
                        byte[] pixels = new byte[checked(width * height * 4)];
                        BitmapData bits = copy.LockBits(new Rectangle(0, 0, width, height), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
                        try
                        {
                            for (int y = 0; y < height; y++)
                                Marshal.Copy(IntPtr.Add(bits.Scan0, y * bits.Stride), pixels, y * width * 4, width * 4);
                        }
                        finally { copy.UnlockBits(bits); }
                        for (int i = 3; i < pixels.Length; i += 4)
                            if (pixels[i] != 255) throw new InvalidDataException("Прозрачное изображение не подходит. Сохраните непрозрачный снимок экрана.");
                        return new PixelFrame(pixels, width, height, width * 4, width, height, 0, 0);
                    }
                }
            }
        }
    }

    // Select a clickable target on an entire game-client screenshot. The
    // rectangle's centre is the click location; a fixed 40×28 reference-pixel
    // patch around it is the same visual guard used by the original F9 method.
    internal sealed class GearImageSelectionForm : Form
    {
        private readonly PixelFrame frame;
        private readonly bool rightButton;
        private readonly PictureBox preview;
        private readonly Bitmap image;
        private Point start, end;
        private bool selecting, selected;
        public GearPoint Result { get; private set; }

        public GearImageSelectionForm(PixelFrame frame, string step, bool right)
        {
            if (frame == null) throw new ArgumentNullException("frame");
            this.frame = frame; rightButton = right;
            Text = "Инвентарь — " + step; StartPosition = FormStartPosition.CenterParent;
            FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false; MinimizeBox = false;
            ClientSize = new Size(984, 646); BackColor = Theme.Background; ForeColor = Theme.Text;
            Font = new Font("Segoe UI", 9f); AutoScaleMode = AutoScaleMode.None;
            Label instructions = new Label(); instructions.SetBounds(12, 6, 960, 56);
            instructions.Text = step + ": выделите мышью то, на что нужно нажать. Клик будет в центре рамки; зелёная рамка — проверяемый образец. Не выделяйте счётчик количества.";
            Controls.Add(instructions);
            const int width = 960, height = 540;
            image = new Bitmap(width, height, PixelFormat.Format32bppArgb);
            byte[] data = new byte[width * height * 4];
            for (int y = 0; y < height; y++)
                for (int x = 0; x < width; x++)
                {
                    int r, g, b; frame.Read(x * 2, y * 2, out r, out g, out b);
                    int i = (y * width + x) * 4;
                    data[i] = (byte)b; data[i + 1] = (byte)g; data[i + 2] = (byte)r; data[i + 3] = 255;
                }
            BitmapData bits = image.LockBits(new Rectangle(0, 0, width, height), ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
            try { Marshal.Copy(data, 0, bits.Scan0, data.Length); }
            finally { image.UnlockBits(bits); }
            preview = new PictureBox(); preview.Name = "gearImagePreview";
            preview.Image = image; preview.SetBounds(12, 62, width, height); preview.Cursor = Cursors.Cross;
            preview.MouseDown += delegate(object sender, MouseEventArgs e)
            {
                if (e.Button != MouseButtons.Left) return;
                start = end = Clamp(e.Location); selecting = true; selected = false; preview.Invalidate();
            };
            preview.MouseMove += delegate(object sender, MouseEventArgs e)
            { if (selecting) { end = Clamp(e.Location); preview.Invalidate(); } };
            preview.MouseUp += delegate(object sender, MouseEventArgs e)
            { if (selecting) { end = Clamp(e.Location); selecting = false; selected = true; preview.Invalidate(); } };
            preview.Paint += delegate(object sender, PaintEventArgs e)
            {
                if (!selecting && !selected) return;
                Rectangle rect = Selection();
                using (Pen pen = new Pen(Color.Yellow, 2)) e.Graphics.DrawRectangle(pen, rect);
                int x = rect.X + rect.Width / 2, y = rect.Y + rect.Height / 2;
                using (Pen pen = new Pen(Color.Lime, 1))
                    e.Graphics.DrawRectangle(pen, x - GearPoint.HalfWidth / 2, y - GearPoint.HalfHeight / 2,
                        GearPoint.HalfWidth, GearPoint.HalfHeight);
            };
            Controls.Add(preview);
            Button save = new Button(); save.Name = "saveGearImage"; save.Text = "Выбрать этот элемент";
            save.SetBounds(12, 608, 190, 30); Controls.Add(save);
            save.Click += delegate
            {
                try
                {
                    Rectangle rect = Selection();
                    if (!selected || rect.Width < 4 || rect.Height < 4)
                        throw new InvalidOperationException("Выделите нужный значок или надпись мышью.");
                    int x = rect.Left * 2 + rect.Width, y = rect.Top * 2 + rect.Height;
                    Result = GearPoint.Create(frame, x, y, rightButton);
                    DialogResult = DialogResult.OK; Close();
                }
                catch (Exception ex) { MessageBox.Show(this, ex.Message, "Образец инвентаря", MessageBoxButtons.OK, MessageBoxIcon.Warning); }
            };
            Button cancel = new Button(); cancel.Text = "Отмена"; cancel.SetBounds(210, 608, 110, 30);
            cancel.DialogResult = DialogResult.Cancel; Controls.Add(cancel); CancelButton = cancel;
        }

        private Point Clamp(Point p)
        { return new Point(Math.Max(0, Math.Min(preview.Width - 1, p.X)), Math.Max(0, Math.Min(preview.Height - 1, p.Y))); }
        private Rectangle Selection()
        { return Rectangle.FromLTRB(Math.Min(start.X, end.X), Math.Min(start.Y, end.Y), Math.Max(start.X, end.X), Math.Max(start.Y, end.Y)); }
        protected override void Dispose(bool disposing)
        {
            if (disposing) { preview.Image = null; image.Dispose(); }
            base.Dispose(disposing);
        }
    }

    // The image is the in-memory region above the minimap, captured by F9 or
    // imported from a full-size screenshot. Only its text mask is saved.
    internal sealed class NoticeSelectionForm : Form
    {
        private readonly PixelFrame frame;
        private readonly PictureBox preview;
        private readonly Bitmap image;
        private Point start, end;
        private bool selecting, selected;
        public NoticeTemplate Result { get; private set; }

        public NoticeSelectionForm(PixelFrame frame)
        {
            this.frame = frame;
            Text = "Выберите текст уведомления"; StartPosition = FormStartPosition.CenterParent;
            FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false; MinimizeBox = false;
            ClientSize = new Size(644, 511); BackColor = Theme.Background; ForeColor = Theme.Text;
            Font = new Font("Segoe UI", 9f); AutoScaleMode = AutoScaleMode.None;
            Label instructions = new Label(); instructions.SetBounds(12, 6, 620, 48);
            instructions.Text = "Обведите мышью всю неизменную надпись об окончании рыбы. Не включайте значок и пустые края. Не выбирайте другое уведомление.";
            Controls.Add(instructions);
            int width = NoticeTemplate.RegionRight - NoticeTemplate.RegionLeft;
            int height = NoticeTemplate.RegionBottom - NoticeTemplate.RegionTop;
            image = new Bitmap(width, height, PixelFormat.Format32bppArgb);
            byte[] data = new byte[width * height * 4];
            for (int y = 0; y < height; y++)
                for (int x = 0; x < width; x++)
                {
                    int r, g, b; frame.Read(x + NoticeTemplate.RegionLeft, y + NoticeTemplate.RegionTop, out r, out g, out b);
                    int i = (y * width + x) * 4;
                    data[i] = (byte)b; data[i + 1] = (byte)g; data[i + 2] = (byte)r; data[i + 3] = 255;
                }
            BitmapData bits = image.LockBits(new Rectangle(0, 0, width, height), ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
            try { Marshal.Copy(data, 0, bits.Scan0, data.Length); }
            finally { image.UnlockBits(bits); }
            preview = new PictureBox(); preview.Name = "noticePreview";
            preview.Image = image; preview.SetBounds(12, 54, width, height);
            preview.Cursor = Cursors.Cross;
            preview.MouseDown += delegate(object sender, MouseEventArgs e)
            {
                if (e.Button != MouseButtons.Left) return;
                start = end = e.Location; selecting = true; selected = false; preview.Invalidate();
            };
            preview.MouseMove += delegate(object sender, MouseEventArgs e)
            {
                if (!selecting) return; end = Clamp(e.Location); preview.Invalidate();
            };
            preview.MouseUp += delegate(object sender, MouseEventArgs e)
            {
                if (!selecting) return; end = Clamp(e.Location); selecting = false; selected = true; preview.Invalidate();
            };
            preview.Paint += delegate(object sender, PaintEventArgs e)
            {
                if (selecting || selected)
                    using (Pen pen = new Pen(Color.Yellow, 2)) e.Graphics.DrawRectangle(pen, Selection());
            };
            Controls.Add(preview);
            Button save = new Button(); save.Name = "saveNotice"; save.Text = "Сохранить образец";
            save.SetBounds(12, 466, 185, 32); Controls.Add(save);
            save.Click += delegate
            {
                try
                {
                    if (!selected) throw new InvalidOperationException("Сначала выделите текст мышью.");
                    Rectangle rect = Selection();
                    Result = NoticeTemplate.Create(frame, rect.X + NoticeTemplate.RegionLeft,
                        rect.Y + NoticeTemplate.RegionTop, rect.Width, rect.Height);
                    DialogResult = DialogResult.OK; Close();
                }
                catch (Exception ex) { MessageBox.Show(this, ex.Message, "Образец уведомления", MessageBoxButtons.OK, MessageBoxIcon.Warning); }
            };
            Button cancel = new Button(); cancel.Text = "Отмена"; cancel.SetBounds(205, 466, 110, 32);
            cancel.DialogResult = DialogResult.Cancel; Controls.Add(cancel); CancelButton = cancel;
        }

        private Point Clamp(Point p)
        { return new Point(Math.Max(0, Math.Min(preview.Width - 1, p.X)), Math.Max(0, Math.Min(preview.Height - 1, p.Y))); }
        private Rectangle Selection()
        { return Rectangle.FromLTRB(Math.Min(start.X, end.X), Math.Min(start.Y, end.Y), Math.Max(start.X, end.X), Math.Max(start.Y, end.Y)); }
        protected override void Dispose(bool disposing)
        {
            if (disposing) { preview.Image = null; image.Dispose(); }
            base.Dispose(disposing);
        }
    }
}
