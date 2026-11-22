using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;

namespace RMacro
{
    internal sealed class UpdateRelease
    {
        public Version Version;
        public string Tag, Sha256;
        public long Size;
        public string DownloadUrl
        {
            get { return "https://github.com/marlen71/AutoFish/releases/download/" + Tag + "/EternalCore.exe"; }
        }
    }

    // The update authority is deliberately fixed to the owner's GitHub repo.
    // Ignore other products, preview/draft releases and unverified assets.
    internal static class UpdatePolicy
    {
        public const int MaxExecutableBytes = 50 * 1024 * 1024;
        private static readonly Regex TagPattern = new Regex(@"^eternal-core-v(\d{1,5})\.(\d{1,5})\.(\d{1,5})$", RegexOptions.CultureInvariant);
        private static readonly Regex DigestPattern = new Regex(@"^sha256:([0-9a-fA-F]{64})$", RegexOptions.CultureInvariant);

        private static string StringValue(Dictionary<string, object> item, string key)
        {
            object value; return item.TryGetValue(key, out value) ? value as string : null;
        }
        private static bool IsFalse(Dictionary<string, object> item, string key)
        {
            object value; return item.TryGetValue(key, out value) && value is bool && !(bool)value;
        }
        private static Version ParseTag(string tag)
        {
            Match match = TagPattern.Match(tag ?? "");
            if (!match.Success) return null;
            int major, minor, build;
            if (!Int32.TryParse(match.Groups[1].Value, NumberStyles.None, CultureInfo.InvariantCulture, out major) ||
                !Int32.TryParse(match.Groups[2].Value, NumberStyles.None, CultureInfo.InvariantCulture, out minor) ||
                !Int32.TryParse(match.Groups[3].Value, NumberStyles.None, CultureInfo.InvariantCulture, out build) ||
                major > 65535 || minor > 65535 || build > 65535) return null;
            Version version = new Version(major, minor, build);
            return tag == "eternal-core-v" + version.ToString(3) ? version : null;
        }
        public static UpdateRelease Select(object[] releases, Version current)
        {
            if (releases == null || releases.Length > 100 || current == null) return null;
            Version installed = new Version(current.Major, current.Minor, Math.Max(0, current.Build));
            UpdateRelease best = null;
            foreach (object raw in releases)
            {
                Dictionary<string, object> release = raw as Dictionary<string, object>;
                if (release == null || !IsFalse(release, "draft") || !IsFalse(release, "prerelease")) continue;
                string tag = StringValue(release, "tag_name");
                Version version = ParseTag(tag);
                if (version == null || version.CompareTo(installed) <= 0 || (best != null && version.CompareTo(best.Version) <= 0)) continue;
                object assetValue;
                if (!release.TryGetValue("assets", out assetValue)) continue;
                object[] assets = assetValue as object[];
                if (assets == null || assets.Length > 200) continue;
                UpdateRelease candidate = null;
                int named = 0;
                foreach (object assetRaw in assets)
                {
                    Dictionary<string, object> asset = assetRaw as Dictionary<string, object>;
                    if (asset == null || StringValue(asset, "name") != "EternalCore.exe") continue;
                    named++;
                    Match digest = DigestPattern.Match(StringValue(asset, "digest") ?? "");
                    object sizeValue; long size = 0;
                    if (asset.TryGetValue("size", out sizeValue) && (sizeValue is int || sizeValue is long))
                        size = Convert.ToInt64(sizeValue, CultureInfo.InvariantCulture);
                    if (digest.Success && size > 0 && size <= MaxExecutableBytes)
                        candidate = new UpdateRelease { Tag = tag, Version = version, Size = size, Sha256 = digest.Groups[1].Value.ToLowerInvariant() };
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
