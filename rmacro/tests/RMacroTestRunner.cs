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
    private const string User = "fixture_user", UserPassword = "fixture-user-password";
    private const string Admin = "fixture_admin", AdminPassword = "fixture-admin-password";
    private static readonly string Device = new string('a', 64);
    private static readonly string OtherDevice = new string('b', 64);
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
            Application.DoEvents(); if (test()) return; Thread.Sleep(20);
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
        string token;
        Profile profile = api.Login(User, UserPassword, Device, out token);
        Check(profile.Uid > 0 && profile.Username == User, "login profile/UID");
        Check(profile.Find("rmfish") != null && profile.Remaining(profile.Find("rmfish")) > 0, "subscription in login");
        Check(api.GetProfile(token, Device).Uid == profile.Uid, "saved token profile");
        try { api.GetProfile(token, OtherDevice); throw new Exception("wrong device accepted"); }
        catch (ApiException ex) { Check(ex.Status == 401, "session must be bound to the device"); }
        string sessionDir = Path.Combine(root, "session-test");
        SessionStore store = new SessionStore(sessionDir); store.Save(api.BaseUrl, token);
        SavedSession saved = store.Load();
        Check(saved != null && saved.Server == api.BaseUrl && saved.Token == token, "DPAPI roundtrip");
        Check(!Encoding.UTF8.GetString(File.ReadAllBytes(Path.Combine(sessionDir, "session.dat"))).Contains(token), "token stored in plaintext");
        store.Save(api.BaseUrl, token); Check(store.Load() != null, "atomic session replacement");
        store.Delete(); Check(store.Load() == null, "logout deletes session");
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
        using (ManualResetEvent stopped = new ManualResetEvent(false))
        using (ProductLease offline = new ProductLease(new LeaseInfo { ServerTime = 1000, ExpiresAt = 2000 },
            delegate { throw new ApiException(0, "NETWORK", "offline"); }, delegate(string reason) { stopped.Set(); }, 1200, 250))
        {
            Check(offline.IsValid, "offline test lease starts valid"); offline.Start();
            Check(stopped.WaitOne(4000), "offline grace must expire without UI pumping");
            Check(!offline.IsValid, "offline lease remains denied");
        }
    }
    private static void CheckGui(ApiClient api, string root)
    {
        string local = Path.Combine(root, "profile", "RMacro");
        Directory.CreateDirectory(local);
        using (LoaderForm first = new LoaderForm(local, Device))
        {
            first.Show(); Application.DoEvents();
            Check(first.FormBorderStyle == FormBorderStyle.None, "branded title bar");
            Check(Find<Control>(first, "loginPage").Visible, "login page opens first");
            Capture(first, false, "01-login");
            Find<TextBox>(first, "usernameEditor").Text = User;
            Find<TextBox>(first, "passwordEditor").Text = UserPassword;
            Find<TextBox>(first, "serverEditor").Text = api.BaseUrl;
            Find<SoftButton>(first, "loginButton").PerformClick();
            WaitUntil(delegate { return Find<Control>(first, "dashboardPage").Visible; }, 12000,
                "login: " + Find<Label>(first, "loginMessage").Text);
            Check(Find<TextBox>(first, "passwordEditor").Text.Length == 0, "password remains in input");
            Check(Find<Label>(first, "warningText").Text.Contains("RMFish"), "soon-expiring subscription warning");
            Check(Find<Label>(first, "uidValue").Text.Length >= 8, "UID shown");
            Check(new SessionStore(local).Load() != null, "remembered login saved");
            Capture(first, true, "02-products");
            first.Close(); Application.DoEvents();
        }
        using (LoaderForm restored = new LoaderForm(local, Device))
        {
            restored.Show();
            WaitUntil(delegate { return Find<Control>(restored, "dashboardPage").Visible; }, 12000, "automatic login");
            Check(Find<Label>(restored, "warningText").Text.Contains("Скоро"), "warning shown on saved login");
            Find<SoftButton>(restored, "navProfile").PerformClick();
            Check(Find<Control>(restored, "profilePage").Visible, "profile navigation");
            Check(Find<DarkLogBox>(restored, "subscriptionList").Editor.Text.Contains("RMFish"), "profile lists product");
            Find<SoftButton>(restored, "navProducts").PerformClick();
            Find<SoftButton>(restored, "launchButton").PerformClick();
            WaitUntil(delegate { MainForm fish = Field<MainForm>(restored, "fishForm"); return fish != null && fish.Visible; }, 12000, "embedded RMFish opens");
            MainForm product = Field<MainForm>(restored, "fishForm");
            ProductLease lease = Field<ProductLease>(restored, "lease");
            Check(lease.IsValid, "active GUI lease");
            Check(!File.Exists(Path.Combine(local, "Runtime", "RMFish.exe")) && !File.Exists(Path.Combine(local, "Runtime", "RMFish.ps1")), "no separate executable or source script installed");
            PowerButton start = Find<PowerButton>(product, "powerButton");
            Check(start != null && start.Enabled, "RMFish power control is available");
            start.PerformClick();
            FishingEngine engine = Field<FishingEngine>(product, "engine");
            WaitUntil(delegate { return engine.Snapshot().Running; }, 5000, "RMFish worker starts without GTA5");
            string admin = AdminToken(api); long uid = Field<Profile>(restored, "profile").Uid;
            Reset(api, admin, uid);
            MethodInfo renew = typeof(ProductLease).GetMethod("Renew", BindingFlags.Instance | BindingFlags.NonPublic);
            Check(renew != null, "lease renew method");
            Thread renewal = new Thread(delegate() { renew.Invoke(lease, null); }); renewal.IsBackground = true; renewal.Start();
            // Do not pump the UI: the lease callback must stop the worker independently.
            Check(renewal.Join(7000), "lease renewal while UI blocked");
            Check(!lease.IsValid, "reset revokes lease while UI is blocked");
            Check(engine.WaitForStop(5000), "revocation requested an independent worker stop");
            MethodInfo startFishing = typeof(MainForm).GetMethod("StartFishing", BindingFlags.Instance | BindingFlags.NonPublic);
            startFishing.Invoke(product, null); Application.DoEvents();
            Check(!engine.Snapshot().Running, "revoked F8/start path cannot restart");
            product.Close(); Application.DoEvents();
            Find<SoftButton>(restored, "logoutButton").PerformClick(); Application.DoEvents();
            Check(new SessionStore(local).Load() == null, "logout clears remembered session");
            restored.Close(); Application.DoEvents();
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
            CheckCore(api, root); CheckGui(api, root);
            Console.WriteLine("PASS: " + count + " RMacro API, DPAPI, UI, authorization and independent stop assertions.");
            Console.WriteLine("No real GTA5 or physical keyboard was tested.");
            return 0;
        }
        catch (Exception ex) { Console.Error.WriteLine(ex); return 1; }
        finally { try { Directory.Delete(root, true); } catch (Exception) { } }
    }
}
