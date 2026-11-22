using System;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;

// Windows CI only: exercise the updater in the actual built EXE against the
// published public release, but never launch or install the downloaded file.
public static class UpdateNetworkRunner
{
    private static string Hash(string path)
    {
        using (SHA256 sha = SHA256.Create())
        using (FileStream input = File.OpenRead(path))
            return BitConverter.ToString(sha.ComputeHash(input));
    }

    private static MethodInfo Method(Type type, string name)
    {
        MethodInfo result = type.GetMethod(name, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
        if (result == null) throw new InvalidOperationException("Missing method " + name);
        return result;
    }

    public static int Run(string source, string directory)
    {
        object staged = null;
        Type updater = null;
        try
        {
            Directory.CreateDirectory(directory);
            string target = Path.Combine(directory, "EternalCore.exe");
            File.Copy(source, target);
            Assembly assembly = Assembly.LoadFrom(source);
            updater = assembly.GetType("RMacro.LoaderUpdater", true);
            Type settings = assembly.GetType("RMacro.ServerSettings", true);
            MethodInfo find = Method(updater, "FindNewer"), prepare = Method(updater, "Prepare");
            MethodInfo append = Method(settings, "AppendToExecutable"), read = Method(settings, "ReadFromExecutable");
            string customAddress = "http://10.20.30.40:8765";
            append.Invoke(null, new object[] { target, customAddress });
            string oldHash = Hash(target);
            object release = find.Invoke(null, new object[] { new Version(0, 0, 0) });
            if (release == null) throw new InvalidOperationException("No usable stable Eternal Core release with a SHA-256 digest was selected.");
            string tag = (string)release.GetType().GetField("Tag").GetValue(release);
            staged = prepare.Invoke(null, new object[] { release, target });
            string stage = (string)staged.GetType().GetField("Directory").GetValue(staged);
            string payload = Path.Combine(stage, "payload.exe"), helper = Path.Combine(stage, "helper.exe");
            if (!File.Exists(payload) || !File.Exists(helper)) throw new InvalidOperationException("Downloaded update was not staged.");
            if ((string)read.Invoke(null, new object[] { payload }) != customAddress)
                throw new InvalidOperationException("Downloaded EXE did not retain the configured endpoint.");
            if (Hash(target) != oldHash) throw new InvalidOperationException("Preparing the update modified the installed EXE.");
            if (Hash(payload) != Hash(helper)) throw new InvalidOperationException("Helper does not match staged EXE.");
            Console.WriteLine("::notice title=Live GitHub updater::PASS: selected " + tag +
                ", downloaded and verified its GitHub size/SHA-256 and PE version, staged without installation, and preserved the test endpoint.");
            return 0;
        }
        catch (Exception ex)
        {
            Exception detail = ex;
            while (detail is TargetInvocationException && detail.InnerException != null) detail = detail.InnerException;
            string text = detail.ToString().Replace("%", "%25").Replace("\r", "%0D").Replace("\n", "%0A");
            if (text.Length > 5000) text = text.Substring(0, 5000);
            Console.WriteLine("::error title=Live GitHub updater::" + text);
            return 1;
        }
        finally
        {
            if (staged != null && updater != null)
                try { Method(updater, "Discard").Invoke(null, new object[] { staged }); } catch (Exception) { }
            try { if (Directory.Exists(directory)) Directory.Delete(directory, true); } catch (Exception) { }
        }
    }
}
