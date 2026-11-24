using System;
using System.Collections.Generic;
using RMacro;

public static class UpdatePolicyRunner
{
    private static int assertions;
    private static void Check(bool value, string text)
    { assertions++; if (!value) throw new Exception("FAIL: " + text); }
    private static Dictionary<string, object> Asset(string name, string digest, object size)
    {
        return new Dictionary<string, object> { { "name", name }, { "digest", digest }, { "size", size },
            { "browser_download_url", "https://evil.example/replace.exe" } };
    }
    private static Dictionary<string, object> Release(string tag, bool draft, bool prerelease, params object[] assets)
    {
        return new Dictionary<string, object> { { "tag_name", tag }, { "draft", draft }, { "prerelease", prerelease }, { "assets", assets } };
    }
    public static int Main()
    {
        try
        {
            string digest = "sha256:" + new string('a', 64);
            object good = Asset("EternalCore.exe", digest, 12345);
            object[] releases = {
                Release("v9.0.0", false, false, good),
                Release("eternal-core-v8.0.0", false, true, good),
                Release("eternal-core-v7.0.0", true, false, good),
                Release("eternal-core-v6.0.0", false, false, Asset("EternalCore-Server.zip", digest, 123)),
                Release("eternal-core-v5.0.0", false, false, Asset("EternalCore.exe", null, 123)),
                Release("eternal-core-v4.0.0", false, false, Asset("EternalCore.exe", digest, UpdatePolicy.MaxExecutableBytes + 1)),
                Release("eternal-core-v3.0.0", false, false, good, good),
                Release("eternal-core-v02.0.0", false, false, good),
                Release("eternal-core-v1.3.0", false, false, good),
                Release("eternal-core-v1.2.0", false, false, good),
                Release("eternal-core-v1.1.0", false, false, good)
            };
            UpdateRelease chosen = UpdatePolicy.Select(releases, new Version(1, 1, 0, 0));
            Check(chosen != null && chosen.Version.ToString(3) == "1.3.0", "only the latest valid stable loader release is chosen");
            Check(chosen.Sha256 == new string('a', 64) && chosen.Size == 12345, "GitHub SHA-256 and size are required");
            Check(chosen.DownloadUrl == "https://github.com/marlen71/AutoFish/releases/download/eternal-core-v1.3.0/EternalCore.exe",
                "download URL is constructed from the fixed owner and ignores metadata URLs");
            Check(UpdatePolicy.Select(releases, new Version(1, 3, 0, 0)) == null, "the updater never downgrades or reinstalls the same stable version");
            Check(UpdatePolicy.IsPrerelease(new Version(1, 3, 0, 0), "1.3.0-dev.1") &&
                !UpdatePolicy.IsPrerelease(new Version(1, 3, 0, 0), "1.3.0") &&
                !UpdatePolicy.IsPrerelease(new Version(1, 3, 0, 0), "1.2.0-dev.1"), "preview detection uses the current numeric version");
            Check(UpdatePolicy.SelectLoader(releases, new Version(1, 3, 0, 0), true) != null &&
                UpdatePolicy.SelectLoader(releases, new Version(1, 3, 0, 0), false) == null,
                "a matching stable release upgrades a preview but never reinstalls a stable build");
            Check(UpdatePolicy.Select(new object[] { Release("eternal-core-v1.2.0", false, false, Asset("EternalCore.exe", digest, "12345")) }, new Version(1, 1, 0)) == null,
                "malformed string sizes are rejected");
            Check(UpdatePolicy.Select(new object[] { Release("eternal-core-v1.2.0", false, false, Asset("EternalCore.exe", "md5:bad", 100)) }, new Version(1, 1, 0)) == null,
                "a missing or non-SHA256 digest is rejected");
            Check(UpdatePolicy.Select(new object[101], new Version(1, 0, 0)) == null, "release list is bounded");
            object productAsset = Asset("RMFishProduct.dll", digest, 12000);
            object[] productReleases = {
                Release("rmfish-product-v1.30.0", false, false, productAsset),
                Release("rmfish-product-v9.0.0", false, true, productAsset),
                Release("rmfish-product-v8.0.0", false, false, productAsset, productAsset),
                Release("rmfish-product-v7.0.0", false, false, Asset("RMFishProduct.dll", null, 12000)),
                Release("eternal-core-v99.0.0", false, false, productAsset),
                Release("rmfish-product-v02.0.0", false, false, productAsset)
            };
            UpdateRelease chosenProduct = UpdatePolicy.SelectProduct(productReleases, new Version(1, 29, 0));
            Check(chosenProduct != null && chosenProduct.Version.ToString(3) == "1.30.0" &&
                chosenProduct.DownloadUrl == "https://github.com/marlen71/AutoFish/releases/download/rmfish-product-v1.30.0/RMFishProduct.dll",
                "only a stable, uniquely named, hashed RMFish module from the fixed repository is selected");
            Check(UpdatePolicy.SelectProduct(productReleases, new Version(1, 30, 0)) == null,
                "product update cannot reinstall or downgrade an existing module");
            Check(UpdatePolicy.Select(productReleases, new Version(1, 0, 0)) == null,
                "product assets cannot be mistaken for loader updates");
            Check(UpdatePolicy.AllowedAssetLocation(new Uri(chosen.DownloadUrl)), "fixed GitHub asset URL is allowed");
            Check(UpdatePolicy.AllowedAssetLocation(new Uri("https://release-assets.githubusercontent.com/path?signature=x")), "GitHub release-asset redirect is allowed");
            Check(!UpdatePolicy.AllowedAssetLocation(new Uri("http://github.com/file")), "plaintext redirects are rejected");
            Check(!UpdatePolicy.AllowedAssetLocation(new Uri("https://github.com.evil.example/file")), "lookalike hosts are rejected");
            Check(!UpdatePolicy.AllowedAssetLocation(new Uri("https://user@github.com/file")), "embedded credentials are rejected");
            Check(!UpdatePolicy.AllowedAssetLocation(new Uri("https://github.com:444/file")), "unexpected ports are rejected");
            Check(!UpdatePolicy.AllowedAssetLocation(new Uri("https://github.com/file#fragment")), "fragment-bearing redirects are rejected");

            List<string> sequence = new List<string>();
            bool installing = StartupUpdate.Run<object, object>(new string[0],
                delegate { sequence.Add("check"); return new object(); },
                delegate(object r) { sequence.Add("prepare"); return new object(); },
                delegate(object s) { sequence.Add("launch"); }, delegate(object s) { sequence.Add("discard"); });
            Check(installing && String.Join(",", sequence) == "check,prepare,launch", "normal startup automatically checks, prepares and starts the helper before opening the window");
            sequence.Clear();
            bool skipped = StartupUpdate.Run<object, object>(new string[] { "--post-update", new string('a', 32) },
                delegate { sequence.Add("check"); return null; }, delegate(object r) { return null; },
                delegate(object s) { }, delegate(object s) { });
            Check(!skipped && sequence.Count == 0, "the new version opens its health window before another update check");
            Check(StartupUpdate.SkipOnce(new string[] { "--skip-update-once" }) &&
                !StartupUpdate.SkipOnce(new string[] { "--post-update", "bad" }) && !StartupUpdate.SkipOnce(new string[0]),
                "only explicit valid recovery launches skip the startup check");
            sequence.Clear();
            bool failed = false;
            try
            {
                StartupUpdate.Run<object, object>(new string[0], delegate { return new object(); },
                    delegate(object r) { return new object(); }, delegate(object s) { throw new InvalidOperationException(); },
                    delegate(object s) { sequence.Add("discard"); });
            }
            catch (InvalidOperationException) { failed = true; }
            Check(failed && String.Join(",", sequence) == "discard", "a failed helper launch discards its staged files and retains the installed loader");
            Console.WriteLine("PASS: " + assertions + " updater policy assertions.");
            if (Environment.GetEnvironmentVariable("GITHUB_ACTIONS") == "true")
                Console.WriteLine("::notice title=Updater policy::PASS " + assertions + " assertions.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.ToString());
            if (Environment.GetEnvironmentVariable("GITHUB_ACTIONS") == "true")
                Console.WriteLine("::error title=Updater policy::" + ex.Message.Replace("%", "%25").Replace("\r", "%0D").Replace("\n", "%0A"));
            return 1;
        }
    }
}
