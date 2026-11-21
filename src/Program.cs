using System;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("RMFish")]
[assembly: AssemblyDescription("RMFish — визуальная автоматизация рыбалки для RMRP")]
[assembly: AssemblyProduct("RMFish")]
[assembly: AssemblyVersion("1.27.0.0")]
[assembly: AssemblyFileVersion("1.27.0.4")]
[assembly: AssemblyInformationalVersion("1.27.0-beta.4")]

namespace RMFish
{
    internal static class Program
    {
        [STAThread]
        private static int Main()
        {
            Mutex mutex = null;
            bool ownsMutex = false;
            try
            {
                // Must happen before the first window is created.
                WindowsNative.EnableDpiAwareness();
                mutex = new Mutex(false, @"Local\RMFish");
                try { ownsMutex = mutex.WaitOne(0, false); }
                catch (AbandonedMutexException) { ownsMutex = true; }
                if (!ownsMutex)
                {
                    MessageBox.Show("RMFish уже запущен. Откройте существующее окно программы.",
                        "RMFish", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return 0;
                }

                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                using (MainForm form = new MainForm(AppDomain.CurrentDomain.BaseDirectory))
                    Application.Run(form);
                return 0;
            }
            catch (Exception ex)
            {
                MessageBox.Show("Не удалось запустить RMFish.\n\n" + ex.Message +
                    "\n\nУбедитесь, что установлен .NET Framework 4.5 или новее.",
                    "RMFish — ошибка запуска", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
            finally
            {
                if (ownsMutex && mutex != null) mutex.ReleaseMutex();
                if (mutex != null) mutex.Dispose();
            }
        }
    }
}
