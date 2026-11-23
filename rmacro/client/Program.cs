using System;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;
using RMFish;

[assembly: AssemblyTitle("Eternal Core")]
[assembly: AssemblyDescription("Eternal Core — лоадер игр, макросов и подписок")]
[assembly: AssemblyProduct("Eternal Core")]
[assembly: AssemblyVersion("1.2.0.0")]
[assembly: AssemblyFileVersion("1.2.0.0")]
[assembly: AssemblyInformationalVersion("1.2.0")]

namespace RMacro
{
    internal static class Program
    {
        [STAThread]
        private static int Main(string[] args)
        {
            if (LoaderUpdater.IsApply(args)) return LoaderUpdater.Apply(args);
            Mutex mutex = null; bool owns = false;
            try
            {
                WindowsNative.EnableDpiAwareness();
                mutex = new Mutex(false, @"Local\RMacro");
                try { owns = mutex.WaitOne(0, false); } catch (AbandonedMutexException) { owns = true; }
                if (!owns) { MessageBox.Show("Eternal Core или прежний лоадер уже запущен. Откройте существующее окно.", "Eternal Core", MessageBoxButtons.OK, MessageBoxIcon.Information); return 0; }
                string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                if (String.IsNullOrEmpty(local)) throw new InvalidOperationException("Недоступна папка локальных данных Windows.");
                string directory = Path.Combine(local, "RMacro"); Directory.CreateDirectory(directory);
                string device = DeviceId.Get();
                Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
                string serverAddress = ServerSettings.ReadFromExecutable(Application.ExecutablePath);
                using (LoaderForm form = new LoaderForm(directory, device, serverAddress, !LoaderUpdater.SkipCheck(args)))
                {
                    form.Shown += delegate { LoaderUpdater.MarkHealthy(args, Application.ExecutablePath); };
                    Application.Run(form);
                }
                return 0;
            }
            catch (Exception ex)
            {
                MessageBox.Show("Не удалось запустить Eternal Core.\n\n" + ex.Message, "Eternal Core", MessageBoxButtons.OK, MessageBoxIcon.Error); return 1;
            }
            finally { if (owns && mutex != null) mutex.ReleaseMutex(); if (mutex != null) mutex.Dispose(); }
        }
    }
}
