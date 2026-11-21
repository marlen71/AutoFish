using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace RMFish
{
    internal static class Theme
    {
        public static readonly Color Background = Color.FromArgb(6, 24, 26);
        public static readonly Color Sidebar = Color.FromArgb(5, 20, 22);
        public static readonly Color Card = Color.FromArgb(13, 35, 38);
        public static readonly Color Raised = Color.FromArgb(20, 43, 46);
        public static readonly Color Border = Color.FromArgb(34, 63, 64);
        public static readonly Color Text = Color.FromArgb(233, 247, 242);
        public static readonly Color Muted = Color.FromArgb(142, 170, 169);
        public static readonly Color Accent = Color.FromArgb(75, 222, 175);
        public static readonly Color AccentDark = Color.FromArgb(7, 38, 31);
        public static readonly Color Warn = Color.FromArgb(237, 192, 114);

        public static GraphicsPath Round(Rectangle rect, int radius)
        {
            int d = Math.Max(1, Math.Min(radius * 2, Math.Min(rect.Width, rect.Height)));
            GraphicsPath path = new GraphicsPath();
            path.AddArc(rect.X, rect.Y, d, d, 180, 90);
            path.AddArc(rect.Right - d, rect.Y, d, d, 270, 90);
            path.AddArc(rect.Right - d, rect.Bottom - d, d, d, 0, 90);
            path.AddArc(rect.X, rect.Bottom - d, d, d, 90, 90);
            path.CloseFigure();
            return path;
        }

        public static Color ParentColor(Control control)
        {
            SoftCard card = control.Parent as SoftCard;
            return card != null ? card.Fill : control.Parent == null ? Background : control.Parent.BackColor;
        }
    }

    internal class SoftCard : Panel
    {
        public Color Fill = Theme.Card;
        public Color Stroke = Theme.Border;
        public int Radius = 12;

        public SoftCard()
        {
            DoubleBuffered = true;
            SetStyle(ControlStyles.SupportsTransparentBackColor, true);
            BackColor = Theme.Background;
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (SolidBrush background = new SolidBrush(Theme.ParentColor(this)))
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

    internal enum MenuIcon { None, Fish, Settings, Guide, Journal }

    internal class SoftButton : Button
    {
        public Color Fill = Theme.Raised;
        public Color Ink = Theme.Text;
        public Color Border = Theme.Border;
        public bool Selected;
        public bool AlignLeft;
        public MenuIcon IconKind;
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
            e.Graphics.Clear(Theme.ParentColor(this));
            Color fill = Enabled ? Fill : Color.FromArgb(24, 39, 40);
            if (Enabled && hovered) fill = ControlPaint.Light(fill, 0.12f);
            Color ink = Enabled ? Ink : Color.FromArgb(101, 118, 115);
            using (GraphicsPath path = Theme.Round(new Rectangle(0, 0, Math.Max(1, Width - 1), Math.Max(1, Height - 1)), 9))
            using (SolidBrush brush = new SolidBrush(fill))
            using (Pen pen = new Pen(Selected ? Theme.Accent : Border))
            {
                e.Graphics.FillPath(brush, path);
                e.Graphics.DrawPath(pen, path);
            }
            int textLeft = AlignLeft ? (IconKind == MenuIcon.None ? 15 : 42) : 3;
            if (IconKind != MenuIcon.None)
                DrawMenuIcon(e.Graphics, IconKind, new Rectangle(14, (Height - 18) / 2, 18, 18), ink);
            Rectangle textRect = new Rectangle(textLeft, 0, Math.Max(1, Width - textLeft - 5), Height);
            TextFormatFlags flags = TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis |
                (AlignLeft ? TextFormatFlags.Left : TextFormatFlags.HorizontalCenter);
            TextRenderer.DrawText(e.Graphics, Text, Font, textRect, ink, flags);
            if (Focused && ShowFocusCues)
                ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(ClientRectangle, -5, -5), ink, fill);
        }

        private static void DrawMenuIcon(Graphics g, MenuIcon icon, Rectangle r, Color color)
        {
            float x = r.X, y = r.Y;
            using (Pen p = new Pen(color, 1.7f))
            using (SolidBrush b = new SolidBrush(color))
            {
                p.StartCap = p.EndCap = LineCap.Round;
                p.LineJoin = LineJoin.Round;
                if (icon == MenuIcon.Fish)
                {
                    g.DrawEllipse(p, x + 4, y + 4, 11, 9);
                    g.DrawLines(p, new PointF[] { new PointF(x + 5, y + 7), new PointF(x + 1, y + 4),
                        new PointF(x + 1, y + 13), new PointF(x + 5, y + 10) });
                    g.FillEllipse(b, x + 11, y + 7, 2, 2);
                    g.DrawLine(p, x + 8, y + 4, x + 9, y + 2);
                }
                else if (icon == MenuIcon.Settings)
                {
                    g.DrawLine(p, x + 1, y + 4, x + 17, y + 4);
                    g.DrawLine(p, x + 1, y + 9, x + 17, y + 9);
                    g.DrawLine(p, x + 1, y + 14, x + 17, y + 14);
                    g.FillEllipse(b, x + 5, y + 2, 4, 4);
                    g.FillEllipse(b, x + 11, y + 7, 4, 4);
                    g.FillEllipse(b, x + 4, y + 12, 4, 4);
                }
                else if (icon == MenuIcon.Guide)
                {
                    g.DrawLines(p, new PointF[] { new PointF(x + 2, y + 3), new PointF(x + 6, y + 3),
                        new PointF(x + 9, y + 5), new PointF(x + 12, y + 3), new PointF(x + 16, y + 3),
                        new PointF(x + 16, y + 14), new PointF(x + 12, y + 14), new PointF(x + 9, y + 16),
                        new PointF(x + 6, y + 14), new PointF(x + 2, y + 14), new PointF(x + 2, y + 3) });
                    g.DrawLine(p, x + 9, y + 5, x + 9, y + 15);
                }
                else if (icon == MenuIcon.Journal)
                {
                    g.DrawRectangle(p, x + 3, y + 2, 12, 14);
                    g.DrawLine(p, x + 6, y + 6, x + 12, y + 6);
                    g.DrawLine(p, x + 6, y + 9, x + 12, y + 9);
                    g.DrawLine(p, x + 6, y + 12, x + 10, y + 12);
                }
            }
        }
    }

    // A real Button so mouse, keyboard, focus cues and accessibility all work.
    internal sealed class PowerButton : Button
    {
        private bool hovered;
        private bool working;
        public bool Working { get { return working; } set { if (working != value) { working = value; Invalidate(); } } }

        public PowerButton()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            Cursor = Cursors.Hand;
            AccessibleRole = AccessibleRole.PushButton;
            TabStop = true;
        }
        protected override void OnMouseEnter(EventArgs e) { hovered = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hovered = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnPaintBackground(PaintEventArgs e) { }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(Theme.ParentColor(this));
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            int size = Math.Min(Width - 18, Height - 18);
            Rectangle circle = new Rectangle((Width - size) / 2, (Height - size) / 2, size, size);
            Color ring = Enabled ? Theme.Accent : Theme.Muted;
            using (Pen glow = new Pen(Color.FromArgb(20, ring), 8))
                e.Graphics.DrawEllipse(glow, Rectangle.Inflate(circle, 3, 3));
            using (SolidBrush bg = new SolidBrush(hovered || working ? Color.FromArgb(16, 58, 50) : Color.FromArgb(10, 39, 38)))
                e.Graphics.FillEllipse(bg, circle);
            using (Pen outline = new Pen(ring, 2.5f)) e.Graphics.DrawEllipse(outline, circle);
            float cx = Width / 2f, cy = Height / 2f;
            using (Pen symbol = new Pen(Enabled ? Theme.Text : Theme.Muted, 3.1f))
            {
                symbol.StartCap = symbol.EndCap = LineCap.Round;
                e.Graphics.DrawArc(symbol, cx - 11, cy - 9, 22, 22, -45, 270);
                e.Graphics.DrawLine(symbol, cx, cy - 15, cx, cy + 1);
            }
            if (Focused && ShowFocusCues)
                ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(circle, -8, -8), Theme.Text, Theme.Background);
        }
    }

    // The selected node follows the actual state machine; an idle/paused bot
    // has no active node rather than presenting a guessed stage as active.
    internal sealed class StageStrip : Control
    {
        private int activeIndex = -1;
        public int ActiveIndex { get { return activeIndex; } set { if (activeIndex != value) { activeIndex = value; Invalidate(); } } }

        public StageStrip()
        {
            DoubleBuffered = true;
            AccessibleName = "Этапы: заброс, ожидание клёва, вываживание";
            AccessibleRole = AccessibleRole.Graphic;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(Theme.ParentColor(this));
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            int[] centers = { 100, Width / 2, Width - 100 };
            const int y = 25, radius = 20;
            using (Pen line = new Pen(Theme.Border, 2))
            {
                e.Graphics.DrawLine(line, centers[0] + radius, y, centers[1] - radius, y);
                e.Graphics.DrawLine(line, centers[1] + radius, y, centers[2] - radius, y);
            }
            if (activeIndex >= 0 && activeIndex < 2)
            {
                using (Pen line = new Pen(Theme.Accent, 2))
                    e.Graphics.DrawLine(line, centers[activeIndex] + radius, y, centers[activeIndex] + radius + 35, y);
            }
            string[] names = { "Заброс", "Ожидание клёва", "Вываживание" };
            for (int i = 0; i < centers.Length; i++)
            {
                bool active = activeIndex == i;
                Color color = active ? Theme.Accent : Theme.Muted;
                Rectangle circle = new Rectangle(centers[i] - radius, y - radius, radius * 2, radius * 2);
                using (SolidBrush bg = new SolidBrush(Theme.Background)) e.Graphics.FillEllipse(bg, circle);
                using (Pen edge = new Pen(active ? Theme.Accent : Theme.Border, active ? 2 : 1.5f)) e.Graphics.DrawEllipse(edge, circle);
                DrawStageIcon(e.Graphics, i, centers[i], y, color);
                using (Font f = new Font("Segoe UI", 9f, active ? FontStyle.Bold : FontStyle.Regular))
                    TextRenderer.DrawText(e.Graphics, names[i], f, new Rectangle(centers[i] - 100, 51, 200, 24),
                        active ? Theme.Text : Theme.Muted, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPadding);
            }
        }

        private static void DrawStageIcon(Graphics g, int index, int x, int y, Color color)
        {
            using (Pen p = new Pen(color, 1.8f))
            using (SolidBrush brush = new SolidBrush(color))
            {
                p.StartCap = p.EndCap = LineCap.Round;
                p.LineJoin = LineJoin.Round;
                if (index == 0)
                {
                    g.DrawLine(p, x - 8, y + 8, x + 9, y - 9);
                    g.DrawLine(p, x - 8, y + 8, x - 11, y + 10);
                    g.DrawEllipse(p, x - 7, y + 3, 4, 4);
                    g.DrawLine(p, x + 9, y - 9, x + 12, y - 10);
                }
                else if (index == 1)
                {
                    g.DrawLine(p, x, y - 11, x, y + 11);
                    g.FillEllipse(brush, x - 6, y - 5, 12, 12);
                    using (Pen split = new Pen(Theme.Background, 1.5f)) g.DrawLine(split, x - 6, y + 1, x + 6, y + 1);
                }
                else
                {
                    g.DrawEllipse(p, x - 8, y - 8, 16, 16);
                    g.DrawEllipse(p, x - 3, y - 3, 6, 6);
                    g.DrawLine(p, x, y - 11, x, y - 8);
                    g.DrawLine(p, x + 8, y, x + 11, y);
                    g.DrawLine(p, x, y + 8, x, y + 11);
                    g.DrawLine(p, x - 8, y, x - 11, y);
                }
            }
        }
    }

    internal sealed class RodArt : Control
    {
        public RodArt() { DoubleBuffered = true; AccessibleName = "Удочка: выбирается вручную в игре"; AccessibleRole = AccessibleRole.Graphic; }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(Theme.ParentColor(this));
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            float x = 10, y = Height - 18;
            using (Pen rod = new Pen(Color.FromArgb(187, 150, 95), 2.5f))
            using (Pen tip = new Pen(Color.FromArgb(218, 190, 146), 1.3f))
            using (Pen handle = new Pen(Color.FromArgb(218, 176, 112), 5))
            using (Pen reel = new Pen(Color.FromArgb(139, 160, 155), 1.6f))
            {
                rod.StartCap = rod.EndCap = LineCap.Round;
                handle.StartCap = handle.EndCap = LineCap.Round;
                e.Graphics.DrawLine(handle, x + 2, y, x + 32, y - 18);
                e.Graphics.DrawLine(rod, x + 30, y - 17, x + 86, y - 43);
                e.Graphics.DrawLine(tip, x + 86, y - 43, x + 115, y - 52);
                e.Graphics.DrawLine(reel, x + 33, y - 15, x + 38, y - 7);
                e.Graphics.DrawEllipse(reel, x + 34, y - 8, 10, 10);
                e.Graphics.DrawEllipse(reel, x + 37, y - 5, 4, 4);
                e.Graphics.DrawLine(reel, x + 45, y - 3, x + 49, y - 6);
            }
        }
    }

    // Slider value is the actual interval in milliseconds. Right means faster
    // (a smaller interval), and the setting applies on the next start only.
    internal sealed class SpeedSlider : Control
    {
        private const int MinInterval = 35, MaxInterval = 250;
        private int value = MinInterval;
        public event EventHandler ValueChanged;

        public int Value
        {
            get { return value; }
            set
            {
                int next = Math.Max(MinInterval, Math.Min(MaxInterval, value));
                if (this.value == next) return;
                this.value = next;
                AccessibleName = "Интервал ЛКМ при вываживании: " + next + " миллисекунд";
                Invalidate();
                AccessibilityNotifyClients(AccessibleEvents.ValueChange, -1);
                if (ValueChanged != null) ValueChanged(this, EventArgs.Empty);
            }
        }

        public SpeedSlider()
        {
            SetStyle(ControlStyles.Selectable | ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                ControlStyles.OptimizedDoubleBuffer, true);
            TabStop = true;
            Cursor = Cursors.Hand;
            AccessibleRole = AccessibleRole.Slider;
            AccessibleName = "Интервал ЛКМ при вываживании: 35 миллисекунд";
            AccessibleDescription = "Стрелка вправо ускоряет, стрелка влево замедляет; применяется при следующем запуске.";
        }
        protected override bool IsInputKey(Keys keyData)
        {
            Keys key = keyData & Keys.KeyCode;
            if (key == Keys.Left || key == Keys.Right || key == Keys.Up || key == Keys.Down || key == Keys.Home || key == Keys.End) return true;
            return base.IsInputKey(keyData);
        }
        protected override void OnKeyDown(KeyEventArgs e)
        {
            if (e.KeyCode == Keys.Left || e.KeyCode == Keys.Down) { Value += 5; e.Handled = true; }
            else if (e.KeyCode == Keys.Right || e.KeyCode == Keys.Up) { Value -= 5; e.Handled = true; }
            else if (e.KeyCode == Keys.Home) { Value = MaxInterval; e.Handled = true; }
            else if (e.KeyCode == Keys.End) { Value = MinInterval; e.Handled = true; }
            base.OnKeyDown(e);
        }
        protected override void OnMouseDown(MouseEventArgs e)
        {
            base.OnMouseDown(e);
            if (e.Button != MouseButtons.Left) return;
            Focus(); Capture = true; SetFromX(e.X);
        }
        protected override void OnMouseMove(MouseEventArgs e)
        {
            base.OnMouseMove(e);
            if (Capture && e.Button == MouseButtons.Left) SetFromX(e.X);
        }
        protected override void OnMouseUp(MouseEventArgs e)
        {
            base.OnMouseUp(e);
            if (e.Button == MouseButtons.Left) Capture = false;
        }
        private void SetFromX(int x)
        {
            int span = Math.Max(1, Width - 24);
            double ratio = Math.Max(0, Math.Min(1, (x - 12) / (double)span));
            int steps = (int)Math.Round((MaxInterval - MinInterval) * ratio / 5.0);
            Value = MaxInterval - steps * 5;
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(Theme.ParentColor(this));
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            int left = 12, right = Math.Max(left + 1, Width - 12), y = Height / 2;
            int knob = left + (int)Math.Round((right - left) * (MaxInterval - value) / (double)(MaxInterval - MinInterval));
            using (Pen track = new Pen(Theme.Border, 6))
            using (Pen filled = new Pen(Theme.Accent, 6))
            {
                track.StartCap = track.EndCap = LineCap.Round;
                filled.StartCap = filled.EndCap = LineCap.Round;
                e.Graphics.DrawLine(track, left, y, right, y);
                if (knob > left) e.Graphics.DrawLine(filled, left, y, knob, y);
            }
            using (SolidBrush halo = new SolidBrush(Color.FromArgb(45, Theme.Accent)))
                e.Graphics.FillEllipse(halo, knob - 10, y - 10, 20, 20);
            using (SolidBrush handle = new SolidBrush(Theme.Accent))
                e.Graphics.FillEllipse(handle, knob - 7, y - 7, 14, 14);
            using (SolidBrush center = new SolidBrush(Theme.Text))
                e.Graphics.FillEllipse(center, knob - 3, y - 3, 6, 6);
            if (Focused && ShowFocusCues)
                ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(ClientRectangle, -2, -2), Theme.Text, Theme.Background);
        }
    }
}
