using System;
using System.Drawing;
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
    internal sealed class LoaderHeader : Panel
    {
        public LoaderHeader()
        {
            DoubleBuffered = true; BackColor = Theme.Sidebar;
            AccessibleRole = AccessibleRole.TitleBar;
            AccessibleName = "Заголовок RMacro; перетащите для перемещения";
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            e.Graphics.Clear(BackColor);
            using (Font brand = new Font("Segoe UI", 14f, FontStyle.Bold))
            {
                TextRenderer.DrawText(e.Graphics, "R", brand, new Rectangle(18, 0, 19, Height), Theme.Text,
                    TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPadding);
                TextRenderer.DrawText(e.Graphics, "Macro", brand, new Rectangle(34, 0, 85, Height), Theme.Accent,
                    TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPadding);
            }
            using (Font caption = new Font("Segoe UI", 7.3f, FontStyle.Bold))
                TextRenderer.DrawText(e.Graphics, "ВАШИ ПРОДУКТЫ  /  В ОДНОМ МЕСТЕ", caption, new Rectangle(130, 0, 280, Height), Theme.Muted,
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
        private Image background;
        public HeroPanel()
        {
            DoubleBuffered = true; BackColor = Theme.Sidebar;
            try
            {
                using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("RMacro.City.png"))
                using (Image image = stream == null ? null : Image.FromStream(stream))
                    if (image != null) background = new Bitmap(image);
            }
            catch (Exception) { }
        }
        protected override void Dispose(bool disposing)
        {
            if (disposing && background != null) { background.Dispose(); background = null; }
            base.Dispose(disposing);
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.Clear(Theme.Sidebar);
            if (background != null)
            {
                float scale = Math.Max(Width / (float)background.Width, Height / (float)background.Height);
                int w = (int)(background.Width * scale), h = (int)(background.Height * scale);
                g.DrawImage(background, new Rectangle(0, (Height - h) / 2, w, h));
            }
            using (LinearGradientBrush overlay = new LinearGradientBrush(ClientRectangle,
                Color.FromArgb(55, 2, 21, 24), Color.FromArgb(235, 4, 23, 25), LinearGradientMode.Vertical))
                g.FillRectangle(overlay, ClientRectangle);
            using (Pen edge = new Pen(Color.FromArgb(25, 70, 68))) g.DrawLine(edge, Width - 1, 0, Width - 1, Height);
            using (SolidBrush accent = new SolidBrush(Theme.Accent)) g.FillEllipse(accent, 38, 50, 8, 8);
            using (Font mini = new Font("Segoe UI", 8f, FontStyle.Bold))
                TextRenderer.DrawText(g, "ЕДИНОЕ ПРОСТРАНСТВО", mini, new Rectangle(54, 43, 250, 24),
                    Color.FromArgb(176, 216, 205), TextFormatFlags.VerticalCenter | TextFormatFlags.NoPadding);
            using (Font headline = new Font("Segoe UI", 25f, FontStyle.Bold))
            {
                TextRenderer.DrawText(g, "Всё начинается", headline, new Rectangle(35, 342, 375, 47), Theme.Text,
                    TextFormatFlags.NoPadding | TextFormatFlags.VerticalCenter);
                TextRenderer.DrawText(g, "с одного входа.", headline, new Rectangle(35, 386, 375, 47), Theme.Accent,
                    TextFormatFlags.NoPadding | TextFormatFlags.VerticalCenter);
            }
            using (Font body = new Font("Segoe UI", 10f))
                TextRenderer.DrawText(g, "Ваши продукты и подписки —\nв одном удобном месте.", body,
                    new Rectangle(38, 451, 330, 54), Color.FromArgb(172, 204, 196), TextFormatFlags.WordBreak | TextFormatFlags.NoPadding);
            using (Pen line = new Pen(Color.FromArgb(65, 116, 105))) g.DrawLine(line, 38, 540, 380, 540);
            using (Font small = new Font("Segoe UI", 8f, FontStyle.Bold))
                TextRenderer.DrawText(g, "RMACRO  ·  LOADER", small, new Rectangle(38, 552, 260, 23), Theme.Muted, TextFormatFlags.NoPadding);
        }
    }

    internal sealed class DarkField : Panel
    {
        public readonly TextBox Editor;
        public DarkField(string accessibleName, bool secret)
        {
            DoubleBuffered = true; BackColor = Theme.Raised;
            Editor = new TextBox(); Editor.Name = "editor"; Editor.BorderStyle = BorderStyle.None;
            Editor.BackColor = Color.FromArgb(11, 33, 35); Editor.ForeColor = Theme.Text;
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
            using (SolidBrush fill = new SolidBrush(Color.FromArgb(11, 33, 35)))
            using (Pen edge = new Pen(ContainsFocus ? Theme.Accent : Theme.Border))
            { e.Graphics.FillPath(fill, path); e.Graphics.DrawPath(edge, path); }
        }
    }

    internal sealed class LoaderForm : Form
    {
        private readonly string localDirectory, device;
        private readonly SessionStore store;
        private readonly System.Windows.Forms.Timer clockTimer = new System.Windows.Forms.Timer();
        private readonly System.Windows.Forms.Timer refreshTimer = new System.Windows.Forms.Timer();
        private readonly System.Windows.Forms.Timer drainTimer = new System.Windows.Forms.Timer();
        private Panel loginPage, dashboardPage, workspacePage, profilePage, sidebar;
        private DarkField usernameField, passwordField, serverField;
        private DarkToggle remember;
        private SoftButton loginButton, launchButton, navProducts, navProfile;
        private PowerButton productPower;
        private Label loginMessage, sessionNote, accountName, productState, uidValue, remainingValue, expiresValue;
        private Label statusTitle, statusDescription, warningText, connectionText, profileUser, profileUid, profileServer;
        private SoftCard warningCard;
        private DarkLogBox profileList;
        private ApiClient api;
        private string token, persistentNotice;
        private Profile profile;
        private MainForm fishForm, drainingFish;
        private ProductLease lease;
        private Mutex fishMutex;
        private bool ownsFishMutex, busy, refreshing, closing;
        private int generation;
        private Image fishArtwork;

        public LoaderForm(string localDirectory, string device)
        {
            this.localDirectory = localDirectory; this.device = device;
            store = new SessionStore(localDirectory);
            Text = "RMacro — ваши продукты";
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
                CloseProduct("Закрытие RMacro. Запрошена остановка.");
            };
            FormClosed += delegate
            {
                clockTimer.Dispose(); refreshTimer.Dispose(); drainTimer.Dispose();
                if (fishArtwork != null) { fishArtwork.Dispose(); fishArtwork = null; }
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
            minimize.AccessibleName = "Свернуть RMacro"; minimize.SetBounds(899, 6, 38, 33);
            minimize.Click += delegate { WindowState = FormWindowState.Minimized; }; header.Controls.Add(minimize);
            WindowButton close = new WindowButton(WindowAction.Close); close.Name = "loaderClose";
            close.AccessibleName = "Закрыть RMacro"; close.SetBounds(940, 6, 38, 33);
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
            Label(loginPage, "Адрес сервера", 478, 296, 340, 19, 8.5f, Theme.Muted, FontStyle.Bold);
            serverField = Field(loginPage, "server", "Адрес сервера", 478, 318, 423, false);
            serverField.Editor.Text = "http://127.0.0.1:8765";
            Label(loginPage, "Для удалённого сервера используйте HTTPS.", 478, 365, 423, 20, 8f, Theme.Muted, FontStyle.Regular);
            remember = new DarkToggle(); remember.Name = "rememberSession"; remember.AccessibleName = "Запомнить вход";
            remember.SetBounds(478, 402, 42, 23); remember.Checked = true; loginPage.Controls.Add(remember);
            Label(loginPage, "Запомнить вход на этом устройстве", 528, 401, 375, 25, 9f, Theme.Text, FontStyle.Regular);
            loginButton = Button(loginPage, "Войти в RMacro    →", 478, 447, 423, 47, true); loginButton.Name = "loginButton";
            loginButton.Click += async delegate { await LoginAsync(); };
            loginMessage = Label(loginPage, "", 478, 502, 423, 55, 8.8f, Theme.Warn, FontStyle.Regular); loginMessage.Name = "loginMessage";
            sessionNote = Label(loginPage, "Пароль не сохраняется · Защита Windows", 478, 565, 423, 20, 8f, Theme.Muted, FontStyle.Regular);
            sessionNote.Name = "sessionNote";
        }

        private void BuildDashboard()
        {
            dashboardPage = new Panel(); dashboardPage.Name = "dashboardPage"; dashboardPage.SetBounds(1, 47, 980, 602); dashboardPage.BackColor = Theme.Background; Controls.Add(dashboardPage);
            sidebar = new Panel(); sidebar.Name = "loaderSidebar"; sidebar.SetBounds(0, 0, 190, 602); sidebar.BackColor = Theme.Sidebar; dashboardPage.Controls.Add(sidebar);
            Label(sidebar, "ПРОСТРАНСТВО", 20, 29, 160, 18, 7.5f, Theme.Muted, FontStyle.Bold);
            Label(sidebar, "RMacro", 18, 48, 160, 40, 20f, Theme.Text, FontStyle.Bold);
            Label(sidebar, "МОИ ПРОДУКТЫ", 20, 112, 160, 20, 7.5f, Theme.Muted, FontStyle.Bold);
            navProducts = Button(sidebar, "Продукт", 15, 139, 160, 40, false); navProducts.Name = "navProducts";
            navProducts.AlignLeft = true; navProducts.IconKind = MenuIcon.Fish;
            navProducts.Click += delegate { ShowDashboardPage(false); };
            navProfile = Button(sidebar, "Профиль", 15, 187, 160, 40, false); navProfile.Name = "navProfile";
            navProfile.AlignLeft = true; navProfile.IconKind = MenuIcon.Journal;
            navProfile.Click += delegate { ShowDashboardPage(true); };
            SoftCard security = Card(sidebar, 15, 372, 160, 121); security.Fill = Color.FromArgb(10, 34, 34);
            Label(security, "◆", 12, 13, 22, 22, 12f, Theme.Accent, FontStyle.Bold);
            Label(security, "ВАШ ДОСТУП", 38, 14, 110, 20, 7.5f, Theme.Text, FontStyle.Bold);
            Label(security, "Подписка проверяется сервером при запуске.", 13, 42, 135, 60, 8.3f, Theme.Muted, FontStyle.Regular);
            SoftButton logout = Button(sidebar, "Выйти из аккаунта", 15, 512, 160, 37, false); logout.Name = "logoutButton";
            logout.Click += async delegate { await LogoutAsync(); };
            Label(sidebar, "RMacro  ·  beta 0.1", 20, 570, 150, 18, 7.8f, Theme.Muted, FontStyle.Regular);
            workspacePage = new Panel(); workspacePage.Name = "workspacePage"; workspacePage.SetBounds(190, 0, 790, 602); workspacePage.BackColor = Theme.Background; dashboardPage.Controls.Add(workspacePage);
            profilePage = new Panel(); profilePage.Name = "profilePage"; profilePage.SetBounds(190, 0, 790, 602); profilePage.BackColor = Theme.Background; dashboardPage.Controls.Add(profilePage);
            BuildProductPage(); BuildProfilePage(); ShowDashboardPage(false);
        }

        private void BuildProductPage()
        {
            Label(workspacePage, "ВАШЕ ПРОСТРАНСТВО", 27, 23, 390, 20, 7.8f, Theme.Accent, FontStyle.Bold);
            Label(workspacePage, "Ваши продукты", 25, 44, 440, 43, 22f, Theme.Text, FontStyle.Bold);
            accountName = Label(workspacePage, "", 496, 27, 175, 30, 9f, Theme.Muted, FontStyle.Regular); accountName.Name = "accountName"; accountName.TextAlign = ContentAlignment.MiddleRight;
            SoftButton refresh = Button(workspacePage, "↻", 691, 25, 70, 34, false); refresh.Name = "refreshProfile";
            refresh.AccessibleName = "Обновить подписки";
            refresh.Click += async delegate { await RefreshProfileAsync(); };
            Label(workspacePage, "ВЫБОР ПРОДУКТА", 27, 100, 400, 20, 8f, Theme.Muted, FontStyle.Bold);
            SoftCard product = Card(workspacePage, 26, 126, 736, 108);
            PictureBox artwork = new PictureBox(); artwork.Name = "fishArtwork"; artwork.SetBounds(13, 13, 80, 80); artwork.SizeMode = PictureBoxSizeMode.Zoom;
            artwork.BackColor = Color.FromArgb(8, 25, 27);
            try
            {
                using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("RMacro.FishIcon.png"))
                using (Image image = stream == null ? null : Image.FromStream(stream)) if (image != null) fishArtwork = new Bitmap(image);
                artwork.Image = fishArtwork;
            }
            catch (Exception) { }
            product.Controls.Add(artwork);
            Label(product, "RMFish", 112, 16, 300, 29, 15f, Theme.Text, FontStyle.Bold);
            Label(product, "АВТОРЫБАЛКА  /  GTA5 · RMRP", 113, 50, 330, 18, 8f, Theme.Muted, FontStyle.Bold);
            productState = Label(product, "●  Проверка подписки", 474, 36, 230, 32, 9.2f, Theme.Accent, FontStyle.Bold); productState.Name = "productState"; productState.TextAlign = ContentAlignment.MiddleRight;
            Label(workspacePage, "ИНФОРМАЦИЯ О ПОДПИСКЕ", 27, 251, 400, 20, 8f, Theme.Muted, FontStyle.Bold);
            SoftCard info1 = Card(workspacePage, 26, 278, 233, 91); SoftCard info2 = Card(workspacePage, 269, 278, 233, 91); SoftCard info3 = Card(workspacePage, 512, 278, 250, 91);
            Label(info1, "ВАШ UID", 15, 13, 200, 18, 7.8f, Theme.Muted, FontStyle.Bold);
            uidValue = Label(info1, "—", 14, 40, 205, 33, 15f, Theme.Text, FontStyle.Bold); uidValue.Name = "uidValue";
            Label(info2, "ОСТАЛОСЬ ВРЕМЕНИ", 15, 13, 200, 18, 7.8f, Theme.Muted, FontStyle.Bold);
            remainingValue = Label(info2, "—", 14, 40, 205, 33, 14f, Theme.Text, FontStyle.Bold); remainingValue.Name = "remainingValue";
            Label(info3, "ДЕЙСТВУЕТ ДО", 15, 13, 215, 18, 7.8f, Theme.Muted, FontStyle.Bold);
            expiresValue = Label(info3, "—", 14, 40, 225, 33, 12.5f, Theme.Text, FontStyle.Bold); expiresValue.Name = "expiresValue";
            Label(workspacePage, "СОСТОЯНИЕ", 27, 389, 400, 20, 8f, Theme.Muted, FontStyle.Bold);
            SoftCard status = Card(workspacePage, 26, 415, 736, 116);
            productPower = new PowerButton(); productPower.Name = "productPower"; productPower.AccessibleName = "Открыть RMFish"; productPower.SetBounds(14, 16, 76, 76);
            productPower.Click += async delegate { await LaunchAsync(); }; status.Controls.Add(productPower);
            statusTitle = Label(status, "Готов к запуску", 105, 21, 330, 27, 11f, Theme.Text, FontStyle.Bold); statusTitle.Name = "statusTitle";
            statusDescription = Label(status, "Продукт встроен в RMacro, установка не нужна.", 106, 52, 330, 40, 8.5f, Theme.Muted, FontStyle.Regular); statusDescription.Name = "statusDescription";
            launchButton = Button(status, "Открыть RMFish   ↗", 502, 36, 211, 44, true); launchButton.Name = "launchButton";
            launchButton.Click += async delegate { await LaunchAsync(); };
            warningCard = Card(workspacePage, 26, 547, 736, 40); warningCard.Fill = Color.FromArgb(12, 39, 37); warningCard.Stroke = Color.FromArgb(35, 77, 69);
            warningText = Label(warningCard, "", 13, 3, 710, 34, 8.6f, Theme.Muted, FontStyle.Regular); warningText.Name = "warningText";
        }

        private void BuildProfilePage()
        {
            Label(profilePage, "АККАУНТ", 27, 23, 390, 20, 7.8f, Theme.Accent, FontStyle.Bold);
            Label(profilePage, "Ваш профиль", 25, 44, 440, 43, 22f, Theme.Text, FontStyle.Bold);
            SoftCard userCard = Card(profilePage, 26, 112, 736, 120);
            Label(userCard, "●", 19, 20, 54, 54, 29f, Theme.Accent, FontStyle.Bold);
            profileUser = Label(userCard, "", 84, 22, 390, 29, 15f, Theme.Text, FontStyle.Bold); profileUser.Name = "profileUser";
            profileUid = Label(userCard, "", 85, 57, 400, 24, 9f, Theme.Muted, FontStyle.Regular); profileUid.Name = "profileUid";
            profileServer = Label(userCard, "", 85, 84, 610, 22, 8f, Theme.Muted, FontStyle.Regular); profileServer.Name = "profileServer";
            Label(profilePage, "ПОДПИСКИ", 27, 250, 400, 20, 8f, Theme.Muted, FontStyle.Bold);
            profileList = new DarkLogBox(); profileList.Name = "subscriptionList"; profileList.SetBounds(26, 276, 736, 207); profilePage.Controls.Add(profileList);
            connectionText = Label(profilePage, "", 27, 504, 720, 48, 9f, Theme.Muted, FontStyle.Regular); connectionText.Name = "connectionText";
            Label(profilePage, "Сброс привязки устройства выполняет администратор.", 27, 559, 720, 22, 8.3f, Theme.Muted, FontStyle.Regular);
        }

        private void ShowDashboardPage(bool showProfile)
        {
            workspacePage.Visible = !showProfile; profilePage.Visible = showProfile;
            navProducts.Selected = !showProfile; navProfile.Selected = showProfile;
            navProducts.Fill = !showProfile ? Color.FromArgb(15, 61, 51) : Theme.Raised;
            navProfile.Fill = showProfile ? Color.FromArgb(15, 61, 51) : Theme.Raised;
            navProducts.Ink = !showProfile ? Theme.Accent : Theme.Text;
            navProfile.Ink = showProfile ? Theme.Accent : Theme.Text;
            navProducts.Invalidate(); navProfile.Invalidate();
            if (showProfile) profilePage.BringToFront(); else workspacePage.BringToFront();
        }

        private void ShowLogin(string message)
        {
            refreshTimer.Stop(); dashboardPage.Visible = false; loginPage.Visible = true; loginPage.BringToFront();
            AcceptButton = loginButton; loginMessage.Text = message; passwordField.Editor.Text = ""; loginButton.Enabled = true;
        }
        private void ShowDashboard(string message)
        {
            loginPage.Visible = false; dashboardPage.Visible = true; dashboardPage.BringToFront(); AcceptButton = null;
            connectionText.Text = message; ShowDashboardPage(false); UpdateProfileView(); refreshTimer.Start();
        }
        private void SetBusy(bool value)
        {
            busy = value; loginButton.Enabled = !value; usernameField.Editor.Enabled = !value;
            passwordField.Editor.Enabled = !value; serverField.Editor.Enabled = !value; remember.Enabled = !value;
            if (launchButton != null) launchButton.Enabled = !value && profile != null && profile.Remaining(profile.Find("rmfish")) > 0;
            if (productPower != null) productPower.Enabled = !value && profile != null && profile.Remaining(profile.Find("rmfish")) > 0;
        }

        private async Task RestoreAsync()
        {
            SavedSession saved = store.Load(); if (saved == null || closing) return;
            serverField.Editor.Text = saved.Server; loginMessage.Text = "Восстанавливаем сохранённый вход…"; SetBusy(true);
            int expected = generation;
            try
            {
                ApiClient candidate = new ApiClient(saved.Server);
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
            string username = usernameField.Editor.Text.Trim(), password = passwordField.Editor.Text, address = serverField.Editor.Text;
            if (username.Length == 0 || password.Length == 0) { loginMessage.Text = "Введите логин и пароль."; return; }
            SetBusy(true); loginMessage.Text = "Проверяем данные…"; int expected = generation;
            try
            {
                ApiClient candidate = new ApiClient(address);
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
            catch (Exception) { if (!closing && expected == generation) loginMessage.Text = "Не удалось выполнить вход. Проверьте подключение."; }
            finally { if (!closing && expected == generation) { passwordField.Editor.Text = ""; SetBusy(false); } }
        }

        private async Task RefreshProfileAsync()
        {
            if (refreshing || api == null || String.IsNullOrEmpty(token) || closing) return;
            refreshing = true; int expected = generation; ApiClient current = api; string currentToken = token;
            try
            {
                Profile result = await Task.Run(delegate { return current.GetProfile(currentToken, device); });
                if (closing || expected != generation) return;
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
            ProductInfo fish = profile.Find("rmfish"); long remaining = profile.Remaining(fish); bool active = fish != null && fish.Active && remaining > 0;
            accountName.Text = "●   " + profile.Username; profileUser.Text = profile.Username;
            uidValue.Text = profile.Uid.ToString("D8", CultureInfo.InvariantCulture); profileUid.Text = "UID  " + uidValue.Text;
            profileServer.Text = api == null ? "" : "Сервер  ·  " + api.BaseUrl;
            remainingValue.Text = FormatRemaining(remaining); expiresValue.Text = fish == null ? "—" : FormatDate(fish.ExpiresAt);
            productState.Text = active ? "●  Подписка активна" : "●  Нет активной подписки";
            productState.ForeColor = active ? Theme.Accent : Theme.Warn;
            bool opened = fishForm != null && !fishForm.IsDisposed && lease != null && lease.IsValid;
            statusTitle.Text = opened ? "RMFish открыт" : active ? "Готов к запуску" : "Доступ не активен";
            statusDescription.Text = opened ? "Окно продукта работает внутри RMacro." : active ? "Продукт встроен в RMacro, установка не нужна." : "Обратитесь к администратору для продления.";
            launchButton.Enabled = !busy && active; productPower.Enabled = !busy && active;
            launchButton.Text = opened ? "Показать RMFish   ↗" : "Открыть RMFish   ↗";
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
                if (list.Length > 0) list.Append("\r\n\r\n");
                list.Append(item.Name).Append("   ·   ");
                if (!item.ExpiresAt.HasValue) list.Append("подписка не выдана");
                else if (left <= 0) list.Append("истекла ").Append(FormatDate(item.ExpiresAt));
                else list.Append("осталось ").Append(FormatRemaining(left)).Append("   ·   до ").Append(FormatDate(item.ExpiresAt));
                if (item.Code != "rmfish") list.Append("   ·   запуск пока не поддерживается");
            }
            profileList.SetContent(list.Length == 0 ? "Нет продуктов." : list.ToString());
            if (soonCount > 0)
            {
                warningText.Text = "!   Скоро закончится: " + warning + (soonCount > 2 ? " и ещё " + (soonCount - 2) + " (см. профиль)" : "") + ". Проверьте срок подписки.";
                warningText.ForeColor = Theme.Warn; warningCard.Stroke = Color.FromArgb(110, 88, 53);
            }
            else
            {
                warningText.Text = !String.IsNullOrEmpty(persistentNotice) ? "!   " + persistentNotice : active ?
                    "◆   Подписка подтверждена. Перед рыбалкой проверьте F10 в игре." :
                    "◆   Подписку для RMFish может добавить администратор.";
                warningText.ForeColor = String.IsNullOrEmpty(persistentNotice) ? Theme.Muted : Theme.Warn;
                warningCard.Stroke = Color.FromArgb(35, 77, 69);
            }
            warningCard.Invalidate();
        }

        private async Task LaunchAsync()
        {
            if (busy || api == null || String.IsNullOrEmpty(token) || closing) return;
            if (fishForm != null && !fishForm.IsDisposed && lease != null && lease.IsValid)
            { fishForm.WindowState = FormWindowState.Normal; fishForm.Show(); fishForm.Activate(); return; }
            CloseProduct("Повторная проверка доступа. Запрошена остановка.");
            SetBusy(true); statusTitle.Text = "Проверяем доступ…"; int expected = generation;
            ApiClient current = api; string currentToken = token; bool refreshAfterFailure = false;
            try
            {
                LeaseInfo initial = await Task.Run(delegate { return current.Authorize(currentToken, device, "rmfish"); });
                if (closing || expected != generation) return;
                if (!AcquireFishMutex())
                {
                    MessageBox.Show(this, "RMFish уже открыт. Закройте существующий экземпляр перед запуском через RMacro.", "RMacro", MessageBoxButtons.OK, MessageBoxIcon.Information); return;
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
                    else { MessageBox.Show(this, ex.Message, "RMacro", MessageBoxButtons.OK, MessageBoxIcon.Warning); refreshAfterFailure = true; }
                }
                if (fishForm != null) CloseProduct("Не удалось открыть RMFish. Запрошена остановка.");
                else if (drainingFish == null) ReleaseFishMutex();
            }
            catch (Exception ex)
            {
                if (fishForm != null) CloseProduct("Не удалось открыть RMFish. Запрошена остановка.");
                else if (drainingFish == null) ReleaseFishMutex();
                if (!closing && expected == generation) MessageBox.Show(this, "Не удалось открыть RMFish: " + ex.Message, "RMacro", MessageBoxButtons.OK, MessageBoxIcon.Error);
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
            generation++; api = null; token = null; profile = null; persistentNotice = null; store.Delete(); ShowLogin("Вы вышли из аккаунта.");
            if (previous != null && !String.IsNullOrEmpty(previousToken))
                try { await Task.Run(delegate { previous.Logout(previousToken, device); }); } catch (Exception) { }
        }
    }
}
