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
        private readonly CheckBox enabled, rightButton;
        public string Command { get; private set; }
        public bool AutoEnabled { get { return enabled.Checked; } }
        public bool RodRightButton { get { return rightButton.Checked; } }

        public RelocationSetupForm(bool autoEnabled, bool rodRight, bool hasNotice, bool hasGear)
        {
            Text = "RMFish — автоотход"; StartPosition = FormStartPosition.CenterParent;
            FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false; MinimizeBox = false;
            ClientSize = new Size(620, 450); BackColor = Theme.Background; ForeColor = Theme.Text;
            Font = new Font("Segoe UI", 9f);
            Label title = new Label(); title.Text = "Автоотход при окончании рыбы"; title.SetBounds(18, 14, 570, 28);
            title.Font = new Font("Segoe UI", 12f, FontStyle.Bold); Controls.Add(title);
            enabled = new CheckBox(); enabled.Name = "relocationEnabled";
            enabled.Text = "Включить автоотход (по умолчанию выключен)";
            enabled.Checked = autoEnabled; enabled.SetBounds(20, 50, 570, 27); Controls.Add(enabled);
            Label warning = new Label(); warning.SetBounds(20, 83, 580, 78);
            warning.ForeColor = Theme.Warn;
            warning.Text = "Только под наблюдением: один пробел, S на 7 с и W на 7 с. Из-за препятствий, камеры и задержек точный возврат не гарантируется. Фокус или F10 прервёт маршрут без повтора.";
            Controls.Add(warning);
            Label steps = new Label(); steps.SetBounds(20, 168, 580, 57);
            steps.Text = "Для работы нужны два образца при одинаковом разрешении: точная надпись об окончании рыбы и три элемента инвентаря. Пока их нет, запуск с автоотходом заблокирован.";
            Controls.Add(steps);
            Button notice = MakeButton("1. Записать уведомление · " + (hasNotice ? "готово" : "нет"), 20, 235, 330);
            notice.Name = "recordNotice";
            notice.Click += delegate { Command = "notice"; DialogResult = DialogResult.OK; Close(); };
            rightButton = new CheckBox(); rightButton.Name = "rodRightButton";
            rightButton.Text = "Удочку открывать правой кнопкой мыши";
            rightButton.Checked = rodRight; rightButton.SetBounds(20, 282, 570, 28); Controls.Add(rightButton);
            Button gear = MakeButton("2. Записать удочку и наживку · " + (hasGear ? "готово" : "нет"), 20, 315, 330);
            gear.Name = "recordGear";
            gear.Click += delegate { Command = "gear"; DialogResult = DialogResult.OK; Close(); };
            Label hint = new Label(); hint.SetBounds(20, 359, 580, 35); hint.ForeColor = Theme.Muted;
            hint.Text = "При записи переключитесь в игру и следуйте инструкции F9. При несовпадении элемента клики остановятся.";
            Controls.Add(hint);
            Button save = MakeButton("Сохранить и закрыть", 20, 400, 190);
            save.Name = "saveRelocation";
            save.Click += delegate { Command = "save"; DialogResult = DialogResult.OK; Close(); };
            Button cancel = MakeButton("Отмена", 218, 400, 115);
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
