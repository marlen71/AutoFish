using System;
using System.IO;
using System.Security.Cryptography;
using RMacro;

public static class ProductUpdateStoreRunner
{
    private static int assertions;
    private static void Check(bool value, string message)
    { assertions++; if (!value) throw new Exception("FAIL: " + message); }
    private static string Hash(byte[] bytes)
    {
        using (SHA256 sha = SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
    }
    private static UpdateRelease Release(Version version, byte[] bytes)
    {
        return new UpdateRelease { Version = version, Tag = "rmfish-product-v" + version.ToString(3),
            AssetName = "RMFishProduct.dll", Sha256 = Hash(bytes), Size = bytes.Length };
    }
    public static int Main(string[] args)
    {
        string root = Path.Combine(Path.GetTempPath(), "rmfish-product-store-" + Guid.NewGuid().ToString("N"));
        try
        {
            if (args.Length != 1) throw new ArgumentException("Fixture DLL is required.");
            byte[] module = File.ReadAllBytes(args[0]);
            Version baseline = new Version("1.29.0");
            Version checkedVersion = null; int checks = 0;
            ProductSelection current = ProductUpdateStore.CheckAndInstall(root, baseline,
                delegate(Version version) { checkedVersion = version; checks++; return null; },
                delegate(UpdateRelease release) { throw new Exception("Unexpected download"); });
            Check(current.AssemblyBytes == null && current.Version == baseline && checks == 1 && checkedVersion == baseline,
                "a first launch checks and falls back to its embedded baseline when no release is newer");
            UpdateRelease good = Release(new Version("1.30.0"), module);
            bool contractRejected = false;
            try
            {
                ProductUpdateStore.CheckAndInstall(root, baseline, delegate(Version v) { return good; },
                    delegate(UpdateRelease r) { return module; },
                    delegate(byte[] b, Version v) { throw new InvalidOperationException("incompatible contract"); });
            }
            catch (InvalidOperationException) { contractRejected = true; }
            Check(contractRejected && !File.Exists(Path.Combine(root, "Products", "rmfish", "installed.txt")),
                "an incompatible module contract is rejected before the installed pointer changes");
            current = ProductUpdateStore.CheckAndInstall(root, baseline,
                delegate(Version version) { checks++; return good; }, delegate(UpdateRelease release) { return module; });
            Check(current.Version == good.Version && Hash(current.AssemblyBytes) == good.Sha256,
                "a verified newer module installs without rebuilding the loader");
            string directory = Path.Combine(root, "Products", "rmfish");
            string manifest = Path.Combine(directory, "installed.txt");
            Check(File.Exists(manifest) && File.ReadAllText(manifest).Contains(good.Sha256), "installed pointer records version and digest");
            string saved = File.ReadAllText(manifest);
            current = ProductUpdateStore.CheckAndInstall(root, baseline,
                delegate(Version version) { checkedVersion = version; checks++; return null; },
                delegate(UpdateRelease release) { throw new Exception("Unexpected download"); });
            Check(checks == 3 && checkedVersion == good.Version && Hash(current.AssemblyBytes) == good.Sha256,
                "every launch checks again and reloads the verified local module");
            current = ProductUpdateStore.CheckAndInstall(root, baseline,
                delegate(Version version) { throw new IOException("network unavailable"); },
                delegate(UpdateRelease release) { throw new Exception("Unexpected download"); });
            Check(current.Version == good.Version && current.Notice != null && Hash(current.AssemblyBytes) == good.Sha256,
                "a failed metadata check reports offline use of the already stored module");
            bool refused = false;
            try
            {
                UpdateRelease bad = Release(new Version("1.31.0"), module); bad.Sha256 = new string('0', 64);
                ProductUpdateStore.CheckAndInstall(root, baseline, delegate(Version v) { return bad; }, delegate(UpdateRelease r) { return module; });
            }
            catch (InvalidDataException) { refused = true; }
            Check(refused && File.ReadAllText(manifest) == saved, "hash mismatch never changes the previous installed pointer");
            refused = false;
            try
            {
                UpdateRelease bad = Release(new Version("1.31.0"), module);
                ProductUpdateStore.CheckAndInstall(root, baseline, delegate(Version v) { return bad; }, delegate(UpdateRelease r) { return module; });
            }
            catch (InvalidDataException) { refused = true; }
            Check(refused && File.ReadAllText(manifest) == saved, "the module identity/version must match its tag before committing");
            refused = false;
            try
            {
                UpdateRelease bad = Release(new Version("1.31.0"), module); bad.AssetName = "../../evil.dll";
                ProductUpdateStore.CheckAndInstall(root, baseline, delegate(Version v) { return bad; }, delegate(UpdateRelease r) { return module; });
            }
            catch (InvalidDataException) { refused = true; }
            Check(refused && File.ReadAllText(manifest) == saved, "arbitrary product names and paths are forbidden");
            string artifact = Path.Combine(directory, "RMFish-1.30.0-" + good.Sha256 + ".dll");
            File.WriteAllBytes(artifact, new byte[] { 0x4d, 0x5a, 1, 2 });
            refused = false;
            try { ProductUpdateStore.CheckAndInstall(root, baseline, delegate(Version v) { return null; }, delegate(UpdateRelease r) { return module; }); }
            catch (InvalidDataException) { refused = true; }
            Check(refused, "a corrupted cached module is never loaded");
            Console.WriteLine("PASS: " + assertions + " independent product update assertions.");
            if (Environment.GetEnvironmentVariable("GITHUB_ACTIONS") == "true")
                Console.WriteLine("::notice title=Independent product updates::PASS " + assertions + " assertions.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex);
            if (Environment.GetEnvironmentVariable("GITHUB_ACTIONS") == "true")
                Console.WriteLine("::error title=Independent product updates::" + ex.Message.Replace("%", "%25").Replace("\r", "%0D").Replace("\n", "%0A"));
            return 1;
        }
        finally { try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch (Exception) { } }
    }
}
