using System;
using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using RMFish;

// Windows CI only. This sends synthetic, system-wide keys on an isolated VM.
public static class GuiSafetyRunner
{
    [DllImport("user32.dll")] private static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);

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
                using (MainForm window = new MainForm(directory))
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
            Check(engine.Start(new EngineOptions()), "worker did not start");
            Check(WaitUntil(delegate { return engine.Snapshot().Phase == FishingPhase.Paused; }, 5000),
                "worker did not pause without GTA5");

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
            Console.WriteLine("::notice title=GUI safety::PASS: synthetic F9 diagnostics and F10 stop while the real WinForms UI thread was blocked. No GTA5 or physical keyboard was tested.");
        return result;
    }
}
