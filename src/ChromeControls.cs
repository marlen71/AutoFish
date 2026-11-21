using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace RMFish
{
    internal sealed class WindowHeader : Panel
    {
        private readonly Icon windowIcon;
        public WindowHeader(Icon icon)
        {
            windowIcon = icon;
            DoubleBuffered = true;
            BackColor = Theme.Sidebar;
            AccessibleName = "Заголовок окна RMFish; перетащите для перемещения";
            AccessibleRole = AccessibleRole.TitleBar;
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            e.Graphics.Clear(BackColor);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            if (windowIcon != null) e.Graphics.DrawIcon(windowIcon, new Rectangle(11, 6, 24, 24));
            using (Font title = new Font("Segoe UI", 9.5f, FontStyle.Bold))
                TextRenderer.DrawText(e.Graphics, "RMFish", title, new Rectangle(43, 0, 78, Height), Theme.Text,
                    TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.NoPadding);
            using (Font caption = new Font("Segoe UI", 7.5f, FontStyle.Regular))
                TextRenderer.DrawText(e.Graphics, "АВТОРЫБАЛКА  /  RMRP", caption, new Rectangle(122, 0, 260, Height), Theme.Muted,
                    TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.NoPadding);
            using (Pen line = new Pen(Theme.Border)) e.Graphics.DrawLine(line, 0, Height - 1, Width, Height - 1);
        }
        protected override void OnMouseDown(MouseEventArgs e)
        {
            base.OnMouseDown(e);
            if (e.Button != MouseButtons.Left) return;
            Form form = FindForm();
            if (form == null || form.WindowState != FormWindowState.Normal) return;
            // Ask Windows to perform the normal window move. Emergency key
            // polling stays on its independent thread during the move loop.
            WindowsNative.ReleaseCapture();
            WindowsNative.SendMessage(form.Handle, 0x00A1, new IntPtr(2), IntPtr.Zero); // WM_NCLBUTTONDOWN / HTCAPTION
        }
    }

    internal enum WindowAction { Minimize, Close }

    internal sealed class WindowButton : Button
    {
        private readonly WindowAction action;
        private bool hovered;
        public WindowButton(WindowAction action)
        {
            this.action = action;
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            Cursor = Cursors.Hand;
            AccessibleRole = AccessibleRole.PushButton;
            AccessibleName = action == WindowAction.Close ? "Закрыть RMFish" : "Свернуть RMFish";
            TabStop = true;
        }
        protected override void OnMouseEnter(EventArgs e) { hovered = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hovered = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnPaintBackground(PaintEventArgs e) { }
        protected override void OnPaint(PaintEventArgs e)
        {
            Color background = hovered ? (action == WindowAction.Close ? Color.FromArgb(112, 49, 49) : Theme.Raised) : Theme.Sidebar;
            e.Graphics.Clear(background);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            int cx = Width / 2, cy = Height / 2;
            using (Pen p = new Pen(hovered ? Theme.Text : Theme.Muted, 1.7f))
            {
                p.StartCap = p.EndCap = LineCap.Round;
                if (action == WindowAction.Minimize) e.Graphics.DrawLine(p, cx - 5, cy + 3, cx + 5, cy + 3);
                else
                {
                    e.Graphics.DrawLine(p, cx - 5, cy - 5, cx + 5, cy + 5);
                    e.Graphics.DrawLine(p, cx + 5, cy - 5, cx - 5, cy + 5);
                }
            }
            if (Focused && ShowFocusCues)
                ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(ClientRectangle, -4, -4), Theme.Text, background);
        }
    }

    internal sealed class NumberStepButton : Button
    {
        private readonly bool increase;
        private bool hovered;
        public NumberStepButton(bool increase)
        {
            this.increase = increase;
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            Cursor = Cursors.Hand;
            TabStop = false; // The editable field supports Up and Down too.
            AccessibleRole = AccessibleRole.PushButton;
        }
        protected override void OnMouseEnter(EventArgs e) { hovered = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hovered = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnPaintBackground(PaintEventArgs e) { }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(Theme.Raised);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            if (hovered)
            {
                using (GraphicsPath path = Theme.Round(Rectangle.Inflate(ClientRectangle, -2, -2), 5))
                using (SolidBrush fill = new SolidBrush(Theme.Border)) e.Graphics.FillPath(fill, path);
            }
            using (Pen pen = new Pen(hovered ? Theme.Accent : Theme.Muted, 1.6f))
            {
                pen.StartCap = pen.EndCap = LineCap.Round;
                int x = Width / 2, y = Height / 2;
                e.Graphics.DrawLine(pen, x - 4, y, x + 4, y);
                if (increase) e.Graphics.DrawLine(pen, x, y - 4, x, y + 4);
            }
        }
    }

    // Editable like the old numeric field, but without native up/down arrows.
    // Pending text is committed before a start, including a hotkey start.
    internal sealed class DarkNumberInput : UserControl
    {
        private readonly int minimum, maximum, increment;
        private int current;
        private bool updatingText;
        private readonly TextBox editor;
        private readonly NumberStepButton minus, plus;
        public event EventHandler ValueChanged;
        public int Minimum { get { return minimum; } }
        public int Maximum { get { return maximum; } }
        public int Increment { get { return increment; } }
        public TextBox Editor { get { return editor; } }
        public int Value { get { return current; } set { SetValue(value, true); } }

        public DarkNumberInput(int minimum, int maximum, int increment)
        {
            if (minimum > maximum || increment < 1) throw new ArgumentOutOfRangeException("minimum");
            this.minimum = minimum; this.maximum = maximum; this.increment = increment;
            current = minimum;
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            BackColor = Theme.Raised;
            AccessibleRole = AccessibleRole.SpinButton;
            Font = new Font("Segoe UI", 9.5f, FontStyle.Regular);
            minus = new NumberStepButton(false);
            plus = new NumberStepButton(true);
            editor = new TextBox();
            editor.Name = "numberEditor";
            minus.Name = "decrease";
            plus.Name = "increase";
            editor.BorderStyle = BorderStyle.None;
            editor.BackColor = Theme.Raised;
            editor.ForeColor = Theme.Text;
            editor.Font = Font;
            editor.TextAlign = HorizontalAlignment.Center;
            editor.Text = current.ToString();
            editor.TextChanged += delegate
            {
                if (updatingText) return;
                int parsed;
                if (Int32.TryParse(editor.Text, out parsed) && parsed >= minimum && parsed <= maximum)
                    SetValue(parsed, false);
            };
            editor.KeyPress += delegate(object sender, KeyPressEventArgs e)
            {
                if (!Char.IsControl(e.KeyChar) && !Char.IsDigit(e.KeyChar)) e.Handled = true;
            };
            editor.KeyDown += delegate(object sender, KeyEventArgs e)
            {
                if (e.KeyCode == Keys.Up || e.KeyCode == Keys.Down)
                {
                    CommitEdit();
                    Value = current + (e.KeyCode == Keys.Up ? increment : -increment);
                    e.SuppressKeyPress = true;
                }
                else if (e.KeyCode == Keys.Enter) { CommitEdit(); e.SuppressKeyPress = true; }
            };
            editor.Enter += delegate { Invalidate(); };
            editor.Leave += delegate { CommitEdit(); Invalidate(); };
            minus.Click += delegate { CommitEdit(); Value = current - increment; };
            plus.Click += delegate { CommitEdit(); Value = current + increment; };
            Controls.Add(minus); Controls.Add(plus); Controls.Add(editor);
            Size = new Size(112, 30);
            ArrangeChildren();
        }

        public void SetAccessibleLabel(string label)
        {
            AccessibleName = label;
            editor.AccessibleName = label;
            editor.AccessibleDescription = "Введите число или используйте стрелки вверх и вниз.";
            minus.AccessibleName = "Уменьшить: " + label;
            plus.AccessibleName = "Увеличить: " + label;
        }
        public void CommitEdit()
        {
            int parsed;
            Value = Int32.TryParse(editor.Text, out parsed) ? parsed : current;
        }
        private void SetValue(int requested, bool updateText)
        {
            int next = Math.Max(minimum, Math.Min(maximum, requested));
            bool changed = next != current;
            current = next;
            if (updateText && editor != null && editor.Text != next.ToString())
            {
                updatingText = true;
                try { editor.Text = next.ToString(); }
                finally { updatingText = false; }
            }
            if (changed && ValueChanged != null) ValueChanged(this, EventArgs.Empty);
        }
        protected override void OnResize(EventArgs e) { base.OnResize(e); ArrangeChildren(); }
        private void ArrangeChildren()
        {
            if (editor == null || minus == null || plus == null) return;
            int height = Math.Max(1, Height - 4);
            minus.SetBounds(2, 2, 27, height);
            plus.SetBounds(Math.Max(30, Width - 29), 2, 27, height);
            editor.SetBounds(30, Math.Max(2, (Height - editor.PreferredHeight) / 2), Math.Max(1, Width - 60), editor.PreferredHeight);
        }
        protected override void OnPaintBackground(PaintEventArgs e)
        {
            e.Graphics.Clear(Theme.ParentColor(this));
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (GraphicsPath path = Theme.Round(new Rectangle(0, 0, Math.Max(1, Width - 1), Math.Max(1, Height - 1)), 7))
            using (SolidBrush fill = new SolidBrush(Theme.Raised))
            using (Pen edge = new Pen(ContainsFocus ? Theme.Accent : Theme.Border))
            {
                e.Graphics.FillPath(fill, path);
                e.Graphics.DrawPath(edge, path);
            }
        }
    }

    internal sealed class DarkToggle : CheckBox
    {
        public DarkToggle()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            Cursor = Cursors.Hand;
            AutoSize = false;
            AccessibleRole = AccessibleRole.CheckButton;
        }
        protected override void OnCheckedChanged(EventArgs e) { Invalidate(); base.OnCheckedChanged(e); }
        protected override void OnPaintBackground(PaintEventArgs e) { }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(Theme.ParentColor(this));
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            Rectangle track = new Rectangle(1, (Height - 20) / 2, 36, 20);
            using (GraphicsPath path = Theme.Round(track, 10))
            using (SolidBrush fill = new SolidBrush(Checked ? Theme.Accent : Theme.Border)) e.Graphics.FillPath(fill, path);
            int x = Checked ? track.Right - 17 : track.X + 3;
            using (SolidBrush thumb = new SolidBrush(Checked ? Theme.AccentDark : Theme.Muted))
                e.Graphics.FillEllipse(thumb, x, track.Y + 3, 14, 14);
            TextRenderer.DrawText(e.Graphics, Text, Font, new Rectangle(48, 0, Math.Max(1, Width - 50), Height),
                Enabled ? Theme.Text : Theme.Muted, TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.EndEllipsis);
            if (Focused && ShowFocusCues)
                ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(ClientRectangle, -2, -2), Theme.Text, Theme.ParentColor(this));
        }
    }

    // A normal selectable, copyable read-only edit control, with the native
    // scrollbar hidden and a small themed scrollbar driving EM_LINESCROLL.
    internal sealed class DarkLogBox : UserControl
    {
        private const int GetLineCountMessage = 0x00BA, GetFirstLineMessage = 0x00CE, LineScrollMessage = 0x00B6;
        private readonly LogTextBox editor;
        private readonly LogScrollBar scrollBar;
        private bool updating, pendingTail = true;
        public TextBox Editor { get { return editor; } }
        public int FirstVisibleLine { get { return editor.IsHandleCreated ? Query(GetFirstLineMessage) : 0; } }
        public int LineCount { get { return editor.IsHandleCreated ? Math.Max(1, Query(GetLineCountMessage)) : 1; } }
        public int VisibleLines { get { return Math.Max(1, (editor.ClientSize.Height - 3) / Math.Max(1, editor.Font.Height)); } }
        public int MaximumFirstLine { get { return Math.Max(0, LineCount - VisibleLines); } }

        public DarkLogBox()
        {
            BackColor = Theme.Card;
            AccessibleName = "Журнал событий";
            editor = new LogTextBox(this);
            editor.Name = "eventLogText";
            editor.AccessibleName = "Журнал событий";
            editor.Multiline = true;
            editor.ReadOnly = true;
            editor.WordWrap = true;
            editor.ScrollBars = ScrollBars.None;
            editor.HideSelection = false;
            editor.BorderStyle = BorderStyle.None;
            editor.BackColor = Theme.Card;
            editor.ForeColor = Theme.Muted;
            editor.Font = new Font("Consolas", 9f);
            editor.TabStop = true;
            scrollBar = new LogScrollBar(this);
            scrollBar.Name = "eventLogScroll";
            Controls.Add(editor); Controls.Add(scrollBar);
            Size = new Size(694, 185);
            ArrangeChildren();
        }
        protected override void OnResize(EventArgs e) { base.OnResize(e); ArrangeChildren(); }
        private void ArrangeChildren()
        {
            if (editor == null || scrollBar == null) return;
            editor.SetBounds(0, 0, Math.Max(1, Width - 20), Height);
            scrollBar.SetBounds(Math.Max(0, Width - 12), 0, 12, Height);
            UpdateMetrics();
        }
        protected override void OnVisibleChanged(EventArgs e)
        {
            base.OnVisibleChanged(e);
            if (Visible && pendingTail && IsHandleCreated)
            {
                BeginInvoke((MethodInvoker)delegate
                {
                    if (!IsDisposed && Visible && pendingTail) { pendingTail = false; ScrollToLine(Int32.MaxValue); }
                });
            }
        }
        public void SetContent(string content)
        {
            content = content ?? "";
            if (editor.Text == content) return;
            bool hadHandle = editor.IsHandleCreated;
            int first = hadHandle ? FirstVisibleLine : 0;
            bool follow = !hadHandle || first >= MaximumFirstLine - 1;
            int start = editor.SelectionStart, length = editor.SelectionLength;
            updating = true;
            try
            {
                editor.Text = content;
                int safeStart = Math.Min(start, editor.TextLength);
                editor.Select(safeStart, Math.Min(length, editor.TextLength - safeStart));
            }
            finally { updating = false; }
            if (hadHandle) ScrollToLine(follow ? Int32.MaxValue : first);
            else pendingTail = true;
        }
        private int Query(int message)
        {
            return WindowsNative.SendMessage(editor.Handle, message, IntPtr.Zero, IntPtr.Zero).ToInt32();
        }
        public void ScrollToLine(int target)
        {
            if (!editor.IsHandleCreated) { pendingTail = true; return; }
            int current = FirstVisibleLine;
            int desired = Math.Max(0, Math.Min(MaximumFirstLine, target));
            if (desired != current)
                WindowsNative.SendMessage(editor.Handle, LineScrollMessage, IntPtr.Zero, new IntPtr(desired - current));
            UpdateMetrics();
        }
        public void ScrollByLines(int amount)
        {
            long target = (long)FirstVisibleLine + amount;
            ScrollToLine((int)Math.Max(0L, Math.Min((long)Int32.MaxValue, target)));
        }
        internal void UpdateMetrics()
        {
            if (updating || scrollBar == null || editor == null) return;
            scrollBar.Invalidate();
        }
    }

    internal sealed class LogTextBox : TextBox
    {
        private readonly DarkLogBox owner;
        public LogTextBox(DarkLogBox owner) { this.owner = owner; }
        protected override void WndProc(ref Message m)
        {
            const int MouseWheel = 0x020A, KeyUp = 0x0101, LeftButtonUp = 0x0202, VScroll = 0x0115;
            if (m.Msg == MouseWheel)
            {
                int delta = (short)((m.WParam.ToInt64() >> 16) & 0xffff);
                if (delta != 0 && owner != null) owner.ScrollByLines(-(delta / 120) * 3);
                m.Result = IntPtr.Zero;
                return;
            }
            base.WndProc(ref m);
            if (owner != null && (m.Msg == KeyUp || m.Msg == LeftButtonUp || m.Msg == VScroll)) owner.UpdateMetrics();
        }
    }

    internal sealed class LogScrollBar : Control
    {
        private readonly DarkLogBox owner;
        private bool dragging;
        private int dragOffset;
        public LogScrollBar(DarkLogBox owner)
        {
            this.owner = owner;
            DoubleBuffered = true;
            Cursor = Cursors.Hand;
            TabStop = false;
            AccessibleName = "Прокрутка журнала";
            AccessibleRole = AccessibleRole.ScrollBar;
        }
        private Rectangle Thumb()
        {
            int track = Math.Max(1, Height - 8);
            int total = owner.LineCount, visible = owner.VisibleLines, max = owner.MaximumFirstLine;
            if (max <= 0) return Rectangle.Empty;
            int h = Math.Min(track, Math.Max(18, (int)Math.Round(track * visible / (double)total)));
            int y = 4 + (int)Math.Round((track - h) * Math.Min(max, owner.FirstVisibleLine) / (double)max);
            return new Rectangle(4, y, 4, h);
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(Theme.Card);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (Pen track = new Pen(Theme.Border, 4))
            {
                track.StartCap = track.EndCap = LineCap.Round;
                e.Graphics.DrawLine(track, Width / 2, 5, Width / 2, Math.Max(5, Height - 5));
            }
            Rectangle thumb = Thumb();
            if (!thumb.IsEmpty)
                using (GraphicsPath path = Theme.Round(thumb, 2))
                using (SolidBrush fill = new SolidBrush(dragging ? Theme.Accent : Theme.Muted)) e.Graphics.FillPath(fill, path);
        }
        protected override void OnMouseDown(MouseEventArgs e)
        {
            base.OnMouseDown(e);
            if (e.Button != MouseButtons.Left) return;
            Rectangle thumb = Thumb();
            if (thumb.IsEmpty) return;
            dragging = true; Capture = true;
            dragOffset = thumb.Contains(e.Location) ? e.Y - thumb.Y : thumb.Height / 2;
            ScrollFromY(e.Y); Invalidate();
        }
        protected override void OnMouseMove(MouseEventArgs e)
        {
            base.OnMouseMove(e);
            if (dragging) ScrollFromY(e.Y);
        }
        protected override void OnMouseUp(MouseEventArgs e)
        {
            base.OnMouseUp(e);
            if (e.Button == MouseButtons.Left) { dragging = false; Capture = false; Invalidate(); }
        }
        protected override void OnMouseWheel(MouseEventArgs e)
        {
            base.OnMouseWheel(e);
            owner.ScrollByLines(-(e.Delta / 120) * 3);
        }
        private void ScrollFromY(int y)
        {
            Rectangle thumb = Thumb();
            int span = Math.Max(1, Height - 8 - thumb.Height);
            double ratio = Math.Max(0, Math.Min(1, (y - dragOffset - 4) / (double)span));
            owner.ScrollToLine((int)Math.Round(ratio * owner.MaximumFirstLine));
        }
    }
}
