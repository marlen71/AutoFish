using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using RMFish;

// Windows CI only. This sends synthetic, system-wide keys on an isolated VM.
public static class GuiSafetyRunner
{
    [DllImport("user32.dll")] private static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);
    [DllImport("user32.dll")] private static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
    [DllImport("user32.dll")] private static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(IntPtr handle);

    private static void Check(bool value, string message)
    {
        if (!value) throw new Exception(message);
    }

    private static bool WaitUntil(Func<bool> condition, int milliseconds)
    {
        Stopwatch clock = Stopwatch.StartNew();
        while (!condition() && clock.ElapsedMilliseconds < milliseconds) Thread.Sleep(10);
        return condition();
    }

    private static bool Logged(FishingEngine engine, string text)
    {
        foreach (string line in engine.Events()) if (line.Contains(text)) return true;
        return false;
    }

    private static T Find<T>(Control root, string name) where T : Control
    {
        Control[] matches = root.Controls.Find(name, true);
        Check(matches.Length == 1 && matches[0] is T, "missing or duplicate control " + name);
        return (T)matches[0];
    }

    private static void CheckLayout(Control parent)
    {
        foreach (Control child in parent.Controls)
        {
            Check(child.Left >= 0 && child.Top >= 0 && child.Right <= parent.ClientSize.Width &&
                child.Bottom <= parent.ClientSize.Height,
                "control outside parent: " + child.Name + " (" + child.GetType().Name + ")");
            // Native text/numeric controls have implementation children which
            // deliberately overlap their own border; inspect our layout only.
            if (child is Panel) CheckLayout(child);
        }
    }

    private static void Refresh(MainForm form)
    {
        MethodInfo refresh = typeof(MainForm).GetMethod("RefreshView", BindingFlags.Instance | BindingFlags.NonPublic);
        Check(refresh != null, "view refresh is missing");
        refresh.Invoke(form, null);
    }

    private static void Capture(MainForm form, int pageIndex)
    {
        string directory = Environment.GetEnvironmentVariable("RMFISH_UI_SCREENSHOT_DIR");
        if (String.IsNullOrEmpty(directory)) return;
        Directory.CreateDirectory(directory);
        Panel sidebar = Find<Panel>(form, "sidebar");
        Panel page = Find<Panel>(form, "page" + pageIndex);
        WindowHeader header = Find<WindowHeader>(form, "windowHeader");
        // Drawing the whole form can include hidden sibling pages; composite
        // only the sidebar and the selected page instead.
        using (Bitmap bitmap = new Bitmap(form.ClientSize.Width, form.ClientSize.Height))
        using (Bitmap left = new Bitmap(sidebar.Width, sidebar.Height))
        using (Bitmap right = new Bitmap(page.Width, page.Height))
        using (Bitmap top = new Bitmap(header.Width, header.Height))
        using (Graphics graphics = Graphics.FromImage(bitmap))
        {
            graphics.Clear(Theme.Accent);
            sidebar.DrawToBitmap(left, new Rectangle(Point.Empty, left.Size));
            page.DrawToBitmap(right, new Rectangle(Point.Empty, right.Size));
            header.DrawToBitmap(top, new Rectangle(Point.Empty, top.Size));
            graphics.DrawImageUnscaled(top, header.Location);
            graphics.DrawImageUnscaled(left, sidebar.Location);
            graphics.DrawImageUnscaled(right, page.Location);
            bitmap.Save(Path.Combine(directory, "page-" + pageIndex + ".png"), ImageFormat.Png);
        }
    }

    private static void CheckMenu(MainForm form)
    {
        CheckLayout(form);
        Check(form.FormBorderStyle == FormBorderStyle.None && form.ShowInTaskbar, "branded window chrome is missing");
        WindowButton minimize = Find<WindowButton>(form, "minimizeWindow");
        Check(minimize.AccessibleName.Length > 0 && Find<WindowButton>(form, "closeWindow").AccessibleName.Length > 0,
            "window controls are not accessible");
        minimize.PerformClick();
        Check(form.WindowState == FormWindowState.Minimized, "custom minimize button did not minimize the window");
        form.WindowState = FormWindowState.Normal;
        Check(form.WindowState == FormWindowState.Normal, "window did not restore after minimizing");
        PictureBox brand = Find<PictureBox>(form, "brandLogo");
        Check(brand.Image != null && brand.Image.Width > 100, "source-mode logo did not load");
        Check(form.Icon != null, "source-mode icon did not load");
        using (Bitmap icon = form.Icon.ToBitmap())
        {
            bool mint = false, white = false;
            for (int y = 0; y < icon.Height; y++)
                for (int x = 0; x < icon.Width; x++)
                {
                    Color c = icon.GetPixel(x, y);
                    if (c.A > 128 && c.G > 140 && c.G > c.R * 1.4 && c.B > 80) mint = true;
                    if (c.A > 128 && c.R > 200 && c.G > 200 && c.B > 200) white = true;
                }
            Check(mint && white, "source-mode icon is not the supplied RMFish artwork");
        }
        StageStrip stages = Find<StageStrip>(form, "stages");
        Check(stages.ActiveIndex == -1, "idle dashboard shows a false active stage");
        Check(Find<Label>(form, "castValue").Text == "0" && Find<Label>(form, "reelValue").Text == "0",
            "initial counters are not zero");
        for (int i = 0; i < 4; i++)
        {
            Find<SoftButton>(form, "navigation" + i).PerformClick();
            Check(Find<Panel>(form, "page" + i).Visible, "navigation did not open page " + i);
            for (int other = 0; other < 4; other++)
                if (other != i) Check(!Find<Panel>(form, "page" + other).Visible, "multiple pages are visible");
            Capture(form, i);
        }
        SpeedSlider slider = Find<SpeedSlider>(form, "speedSlider");
        Find<SoftButton>(form, "navigation1").PerformClick();
        DarkNumberInput clicks = Find<DarkNumberInput>(form, "clickInput");
        slider.Value = 125;
        Check(clicks.Value == 125, "dashboard slider did not update reeling interval");
        MethodInfo keyDown = typeof(SpeedSlider).GetMethod("OnKeyDown", BindingFlags.Instance | BindingFlags.NonPublic);
        Check(keyDown != null && slider.AccessibleRole == AccessibleRole.Slider, "slider keyboard/accessibility support is missing");
        keyDown.Invoke(slider, new object[] { new KeyEventArgs(Keys.Right) });
        Check(slider.Value == 120 && clicks.Value == 120, "right arrow should make reeling faster");
        keyDown.Invoke(slider, new object[] { new KeyEventArgs(Keys.Left) });
        Check(slider.Value == 125 && clicks.Value == 125, "left arrow should make reeling slower");
        keyDown.Invoke(slider, new object[] { new KeyEventArgs(Keys.Home) });
        Check(slider.Value == 250, "Home should select the slow end");
        keyDown.Invoke(slider, new object[] { new KeyEventArgs(Keys.End) });
        Check(slider.Value == 35, "End should select the fast end");
        clicks.Value = 40;
        Check(slider.Value == 40, "settings did not update dashboard slider");
        slider.Value = -1;
        Check(clicks.Value == 35, "slider did not clamp to the safe minimum");
        slider.Value = 999;
        Check(clicks.Value == 250, "slider did not clamp to the safe maximum");
        clicks.Value = 70;
        MethodInfo getOptions = typeof(MainForm).GetMethod("GetOptions", BindingFlags.Instance | BindingFlags.NonPublic);
        Check(getOptions != null && ((EngineOptions)getOptions.Invoke(form, null)).ReelClickMilliseconds == 70,
            "slider is not connected to real engine options");
        DarkNumberInput limit = Find<DarkNumberInput>(form, "sessionInput");
        Check(limit.Minimum == 1 && limit.Maximum == 1800 && limit.Value >= 1, "mandatory session limit changed");
        limit.Editor.Text = "0";
        EngineOptions low = (EngineOptions)getOptions.Invoke(form, null);
        Check(low.SessionLimitSeconds == 1 && limit.Editor.Text == "1", "typed session limit did not clamp before start");
        limit.Editor.Text = "9999";
        Check(((EngineOptions)getOptions.Invoke(form, null)).SessionLimitSeconds == 1800, "maximum session limit was not enforced");
        limit.Value = 120;
        clicks.Editor.Text = "29";
        clicks.CommitEdit();
        Check(clicks.Value == 35 && slider.Value == 35, "typed interval did not clamp and synchronize");
        clicks.Editor.Text = "80";
        Check(clicks.Value == 80 && slider.Value == 80, "typing did not synchronize the real speed setting");
        Find<NumberStepButton>(clicks, "increase").PerformClick();
        Check(clicks.Value == 85 && slider.Value == 85, "plus button did not change the interval");
        Find<NumberStepButton>(clicks, "decrease").PerformClick();
        Check(clicks.Value == 80 && slider.Value == 80, "minus button did not change the interval");
        clicks.Value = 70;
        Find<CheckBox>(form, "minimizeInput").Checked = false;
        Find<SoftButton>(form, "saveSettings").PerformClick();
        Check(Find<Label>(form, "settingsFeedback").Text.Contains("Сохранено"), "settings did not show inline save confirmation");

        Find<SoftButton>(form, "navigation3").PerformClick();
        DarkLogBox log = Find<DarkLogBox>(form, "eventLog");
        Check(log.Editor.ReadOnly && log.Editor.ScrollBars == ScrollBars.None, "journal is not read-only or uses a native scrollbar");
        string[] lines = new string[90];
        for (int i = 0; i < lines.Length; i++) lines[i] = "Событие " + i + " — проверка содержимого журнала";
        string manyLines = String.Join("\r\n", lines);
        log.SetContent(manyLines);
        log.ScrollToLine(Int32.MaxValue);
        Check(log.MaximumFirstLine > 0 && log.FirstVisibleLine > 0, "journal cannot scroll to the bottom");
        int beforeWheel = log.FirstVisibleLine;
        MethodInfo wndProc = typeof(LogTextBox).GetMethod("WndProc", BindingFlags.Instance | BindingFlags.NonPublic);
        Message wheel = Message.Create(log.Editor.Handle, 0x020A, new IntPtr(120 << 16), IntPtr.Zero);
        wndProc.Invoke(log.Editor, new object[] { wheel });
        Check(log.FirstVisibleLine < beforeWheel, "mouse wheel did not scroll the journal");
        log.ScrollToLine(0);
        Check(log.FirstVisibleLine == 0, "journal cannot scroll to the top");
        log.Editor.Select(0, 7);
        log.SetContent(manyLines + "\r\nНовое событие");
        Check(log.FirstVisibleLine == 0 && log.Editor.SelectionLength == 7, "new events disturbed journal reading/selection");
        LogScrollBar bar = Find<LogScrollBar>(form, "eventLogScroll");
        MethodInfo mouseDown = typeof(LogScrollBar).GetMethod("OnMouseDown", BindingFlags.Instance | BindingFlags.NonPublic);
        MethodInfo mouseUp = typeof(LogScrollBar).GetMethod("OnMouseUp", BindingFlags.Instance | BindingFlags.NonPublic);
        mouseDown.Invoke(bar, new object[] { new MouseEventArgs(MouseButtons.Left, 1, 6, bar.Height - 5, 0) });
        mouseUp.Invoke(bar, new object[] { new MouseEventArgs(MouseButtons.Left, 1, 6, bar.Height - 5, 0) });
        Check(log.FirstVisibleLine > 0, "themed journal scrollbar did not move the text");
        FishingEngine currentEngine = (FishingEngine)typeof(MainForm).GetField("engine", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(form);
        log.SetContent(String.Join("\r\n", currentEngine.Events()));
        Find<SoftButton>(form, "navigation0").PerformClick();
    }

    private static void CheckWindowDrag(MainForm form)
    {
        Point origin = Point.Empty;
        form.Invoke((MethodInvoker)delegate
        {
            form.WindowState = FormWindowState.Normal;
            form.Location = new Point(80, 30);
            form.Activate();
            SetForegroundWindow(form.Handle);
            origin = form.Location;
        });
        try
        {
            Check(SetCursorPos(origin.X + 350, origin.Y + 18), "could not position synthetic mouse for drag");
            mouse_event(0x0002, 0, 0, 0, UIntPtr.Zero);
            Thread.Sleep(150);
            Check(SetCursorPos(origin.X + 400, origin.Y + 38), "could not move synthetic mouse for drag");
            Thread.Sleep(150);
        }
        finally { mouse_event(0x0004, 0, 0, 0, UIntPtr.Zero); }
        Check(WaitUntil(delegate
        {
            Point current = Point.Empty;
            form.Invoke((MethodInvoker)delegate { current = form.Location; });
            return current != origin;
        }, 5000), "dragging the custom title bar did not move the window");
    }

    public static int Run(string directory)
    {
        ManualResetEvent shown = new ManualResetEvent(false);
        ManualResetEvent uiBlocked = new ManualResetEvent(false);
        ManualResetEvent releaseUi = new ManualResetEvent(false);
        MainForm form = null;
        Exception uiError = null;
        Thread ui = new Thread(delegate()
        {
            try
            {
                WindowsNative.EnableDpiAwareness();
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                // Keep test settings and STOP.txt out of the real user profile.
                using (MainForm window = new MainForm(directory, directory))
                {
                    form = window;
                    window.Shown += delegate { shown.Set(); };
                    Application.Run(window);
                }
            }
            catch (Exception ex) { uiError = ex; shown.Set(); }
        });
        ui.IsBackground = true;
        ui.SetApartmentState(ApartmentState.STA);
        ui.Start();
        int result = 0;
        try
        {
            Check(shown.WaitOne(30000), "GUI did not open");
            if (uiError != null) throw new Exception("GUI failed to open", uiError);
            Check(form != null, "main form is missing");
            FieldInfo field = typeof(MainForm).GetField("engine", BindingFlags.Instance | BindingFlags.NonPublic);
            Check(field != null, "engine field is missing");
            FishingEngine engine = (FishingEngine)field.GetValue(form);

            form.Invoke((MethodInvoker)delegate { CheckMenu(form); });
            CheckWindowDrag(form);
            form.Invoke((MethodInvoker)delegate { Find<PowerButton>(form, "powerButton").PerformClick(); });
            Check(WaitUntil(delegate { return engine.Snapshot().Running && engine.Snapshot().Phase == FishingPhase.Paused; }, 5000),
                "power button did not start and pause the worker without GTA5");
            string saved = Path.Combine(directory, "RMFish", "settings.ini");
            Check(File.Exists(saved) && File.ReadAllText(saved).Contains("reel_click_ms=70"),
                "dashboard speed was not saved on start");
            form.Invoke((MethodInvoker)delegate
            {
                Refresh(form);
                Check(Find<StageStrip>(form, "stages").ActiveIndex == -1, "paused bot shows an active fishing stage");
                Find<SoftButton>(form, "navigation1").PerformClick();
                Refresh(form);
                Find<SoftButton>(form, "sideStopButton").PerformClick();
            });
            Check(WaitUntil(delegate { return !engine.Snapshot().Running; }, 5000) && engine.WaitForStop(2000),
                "sidebar stop button did not stop the worker from settings");
            form.Invoke((MethodInvoker)delegate
            {
                Find<SoftButton>(form, "navigation0").PerformClick();
                Refresh(form); Find<PowerButton>(form, "powerButton").PerformClick();
            });
            Check(WaitUntil(delegate { return engine.Snapshot().Running; }, 5000), "power button did not restart the worker");
            form.Invoke((MethodInvoker)delegate { Refresh(form); Find<SoftButton>(form, "stopButton").PerformClick(); });
            Check(WaitUntil(delegate { return !engine.Snapshot().Running; }, 5000) && engine.WaitForStop(2000),
                "dashboard stop button did not stop the worker");
            form.Invoke((MethodInvoker)delegate { Refresh(form); Find<PowerButton>(form, "powerButton").PerformClick(); });
            Check(WaitUntil(delegate { return engine.Snapshot().Running; }, 5000), "power button did not restart");
            form.Invoke((MethodInvoker)delegate { Refresh(form); Find<PowerButton>(form, "powerButton").PerformClick(); });
            Check(WaitUntil(delegate { return !engine.Snapshot().Running; }, 5000) && engine.WaitForStop(2000),
                "power button did not request stop");
            form.Invoke((MethodInvoker)delegate { Refresh(form); Find<PowerButton>(form, "powerButton").PerformClick(); });
            Check(WaitUntil(delegate { return engine.Snapshot().Phase == FishingPhase.Paused; }, 5000),
                "worker did not start for emergency-key test");

            // Block the actual WinForms message loop. WM_HOTKEY cannot be
            // processed until releaseUi is set, but the safety poller can run.
            form.BeginInvoke((MethodInvoker)delegate { uiBlocked.Set(); releaseUi.WaitOne(); });
            Check(uiBlocked.WaitOne(5000), "could not block the UI thread for the test");
            keybd_event(SafetyKeyMonitor.F9, 0, 0, UIntPtr.Zero);
            Check(WaitUntil(delegate { return Logged(engine, "Диагностика:"); }, 5000),
                "F9 did not launch background diagnostics while the UI was blocked");
            keybd_event(SafetyKeyMonitor.F9, 0, 2, UIntPtr.Zero);
            keybd_event(SafetyKeyMonitor.F10, 0, 0, UIntPtr.Zero);
            Check(WaitUntil(delegate { return !engine.Snapshot().Running; }, 5000),
                "F10 did not stop the worker while the UI was blocked");
            Check(engine.WaitForStop(2000) && engine.Snapshot().Detail.Contains("F10"),
                "F10 did not finish with the expected stop reason");

            // Closing via the custom window button must stop an active worker.
            keybd_event(SafetyKeyMonitor.F10, 0, 2, UIntPtr.Zero);
            releaseUi.Set();
            form.Invoke((MethodInvoker)delegate { }); // drain the blocked UI
            Thread.Sleep(150); // let the safety poller observe key release
            form.Invoke((MethodInvoker)delegate { Refresh(form); Find<PowerButton>(form, "powerButton").PerformClick(); });
            Check(WaitUntil(delegate { return engine.Snapshot().Running; }, 5000), "worker did not restart for window-close test");
            form.BeginInvoke((MethodInvoker)delegate { Find<WindowButton>(form, "closeWindow").PerformClick(); });
            Check(ui.Join(7000), "custom close button did not close the window");
            Check(engine.WaitForStop(2000) && !engine.Snapshot().Running, "closing the window did not stop the worker");
        }
        catch (Exception ex)
        {
            Console.WriteLine("::error title=GUI safety::" + ex.Message.Replace("%", "%25").Replace("\r", "%0D").Replace("\n", "%0A"));
            Console.Error.WriteLine(ex);
            result = 1;
        }
        finally
        {
            keybd_event(SafetyKeyMonitor.F9, 0, 2, UIntPtr.Zero);
            keybd_event(SafetyKeyMonitor.F10, 0, 2, UIntPtr.Zero);
            releaseUi.Set();
            try
            {
                if (form != null && form.IsHandleCreated && !form.IsDisposed)
                    form.BeginInvoke((MethodInvoker)delegate { form.Close(); });
            }
            catch (InvalidOperationException) { }
            if (!ui.Join(5000))
            {
                Console.WriteLine("::error title=GUI safety::The WinForms UI did not close after the test.");
                result = 1;
            }
        }
        if (result == 0)
            Console.WriteLine("::notice title=GUI safety::PASS: custom window, drag/minimize/close, settings, themed journal, start/stop, and synthetic F9/F10 with the UI blocked. No GTA5 or physical keyboard was tested.");
        return result;
    }
}
