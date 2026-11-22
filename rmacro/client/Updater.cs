using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace RMacro
{
    internal sealed class StagedUpdate
    {
        public string Directory, Target, Hash, Nonce;
        public string Helper { get { return Path.Combine(Directory, "helper.exe"); } }
    }

    // Downloads only the published loader EXE. Server, scripts, credentials,
    // session.dat and the installation's other files are never updated here.
    internal static class LoaderUpdater
    {
        private const string Api = "https://api.github.com/repos/marlen71/AutoFish/releases?per_page=100&page=";
        private const int MetadataLimit = 8 * 1024 * 1024;
        private static readonly Regex NoncePattern = new Regex(@"^[0-9a-f]{32}$", RegexOptions.CultureInvariant);
        private static readonly Regex HashPattern = new Regex(@"^[0-9a-f]{64}$", RegexOptions.CultureInvariant);

        private static HttpWebRequest Request(Uri uri)
        {
            ServicePointManager.SecurityProtocol |= (SecurityProtocolType)3072; // TLS 1.2 on .NET 4.5
            HttpWebRequest request = (HttpWebRequest)WebRequest.Create(uri);
            request.Method = "GET"; request.AllowAutoRedirect = false;
            request.Timeout = 10000; request.ReadWriteTimeout = 10000;
            request.UserAgent = "EternalCore-Updater/1";
            request.AutomaticDecompression = DecompressionMethods.None;
            return request;
        }

        private static byte[] ReadBounded(HttpWebResponse response, long maximum)
        {
            if (response.ContentLength > maximum) throw new InvalidDataException("Слишком большой ответ обновления.");
            using (Stream input = response.GetResponseStream())
            using (MemoryStream output = new MemoryStream())
            {
                if (input == null) throw new InvalidDataException("Пустой ответ обновления.");
                byte[] chunk = new byte[16384]; int n;
                while ((n = input.Read(chunk, 0, chunk.Length)) > 0)
                {
                    if (output.Length + n > maximum) throw new InvalidDataException("Слишком большой ответ обновления.");
                    output.Write(chunk, 0, n);
                }
                return output.ToArray();
            }
        }

        public static UpdateRelease FindNewer(Version current)
        {
            UpdateRelease best = null;
            // GitHub orders releases by creation time. Three bounded pages avoid
            // confusing a large collection of other-product releases with the
            // newest Eternal Core release.
            for (int page = 1; page <= 3; page++)
            {
                HttpWebRequest request = Request(new Uri(Api + page));
                request.Accept = "application/vnd.github+json";
                byte[] bytes;
                using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                {
                    if ((int)response.StatusCode != 200) throw new InvalidDataException("GitHub не вернул список релизов.");
                    bytes = ReadBounded(response, MetadataLimit);
                }
                JavaScriptSerializer json = new JavaScriptSerializer(); json.MaxJsonLength = MetadataLimit;
                object[] releases = json.DeserializeObject(new UTF8Encoding(false, true).GetString(bytes)) as object[];
                if (releases == null || releases.Length > 100) throw new InvalidDataException("Некорректный список релизов.");
                UpdateRelease candidate = UpdatePolicy.Select(releases, current);
                if (candidate != null && (best == null || candidate.Version.CompareTo(best.Version) > 0)) best = candidate;
                if (releases.Length < 100) break;
            }
            return best;
        }

        private static byte[] Download(UpdateRelease release)
        {
            Uri current = new Uri(release.DownloadUrl);
            for (int hop = 0; hop <= 4; hop++)
            {
                if (!UpdatePolicy.AllowedAssetLocation(current)) throw new InvalidDataException("Недопустимый адрес загрузки обновления.");
                HttpWebRequest request = Request(current);
                request.Accept = "application/octet-stream";
                using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                {
                    int code = (int)response.StatusCode;
                    if (code == 301 || code == 302 || code == 303 || code == 307 || code == 308)
                    {
                        Uri next;
                        if (!Uri.TryCreate(current, response.Headers[HttpResponseHeader.Location], out next) || !UpdatePolicy.AllowedAssetLocation(next))
                            throw new InvalidDataException("Недопустимый переход при загрузке обновления.");
                        current = next; continue;
                    }
                    if (code != 200) throw new InvalidDataException("GitHub отклонил загрузку обновления.");
                    byte[] bytes = ReadBounded(response, release.Size);
                    if (bytes.LongLength != release.Size || !String.Equals(Hash(bytes), release.Sha256, StringComparison.Ordinal))
                        throw new InvalidDataException("Размер или SHA-256 обновления не совпадает с GitHub.");
                    if (bytes.Length < 2 || bytes[0] != 0x4d || bytes[1] != 0x5a)
                        throw new InvalidDataException("Обновление не является Windows EXE.");
                    return bytes;
                }
            }
            throw new InvalidDataException("Слишком много переходов при загрузке обновления.");
        }

        private static string Hex(byte[] digest)
        {
            StringBuilder result = new StringBuilder(digest.Length * 2);
            foreach (byte b in digest) result.Append(b.ToString("x2"));
            return result.ToString();
        }
        public static string Hash(byte[] bytes) { using (SHA256 sha = SHA256.Create()) return Hex(sha.ComputeHash(bytes)); }
        public static string HashFile(string path)
        { using (SHA256 sha = SHA256.Create()) using (FileStream file = File.OpenRead(path)) return Hex(sha.ComputeHash(file)); }

        public static StagedUpdate Prepare(UpdateRelease release, string executable)
        {
            if (release == null) throw new ArgumentNullException("release");
            string target = Path.GetFullPath(executable);
            if (!String.Equals(Path.GetFileName(target), "EternalCore.exe", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Для обновления имя приложения должно быть EternalCore.exe.");
            string server = ServerSettings.ReadFromExecutable(target);
            byte[] verified = Download(release);
            string nonce = Guid.NewGuid().ToString("N");
            string directory = Path.Combine(Path.GetDirectoryName(target), ".eternal-core-update-" + nonce);
            StagedUpdate staged = new StagedUpdate { Directory = directory, Target = target, Nonce = nonce };
            try
            {
                Directory.CreateDirectory(directory);
                string payload = Path.Combine(directory, "payload.exe");
                using (FileStream output = new FileStream(payload, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                    output.Write(verified, 0, verified.Length);
                FileVersionInfo version = FileVersionInfo.GetVersionInfo(payload);
                if (!String.Equals(version.ProductVersion, release.Version.ToString(3), StringComparison.Ordinal))
                    throw new InvalidDataException("Версия EXE не совпадает с выбранным релизом.");
                ServerSettings.AppendToExecutable(payload, server);
                if (!String.Equals(ServerSettings.ReadFromExecutable(payload), server, StringComparison.Ordinal))
                    throw new InvalidDataException("Не удалось сохранить настройки подключения.");
                staged.Hash = HashFile(payload);
                File.Copy(payload, staged.Helper, false);
                if (HashFile(staged.Helper) != staged.Hash) throw new InvalidDataException("Ошибка подготовки обновления.");
                return staged;
            }
            catch { Discard(staged); throw; }
        }

        public static void Discard(StagedUpdate staged)
        {
            try { if (staged != null && Directory.Exists(staged.Directory)) Directory.Delete(staged.Directory, true); }
            catch (Exception) { }
        }
        private static string Quote(string value) { return "\"" + value + "\""; } // Windows paths cannot contain a quote

        public static void LaunchHelper(StagedUpdate staged)
        {
            using (Process parent = Process.GetCurrentProcess())
            {
                string arguments = "--apply-update " + parent.Id + " " + parent.StartTime.ToUniversalTime().Ticks + " " +
                    Quote(staged.Target) + " " + staged.Hash + " " + staged.Nonce;
                ProcessStartInfo info = new ProcessStartInfo(staged.Helper, arguments);
                info.UseShellExecute = false; info.CreateNoWindow = true; info.WorkingDirectory = staged.Directory;
                if (Process.Start(info) == null) throw new InvalidOperationException("Не удалось запустить установку обновления.");
            }
        }

        public static bool IsApply(string[] args) { return args != null && args.Length > 0 && args[0] == "--apply-update"; }
        public static bool SkipCheck(string[] args) { return args != null && args.Length == 1 && args[0] == "--skip-update-once"; }

        public static void MarkHealthy(string[] args, string executable)
        {
            if (args == null || args.Length != 2 || args[0] != "--post-update" || !NoncePattern.IsMatch(args[1])) return;
            try
            {
                string stage = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(executable)), ".eternal-core-update-" + args[1]);
                if (Directory.Exists(stage)) File.WriteAllText(Path.Combine(stage, "ready"), "ok", Encoding.ASCII);
            }
            catch (Exception) { /* No health marker means the helper will roll back. */ }
        }

        private static bool SameDirectory(string a, string b)
        { return String.Equals(Path.GetFullPath(a).TrimEnd(Path.DirectorySeparatorChar), Path.GetFullPath(b).TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase); }

        private static void StartLoader(string target, string arguments)
        {
            ProcessStartInfo info = new ProcessStartInfo(target, arguments);
            info.UseShellExecute = false; info.WorkingDirectory = Path.GetDirectoryName(target);
            if (Process.Start(info) == null) throw new InvalidOperationException("Не удалось открыть лоадер.");
        }

        // Executed by a separately copied helper so neither the running parent
        // nor the helper itself is the file being replaced. File.Replace is
        // atomic on a supported local Windows volume and retains the old EXE.
        public static int Apply(string[] args)
        {
            string target = null, backup = null;
            Process child = null;
            bool replaced = false, parentGone = false;
            try
            {
                int parentId; long parentStart;
                if (args == null || args.Length != 6 || args[0] != "--apply-update" ||
                    !Int32.TryParse(args[1], out parentId) || parentId <= 0 || !Int64.TryParse(args[2], out parentStart) ||
                    !HashPattern.IsMatch(args[4]) || !NoncePattern.IsMatch(args[5]))
                    throw new InvalidDataException("Некорректные параметры обновления.");
                target = Path.GetFullPath(args[3]);
                string self = Path.GetFullPath(Assembly.GetExecutingAssembly().Location);
                string stage = Path.GetDirectoryName(self);
                if (!String.Equals(Path.GetFileName(target), "EternalCore.exe", StringComparison.OrdinalIgnoreCase) ||
                    !String.Equals(Path.GetFileName(self), "helper.exe", StringComparison.OrdinalIgnoreCase) ||
                    !String.Equals(Path.GetFileName(stage), ".eternal-core-update-" + args[5], StringComparison.Ordinal) ||
                    !SameDirectory(Path.GetDirectoryName(stage), Path.GetDirectoryName(target)))
                    throw new InvalidDataException("Недопустимая папка обновления.");
                string payload = Path.Combine(stage, "payload.exe"), ready = Path.Combine(stage, "ready");
                backup = Path.Combine(stage, "previous.exe");
                if (File.Exists(backup) || File.Exists(ready) || HashFile(payload) != args[4])
                    throw new InvalidDataException("Повреждён подготовленный файл обновления.");
                try
                {
                    using (Process parent = Process.GetProcessById(parentId))
                    {
                        if (parent.StartTime.ToUniversalTime().Ticks != parentStart) throw new InvalidDataException("Исходный процесс изменился.");
                        if (!parent.WaitForExit(30000)) throw new InvalidOperationException("Предыдущее окно не завершилось; обновление отменено.");
                    }
                }
                catch (ArgumentException) { /* The exact parent has already exited. */ }
                parentGone = true;
                if (HashFile(payload) != args[4] ||
                    !String.Equals(ServerSettings.ReadFromExecutable(payload), ServerSettings.ReadFromExecutable(target), StringComparison.Ordinal))
                    throw new InvalidDataException("Файл или настройки обновления изменились.");
                File.Replace(payload, target, backup);
                replaced = true;
                if (HashFile(target) != args[4]) throw new InvalidDataException("Проверка установленного файла не прошла.");
                ProcessStartInfo info = new ProcessStartInfo(target, "--post-update " + args[5]);
                info.UseShellExecute = false; info.WorkingDirectory = Path.GetDirectoryName(target);
                child = Process.Start(info);
                if (child == null) throw new InvalidOperationException("Новая версия не запустилась.");
                Stopwatch wait = Stopwatch.StartNew();
                while (wait.ElapsedMilliseconds < 20000 && !File.Exists(ready))
                {
                    if (child.HasExited) break;
                    Thread.Sleep(200);
                }
                if (!File.Exists(ready)) throw new InvalidOperationException("Новая версия не открыла окно; возвращаем предыдущую.");
                // Keep previous.exe in this update directory for manual recovery.
                return 0;
            }
            catch (Exception ex)
            {
                string failure = ex.Message;
                if (child != null)
                {
                    try { if (!child.HasExited) { child.Kill(); child.WaitForExit(5000); } } catch (Exception) { }
                }
                if (replaced && target != null && backup != null)
                {
                    try { File.Replace(backup, target, null); replaced = false; }
                    catch (Exception rollback) { failure += " Не удалось восстановить файл автоматически: " + rollback.Message + ". Резервная копия: " + backup; }
                }
                if (parentGone && !replaced && target != null)
                    try { StartLoader(target, "--skip-update-once"); } catch (Exception) { }
                MessageBox.Show("Обновление Eternal Core не установлено.\n\n" + failure, "Eternal Core", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return 1;
            }
            finally { if (child != null) child.Dispose(); }
        }
    }
}
