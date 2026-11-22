using System;
using System.Drawing;
using System.Diagnostics;
using System.Collections.Generic;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using RMFish;

namespace RMacro
{
    internal static class SupportLink
    {
        public const string Url = "https://discord.gg/jVKudmmBbA";
        // Injectable in the GUI smoke test; production always opens the fixed URL.
        internal static Action<string> Launcher = delegate(string url)
        { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); };
        public static void Open() { Launcher(Url); }
    }

    internal sealed class LoaderHeader : Panel
    {
        private Image logo;
        public LoaderHeader()
        {
            DoubleBuffered = true; BackColor = Theme.Sidebar;
            AccessibleRole = AccessibleRole.TitleBar;
            AccessibleName = "Заголовок Eternal Core; перетащите для перемещения";
            try
            {
                using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("EternalCore.Icon.png"))
                using (Image image = stream == null ? null : Image.FromStream(stream))
                    if (image != null) logo = new Bitmap(image);
            }
            catch (Exception) { }
        }
        protected override void Dispose(bool disposing)
        {
            if (disposing && logo != null) { logo.Dispose(); logo = null; }
            base.Dispose(disposing);
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            e.Graphics.Clear(BackColor);
            if (logo != null) e.Graphics.DrawImage(logo, new Rectangle(12, 5, 36, 36));
            using (Font brand = new Font("Segoe UI", 13f, FontStyle.Bold))
            {
                TextRenderer.DrawText(e.Graphics, "ETERNAL", brand, new Rectangle(54, 0, 91, Height), Theme.Text,
                    TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPadding);
                TextRenderer.DrawText(e.Graphics, "CORE", brand, new Rectangle(145, 0, 62, Height), Theme.Accent,
                    TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPadding);
            }
            using (Font caption = new Font("Segoe UI", 7.3f, FontStyle.Bold))
                TextRenderer.DrawText(e.Graphics, "ИГРЫ  /  МАКРОСЫ  /  ПОДПИСКИ", caption, new Rectangle(244, 0, 320, Height), Theme.Muted,
                    TextFormatFlags.VerticalCenter | TextFormatFlags.NoPadding);
            using (Pen line = new Pen(Theme.Border)) e.Graphics.DrawLine(line, 0, Height - 1, Width, Height - 1);
        }
        protected override void OnMouseDown(MouseEventArgs e)
        {
            base.OnMouseDown(e);
            Form form = FindForm();
            if (e.Button != MouseButtons.Left || form == null || form.WindowState != FormWindowState.Normal) return;
            WindowsNative.ReleaseCapture();
            WindowsNative.SendMessage(form.Handle, 0x00A1, new IntPtr(2), IntPtr.Zero);
        }
    }

    internal sealed class HeroPanel : Panel
    {
        private Image logo;
        public HeroPanel()
        {
            DoubleBuffered = true; BackColor = Theme.Sidebar;
            try
            {
                using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("EternalCore.Logo.png"))
                using (Image image = stream == null ? null : Image.FromStream(stream))
                    if (image != null) logo = new Bitmap(image);
            }
            catch (Exception) { }
        }
        protected override void Dispose(bool disposing)
        {
            if (disposing && logo != null) { logo.Dispose(); logo = null; }
            base.Dispose(disposing);
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            Graphics g = e.Graphics; g.SmoothingMode = SmoothingMode.AntiAlias;
            using (LinearGradientBrush bg = new LinearGradientBrush(ClientRectangle,
                Color.FromArgb(18, 23, 40), Color.FromArgb(12, 12, 22), LinearGradientMode.ForwardDiagonal))
                g.FillRectangle(bg, ClientRectangle);
            using (Pen edge = new Pen(Theme.Border)) g.DrawLine(edge, Width - 1, 0, Width - 1, Height);
            using (SolidBrush accent = new SolidBrush(Theme.Accent)) g.FillEllipse(accent, 38, 35, 7, 7);
            using (Font mini = new Font("Segoe UI", 8f, FontStyle.Bold))
                TextRenderer.DrawText(g, "ТВОЁ ЕДИНОЕ ПРОСТРАНСТВО", mini, new Rectangle(53, 27, 300, 24),
                    Theme.Muted, TextFormatFlags.VerticalCenter | TextFormatFlags.NoPadding);
            if (logo != null) g.DrawImage(logo, new Rectangle(80, 62, 260, 268));
            using (Font headline = new Font("Segoe UI", 24f, FontStyle.Bold))
            {
                TextRenderer.DrawText(g, "Больше, чем", headline, new Rectangle(35, 348, 375, 45), Theme.Text,
                    TextFormatFlags.NoPadding | TextFormatFlags.VerticalCenter);
                TextRenderer.DrawText(g, "просто игра.", headline, new Rectangle(35, 390, 375, 45), Theme.Accent,
                    TextFormatFlags.NoPadding | TextFormatFlags.VerticalCenter);
            }
            using (Font body = new Font("Segoe UI", 10f))
                TextRenderer.DrawText(g, "Игры, макросы и подписки —\nв одном месте.", body,
                    new Rectangle(38, 454, 330, 54), Theme.Muted, TextFormatFlags.WordBreak | TextFormatFlags.NoPadding);
            using (Pen line = new Pen(Theme.Border)) g.DrawLine(line, 38, 540, 380, 540);
            using (Font small = new Font("Segoe UI", 8f, FontStyle.Bold))
                TextRenderer.DrawText(g, "ETERNAL CORE  ·  RELEASE V1", small, new Rectangle(38, 552, 300, 23), Theme.Muted, TextFormatFlags.NoPadding);
        }
    }

    internal sealed class DarkField : Panel
    {
        public readonly TextBox Editor;
        public DarkField(string accessibleName, bool secret)
        {
            DoubleBuffered = true; BackColor = Theme.Raised;
            Editor = new TextBox(); Editor.Name = "editor"; Editor.BorderStyle = BorderStyle.None;
            Editor.BackColor = Color.FromArgb(16, 18, 31); Editor.ForeColor = Theme.Text;
            Editor.Font = new Font("Segoe UI", 10f); Editor.UseSystemPasswordChar = secret;
            Editor.AccessibleName = accessibleName; Editor.Margin = Padding.Empty;
            Editor.Enter += delegate { Invalidate(); }; Editor.Leave += delegate { Invalidate(); };
            Controls.Add(Editor);
        }
        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            if (Editor != null) Editor.SetBounds(13, Math.Max(2, (Height - Editor.PreferredHeight) / 2), Math.Max(1, Width - 26), Editor.PreferredHeight);
        }
        protected override void OnPaintBackground(PaintEventArgs e)
        {
            e.Graphics.Clear(Parent == null ? Theme.Background : Parent.BackColor);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (GraphicsPath path = Theme.Round(new Rectangle(0, 0, Math.Max(1, Width - 1), Math.Max(1, Height - 1)), 8))
            using (SolidBrush fill = new SolidBrush(Color.FromArgb(16, 18, 31)))
            using (Pen edge = new Pen(ContainsFocus ? Theme.Accent : Theme.Border))
            { e.Graphics.FillPath(fill, path); e.Graphics.DrawPath(edge, path); }
        }
    }

    internal sealed class CatalogEntry
    {
        public string Code, Title, Subtitle;
        public bool Highlight;
    }

    // A compact, keyboard- and wheel-accessible list with its own dark chrome;
    // no standard Windows scrollbar is shown in the loader.
    internal sealed class CatalogList : Control
    {
        private const int RowHeight = 48;
        private List<CatalogEntry> items = new List<CatalogEntry>();
        private int selected = -1, first;
        public event EventHandler SelectionChanged;
        public string EmptyText = "Пока ничего нет.";
        public int Count { get { return items.Count; } }
        public string SelectedCode { get { return selected < 0 || selected >= items.Count ? null : items[selected].Code; } }

        public CatalogList()
        {
            DoubleBuffered = true; BackColor = Theme.Card; ForeColor = Theme.Text;
            TabStop = true; Cursor = Cursors.Hand; AccessibleRole = AccessibleRole.List;
        }
        public void SetItems(List<CatalogEntry> entries, string selectedCode)
        {
            string previous = SelectedCode;
            items = entries ?? new List<CatalogEntry>(); selected = -1;
            for (int i = 0; i < items.Count; i++) if (items[i].Code == selectedCode) { selected = i; break; }
            if (selected < 0 && items.Count > 0) selected = 0;
            if (previous != SelectedCode) EnsureVisible();
            else first = Math.Max(0, Math.Min(first, Math.Max(0, items.Count - VisibleCount)));
            Invalidate();
        }
        private int VisibleCount { get { return Math.Max(1, Height / RowHeight); } }
        private void EnsureVisible()
        {
            first = Math.Max(0, Math.Min(first, Math.Max(0, items.Count - VisibleCount)));
            if (selected >= 0 && selected < first) first = selected;
            if (selected >= first + VisibleCount) first = selected - VisibleCount + 1;
        }
        public void SelectCode(string code)
        {
            for (int i = 0; i < items.Count; i++) if (items[i].Code == code) { SelectIndex(i); return; }
        }
        private void SelectIndex(int index)
        {
            if (!Enabled || index < 0 || index >= items.Count || index == selected) return;
            selected = index; EnsureVisible(); Invalidate();
            EventHandler handler = SelectionChanged; if (handler != null) handler(this, EventArgs.Empty);
        }
        protected override bool IsInputKey(Keys keyData)
        {
            Keys key = keyData & Keys.KeyCode;
            if (key == Keys.Up || key == Keys.Down || key == Keys.Home || key == Keys.End || key == Keys.PageUp || key == Keys.PageDown) return true;
            return base.IsInputKey(keyData);
        }
        protected override void OnKeyDown(KeyEventArgs e)
        {
            base.OnKeyDown(e);
            if (e.KeyCode == Keys.Up) SelectIndex(Math.Max(0, selected - 1));
            else if (e.KeyCode == Keys.Down) SelectIndex(Math.Min(items.Count - 1, selected + 1));
            else if (e.KeyCode == Keys.Home) SelectIndex(0);
            else if (e.KeyCode == Keys.End) SelectIndex(items.Count - 1);
            else if (e.KeyCode == Keys.PageUp) SelectIndex(Math.Max(0, selected - VisibleCount));
            else if (e.KeyCode == Keys.PageDown) SelectIndex(Math.Min(items.Count - 1, selected + VisibleCount));
            else return;
            e.Handled = true;
        }
        protected override void OnMouseDown(MouseEventArgs e)
        {
            base.OnMouseDown(e); if (e.Button != MouseButtons.Left) return;
            Focus(); SelectIndex(first + e.Y / RowHeight);
        }
        protected override void OnMouseWheel(MouseEventArgs e)
        {
            base.OnMouseWheel(e);
            if (!Enabled || items.Count <= VisibleCount || e.Delta == 0) return;
            int direction = e.Delta > 0 ? -1 : 1;
            first = Math.Max(0, Math.Min(items.Count - VisibleCount, first + direction * Math.Max(1, Math.Abs(e.Delta) / 120)));
            Invalidate();
        }
        protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
        protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }
        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e); e.Graphics.Clear(BackColor); e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            if (items.Count == 0)
            {
                using (Font empty = new Font("Segoe UI", 8.7f))
                    TextRenderer.DrawText(e.Graphics, EmptyText, empty, new Rectangle(15, 8, Width - 30, Height - 16), Theme.Muted,
                        TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.WordBreak | TextFormatFlags.NoPadding);
                return;
            }
            using (Font title = new Font("Segoe UI", 9.4f, FontStyle.Bold))
            using (Font subtitle = new Font("Segoe UI", 7.7f))
            for (int row = 0; row < VisibleCount && first + row < items.Count; row++)
            {
                int index = first + row; CatalogEntry item = items[index];
                Rectangle bounds = new Rectangle(5, row * RowHeight + 3, Math.Max(1, Width - 18), RowHeight - 5);
                bool current = index == selected;
                if (current)
                {
                    using (GraphicsPath path = Theme.Round(bounds, 7))
                    using (SolidBrush fill = new SolidBrush(Color.FromArgb(27, 40, 62)))
                    using (Pen edge = new Pen(Focused ? Theme.Accent : Color.FromArgb(56, 95, 128)))
                    { e.Graphics.FillPath(fill, path); e.Graphics.DrawPath(edge, path); }
                }
                using (SolidBrush dot = new SolidBrush(item.Highlight ? Theme.Accent : Theme.Muted))
                    e.Graphics.FillEllipse(dot, bounds.X + 10, bounds.Y + 18, 7, 7);
                TextRenderer.DrawText(e.Graphics, item.Title ?? "", title, new Rectangle(bounds.X + 26, bounds.Y + 5, bounds.Width - 34, 19),
                    Theme.Text, TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding | TextFormatFlags.SingleLine);
                TextRenderer.DrawText(e.Graphics, item.Subtitle ?? "", subtitle, new Rectangle(bounds.X + 26, bounds.Y + 24, bounds.Width - 34, 15),
                    Theme.Muted, TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding | TextFormatFlags.SingleLine);
            }
            if (items.Count > VisibleCount)
            {
                int track = Height - 12, thumb = Math.Max(16, track * VisibleCount / items.Count);
                int y = 6 + (track - thumb) * first / Math.Max(1, items.Count - VisibleCount);
                using (Pen rail = new Pen(Theme.Border, 3)) e.Graphics.DrawLine(rail, Width - 6, 6, Width - 6, Height - 6);
                using (Pen bar = new Pen(Theme.Muted, 3)) e.Graphics.DrawLine(bar, Width - 6, y, Width - 6, y + thumb);
            }
        }
    }

    internal sealed class LoaderForm : Form
    {
        private readonly string localDirectory, device, serverAddress;
        private readonly SessionStore store;
        private readonly System.Windows.Forms.Timer clockTimer = new System.Windows.Forms.Timer();
        private readonly System.Windows.Forms.Timer refreshTimer = new System.Windows.Forms.Timer();
        private readonly System.Windows.Forms.Timer drainTimer = new System.Windows.Forms.Timer();
        private Panel loginPage, dashboardPage, workspacePage, profilePage, sidebar;
        private DarkField usernameField, passwordField, keyField, oldPasswordField, newPasswordField, confirmPasswordField;
        private CatalogList gameList, macroList;
        private string selectedGameCode, selectedProductCode, pendingActivationKey, pendingActivationId;
        private DarkToggle remember;
        private SoftButton loginButton, launchButton, navProducts, navProfile, activateButton, changePasswordButton;
        private PowerButton productPower;
        private Label loginMessage, sessionNote, accountName, productState, uidValue, remainingValue, expiresValue;
        private Label statusTitle, statusDescription, warningText, connectionText, profileUser, profileUid, keyMessage, passwordMessage;
        private SoftCard warningCard;
        private DarkLogBox profileList;
        private ApiClient api;
        private string token, persistentNotice;
        private Profile profile;
        private MainForm fishForm, drainingFish;
        private ProductLease lease;
        private Mutex fishMutex;
        private bool ownsFishMutex, busy, refreshing, closing;
        private int generation, profileRevision;

        public LoaderForm(string localDirectory, string device, string serverAddress)
        {
            this.localDirectory = localDirectory; this.device = device;
            this.serverAddress = new ApiClient(serverAddress).BaseUrl;
            store = new SessionStore(localDirectory);
            Text = "Eternal Core — ваши продукты";
            Name = "loaderForm"; FormBorderStyle = FormBorderStyle.None; StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(982, 650); MinimizeBox = true; MaximizeBox = false; ShowInTaskbar = true;
            DoubleBuffered = true; BackColor = Theme.Accent; ForeColor = Theme.Text;
            Font = new Font("Segoe UI", 9f); AutoScaleMode = AutoScaleMode.Font;
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch (Exception) { }
            BuildChrome(); BuildLogin(); BuildDashboard();
            ShowLogin("");
            clockTimer.Interval = 1000;
            clockTimer.Tick += delegate { UpdateProfileView(); };
            clockTimer.Start();
            refreshTimer.Interval = 45000;
            refreshTimer.Tick += async delegate { await RefreshProfileAsync(); };
            drainTimer.Interval = 300;
            drainTimer.Tick += delegate
            {
                if (drainingFish != null && drainingFish.FinishWorkerShutdown())
                { drainingFish = null; drainTimer.Stop(); ReleaseFishMutex(); UpdateProfileView(); }
            };
            Shown += async delegate { await RestoreAsync(); };
            FormClosing += delegate
            {
                closing = true; generation++;
                clockTimer.Stop(); refreshTimer.Stop();
                CloseProduct("Закрытие Eternal Core. Запрошена остановка.");
            };
            FormClosed += delegate
            {
                clockTimer.Dispose(); refreshTimer.Dispose(); drainTimer.Dispose();
            };
        }

        private static Label Label(Control parent, string text, int x, int y, int width, int height, float size, Color color, FontStyle style)
        {
            Label label = new Label(); label.Text = text; label.SetBounds(x, y, width, height);
            label.Font = new Font("Segoe UI", size, style); label.ForeColor = color; label.BackColor = Color.Transparent;
            label.TextAlign = ContentAlignment.MiddleLeft; parent.Controls.Add(label); return label;
        }
        private static SoftCard Card(Control parent, int x, int y, int width, int height)
        {
            SoftCard result = new SoftCard(); result.SetBounds(x, y, width, height); parent.Controls.Add(result); return result;
        }
        private static SoftButton Button(Control parent, string text, int x, int y, int width, int height, bool primary)
        {
            SoftButton result = new SoftButton(); result.Text = text; result.AccessibleName = text; result.SetBounds(x, y, width, height);
            if (primary) { result.Fill = Theme.Accent; result.Border = Theme.Accent; result.Ink = Theme.AccentDark; }
            parent.Controls.Add(result); return result;
        }
        private static DarkField Field(Control parent, string name, string accessible, int x, int y, int width, bool secret)
        {
            DarkField result = new DarkField(accessible, secret); result.Name = name; result.SetBounds(x, y, width, 44);
            result.Editor.Name = name + "Editor"; parent.Controls.Add(result); return result;
        }

        private void BuildChrome()
        {
            LoaderHeader header = new LoaderHeader(); header.Name = "loaderHeader"; header.SetBounds(1, 1, 980, 46); Controls.Add(header);
            WindowButton minimize = new WindowButton(WindowAction.Minimize); minimize.Name = "loaderMinimize";
            minimize.AccessibleName = "Свернуть Eternal Core"; minimize.SetBounds(899, 6, 38, 33);
            minimize.Click += delegate { WindowState = FormWindowState.Minimized; }; header.Controls.Add(minimize);
            WindowButton close = new WindowButton(WindowAction.Close); close.Name = "loaderClose";
            close.AccessibleName = "Закрыть Eternal Core"; close.SetBounds(940, 6, 38, 33);
            close.Click += delegate { Close(); }; header.Controls.Add(close);
        }

        private void BuildLogin()
        {
            loginPage = new Panel(); loginPage.Name = "loginPage"; loginPage.SetBounds(1, 47, 980, 602); loginPage.BackColor = Theme.Background; Controls.Add(loginPage);
            HeroPanel hero = new HeroPanel(); hero.Name = "loginHero"; hero.SetBounds(0, 0, 420, 602); loginPage.Controls.Add(hero);
            Label(loginPage, "ДОБРО ПОЖАЛОВАТЬ", 478, 36, 380, 22, 8f, Theme.Accent, FontStyle.Bold);
            Label(loginPage, "С возвращением", 475, 57, 420, 46, 23f, Theme.Text, FontStyle.Bold);
            Label(loginPage, "Войдите, чтобы открыть свои продукты.", 478, 103, 420, 25, 10f, Theme.Muted, FontStyle.Regular);
            Label(loginPage, "Логин", 478, 144, 340, 19, 8.5f, Theme.Muted, FontStyle.Bold);
            usernameField = Field(loginPage, "username", "Логин", 478, 166, 423, false);
            Label(loginPage, "Пароль", 478, 220, 340, 19, 8.5f, Theme.Muted, FontStyle.Bold);
            passwordField = Field(loginPage, "password", "Пароль", 478, 242, 423, true);
            Label(loginPage, "ОДИН АККАУНТ ДЛЯ ВАШИХ ИГР И МАКРОСОВ", 478, 301, 423, 22, 8f, Theme.Muted, FontStyle.Bold);
            remember = new DarkToggle(); remember.Name = "rememberSession"; remember.AccessibleName = "Запомнить вход";
            remember.SetBounds(478, 347, 42, 23); remember.Checked = true; loginPage.Controls.Add(remember);
            Label(loginPage, "Запомнить вход на этом устройстве", 528, 346, 375, 25, 9f, Theme.Text, FontStyle.Regular);
            loginButton = Button(loginPage, "Войти в Eternal Core    →", 478, 396, 423, 47, true); loginButton.Name = "loginButton";
            loginButton.Click += async delegate { await LoginAsync(); };
            loginMessage = Label(loginPage, "", 478, 450, 423, 55, 8.8f, Theme.Warn, FontStyle.Regular); loginMessage.Name = "loginMessage";
            SoftButton support = Button(loginPage, "Тех. Поддержка   ↗", 478, 517, 220, 38, false); support.Name = "loginSupport";
            support.Click += delegate { OpenSupport(loginMessage); };
            bool plainLan = new Uri(serverAddress).Scheme == Uri.UriSchemeHttp && !new Uri(serverAddress).IsLoopback;
            sessionNote = Label(loginPage, plainLan ? "HTTP в LAN не шифрует данные · пароль не сохраняется" :
                "Пароль не сохраняется · Защита Windows", 478, 565, 440, 20, 8f, Theme.Muted, FontStyle.Regular);
            sessionNote.Name = "sessionNote";
        }

        private void BuildDashboard()
        {
            dashboardPage = new Panel(); dashboardPage.Name = "dashboardPage"; dashboardPage.SetBounds(1, 47, 980, 602); dashboardPage.BackColor = Theme.Background; Controls.Add(dashboardPage);
            sidebar = new Panel(); sidebar.Name = "loaderSidebar"; sidebar.SetBounds(0, 0, 190, 602); sidebar.BackColor = Theme.Sidebar; dashboardPage.Controls.Add(sidebar);
            Label(sidebar, "ПРОСТРАНСТВО", 20, 29, 160, 18, 7.5f, Theme.Muted, FontStyle.Bold);
            Label(sidebar, "Eternal Core", 18, 48, 165, 40, 15f, Theme.Text, FontStyle.Bold);
            Label(sidebar, "МОИ ПРОДУКТЫ", 20, 112, 160, 20, 7.5f, Theme.Muted, FontStyle.Bold);
            navProducts = Button(sidebar, "Библиотека", 15, 139, 160, 40, false); navProducts.Name = "navProducts";
            navProducts.AlignLeft = true; navProducts.IconKind = MenuIcon.Fish;
            navProducts.Click += delegate { ShowDashboardPage(false); };
            navProfile = Button(sidebar, "Профиль", 15, 187, 160, 40, false); navProfile.Name = "navProfile";
            navProfile.AlignLeft = true; navProfile.IconKind = MenuIcon.Journal;
            navProfile.Click += delegate { ShowDashboardPage(true); };
            SoftCard security = Card(sidebar, 15, 372, 160, 121); security.Fill = Color.FromArgb(19, 23, 39);
            Label(security, "◆", 12, 13, 22, 22, 12f, Theme.Accent, FontStyle.Bold);
            Label(security, "ВАШ ДОСТУП", 38, 14, 110, 20, 7.5f, Theme.Text, FontStyle.Bold);
            Label(security, "Подписка проверяется сервером при запуске.", 13, 42, 135, 60, 8.3f, Theme.Muted, FontStyle.Regular);
            SoftButton logout = Button(sidebar, "Выйти из аккаунта", 15, 512, 160, 37, false); logout.Name = "logoutButton";
            logout.Click += async delegate { await LogoutAsync(); };
            Label(sidebar, "Eternal Core  ·  release v1", 20, 570, 150, 18, 7.8f, Theme.Muted, FontStyle.Regular);
            workspacePage = new Panel(); workspacePage.Name = "workspacePage"; workspacePage.SetBounds(190, 0, 790, 602); workspacePage.BackColor = Theme.Background; dashboardPage.Controls.Add(workspacePage);
            profilePage = new Panel(); profilePage.Name = "profilePage"; profilePage.SetBounds(190, 0, 790, 602); profilePage.BackColor = Theme.Background; dashboardPage.Controls.Add(profilePage);
            BuildProductPage(); BuildProfilePage(); ShowDashboardPage(false);
        }

        private void BuildProductPage()
        {
            Label(workspacePage, "ВАШЕ ПРОСТРАНСТВО", 27, 20, 390, 20, 7.8f, Theme.Accent, FontStyle.Bold);
            Label(workspacePage, "Библиотека", 25, 40, 440, 40, 22f, Theme.Text, FontStyle.Bold);
            accountName = Label(workspacePage, "", 496, 24, 175, 30, 9f, Theme.Muted, FontStyle.Regular); accountName.Name = "accountName"; accountName.TextAlign = ContentAlignment.MiddleRight;
            SoftButton refresh = Button(workspacePage, "↻", 691, 23, 70, 34, false); refresh.Name = "refreshProfile";
            refresh.AccessibleName = "Обновить подписки"; refresh.Click += async delegate { await RefreshProfileAsync(); };
            Label(workspacePage, "ИГРЫ", 27, 94, 220, 20, 8f, Theme.Muted, FontStyle.Bold);
            Label(workspacePage, "ВАШИ МАКРОСЫ  /  DLC", 278, 94, 460, 20, 8f, Theme.Muted, FontStyle.Bold);
            SoftCard gamesCard = Card(workspacePage, 26, 120, 236, 154);
            gameList = new CatalogList(); gameList.Name = "gameList"; gameList.AccessibleName = "Выберите игру";
            gameList.SetBounds(2, 2, 232, 150); gameList.EmptyText = "Игры ещё не добавлены."; gamesCard.Controls.Add(gameList);
            gameList.SelectionChanged += delegate { selectedGameCode = gameList.SelectedCode; selectedProductCode = null; UpdateProfileView(); };
            SoftCard macrosCard = Card(workspacePage, 276, 120, 486, 154);
            macroList = new CatalogList(); macroList.Name = "macroList"; macroList.AccessibleName = "Выберите доступный макрос";
            macroList.SetBounds(2, 2, 482, 150); macroList.EmptyText = "Для этой игры подписок пока нет. Обратитесь к администратору."; macrosCard.Controls.Add(macroList);
            macroList.SelectionChanged += delegate { selectedProductCode = macroList.SelectedCode; UpdateProfileView(); };
            Label(workspacePage, "ИНФОРМАЦИЯ О ПОДПИСКЕ", 27, 287, 400, 20, 8f, Theme.Muted, FontStyle.Bold);
            SoftCard info1 = Card(workspacePage, 26, 310, 233, 78); SoftCard info2 = Card(workspacePage, 269, 310, 233, 78); SoftCard info3 = Card(workspacePage, 512, 310, 250, 78);
            Label(info1, "ВАШ UID", 15, 8, 200, 18, 7.8f, Theme.Muted, FontStyle.Bold);
            uidValue = Label(info1, "—", 14, 32, 205, 33, 15f, Theme.Text, FontStyle.Bold); uidValue.Name = "uidValue";
            Label(info2, "ОСТАЛОСЬ ВРЕМЕНИ", 15, 8, 200, 18, 7.8f, Theme.Muted, FontStyle.Bold);
            remainingValue = Label(info2, "—", 14, 32, 205, 33, 13f, Theme.Text, FontStyle.Bold); remainingValue.Name = "remainingValue";
            Label(info3, "ДЕЙСТВУЕТ ДО", 15, 8, 215, 18, 7.8f, Theme.Muted, FontStyle.Bold);
            expiresValue = Label(info3, "—", 14, 32, 225, 33, 12.5f, Theme.Text, FontStyle.Bold); expiresValue.Name = "expiresValue";
            Label(workspacePage, "ВЫБРАННЫЙ МАКРОС", 27, 399, 400, 20, 8f, Theme.Muted, FontStyle.Bold);
            SoftCard status = Card(workspacePage, 26, 422, 736, 100);
            productPower = new PowerButton(); productPower.Name = "productPower"; productPower.AccessibleName = "Открыть выбранный макрос"; productPower.SetBounds(14, 12, 72, 72);
            productPower.Click += async delegate { await LaunchAsync(); }; status.Controls.Add(productPower);
            statusTitle = Label(status, "Выберите макрос", 101, 14, 378, 27, 11f, Theme.Text, FontStyle.Bold); statusTitle.Name = "statusTitle";
            statusDescription = Label(status, "Подписки проверяются сервером.", 102, 42, 370, 27, 8.5f, Theme.Muted, FontStyle.Regular); statusDescription.Name = "statusDescription";
            productState = Label(status, "", 102, 75, 370, 20, 8f, Theme.Accent, FontStyle.Bold); productState.Name = "productState";
            launchButton = Button(status, "Открыть   ↗", 508, 28, 205, 44, true); launchButton.Name = "launchButton";
            launchButton.Click += async delegate { await LaunchAsync(); };
            warningCard = Card(workspacePage, 26, 538, 736, 49); warningCard.Fill = Color.FromArgb(21, 25, 43); warningCard.Stroke = Color.FromArgb(52, 67, 100);
            warningText = Label(warningCard, "", 13, 4, 710, 41, 8.6f, Theme.Muted, FontStyle.Regular); warningText.Name = "warningText";
        }

        private void BuildProfilePage()
        {
            Label(profilePage, "АККАУНТ  /  ETERNAL CORE", 27, 16, 390, 20, 7.8f, Theme.Accent, FontStyle.Bold);
            Label(profilePage, "Ваш профиль", 25, 36, 440, 39, 21f, Theme.Text, FontStyle.Bold);
            SoftCard userCard = Card(profilePage, 26, 82, 736, 67);
            Label(userCard, "●", 16, 11, 45, 45, 24f, Theme.Accent, FontStyle.Bold);
            profileUser = Label(userCard, "", 66, 9, 350, 27, 13f, Theme.Text, FontStyle.Bold); profileUser.Name = "profileUser";
            profileUid = Label(userCard, "", 67, 36, 310, 21, 8.5f, Theme.Muted, FontStyle.Regular); profileUid.Name = "profileUid";
            Label(userCard, "ЛИЧНЫЙ КАБИНЕТ", 506, 19, 205, 25, 8f, Theme.Muted, FontStyle.Bold);

            SoftCard keyCard = Card(profilePage, 26, 161, 356, 130);
            Label(keyCard, "АКТИВАЦИЯ КЛЮЧА", 13, 9, 320, 19, 8f, Theme.Accent, FontStyle.Bold);
            keyField = Field(keyCard, "activationKey", "Ключ подписки", 13, 33, 205, false);
            keyField.Editor.MaxLength = 64;
            activateButton = Button(keyCard, "Активировать", 226, 33, 117, 44, true); activateButton.Name = "activateKeyButton";
            activateButton.Font = new Font("Segoe UI", 8.3f, FontStyle.Bold);
            activateButton.Click += async delegate { await ActivateKeyAsync(); };
            keyMessage = Label(keyCard, "Введите ключ от администратора.", 13, 84, 329, 38, 8f, Theme.Muted, FontStyle.Regular); keyMessage.Name = "keyMessage";

            SoftCard passwordCard = Card(profilePage, 26, 303, 356, 282);
            Label(passwordCard, "СМЕНИТЬ ПАРОЛЬ", 13, 10, 320, 20, 8f, Theme.Accent, FontStyle.Bold);
            Label(passwordCard, "Старый пароль", 13, 43, 112, 25, 8.4f, Theme.Muted, FontStyle.Regular);
            oldPasswordField = Field(passwordCard, "oldPassword", "Старый пароль", 128, 38, 215, true); oldPasswordField.Height = 37;
            Label(passwordCard, "Новый пароль", 13, 91, 112, 25, 8.4f, Theme.Muted, FontStyle.Regular);
            newPasswordField = Field(passwordCard, "newPassword", "Новый пароль", 128, 86, 215, true); newPasswordField.Height = 37;
            Label(passwordCard, "Повторите", 13, 139, 112, 25, 8.4f, Theme.Muted, FontStyle.Regular);
            confirmPasswordField = Field(passwordCard, "confirmPassword", "Подтверждение нового пароля", 128, 134, 215, true); confirmPasswordField.Height = 37;
            oldPasswordField.Editor.MaxLength = newPasswordField.Editor.MaxLength = confirmPasswordField.Editor.MaxLength = 256;
            changePasswordButton = Button(passwordCard, "Сохранить новый пароль", 13, 181, 330, 37, false); changePasswordButton.Name = "changePasswordButton";
            changePasswordButton.Click += async delegate { await ChangePasswordAsync(); };
            passwordMessage = Label(passwordCard, "От 8 символов; для администратора — от 12.", 13, 224, 330, 48, 8f, Theme.Muted, FontStyle.Regular); passwordMessage.Name = "passwordMessage";

            Label(profilePage, "МОИ ПОДПИСКИ", 402, 161, 330, 20, 8f, Theme.Muted, FontStyle.Bold);
            profileList = new DarkLogBox(); profileList.Name = "subscriptionList"; profileList.SetBounds(398, 185, 364, 227); profilePage.Controls.Add(profileList);
            SoftCard supportCard = Card(profilePage, 398, 424, 364, 99);
            Label(supportCard, "НУЖНА ПОМОЩЬ?", 13, 9, 330, 19, 8f, Theme.Accent, FontStyle.Bold);
            Label(supportCard, "Свяжитесь с нами в Discord.", 13, 28, 330, 21, 8.5f, Theme.Muted, FontStyle.Regular);
            SoftButton support = Button(supportCard, "Тех. Поддержка   ↗", 13, 54, 330, 34, false); support.Name = "profileSupport";
            support.Click += delegate { OpenSupport(connectionText); };
            connectionText = Label(profilePage, "", 400, 530, 360, 51, 8.2f, Theme.Muted, FontStyle.Regular); connectionText.Name = "connectionText";
        }

        private static void OpenSupport(Label feedback)
        {
            try { SupportLink.Open(); }
            catch (Exception) { feedback.Text = "Не удалось открыть Discord. Проверьте браузер по умолчанию."; }
        }

        private void ShowDashboardPage(bool showProfile)
        {
            workspacePage.Visible = !showProfile; profilePage.Visible = showProfile;
            navProducts.Selected = !showProfile; navProfile.Selected = showProfile;
            navProducts.Fill = !showProfile ? Color.FromArgb(27, 43, 68) : Theme.Raised;
            navProfile.Fill = showProfile ? Color.FromArgb(27, 43, 68) : Theme.Raised;
            navProducts.Ink = !showProfile ? Theme.Accent : Theme.Text;
            navProfile.Ink = showProfile ? Theme.Accent : Theme.Text;
            navProducts.Invalidate(); navProfile.Invalidate();
            if (showProfile) profilePage.BringToFront(); else workspacePage.BringToFront();
        }

        private void ShowLogin(string message)
        {
            refreshTimer.Stop(); dashboardPage.Visible = false; loginPage.Visible = true; loginPage.BringToFront();
            AcceptButton = loginButton; loginMessage.Text = message; passwordField.Editor.Text = ""; loginButton.Enabled = true;
            if (keyField != null) keyField.Editor.Text = "";
            if (oldPasswordField != null) oldPasswordField.Editor.Text = "";
            if (newPasswordField != null) newPasswordField.Editor.Text = "";
            if (confirmPasswordField != null) confirmPasswordField.Editor.Text = "";
            pendingActivationKey = null; pendingActivationId = null;
            SetBusy(false);
        }
        private void ShowDashboard(string message)
        {
            loginPage.Visible = false; dashboardPage.Visible = true; dashboardPage.BringToFront(); AcceptButton = null;
            connectionText.Text = message; ShowDashboardPage(false); UpdateProfileView(); refreshTimer.Start();
        }
        private void SetBusy(bool value)
        {
            busy = value; loginButton.Enabled = !value; usernameField.Editor.Enabled = !value;
            passwordField.Editor.Enabled = !value; remember.Enabled = !value;
            if (gameList != null) gameList.Enabled = !value;
            if (macroList != null) macroList.Enabled = !value;
            if (keyField != null) keyField.Editor.Enabled = !value;
            if (oldPasswordField != null) oldPasswordField.Editor.Enabled = !value;
            if (newPasswordField != null) newPasswordField.Editor.Enabled = !value;
            if (confirmPasswordField != null) confirmPasswordField.Editor.Enabled = !value;
            if (activateButton != null) activateButton.Enabled = !value;
            if (changePasswordButton != null) changePasswordButton.Enabled = !value;
            if (value) { if (launchButton != null) launchButton.Enabled = false; if (productPower != null) productPower.Enabled = false; }
            else UpdateProfileView();
        }

        private async Task RestoreAsync()
        {
            SavedSession saved = store.Load(); if (saved == null || closing) return;
            // A saved token is only ever sent to the endpoint embedded in this
            // build, not to the address saved by a previous/different build.
            if (!String.Equals(new ApiClient(saved.Server).BaseUrl, serverAddress, StringComparison.OrdinalIgnoreCase))
            { store.Delete(); ShowLogin("Настройки доступа изменились. Войдите заново."); return; }
            loginMessage.Text = "Восстанавливаем сохранённый вход…"; SetBusy(true);
            int expected = generation;
            try
            {
                ApiClient candidate = new ApiClient(serverAddress);
                Profile result = await Task.Run(delegate { return candidate.GetProfile(saved.Token, device); });
                if (closing || expected != generation) return;
                api = candidate; token = saved.Token; profile = result; ShowDashboard("Вход восстановлен. Подключение подтверждено сервером.");
            }
            catch (ApiException ex)
            {
                if (closing || expected != generation) return;
                if (ex.Status == 401 || ex.Status == 403) store.Delete();
                ShowLogin(ex.Status == 0 ? "Сервер недоступен. Сохранённый вход не удалён; попробуйте позже." : ex.Message);
            }
            catch (Exception) { if (!closing && expected == generation) ShowLogin("Не удалось восстановить вход. Проверьте настройки сервера."); }
            finally { if (!closing && expected == generation) SetBusy(false); }
        }

        private async Task LoginAsync()
        {
            if (busy) return;
            string username = usernameField.Editor.Text.Trim(), password = passwordField.Editor.Text;
            if (username.Length == 0 || password.Length == 0) { loginMessage.Text = "Введите логин и пароль."; return; }
            SetBusy(true); loginMessage.Text = "Проверяем данные…"; int expected = generation;
            try
            {
                ApiClient candidate = new ApiClient(serverAddress);
                string receivedToken = null;
                Profile result = await Task.Run(delegate { return candidate.Login(username, password, device, out receivedToken); });
                if (closing || expected != generation) return;
                api = candidate; token = receivedToken; profile = result; persistentNotice = null;
                string note = "Подключение подтверждено сервером.";
                if (remember.Checked)
                {
                    try { store.Save(candidate.BaseUrl, receivedToken); }
                    catch (Exception) { store.Delete(); note = "Вход выполнен, но Windows не сохранила сессию на этом устройстве."; persistentNotice = note; }
                }
                else store.Delete();
                passwordField.Editor.Text = "";
                ShowDashboard(note);
            }
            catch (ApiException ex) { if (!closing && expected == generation) loginMessage.Text = ex.Message; }
            catch (Exception ex)
            {
                // Type and call sites aid diagnostics without writing the login,
                // password, token, device identifier, or server response to a log.
                Console.Error.WriteLine("Eternal Core login processing: " + ex.GetType().FullName + "\n" + ex.StackTrace);
                if (!closing && expected == generation) loginMessage.Text = "Не удалось выполнить вход. Проверьте подключение.";
            }
            finally { if (!closing && expected == generation) { passwordField.Editor.Text = ""; SetBusy(false); } }
        }

        private async Task ActivateKeyAsync()
        {
            if (busy || api == null || String.IsNullOrEmpty(token) || closing) return;
            string key = keyField.Editor.Text.Trim().ToUpperInvariant();
            if (key.Length == 0) { keyMessage.Text = "Введите ключ подписки."; return; }
            if (!String.Equals(pendingActivationKey, key, StringComparison.Ordinal) || String.IsNullOrEmpty(pendingActivationId))
            { pendingActivationKey = key; pendingActivationId = Guid.NewGuid().ToString("N"); }
            string operation = pendingActivationId;
            ApiClient current = api; string currentToken = token; int expected = generation;
            SetBusy(true); keyMessage.Text = "Проверяем ключ…"; bool sessionInvalid = false;
            try
            {
                long expiry = await Task.Run(delegate { return current.ActivateKey(currentToken, device, key, operation); });
                if (closing || expected != generation) return;
                pendingActivationKey = null; pendingActivationId = null; keyField.Editor.Text = "";
                profileRevision++; // an older refresh must not overwrite the newly activated entitlement
                keyMessage.ForeColor = Theme.Accent;
                keyMessage.Text = "Ключ активирован · до " + FormatDate(expiry);
                try
                {
                    Profile updated = await Task.Run(delegate { return current.GetProfile(currentToken, device); });
                    if (!closing && expected == generation) { profile = updated; UpdateProfileView(); }
                }
                catch (Exception)
                {
                    if (!closing && expected == generation) keyMessage.Text = "Ключ активирован. Обновите подписки, когда связь восстановится.";
                }
            }
            catch (ApiException ex)
            {
                if (closing || expected != generation) return;
                keyMessage.ForeColor = Theme.Warn;
                keyMessage.Text = ex.Status == 0 ? "Ответ потерян. Повторите с тем же ключом: эта попытка не добавит время дважды." : ex.Message;
                sessionInvalid = ex.Status == 401;
            }
            catch (Exception)
            {
                if (!closing && expected == generation) { keyMessage.ForeColor = Theme.Warn; keyMessage.Text = "Не удалось подтвердить активацию. Повторите с тем же ключом."; }
            }
            finally { if (!closing && expected == generation) SetBusy(false); }
            if (sessionInvalid && !closing && expected == generation) await RefreshProfileAsync();
        }

        private async Task ChangePasswordAsync()
        {
            if (busy || api == null || String.IsNullOrEmpty(token) || closing) return;
            string oldPassword = oldPasswordField.Editor.Text, newPassword = newPasswordField.Editor.Text, confirm = confirmPasswordField.Editor.Text;
            if (oldPassword.Length == 0 || newPassword.Length < 8)
            { passwordMessage.ForeColor = Theme.Warn; passwordMessage.Text = "Введите старый пароль и новый пароль не короче 8 символов."; return; }
            if (!String.Equals(newPassword, confirm, StringComparison.Ordinal))
            { passwordMessage.ForeColor = Theme.Warn; passwordMessage.Text = "Новый пароль и подтверждение не совпадают."; return; }
            ApiClient current = api; string currentToken = token; int expected = generation; bool sessionInvalid = false;
            SetBusy(true); passwordMessage.Text = "Сохраняем пароль…";
            try
            {
                await Task.Run(delegate { current.ChangePassword(currentToken, device, oldPassword, newPassword, confirm); });
                if (closing || expected != generation) return;
                passwordMessage.ForeColor = Theme.Accent;
                passwordMessage.Text = "Пароль изменён. Остальные сеансы завершены.";
            }
            catch (ApiException ex)
            {
                if (closing || expected != generation) return;
                passwordMessage.ForeColor = Theme.Warn;
                passwordMessage.Text = ex.Status == 0 ? "Ответ потерян: пароль мог измениться. Проверьте вход." : ex.Message;
                sessionInvalid = ex.Status == 401;
            }
            catch (Exception)
            {
                if (!closing && expected == generation) { passwordMessage.ForeColor = Theme.Warn; passwordMessage.Text = "Не удалось подтвердить смену пароля. Проверьте вход."; }
            }
            finally
            {
                if (!closing && expected == generation)
                {
                    oldPasswordField.Editor.Text = ""; newPasswordField.Editor.Text = ""; confirmPasswordField.Editor.Text = "";
                    SetBusy(false);
                }
            }
            if (sessionInvalid && !closing && expected == generation) await RefreshProfileAsync();
        }

        private async Task RefreshProfileAsync()
        {
            if (refreshing || api == null || String.IsNullOrEmpty(token) || closing) return;
            refreshing = true; int expected = generation, revision = profileRevision; ApiClient current = api; string currentToken = token;
            try
            {
                Profile result = await Task.Run(delegate { return current.GetProfile(currentToken, device); });
                if (closing || expected != generation || revision != profileRevision) return;
                profile = result; connectionText.Text = "Подключение подтверждено · " + DateTime.Now.ToString("HH:mm:ss"); UpdateProfileView();
            }
            catch (ApiException ex)
            {
                if (closing || expected != generation) return;
                if (ex.Status == 401 || ex.Status == 403)
                {
                    CloseProduct("Сессия завершена сервером. Запрошена остановка.");
                    store.Delete(); api = null; token = null; profile = null; generation++; ShowLogin("Сессия завершена. Войдите заново.");
                }
                else connectionText.Text = "Нет связи с сервером. Доступ к продукту можно продолжать только до окончания подтверждённого интервала.";
            }
            catch (Exception) { if (!closing && expected == generation) connectionText.Text = "Не удалось обновить состояние подписки."; }
            finally { refreshing = false; }
        }

        private static string FormatRemaining(long seconds)
        {
            if (seconds <= 0) return "—";
            long days = seconds / 86400; long hours = (seconds / 3600) % 24; long minutes = (seconds / 60) % 60; long secs = seconds % 60;
            return days > 0 ? String.Format("{0} д  {1:00}:{2:00}:{3:00}", days, hours, minutes, secs) :
                String.Format("{0:00}:{1:00}:{2:00}", hours, minutes, secs);
        }
        private static string FormatDate(long? seconds)
        {
            if (!seconds.HasValue) return "—";
            try { return new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc).AddSeconds(seconds.Value).ToLocalTime().ToString("dd.MM.yyyy  HH:mm", CultureInfo.InvariantCulture); }
            catch (ArgumentOutOfRangeException) { return "—"; }
        }
        private void UpdateProfileView()
        {
            if (profile == null || dashboardPage == null || !dashboardPage.Visible) return;
            accountName.Text = "●   " + profile.Username; profileUser.Text = profile.Username;
            uidValue.Text = profile.Uid.ToString("D8", CultureInfo.InvariantCulture); profileUid.Text = "UID  " + uidValue.Text;

            List<CatalogEntry> games = new List<CatalogEntry>();
            foreach (GameInfo game in profile.Games)
            {
                int owned = 0;
                foreach (ProductInfo product in profile.Products)
                    if (product.GameCode == game.Code && product.ExpiresAt.HasValue) owned++;
                games.Add(new CatalogEntry { Code = game.Code, Title = game.Name,
                    Subtitle = owned == 0 ? "Пока нет макросов" : "Макросов: " + owned, Highlight = owned > 0 });
            }
            if (String.IsNullOrEmpty(selectedGameCode))
                foreach (GameInfo game in profile.Games) if (game.Code == "gta5") { selectedGameCode = game.Code; break; }
            gameList.SetItems(games, selectedGameCode); selectedGameCode = gameList.SelectedCode;
            List<CatalogEntry> macros = new List<CatalogEntry>();
            foreach (ProductInfo item in profile.Products)
            {
                if (item.GameCode != selectedGameCode || !item.ExpiresAt.HasValue) continue;
                long left = profile.Remaining(item);
                bool available = item.Active && left > 0;
                macros.Add(new CatalogEntry { Code = item.Code, Title = item.Name,
                    Subtitle = available ? "Активен · осталось " + FormatRemaining(left) : "Подписка истекла",
                    Highlight = available });
            }
            macros.Sort(delegate(CatalogEntry x, CatalogEntry y)
            {
                if (x.Highlight != y.Highlight) return x.Highlight ? -1 : 1;
                return String.Compare(x.Title, y.Title, StringComparison.CurrentCultureIgnoreCase);
            });
            macroList.SetItems(macros, selectedProductCode); selectedProductCode = macroList.SelectedCode;
            ProductInfo chosen = String.IsNullOrEmpty(selectedProductCode) ? null : profile.Find(selectedProductCode);
            long remaining = profile.Remaining(chosen);
            bool active = chosen != null && chosen.Active && remaining > 0;
            bool supported = chosen != null && chosen.Code == "rmfish";
            bool opened = supported && fishForm != null && !fishForm.IsDisposed && lease != null && lease.IsValid;
            remainingValue.Text = FormatRemaining(remaining); expiresValue.Text = chosen == null ? "—" : FormatDate(chosen.ExpiresAt);
            productState.Text = chosen == null ? "" : active ? "●  Подписка активна" : "●  Подписка истекла";
            productState.ForeColor = active ? Theme.Accent : Theme.Warn;
            statusTitle.Text = chosen == null ? "Выберите макрос" : opened ? "RMFish открыт" :
                !active ? chosen.Name + " · доступ истёк" : supported ? chosen.Name + " · готов к запуску" : chosen.Name + " · запуск пока недоступен";
            statusDescription.Text = chosen == null ? "Выберите игру и доступный макрос выше." : opened ? "Окно продукта работает внутри Eternal Core." :
                !active ? "Для продления обратитесь к администратору." : supported ? "Макрос встроен в Eternal Core, установка не нужна." : "Нужна версия лоадера с поддержкой этого макроса.";
            launchButton.Enabled = !busy && active && supported; productPower.Enabled = !busy && active && supported;
            launchButton.Text = opened ? "Показать RMFish   ↗" : "Открыть   ↗";

            string warning = ""; int soonCount = 0;
            System.Text.StringBuilder list = new System.Text.StringBuilder();
            foreach (ProductInfo item in profile.Products)
            {
                long left = profile.Remaining(item);
                if (item.ExpiresAt.HasValue && left > 0 && left <= 3 * 86400)
                {
                    soonCount++;
                    if (soonCount <= 2) warning += (warning.Length == 0 ? "" : ", ") + item.Name;
                }
                if (!item.ExpiresAt.HasValue) continue;
                if (list.Length > 0) list.Append("\r\n\r\n");
                list.Append(item.GameName).Append("  /  ").Append(item.Name).Append("   ·   ");
                if (left <= 0) list.Append("истекла ").Append(FormatDate(item.ExpiresAt));
                else list.Append("осталось ").Append(FormatRemaining(left)).Append("   ·   до ").Append(FormatDate(item.ExpiresAt));
                if (item.Code != "rmfish") list.Append("   ·   запуск пока не поддерживается");
            }
            profileList.SetContent(list.Length == 0 ? "Подписок пока нет. Обратитесь к администратору." : list.ToString());
            if (!String.IsNullOrEmpty(persistentNotice))
            {
                warningText.Text = "!   " + persistentNotice + (soonCount > 0 ? " · Скоро закончится: " + warning : "");
                warningText.ForeColor = Theme.Warn; warningCard.Stroke = Color.FromArgb(110, 88, 53);
            }
            else if (soonCount > 0)
            {
                warningText.Text = "!   Скоро закончится: " + warning + (soonCount > 2 ? " и ещё " + (soonCount - 2) + " (см. профиль)" : "") + ". Проверьте срок подписки.";
                warningText.ForeColor = Theme.Warn; warningCard.Stroke = Color.FromArgb(110, 88, 53);
            }
            else
            {
                warningText.Text = active && supported ? "◆   Подписка подтверждена. Перед рыбалкой проверьте F10 в игре." :
                    "◆   Подписки и устройства настраивает администратор.";
                warningText.ForeColor = Theme.Muted; warningCard.Stroke = Color.FromArgb(52, 67, 100);
            }
            warningCard.Invalidate();
        }

        private async Task LaunchAsync()
        {
            if (busy || api == null || String.IsNullOrEmpty(token) || closing || profile == null) return;
            ProductInfo selected = String.IsNullOrEmpty(selectedProductCode) ? null : profile.Find(selectedProductCode);
            if (selected == null || selected.Code != "rmfish" || !selected.Active || profile.Remaining(selected) <= 0) return;
            if (fishForm != null && !fishForm.IsDisposed && lease != null && lease.IsValid)
            { fishForm.WindowState = FormWindowState.Normal; fishForm.Show(); fishForm.Activate(); return; }
            CloseProduct("Повторная проверка доступа. Запрошена остановка.");
            persistentNotice = null;
            SetBusy(true); statusTitle.Text = "Проверяем доступ…"; int expected = generation;
            ApiClient current = api; string currentToken = token; bool refreshAfterFailure = false;
            try
            {
                LeaseInfo initial = await Task.Run(delegate { return current.Authorize(currentToken, device, "rmfish"); });
                if (closing || expected != generation) return;
                if (!AcquireFishMutex())
                {
                    persistentNotice = "RMFish уже открыт или ещё останавливается. Закройте предыдущий экземпляр.";
                    connectionText.Text = persistentNotice; return;
                }
                Directory.CreateDirectory(Path.Combine(localDirectory, "Runtime"));
                ProductLease currentLease = null; MainForm currentForm = null;
                currentLease = new ProductLease(initial,
                    delegate { return current.Authorize(currentToken, device, "rmfish"); },
                    delegate(string reason)
                    {
                        if (currentForm != null) currentForm.RevokeAuthorization(reason);
                        try
                        {
                            if (IsHandleCreated && !IsDisposed && !Disposing)
                                BeginInvoke((MethodInvoker)(async delegate
                                {
                                    if (!IsDisposed) { connectionText.Text = reason; UpdateProfileView(); await RefreshProfileAsync(); }
                                }));
                        }
                        catch (InvalidOperationException) { }
                    });
                if (!currentLease.IsValid) { currentLease.Dispose(); ReleaseFishMutex(); throw new ApiException(403, "NO_SUBSCRIPTION", "Подписка истекает. Продлите её перед запуском."); }
                string settingsRoot = Path.GetDirectoryName(localDirectory);
                currentForm = new MainForm(Path.Combine(localDirectory, "Runtime"), settingsRoot, delegate { return currentLease.IsValid; });
                fishForm = currentForm; lease = currentLease;
                currentForm.FormClosed += delegate
                {
                    currentLease.Dispose();
                    if (fishForm == currentForm)
                    {
                        fishForm = null; lease = null;
                        if (currentForm.FinishWorkerShutdown()) ReleaseFishMutex();
                        else { drainingFish = currentForm; drainTimer.Start(); }
                        UpdateProfileView();
                    }
                };
                currentLease.Start(); currentForm.Show(); currentForm.Activate(); UpdateProfileView();
            }
            catch (ApiException ex)
            {
                if (!closing && expected == generation)
                {
                    if (ex.Status == 401) { store.Delete(); api = null; token = null; profile = null; generation++; ShowLogin("Сессия завершена. Войдите заново."); }
                    else { persistentNotice = ex.Message; connectionText.Text = ex.Message; refreshAfterFailure = true; }
                }
                if (fishForm != null) CloseProduct("Не удалось открыть RMFish. Запрошена остановка.");
                else if (drainingFish == null) ReleaseFishMutex();
            }
            catch (Exception ex)
            {
                if (fishForm != null) CloseProduct("Не удалось открыть RMFish. Запрошена остановка.");
                else if (drainingFish == null) ReleaseFishMutex();
                if (!closing && expected == generation) { persistentNotice = "Не удалось открыть RMFish: " + ex.Message; connectionText.Text = persistentNotice; }
            }
            finally { if (!closing) { SetBusy(false); UpdateProfileView(); } }
            if (refreshAfterFailure && !closing && expected == generation) await RefreshProfileAsync();
        }

        private bool AcquireFishMutex()
        {
            if (fishMutex != null) return false; // active or a worker is still stopping
            fishMutex = new Mutex(false, @"Local\RMFish");
            try { ownsFishMutex = fishMutex.WaitOne(0, false); }
            catch (AbandonedMutexException) { ownsFishMutex = true; }
            if (!ownsFishMutex) { fishMutex.Dispose(); fishMutex = null; }
            return ownsFishMutex;
        }
        private void ReleaseFishMutex()
        {
            if (fishMutex == null) return;
            if (ownsFishMutex) { try { fishMutex.ReleaseMutex(); } catch (ApplicationException) { } }
            fishMutex.Dispose(); fishMutex = null; ownsFishMutex = false;
        }
        private void CloseProduct(string reason)
        {
            MainForm current = fishForm; ProductLease currentLease = lease;
            if (current != null && !current.IsDisposed) { current.RevokeAuthorization(reason); current.Close(); }
            if (currentLease != null) currentLease.Dispose();
            fishForm = null; lease = null;
            if (drainingFish == null) ReleaseFishMutex();
        }
        private async Task LogoutAsync()
        {
            if (busy) return;
            CloseProduct("Выход из аккаунта. Запрошена остановка.");
            ApiClient previous = api; string previousToken = token;
            generation++; api = null; token = null; profile = null; persistentNotice = null;
            selectedGameCode = null; selectedProductCode = null; store.Delete(); ShowLogin("Вы вышли из аккаунта.");
            if (previous != null && !String.IsNullOrEmpty(previousToken))
                try { await Task.Run(delegate { previous.Logout(previousToken, device); }); } catch (Exception) { }
        }
    }
}
