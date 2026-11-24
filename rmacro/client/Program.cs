using System;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;
using RMFish;

[assembly: AssemblyTitle("Eternal Core")]
[assembly: AssemblyDescription("Eternal Core — лоадер игр, макросов и подписок")]
[assembly: AssemblyProduct("Eternal Core")]
[assembly: AssemblyVersion("1.4.0.0")]
[assembly: AssemblyFileVersion("1.4.0.1")]
[assembly: AssemblyInformationalVersion("1.4.0-dev.1")]

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
                Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
                // No main loader window exists until the check and, if needed,
                // the automatic staged installation have finished. A failed
                // network/update leaves the verified existing EXE in place.
                try
                {
                    bool installing = StartupUpdate.Run<UpdateRelease, StagedUpdate>(args,
                        LoaderUpdater.FindNewerCurrent,
                        delegate(UpdateRelease release) { return LoaderUpdater.Prepare(release, Application.ExecutablePath); },
                        LoaderUpdater.LaunchHelper, LoaderUpdater.Discard);
                    if (installing) return 0; // helper waits for this process to exit
                }
                catch (Exception)
                {
                    MessageBox.Show("Не удалось автоматически проверить или установить обновление Eternal Core. Текущая версия сохранена; лоадер будет открыт. Проверьте сеть и повторите запуск.",
                        "Eternal Core — обновление", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                }
                string device = DeviceId.Get();
                ServerConnectionSettings connection = ServerSettings.ReadConnectionFromExecutable(Application.ExecutablePath);
                using (LoaderForm form = new LoaderForm(directory, device, connection, false))
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
