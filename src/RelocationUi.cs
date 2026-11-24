using System;
using System.Drawing;
using System.Drawing.Imaging;
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
            Button notice = MakeButton("1. Записать уведомление · " + (hasNotice ? "готово" : "нет"), 20, 205, 330);
            notice.Name = "recordNotice";
            notice.Click += delegate { Command = "notice"; DialogResult = DialogResult.OK; Close(); };
            rightButton = new CheckBox(); rightButton.Name = "rodRightButton";
            rightButton.Text = "Удочку открывать правой кнопкой мыши";
            rightButton.Checked = rodRight; rightButton.SetBounds(20, 248, 570, 28); Controls.Add(rightButton);
            Button gear = MakeButton("2. Записать удочку и наживку · " + (hasGear ? "готово" : "нет"), 20, 282, 330);
            gear.Name = "recordGear";
            gear.Click += delegate { Command = "gear"; DialogResult = DialogResult.OK; Close(); };
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

    // The image is the in-memory region above the minimap, captured by F9.
    // Only the selected binary text mask, not this image, is saved to disk.
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
            Font = new Font("Segoe UI", 9f);
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
