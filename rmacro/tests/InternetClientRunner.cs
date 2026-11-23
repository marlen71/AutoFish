using System;
using RMacro;

// A local, synthetic fixture. Production certificate validation is not overridden.
internal static class InternetClientRunner
{
    private static void Check(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
    }

    private static int Main(string[] args)
    {
        try
        {
            if (args.Length != 3) throw new ArgumentException("Expected fixture URL, test mode and configured loader.");
            ApiClient api = new ApiClient(args[0]);
            Check(ServerSettings.ReadFromExecutable(args[2]) == api.BaseUrl, "HTTPS endpoint was not embedded in the actual loader.");
            if (args[1] == "untrusted")
            {
                try
                {
                    api.Request("/api/health", null, null, null);
                    throw new Exception("Untrusted test certificate was accepted.");
                }
                catch (ApiException ex)
                {
                    Check(ex.Status == 0 && ex.Code == "NETWORK", "Expected a TLS network failure.");
                    Check(ex.Message.Contains("TLS"), "Expected a TLS-specific diagnostic.");
                    Check(!ex.Message.Contains("127.0.0.1"), "Diagnostic must not show the server address.");
                }
                Console.WriteLine("PASS: Windows client rejected the untrusted IP certificate.");
                return 0;
            }
            if (args[1] != "trusted") throw new ArgumentException("Unknown mode.");
            Check(JsonValues.Boolean(api.Request("/api/health", null, null, null), "ok"), "Health failed.");
            string device = new String('a', 64), token;
            Profile profile = api.Login("fixture_user", "fixture-user-password", device, out token);
            Check(profile.Username == "fixture_user", "Unexpected logged-in user.");
            Check(api.GetProfile(token, device).Uid == profile.Uid, "Profile failed.");
            Check(api.Authorize(token, device, "rmfish").ExpiresAt > 0, "Authorization failed.");
            try
            {
                api.Request("/api/admin/users", null, null, null);
                throw new Exception("Public gateway forwarded the admin API.");
            }
            catch (ApiException ex) { Check(ex.Status == 404, "Expected admin API to be blocked."); }
            api.Logout(token, device);
            Console.WriteLine("PASS: Windows client authenticated over trusted HTTPS with an IP SAN.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex);
            return 1;
        }
    }
}
