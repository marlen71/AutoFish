using System;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace RMacro
{
    internal sealed class ProductSelection
    {
        // Null means the product built into this loader. Separate modules are
        // loaded from the verified bytes, so an open module doesn't lock its file.
        public byte[] AssemblyBytes;
        public Assembly ValidatedAssembly;
        public Version Version;
        public string Notice;
    }

    // Only RMFish is implemented today. Code from this repository's stable
    // rmfish-product-vX.Y.Z releases is the sole external update authority.
    // The local manifest is not a signature or DRM: a user who controls their
    // own Windows profile can modify it, just as they can modify the loader.
    internal static class ProductUpdateStore
    {
        // Must match the separately built RMFishProduct.dll included in this
        // source revision. Newer stable product releases can update it without
        // rebuilding or redistributing the loader.
        public const string EmbeddedVersion = "1.29.0";
        private static readonly Regex Digest = new Regex(@"^[0-9a-f]{64}$", RegexOptions.CultureInvariant);

        private static string Hash(byte[] bytes)
        {
            using (SHA256 sha = SHA256.Create())
            {
                StringBuilder text = new StringBuilder(64);
                foreach (byte b in sha.ComputeHash(bytes)) text.Append(b.ToString("x2", CultureInfo.InvariantCulture));
                return text.ToString();
            }
        }
        private static bool IsPe(byte[] bytes)
        { return bytes != null && bytes.Length >= 2 && bytes[0] == 0x4d && bytes[1] == 0x5a; }
        private static Version ParseVersion(string value)
        {
            Version result;
            if (!Version.TryParse(value, out result) || result.Major < 0 || result.Minor < 0 || result.Build < 0 ||
                result.Major > 65535 || result.Minor > 65535 || result.Build > 65535 || result.Revision != -1 ||
                result.ToString(3) != value) throw new InvalidDataException("Повреждена версия установленного RMFish.");
            return result;
        }
        private static string Artifact(string directory, Version version, string digest)
        { return Path.Combine(directory, "RMFish-" + version.ToString(3) + "-" + digest + ".dll"); }

        private static void VerifyIdentity(string path, Version version)
        {
            AssemblyName identity;
            try { identity = AssemblyName.GetAssemblyName(path); }
            catch (Exception ex) { throw new InvalidDataException("Обновление RMFish не является корректной сборкой .NET.", ex); }
            Version expected = new Version(version.Major, version.Minor, version.Build, 0);
            if (identity.Name != "RMFishProduct" || identity.Version != expected)
                throw new InvalidDataException("Версия или имя модуля RMFish не соответствует релизу.");
        }

        private static ProductSelection ReadInstalled(string directory, Version embedded)
        {
            ProductSelection result = new ProductSelection { Version = embedded };
            string manifest = Path.Combine(directory, "installed.txt");
            if (!File.Exists(manifest)) return result;
            FileInfo info = new FileInfo(manifest);
            if (info.Length > 256) throw new InvalidDataException("Повреждена запись установленной версии RMFish.");
            string[] lines = File.ReadAllLines(manifest, Encoding.ASCII);
            if (lines.Length != 2 || !Digest.IsMatch(lines[1]))
                throw new InvalidDataException("Повреждена запись установленной версии RMFish.");
            Version installed = ParseVersion(lines[0]);
            if (installed.CompareTo(embedded) <= 0) return result;
            string path = Artifact(directory, installed, lines[1]);
            FileInfo module = new FileInfo(path);
            if (!module.Exists || module.Length < 2 || module.Length > UpdatePolicy.MaxExecutableBytes)
                throw new InvalidDataException("Установленный модуль RMFish отсутствует или повреждён.");
            byte[] bytes = File.ReadAllBytes(path);
            if (bytes.LongLength != module.Length || !IsPe(bytes) || Hash(bytes) != lines[1])
                throw new InvalidDataException("Контрольная сумма установленного RMFish не совпадает.");
            VerifyIdentity(path, installed);
            result.AssemblyBytes = bytes; result.Version = installed;
            return result;
        }

        private static void WriteManifest(string directory, Version version, string digest)
        {
            string target = Path.Combine(directory, "installed.txt");
            string temporary = Path.Combine(directory, ".installed-" + Guid.NewGuid().ToString("N") + ".tmp");
            try
            {
                using (FileStream file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                using (StreamWriter writer = new StreamWriter(file, Encoding.ASCII))
                { writer.Write(version.ToString(3)); writer.Write('\n'); writer.Write(digest); writer.Write('\n'); }
                if (File.Exists(target)) File.Replace(temporary, target, null);
                else File.Move(temporary, target);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }

        public static ProductSelection CheckAndInstall(string localDirectory, Version embedded,
            Func<Version, UpdateRelease> find, Func<UpdateRelease, byte[]> download)
        { return CheckAndInstall(localDirectory, embedded, find, download, null); }

        public static ProductSelection CheckAndInstall(string localDirectory, Version embedded,
            Func<Version, UpdateRelease> find, Func<UpdateRelease, byte[]> download,
            Func<byte[], Version, Assembly> validateContract)
        {
            if (String.IsNullOrEmpty(localDirectory) || embedded == null || find == null || download == null)
                throw new ArgumentException("Недостаточно данных для проверки обновления RMFish.");
            string directory = Path.Combine(localDirectory, "Products", "rmfish");
            Directory.CreateDirectory(directory);
            ProductSelection previous = ReadInstalled(directory, embedded);
            if (previous.AssemblyBytes != null && validateContract != null)
                previous.ValidatedAssembly = validateContract(previous.AssemblyBytes, previous.Version);
            UpdateRelease release;
            try { release = find(previous.Version); }
            catch (Exception)
            {
                previous.Notice = "Не удалось проверить обновление RMFish в GitHub; используется сохранённая версия.";
                return previous;
            }
            if (release == null) return previous;
            if (release.Version == null || release.Version.Revision != -1 || release.Version.CompareTo(previous.Version) <= 0 ||
                release.Tag != "rmfish-product-v" + release.Version.ToString(3) || release.AssetName != "RMFishProduct.dll" ||
                release.Size < 2 || release.Size > UpdatePolicy.MaxExecutableBytes || !Digest.IsMatch(release.Sha256 ?? ""))
                throw new InvalidDataException("Некорректные сведения об обновлении RMFish.");
            // A failed or tampered download never replaces the prior version.
            byte[] bytes = download(release);
            if (!IsPe(bytes) || bytes.LongLength != release.Size || Hash(bytes) != release.Sha256)
                throw new InvalidDataException("Размер или SHA-256 обновления RMFish не совпадает с GitHub.");
            string artifact = Artifact(directory, release.Version, release.Sha256);
            string temporary = Path.Combine(directory, ".product-" + Guid.NewGuid().ToString("N") + ".tmp");
            try
            {
                using (FileStream file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                    file.Write(bytes, 0, bytes.Length);
                VerifyIdentity(temporary, release.Version);
                Assembly validated = validateContract == null ? null : validateContract(bytes, release.Version);
                if (File.Exists(artifact))
                {
                    byte[] existing = File.ReadAllBytes(artifact);
                    if (existing.LongLength != release.Size || Hash(existing) != release.Sha256)
                        throw new InvalidDataException("Сохранённый файл RMFish повреждён.");
                }
                else File.Move(temporary, artifact);
                // Commit a small atomic pointer only after all checks. Older
                // artifacts remain available for manual recovery.
                WriteManifest(directory, release.Version, release.Sha256);
                return new ProductSelection { AssemblyBytes = bytes, ValidatedAssembly = validated, Version = release.Version,
                    Notice = "RMFish обновлён до версии " + release.Version.ToString(3) + "." };
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
    }
}
