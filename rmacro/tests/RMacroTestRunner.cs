using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using RMFish;
using RMacro;

internal static class RMacroTestRunner
{
    private static int count;
    private static Control uiDispatcher;
    private const string User = "fixture_user", UserPassword = "fixture-user-password";
    private const string Admin = "fixture_admin", AdminPassword = "fixture-admin-password";
    private static readonly string Device = new string('a', 64);
    private static readonly string OtherDevice = new string('b', 64);
    private static void Trace(string stage) { Console.WriteLine("STAGE: " + stage); Console.Out.Flush(); }
    private static void Check(bool value, string message)
    { count++; if (!value) throw new Exception("Assertion failed: " + message); }
    private static T Find<T>(Control root, string name) where T : Control
    {
        if (root.Name == name && root is T) return (T)root;
        foreach (Control child in root.Controls) { T found = Find<T>(child, name); if (found != null) return found; }
        return null;
    }
    private static void WaitUntil(Func<bool> test, int milliseconds, string reason)
    {
        Stopwatch clock = Stopwatch.StartNew();
        while (clock.ElapsedMilliseconds < milliseconds)
        {
            if (test()) return; Thread.Sleep(20);
        }
        throw new Exception("Timed out: " + reason);
    }
    private static T Field<T>(object target, string name)
    {
        FieldInfo field = target.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic);
        if (field == null) throw new Exception("Missing field " + name);
        return (T)field.GetValue(target);
    }
    private static void Capture(LoaderForm form, bool dashboard, string name)
    {
        string folder = Environment.GetEnvironmentVariable("RMACRO_UI_SCREENSHOTS");
        if (String.IsNullOrEmpty(folder)) return;
        Directory.CreateDirectory(folder);
        Control header = Find<Control>(form, "loaderHeader");
        using (Bitmap all = new Bitmap(form.ClientSize.Width, form.ClientSize.Height))
        using (Graphics graphics = Graphics.FromImage(all))
        {
            graphics.Clear(Theme.Accent);
            using (Bitmap top = new Bitmap(header.Width, header.Height))
            { header.DrawToBitmap(top, new Rectangle(Point.Empty, top.Size)); graphics.DrawImageUnscaled(top, header.Location); }
            if (!dashboard)
            {
                Control login = Find<Control>(form, "loginPage");
                using (Bitmap page = new Bitmap(login.Width, login.Height))
                { login.DrawToBitmap(page, new Rectangle(Point.Empty, page.Size)); graphics.DrawImageUnscaled(page, login.Location); }
            }
            else
            {
                Control side = Find<Control>(form, "loaderSidebar"), work = Find<Control>(form, "workspacePage");
                using (Bitmap left = new Bitmap(side.Width, side.Height))
                { side.DrawToBitmap(left, new Rectangle(Point.Empty, left.Size)); graphics.DrawImageUnscaled(left, 1, 47); }
                using (Bitmap right = new Bitmap(work.Width, work.Height))
                { work.DrawToBitmap(right, new Rectangle(Point.Empty, right.Size)); graphics.DrawImageUnscaled(right, 191, 47); }
            }
            all.Save(Path.Combine(folder, name + ".png"), ImageFormat.Png);
        }
    }
    private static string AdminToken(ApiClient api)
    {
        return JsonValues.String(api.Request("/api/admin/login", ApiClient.Body("username", Admin, "password", AdminPassword), null, null), "token");
    }
    private static void Reset(ApiClient api, string admin, long uid)
    { api.Request("/api/admin/users/" + uid + "/reset-hwid", ApiClient.Body(), admin, null); }
    private static void CheckCore(ApiClient api, string root)
    {
        try { new ApiClient("http://192.168.1.7:8765"); throw new Exception("Insecure remote HTTP accepted"); }
        catch (ApiException ex) { Check(ex.Code == "HTTPS_REQUIRED", "non-local plaintext must be rejected"); }
        try { new ApiClient("https://user:pass@example.com"); throw new Exception("Credentials in URL accepted"); }
        catch (ApiException ex) { Check(ex.Code == "BAD_ADDRESS", "URL credentials must be rejected"); }
        Check(new ApiClient("https://example.com").BaseUrl == "https://example.com", "HTTPS address rejected");
        Trace("API login");
        string token;
        Profile profile = api.Login(User, UserPassword, Device, out token);
        Check(profile.Uid > 0 && profile.Username == User, "login profile/UID");
        Check(profile.Find("rmfish") != null && profile.Remaining(profile.Find("rmfish")) > 0, "subscription in login");
        Check(api.GetProfile(token, Device).Uid == profile.Uid, "saved token profile");
        try { api.GetProfile(token, OtherDevice); throw new Exception("wrong device accepted"); }
        catch (ApiException ex) { Check(ex.Status == 401, "session must be bound to the device"); }
        Trace("DPAPI persistence");
        string sessionDir = Path.Combine(root, "session-test");
        SessionStore store = new SessionStore(sessionDir); store.Save(api.BaseUrl, token);
        SavedSession saved = store.Load();
        Check(saved != null && saved.Server == api.BaseUrl && saved.Token == token, "DPAPI roundtrip");
        Check(!Encoding.UTF8.GetString(File.ReadAllBytes(Path.Combine(sessionDir, "session.dat"))).Contains(token), "token stored in plaintext");
        store.Save(api.BaseUrl, token); Check(store.Load() != null, "atomic session replacement");
        store.Delete(); Check(store.Load() == null, "logout deletes session");
        Trace("lease and remote reset");
        string admin = AdminToken(api);
        LeaseInfo initial = api.Authorize(token, Device, "rmfish");
        using (ManualResetEvent stopped = new ManualResetEvent(false))
        using (ProductLease monitor = new ProductLease(initial, delegate { return api.Authorize(token, Device, "rmfish"); },
            delegate(string reason) { stopped.Set(); }, 4000, 250))
        {
            Check(monitor.IsValid, "new product lease"); monitor.Start(); Reset(api, admin, profile.Uid);
            Check(stopped.WaitOne(5000), "remote HWID reset must revoke a running lease");
            Check(!monitor.IsValid, "revoked lease remains denied");
        }
        Trace("offline grace");
        using (ManualResetEvent stopped = new ManualResetEvent(false))
        using (ProductLease offline = new ProductLease(new LeaseInfo { ServerTime = 1000, ExpiresAt = 2000 },
            delegate { throw new ApiException(0, "NETWORK", "offline"); }, delegate(string reason) { stopped.Set(); }, 1200, 250))
        {
            Check(offline.IsValid, "offline test lease starts valid"); offline.Start();
            Check(stopped.WaitOne(4000), "offline grace must expire without UI pumping");
            Check(!offline.IsValid, "offline lease remains denied");
        }
    }
    // Use a real WinForms message loop, just like production. The test thread
    // can deliberately block it to prove the lease stop remains independent.
    private sealed class UiHost : IDisposable
    {
        public LoaderForm Form;
        private readonly ApplicationContext context;

        public UiHost(ApplicationContext context, string directory)
        {
            this.context = context;
            // Creation must be dispatched to the UI thread; supplied context is
            // serviced by the single Application.Run on Main's STA thread.
            if (uiDispatcher == null) throw new Exception("UI dispatcher unavailable");
            uiDispatcher.Invoke((MethodInvoker)delegate
            {
                Form = new LoaderForm(directory, Device);
                context.MainForm = Form;
                Form.Show();
            });
        }
        public void Run(Action<LoaderForm> action)
        {
            Form.Invoke((MethodInvoker)delegate { action(Form); });
        }
        public T Value<T>(Func<LoaderForm, T> action)
        {
            T value = default(T);
            Run(delegate(LoaderForm form) { value = action(form); });
            return value;
        }
        public void Dispose()
        {
            Run(delegate(LoaderForm f) { context.MainForm = null; f.Close(); });
        }
    }

    private static void TraceUi(LoaderForm form)
    {
        Profile data = Field<Profile>(form, "profile");
        Label warning = Find<Label>(form, "warningText"), login = Find<Label>(form, "loginMessage");
        Trace("UI state: busy=" + Field<bool>(form, "busy") + " dashboard=" + Find<Control>(form, "dashboardPage").Visible +
            " login=" + Find<Control>(form, "loginPage").Visible + " profile=" + (data != null) +
            " bannerBytes=" + Convert.ToBase64String(Encoding.UTF8.GetBytes(warning.Text)) +
            " loginBytes=" + Convert.ToBase64String(Encoding.UTF8.GetBytes(login.Text)));
    }

    private static void CheckGui(ApiClient api, string root, ApplicationContext context)
    {
        Trace("open login window");
        string local = Path.Combine(root, "profile", "RMacro");
        Directory.CreateDirectory(local);
        using (UiHost first = new UiHost(context, local))
        {
            first.Run(delegate(LoaderForm form)
            {
                Check(form.FormBorderStyle == FormBorderStyle.None, "branded title bar");
                Check(Find<Control>(form, "loginPage").Visible, "login page opens first");
                Check(!Find<Control>(form, "dashboardPage").Visible, "dashboard must be hidden before login");
                Capture(form, false, "01-login");
                Find<TextBox>(form, "usernameEditor").Text = User;
                Find<TextBox>(form, "passwordEditor").Text = UserPassword;
                Find<TextBox>(form, "serverEditor").Text = api.BaseUrl;
                Trace("submit GUI login");
                Find<SoftButton>(form, "loginButton").PerformClick();
            });
            WaitUntil(delegate { return first.Value(delegate(LoaderForm f) { return Find<Control>(f, "dashboardPage").Visible && !Field<bool>(f, "busy"); }); }, 12000, "login did not complete");
            first.Run(delegate(LoaderForm form)
            {
                Check(Find<TextBox>(form, "passwordEditor").Text.Length == 0, "password remains in input");
                string banner = Find<Label>(form, "warningText").Text;
                Check(banner.Contains("RMFish"), "soon-expiring subscription warning; banner length=" + banner.Length);
                Check(Find<Label>(form, "uidValue").Text.Length >= 8, "UID shown");
                Check(new SessionStore(local).Load() != null, "remembered login saved");
                Trace("GUI login complete"); Capture(form, true, "02-products");
            });
        }
        Trace("restore saved session");
        using (UiHost restored = new UiHost(context, local))
        {
            try { WaitUntil(delegate { return restored.Value(delegate(LoaderForm f) { return Find<Control>(f, "dashboardPage").Visible && !Field<bool>(f, "busy"); }); }, 12000, "automatic login"); }
            catch { restored.Run(TraceUi); throw; }
            restored.Run(delegate(LoaderForm form)
            {
                Check(Find<Label>(form, "warningText").Text.Contains("Скоро"), "warning shown on saved login");
                Find<SoftButton>(form, "navProfile").PerformClick();
                Check(Find<Control>(form, "profilePage").Visible, "profile navigation");
                Check(Find<DarkLogBox>(form, "subscriptionList").Editor.Text.Contains("RMFish"), "profile lists product");
                Find<SoftButton>(form, "navProducts").PerformClick();
                Trace("open embedded product"); Find<SoftButton>(form, "launchButton").PerformClick();
            });
            WaitUntil(delegate { return restored.Value(delegate(LoaderForm f) { MainForm fish = Field<MainForm>(f, "fishForm"); return fish != null && fish.Visible; }); }, 12000, "embedded RMFish opens");
            Trace("product window opened");
            MainForm product = restored.Value(delegate(LoaderForm f) { return Field<MainForm>(f, "fishForm"); });
            ProductLease lease = restored.Value(delegate(LoaderForm f) { return Field<ProductLease>(f, "lease"); });
            Check(lease.IsValid, "active GUI lease");
            Check(!File.Exists(Path.Combine(local, "Runtime", "RMFish.exe")) && !File.Exists(Path.Combine(local, "Runtime", "RMFish.ps1")), "no separate executable or source script installed");
            FishingEngine engine = Field<FishingEngine>(product, "engine");
            restored.Run(delegate(LoaderForm form)
            {
                PowerButton start = Find<PowerButton>(product, "powerButton");
                Check(start != null && start.Enabled, "RMFish power control is available");
                Trace("start worker"); start.PerformClick();
            });
            WaitUntil(delegate { return engine.Snapshot().Running; }, 5000, "RMFish worker starts without GTA5");
            long uid = restored.Value(delegate(LoaderForm f) { return Field<Profile>(f, "profile").Uid; });
            MethodInfo startFishing = typeof(MainForm).GetMethod("StartFishing", BindingFlags.Instance | BindingFlags.NonPublic);
            using (ManualResetEvent blocked = new ManualResetEvent(false))
            using (ManualResetEvent release = new ManualResetEvent(false))
            using (ManualResetEvent f8Complete = new ManualResetEvent(false))
            {
                Exception f8Error = null;
                restored.Form.BeginInvoke((MethodInvoker)delegate
                {
                    blocked.Set();
                    try { release.WaitOne(); startFishing.Invoke(product, null); }
                    catch (Exception ex) { f8Error = ex; }
                    finally { f8Complete.Set(); }
                });
                Check(blocked.WaitOne(5000), "UI could not be blocked");
                try
                {
                    Trace("revoke worker from server while UI blocked");
                    string admin = AdminToken(api); Reset(api, admin, uid);
                    MethodInfo renew = typeof(ProductLease).GetMethod("Renew", BindingFlags.Instance | BindingFlags.NonPublic);
                    Check(renew != null, "lease renew method");
                    Thread renewal = new Thread(delegate() { renew.Invoke(lease, null); }); renewal.IsBackground = true; renewal.Start();
                    Check(renewal.Join(7000), "lease renewal while UI blocked");
                    Check(!lease.IsValid, "reset revokes lease while UI is blocked");
                    Check(engine.WaitForStop(5000), "revocation requested an independent worker stop");
                    Trace("worker stopped while UI blocked");
                }
                finally { release.Set(); }
                Check(f8Complete.WaitOne(7000), "F8 gate check did not return");
                if (f8Error != null) throw new Exception("F8 gate test failed", f8Error);
                Check(!engine.Snapshot().Running, "revoked F8/start path cannot restart");
            }
            Trace("logout and close");
            restored.Run(delegate(LoaderForm form)
            {
                if (!product.IsDisposed) product.Close();
                if (Find<Control>(form, "dashboardPage").Visible) Find<SoftButton>(form, "logoutButton").PerformClick();
            });
            WaitUntil(delegate { return new SessionStore(local).Load() == null; }, 7000, "logout clears remembered session");
            Check(new SessionStore(local).Load() == null, "logout clears remembered session");
        }
    }
    [STAThread]
    public static int Main()
    {
        string root = Path.Combine(Path.GetTempPath(), "rmacro-gui-test-" + Guid.NewGuid().ToString("N"));
        try
        {
            Directory.CreateDirectory(root);
            string port = Environment.GetEnvironmentVariable("RMACRO_TEST_PORT");
            if (String.IsNullOrEmpty(port)) throw new Exception("RMACRO_TEST_PORT is required");
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            ApiClient api = new ApiClient("http://127.0.0.1:" + port);
            CheckCore(api, root);
            using (ApplicationContext context = new ApplicationContext())
            {
                Exception uiError = null;
                using (ManualResetEvent finished = new ManualResetEvent(false))
                using (Control dispatcher = new Control())
                {
                    dispatcher.CreateControl(); uiDispatcher = dispatcher;
                    dispatcher.BeginInvoke((MethodInvoker)delegate
                    {
                        Thread tester = new Thread(delegate()
                        {
                            try { CheckGui(api, root, context); }
                            catch (Exception ex) { uiError = ex; }
                            finally { finished.Set(); dispatcher.BeginInvoke((MethodInvoker)delegate { context.ExitThread(); }); }
                        });
                        tester.IsBackground = true; tester.Start();
                    });
                    Application.Run(context);
                    if (!finished.WaitOne(10000)) throw new Exception("GUI test did not finish");
                    if (uiError != null) throw new Exception("GUI integration failed", uiError);
                }
            }
            Console.WriteLine("PASS: " + count + " RMacro API, DPAPI, UI, authorization and independent stop assertions.");
            Console.WriteLine("No real GTA5 or physical keyboard was tested.");
            return 0;
        }
        catch (Exception ex) { Console.Error.WriteLine(ex); return 1; }
        finally { try { Directory.Delete(root, true); } catch (Exception) { } }
    }
}
