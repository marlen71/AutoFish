using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using RMacro;

// Local Windows fixture: no CA is installed or globally trusted.
internal static class InternetClientRunner
{
    private static void Check(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
    }

    private static void ExpectTlsFailure(ApiClient api, string label)
    {
        try
        {
            api.Request("/api/health", null, null, null);
            throw new Exception(label + " was accepted.");
        }
        catch (ApiException ex)
        {
            Check(ex.Status == 0 && ex.Code == "NETWORK", label + ": expected a TLS network failure.");
            Check(ex.Message.Contains("TLS"), label + ": expected a TLS-specific diagnostic: " + ex.Message);
            Check(!ex.Message.Contains("127.0.0."), "Diagnostic must not show the server address.");
        }
    }

    private static void CheckUpdater(string configured, string source, ServerConnectionSettings connection)
    {
        string before = LoaderUpdater.HashFile(configured);
        byte[] image = File.ReadAllBytes(source);
        Check(ServerSettings.SupportsPinnedConfiguration(image), "Built EXE lacks V2 support marker.");
        Check(!ServerSettings.SupportsPinnedConfiguration(new byte[] { 0x4d, 0x5a }), "Old EXE unexpectedly supports pinned configuration.");
        string malformed = Path.Combine(Path.GetDirectoryName(configured), "malformed.exe");
        using (BinaryWriter writer = new BinaryWriter(File.Create(malformed)))
        {
            byte[] bad = Encoding.UTF8.GetBytes(connection.Address + "\nnot-base64!");
            writer.Write(new byte[] { 0x4d, 0x5a }); writer.Write(bad); writer.Write((uint)bad.Length);
            writer.Write(Encoding.ASCII.GetBytes("RMACRO_TLS_V2"));
        }
        bool rejected = false;
        try { ServerSettings.ReadConnectionFromExecutable(malformed); }
        catch (InvalidOperationException) { rejected = true; }
        Check(rejected, "A malformed pinned footer must fail closed.");
        rejected = false;
        try { new ServerConnectionSettings("http://127.0.0.1:8765", connection.TrustedRoot); }
        catch (InvalidOperationException) { rejected = true; }
        Check(rejected, "A pinned root must never be used with plaintext HTTP.");
        UpdateRelease release = new UpdateRelease { Version = new Version(FileVersionInfo.GetVersionInfo(source).ProductVersion) };
        try
        {
            LoaderUpdater.StageVerified(release, configured, connection, new byte[] { 0x4d, 0x5a });
            throw new Exception("Updater accepted a build without private TLS support.");
        }
        catch (InvalidDataException) { }
        StagedUpdate staged = null;
        try
        {
            // Exercise the same staging function used after a verified download,
            // without depending on the currently published release version.
            staged = LoaderUpdater.StageVerified(release, configured, connection, image);
            string payload = Path.Combine(staged.Directory, "payload.exe");
            Check(connection.SameAs(ServerSettings.ReadConnectionFromExecutable(payload)), "Updater lost or changed the endpoint/root.");
            Check(LoaderUpdater.HashFile(payload) == LoaderUpdater.HashFile(staged.Helper), "Staged helper mismatch.");
            Check(LoaderUpdater.HashFile(configured) == before, "Staging modified the installed loader.");
        }
        finally { LoaderUpdater.Discard(staged); }
    }

    private static int Main(string[] args)
    {
        try
        {
            if (args.Length != 5) throw new ArgumentException("Expected URL, mode, configured loader, other loader, source loader.");
            ServerConnectionSettings connection = ServerSettings.ReadConnectionFromExecutable(args[2]);
            Check(connection.Address == new ApiClient(args[0]).BaseUrl, "HTTPS endpoint was not embedded in the actual loader.");
            Check(connection.TrustedRoot != null && connection.TrustId.Length == 64, "Public root was not embedded.");
            byte[] rootCopy = connection.TrustedRoot;
            rootCopy[0] ^= 1;
            Check(!ApiClient.EqualBytes(rootCopy, connection.TrustedRoot), "Root bytes must be immutable.");
            object before = ServicePointManager.ServerCertificateValidationCallback;
            if (args[1] == "must-fail")
            {
                ExpectTlsFailure(new ApiClient(connection.Address, connection.TrustedRoot), "Invalid pinned server");
                Check(Object.ReferenceEquals(before, ServicePointManager.ServerCertificateValidationCallback), "Global TLS callback changed.");
                Console.WriteLine("PASS: invalid pinned certificate was rejected without changing system trust.");
                return 0;
            }
            if (args[1] != "trusted") throw new ArgumentException("Unknown mode.");
            ServerConnectionSettings wrong = ServerSettings.ReadConnectionFromExecutable(args[3]);
            Check(wrong.Address == connection.Address && !wrong.SameAs(connection), "Wrong-root fixture must use the same endpoint.");
            CheckUpdater(args[2], args[4], connection);

            // Same process and same host, before and after a valid connection:
            // a pooled connection must never bypass another pin's validation.
            ExpectTlsFailure(new ApiClient(wrong.Address, wrong.TrustedRoot), "Wrong root");
            ExpectTlsFailure(new ApiClient(connection.Address), "Unconfigured Windows trust");
            ApiClient api = new ApiClient(connection.Address, connection.TrustedRoot);
            Check(JsonValues.Boolean(api.Request("/api/health", null, null, null), "ok"), "Health failed.");
            ExpectTlsFailure(new ApiClient(wrong.Address, wrong.TrustedRoot), "Wrong root after successful connection");
            ExpectTlsFailure(new ApiClient(connection.Address), "Unconfigured trust after successful connection");
            string device = new String('a', 64), token;
            Profile profile = api.Login("fixture_user", "fixture-user-password", device, out token);
            Check(profile.Username == "fixture_user", "Unexpected logged-in user.");
            string sessionDirectory = Path.Combine(Path.GetDirectoryName(args[2]), "session-test");
            SessionStore store = new SessionStore(sessionDirectory);
            store.Save(connection.Address, token, connection.TrustId);
            SavedSession saved = store.Load();
            Check(saved != null && saved.TrustId == connection.TrustId && saved.TrustId != wrong.TrustId,
                "Saved token was not bound to the pinned root.");
            store.Delete();
            Check(api.GetProfile(token, device).Uid == profile.Uid, "Profile failed.");
            Check(api.Authorize(token, device, "rmfish").ExpiresAt > 0, "Authorization failed.");
            try
            {
                api.Request("/api/admin/users", null, null, null);
                throw new Exception("Public gateway forwarded the admin API.");
            }
            catch (ApiException ex) { Check(ex.Status == 404, "Expected admin API to be blocked."); }
            api.Logout(token, device);
            Check(Object.ReferenceEquals(before, ServicePointManager.ServerCertificateValidationCallback), "Global TLS callback changed.");
            Console.WriteLine("PASS: private pinned HTTPS, login, wrong root, default trust isolation and update preservation.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex);
            return 1;
        }
    }
}
