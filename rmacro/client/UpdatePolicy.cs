using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;

namespace RMacro
{
    internal sealed class UpdateRelease
    {
        public Version Version;
        public string Tag, Sha256, AssetName;
        public long Size;
        public string DownloadUrl
        {
            get { return "https://github.com/marlen71/AutoFish/releases/download/" + Tag + "/" + (AssetName ?? "EternalCore.exe"); }
        }
    }

    // Runs before constructing the loader's main form. The post-update and
    // rollback launches must open their health/recovery window immediately;
    // all normal starts check and install without an interactive prompt.
    internal static class StartupUpdate
    {
        private static readonly Regex Nonce = new Regex(@"^[0-9a-f]{32}$", RegexOptions.CultureInvariant);
        public static bool SkipOnce(string[] args)
        {
            return args != null && ((args.Length == 1 && args[0] == "--skip-update-once") ||
                (args.Length == 2 && args[0] == "--post-update" && Nonce.IsMatch(args[1] ?? "")));
        }

        public static bool Run<TRelease, TStage>(string[] args, Func<TRelease> find,
            Func<TRelease, TStage> prepare, Action<TStage> launch, Action<TStage> discard)
            where TRelease : class where TStage : class
        {
            if (SkipOnce(args)) return false;
            TStage staged = null;
            try
            {
                TRelease release = find();
                if (release == null) return false;
                staged = prepare(release);
                if (staged == null) throw new InvalidOperationException("Не удалось подготовить обновление.");
                launch(staged);
                staged = null; // the helper now owns it
                return true;
            }
            finally { if (staged != null) discard(staged); }
        }
    }

    // The update authority is deliberately fixed to the owner's GitHub repo.
    // Ignore other products, preview/draft releases and unverified assets.
    internal static class UpdatePolicy
    {
        public const int MaxExecutableBytes = 50 * 1024 * 1024;
        private static readonly Regex TagPattern = new Regex(@"^eternal-core-v(\d{1,5})\.(\d{1,5})\.(\d{1,5})$", RegexOptions.CultureInvariant);
        private static readonly Regex ProductTagPattern = new Regex(@"^rmfish-product-v(\d{1,5})\.(\d{1,5})\.(\d{1,5})$", RegexOptions.CultureInvariant);
        private static readonly Regex DigestPattern = new Regex(@"^sha256:([0-9a-fA-F]{64})$", RegexOptions.CultureInvariant);

        private static string StringValue(Dictionary<string, object> item, string key)
        {
            object value; return item.TryGetValue(key, out value) ? value as string : null;
        }
        private static bool IsFalse(Dictionary<string, object> item, string key)
        {
            object value; return item.TryGetValue(key, out value) && value is bool && !(bool)value;
        }
        private static Version ParseTag(string tag, bool product)
        {
            Match match = (product ? ProductTagPattern : TagPattern).Match(tag ?? "");
            if (!match.Success) return null;
            int major, minor, build;
            if (!Int32.TryParse(match.Groups[1].Value, NumberStyles.None, CultureInfo.InvariantCulture, out major) ||
                !Int32.TryParse(match.Groups[2].Value, NumberStyles.None, CultureInfo.InvariantCulture, out minor) ||
                !Int32.TryParse(match.Groups[3].Value, NumberStyles.None, CultureInfo.InvariantCulture, out build) ||
                major > 65535 || minor > 65535 || build > 65535) return null;
            Version version = new Version(major, minor, build);
            return tag == (product ? "rmfish-product-v" : "eternal-core-v") + version.ToString(3) ? version : null;
        }
        public static bool IsPrerelease(Version current, string informationalVersion)
        {
            if (current == null || current.Build < 0 || informationalVersion == null) return false;
            string prefix = current.Major + "." + current.Minor + "." + current.Build + "-";
            return informationalVersion.StartsWith(prefix, StringComparison.Ordinal) && informationalVersion.Length > prefix.Length;
        }
        public static UpdateRelease Select(object[] releases, Version current) { return SelectLoader(releases, current, false); }
        public static UpdateRelease SelectLoader(object[] releases, Version current, bool currentIsPrerelease)
        { return SelectKind(releases, current, false, currentIsPrerelease); }
        public static UpdateRelease SelectProduct(object[] releases, Version current) { return SelectKind(releases, current, true, false); }

        private static UpdateRelease SelectKind(object[] releases, Version current, bool product, bool allowEqual)
        {
            if (releases == null || releases.Length > 100 || current == null) return null;
            string expectedName = product ? "RMFishProduct.dll" : "EternalCore.exe";
            Version installed = new Version(current.Major, current.Minor, Math.Max(0, current.Build));
            UpdateRelease best = null;
            foreach (object raw in releases)
            {
                Dictionary<string, object> release = raw as Dictionary<string, object>;
                if (release == null || !IsFalse(release, "draft") || !IsFalse(release, "prerelease")) continue;
                string tag = StringValue(release, "tag_name");
                Version version = ParseTag(tag, product);
                if (version == null) continue;
                int comparison = version.CompareTo(installed);
                if (comparison < 0 || (comparison == 0 && !allowEqual) ||
                    (best != null && version.CompareTo(best.Version) <= 0)) continue;
                object assetValue;
                if (!release.TryGetValue("assets", out assetValue)) continue;
                object[] assets = assetValue as object[];
                if (assets == null || assets.Length > 200) continue;
                UpdateRelease candidate = null;
                int named = 0;
                foreach (object assetRaw in assets)
                {
                    Dictionary<string, object> asset = assetRaw as Dictionary<string, object>;
                    if (asset == null || StringValue(asset, "name") != expectedName) continue;
                    named++;
                    Match digest = DigestPattern.Match(StringValue(asset, "digest") ?? "");
                    object sizeValue; long size = 0;
                    if (asset.TryGetValue("size", out sizeValue) && (sizeValue is int || sizeValue is long))
                        size = Convert.ToInt64(sizeValue, CultureInfo.InvariantCulture);
                    if (digest.Success && size > 0 && size <= MaxExecutableBytes)
                        candidate = new UpdateRelease { Tag = tag, Version = version, Size = size,
                            AssetName = expectedName, Sha256 = digest.Groups[1].Value.ToLowerInvariant() };
                }
                if (named == 1 && candidate != null) best = candidate;
            }
            return best;
        }

        public static bool AllowedAssetLocation(Uri uri)
        {
            if (uri == null || uri.Scheme != Uri.UriSchemeHttps || !uri.IsDefaultPort ||
                !String.IsNullOrEmpty(uri.UserInfo) || !String.IsNullOrEmpty(uri.Fragment)) return false;
            string host = uri.DnsSafeHost;
            return String.Equals(host, "github.com", StringComparison.OrdinalIgnoreCase) ||
                String.Equals(host, "release-assets.githubusercontent.com", StringComparison.OrdinalIgnoreCase) ||
                String.Equals(host, "objects.githubusercontent.com", StringComparison.OrdinalIgnoreCase);
        }
    }
}
