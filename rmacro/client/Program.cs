using System;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;
using RMFish;

[assembly: AssemblyTitle("RMacro")]
[assembly: AssemblyDescription("RMacro — лоадер продуктов и подписок")]
[assembly: AssemblyProduct("RMacro")]
[assembly: AssemblyVersion("0.1.0.0")]
[assembly: AssemblyFileVersion("0.1.0.2")]
[assembly: AssemblyInformationalVersion("0.1.0-beta.2")]

namespace RMacro
{
    internal static class Program
    {
        [STAThread]
        private static int Main()
        {
            Mutex mutex = null; bool owns = false;
            try
            {
                WindowsNative.EnableDpiAwareness();
                mutex = new Mutex(false, @"Local\RMacro");
                try { owns = mutex.WaitOne(0, false); } catch (AbandonedMutexException) { owns = true; }
                if (!owns) { MessageBox.Show("RMacro уже запущен. Откройте существующее окно.", "RMacro", MessageBoxButtons.OK, MessageBoxIcon.Information); return 0; }
                string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                if (String.IsNullOrEmpty(local)) throw new InvalidOperationException("Недоступна папка локальных данных Windows.");
                string directory = Path.Combine(local, "RMacro"); Directory.CreateDirectory(directory);
                string device = DeviceId.Get();
                Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
                string serverAddress = ServerSettings.ReadFromExecutable(Application.ExecutablePath);
                using (LoaderForm form = new LoaderForm(directory, device, serverAddress)) Application.Run(form);
                return 0;
            }
            catch (Exception ex)
            {
                MessageBox.Show("Не удалось запустить RMacro.\n\n" + ex.Message, "RMacro", MessageBoxButtons.OK, MessageBoxIcon.Error); return 1;
            }
            finally { if (owns && mutex != null) mutex.ReleaseMutex(); if (mutex != null) mutex.Dispose(); }
        }
    }
}
