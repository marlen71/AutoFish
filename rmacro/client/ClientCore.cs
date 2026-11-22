using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using Microsoft.Win32;

namespace RMacro
{
    internal sealed class ApiException : Exception
    {
        public readonly int Status;
        public readonly string Code;
        public ApiException(int status, string code, string message) : base(message) { Status = status; Code = code; }
    }

    internal sealed class GameInfo
    {
        public string Code, Name;
    }

    internal sealed class ProductInfo
    {
        public string Code, Name, GameCode, GameName;
        public long? ExpiresAt;
        public bool Active;
    }

    internal sealed class Profile
    {
        public long Uid, ServerTime;
        public string Username;
        public List<GameInfo> Games;
        public List<ProductInfo> Products;
        public long ReceivedAt;

        public long Remaining(ProductInfo item)
        {
            if (item == null || !item.ExpiresAt.HasValue) return 0;
            long elapsed = Math.Max(0, (Stopwatch.GetTimestamp() - ReceivedAt) / Stopwatch.Frequency);
            return Math.Max(0, item.ExpiresAt.Value - ServerTime - elapsed);
        }

        public ProductInfo Find(string code)
        {
            foreach (ProductInfo product in Products) if (product.Code == code) return product;
            return null;
        }
    }

    internal sealed class LeaseInfo
    {
        public long ServerTime, ExpiresAt, RoundTripMilliseconds;
    }

    internal static class JsonValues
    {
        public static Dictionary<string, object> Object(object value)
        {
            Dictionary<string, object> result = value as Dictionary<string, object>;
            if (result == null) throw new ApiException(0, "BAD_RESPONSE", "Некорректный ответ сервера.");
            return result;
        }
        public static string String(Dictionary<string, object> value, string key)
        {
            object item;
            if (!value.TryGetValue(key, out item) || !(item is string))
                throw new ApiException(0, "BAD_RESPONSE", "Некорректный ответ сервера.");
            return (string)item;
        }
        public static long Integer(Dictionary<string, object> value, string key)
        {
            object item;
            if (!value.TryGetValue(key, out item) || item == null)
                throw new ApiException(0, "BAD_RESPONSE", "Некорректный ответ сервера.");
            try { return Convert.ToInt64(item); }
            catch (Exception) { throw new ApiException(0, "BAD_RESPONSE", "Некорректный ответ сервера."); }
        }
        public static bool Boolean(Dictionary<string, object> value, string key)
        {
            object item;
            if (!value.TryGetValue(key, out item) || !(item is bool))
                throw new ApiException(0, "BAD_RESPONSE", "Некорректный ответ сервера.");
            return (bool)item;
        }
    }

    internal sealed class ApiClient
    {
        private const int MaxResponseBytes = 1024 * 1024;
        private readonly Uri baseUri;
        public string BaseUrl { get { return baseUri.GetLeftPart(UriPartial.Authority); } }

        public ApiClient(string address)
        {
            Uri parsed;
            if (!Uri.TryCreate((address ?? "").Trim(), UriKind.Absolute, out parsed) ||
                (parsed.Scheme != Uri.UriSchemeHttps && parsed.Scheme != Uri.UriSchemeHttp) ||
                !String.IsNullOrEmpty(parsed.UserInfo) || !String.IsNullOrEmpty(parsed.Query) ||
                !String.IsNullOrEmpty(parsed.Fragment) || (parsed.AbsolutePath != "/" && parsed.AbsolutePath != ""))
                throw new ApiException(0, "BAD_ADDRESS", "Укажите адрес сервера целиком: https://домен или http://127.0.0.1:8765.");
            if (parsed.Scheme == Uri.UriSchemeHttp && !IsLanAddress(parsed))
                throw new ApiException(0, "HTTPS_REQUIRED", "HTTP разрешён только для локальной сети; для публичного сервера необходим HTTPS.");
            baseUri = parsed;
            // Do not override certificate validation or allow automatic redirects
            // to a different host. Windows verifies the HTTPS certificate.
            ServicePointManager.SecurityProtocol |= (SecurityProtocolType)3072; // TLS 1.2 on .NET Framework 4.5
        }

        internal static bool IsLanAddress(Uri uri)
        {
            if (uri.IsLoopback) return true;
            // Match the server's HTTP policy: literal RFC1918 IPv4, not a
            // hostname that might resolve to a different/public destination.
            IPAddress address;
            if (!IPAddress.TryParse(uri.DnsSafeHost, out address) ||
                address.AddressFamily != System.Net.Sockets.AddressFamily.InterNetwork) return false;
            byte[] octets = address.GetAddressBytes();
            return octets[0] == 10 || (octets[0] == 172 && octets[1] >= 16 && octets[1] <= 31) ||
                (octets[0] == 192 && octets[1] == 168);
        }

        private static string ReadBounded(Stream stream)
        {
            using (MemoryStream buffer = new MemoryStream())
            {
                byte[] chunk = new byte[8192];
                int count;
                while ((count = stream.Read(chunk, 0, chunk.Length)) > 0)
                {
                    if (buffer.Length + count > MaxResponseBytes)
                        throw new ApiException(0, "BAD_RESPONSE", "Ответ сервера слишком большой.");
                    buffer.Write(chunk, 0, count);
                }
                return Encoding.UTF8.GetString(buffer.ToArray());
            }
        }

        internal Dictionary<string, object> Request(string path, Dictionary<string, object> body, string token, string device)
        {
            if (String.IsNullOrEmpty(path) || path[0] != '/' || path.StartsWith("//", StringComparison.Ordinal))
                throw new ArgumentException("Invalid API path", "path");
            HttpWebRequest request = (HttpWebRequest)WebRequest.Create(new Uri(baseUri, path));
            request.Method = body == null ? "GET" : "POST";
            request.Timeout = 8000;
            request.ReadWriteTimeout = 8000;
            request.AllowAutoRedirect = false;
            request.AutomaticDecompression = DecompressionMethods.None;
            if (IsLanAddress(baseUri)) request.Proxy = null;
            if (!String.IsNullOrEmpty(token)) request.Headers[HttpRequestHeader.Authorization] = "Bearer " + token;
            if (!String.IsNullOrEmpty(device)) request.Headers["X-RMacro-Device"] = device;
            JavaScriptSerializer json = new JavaScriptSerializer();
            json.MaxJsonLength = MaxResponseBytes;
            try
            {
                if (body != null)
                {
                    byte[] bytes = Encoding.UTF8.GetBytes(json.Serialize(body));
                    request.ContentType = "application/json; charset=utf-8";
                    request.ContentLength = bytes.Length;
                    using (Stream output = request.GetRequestStream()) output.Write(bytes, 0, bytes.Length);
                }
                using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                using (Stream input = response.GetResponseStream())
                {
                    if ((int)response.StatusCode < 200 || (int)response.StatusCode >= 300)
                        throw new ApiException((int)response.StatusCode, "HTTP_ERROR", "Сервер отклонил запрос.");
                    return JsonValues.Object(json.DeserializeObject(ReadBounded(input)));
                }
            }
            catch (WebException ex)
            {
                HttpWebResponse response = ex.Response as HttpWebResponse;
                if (response != null)
                {
                    using (response)
                    {
                        string message = "Сервер отклонил запрос.", code = "HTTP_ERROR";
                        try
                        {
                            using (Stream input = response.GetResponseStream())
                            {
                                Dictionary<string, object> error = JsonValues.Object(json.DeserializeObject(ReadBounded(input)));
                                message = JsonValues.String(error, "message"); code = JsonValues.String(error, "code");
                            }
                        }
                        catch (Exception) { }
                        throw new ApiException((int)response.StatusCode, code, message);
                    }
                }
                throw new ApiException(0, "NETWORK", "Не удалось связаться с сервером. Проверьте интернет или обратитесь к администратору.");
            }
            catch (InvalidOperationException) { throw new ApiException(0, "BAD_RESPONSE", "Некорректный ответ сервера."); }
            catch (ArgumentException) { throw new ApiException(0, "BAD_RESPONSE", "Некорректный ответ сервера."); }
        }

        internal static Dictionary<string, object> Body(params object[] entries)
        {
            Dictionary<string, object> result = new Dictionary<string, object>();
            for (int i = 0; i < entries.Length; i += 2) result[(string)entries[i]] = entries[i + 1];
            return result;
        }

        internal static Profile ParseProfile(Dictionary<string, object> value)
        {
            Dictionary<string, object> user = JsonValues.Object(value["user"]);
            object raw;
            if (!value.TryGetValue("products", out raw)) throw new ApiException(0, "BAD_RESPONSE", "Некорректный ответ сервера.");
            object[] items = raw as object[];
            if (items == null || items.Length > 1000) throw new ApiException(0, "BAD_RESPONSE", "Некорректный ответ сервера.");
            Profile profile = new Profile();
            profile.ServerTime = JsonValues.Integer(value, "server_time");
            profile.Uid = JsonValues.Integer(user, "uid");
            profile.Username = JsonValues.String(user, "username");
            profile.ReceivedAt = Stopwatch.GetTimestamp();
            profile.Games = new List<GameInfo>();
            object gamesRaw;
            if (value.TryGetValue("games", out gamesRaw))
            {
                object[] games = gamesRaw as object[];
                if (games == null || games.Length > 1000) throw new ApiException(0, "BAD_RESPONSE", "Некорректный ответ сервера.");
                foreach (object item in games)
                {
                    Dictionary<string, object> game = JsonValues.Object(item);
                    profile.Games.Add(new GameInfo { Code = JsonValues.String(game, "code"), Name = JsonValues.String(game, "name") });
                }
            }
            else profile.Games.Add(new GameInfo { Code = "gta5", Name = "GTA5 · RMRP" }); // beta.1 server
            profile.Products = new List<ProductInfo>();
            foreach (object item in items)
            {
                Dictionary<string, object> entry = JsonValues.Object(item);
                ProductInfo product = new ProductInfo();
                product.Code = JsonValues.String(entry, "code");
                product.Name = JsonValues.String(entry, "name");
                object gameCode, gameName;
                product.GameCode = entry.TryGetValue("game_code", out gameCode) && gameCode is string ? (string)gameCode : "gta5";
                product.GameName = entry.TryGetValue("game_name", out gameName) && gameName is string ? (string)gameName : "GTA5 · RMRP";
                product.Active = JsonValues.Boolean(entry, "active");
                object expires;
                if (!entry.TryGetValue("expires_at", out expires)) throw new ApiException(0, "BAD_RESPONSE", "Некорректный ответ сервера.");
                if (expires != null) product.ExpiresAt = JsonValues.Integer(entry, "expires_at");
                profile.Products.Add(product);
            }
            return profile;
        }

        public Profile Login(string username, string password, string device, out string token)
        {
            Dictionary<string, object> result = Request("/api/login", Body("username", username, "password", password, "device", device), null, null);
            token = JsonValues.String(result, "token");
            if (!Regex.IsMatch(token, "^[A-Za-z0-9_-]{40,64}$")) throw new ApiException(0, "BAD_RESPONSE", "Некорректный ответ сервера.");
            return ParseProfile(result);
        }
        public Profile GetProfile(string token, string device) { return ParseProfile(Request("/api/me", null, token, device)); }
        public void ChangePassword(string token, string device, string oldPassword, string newPassword, string confirmation)
        {
            Request("/api/me/password", Body("old_password", oldPassword, "new_password", newPassword,
                "confirmation", confirmation), token, device);
        }
        public long ActivateKey(string token, string device, string key, string requestId)
        {
            Dictionary<string, object> result = Request("/api/me/activate-key", Body("key", key, "request_id", requestId), token, device);
            return JsonValues.Integer(result, "expires_at");
        }
        public LeaseInfo Authorize(string token, string device, string product)
        {
            Stopwatch watch = Stopwatch.StartNew();
            Dictionary<string, object> result = Request("/api/authorize", Body("product", product), token, device);
            watch.Stop();
            if (JsonValues.String(result, "code") != product) throw new ApiException(0, "BAD_RESPONSE", "Некорректный ответ сервера.");
            return new LeaseInfo { ServerTime = JsonValues.Integer(result, "server_time"), ExpiresAt = JsonValues.Integer(result, "expires_at"),
                RoundTripMilliseconds = watch.ElapsedMilliseconds };
        }
        public void Logout(string token, string device) { Request("/api/logout", Body(), token, device); }
    }

    // The owner may append a validated endpoint to a copy of the executable.
    // This keeps the address out of the UI; it is not a secret or a security boundary.
    internal static class ServerSettings
    {
        private const string DefaultAddress = "http://192.168.0.105:8765";
        private const string Marker = "RMACRO_URL_V1";
        private const int MaxAddressBytes = 1024;

        // Append the *current* validated endpoint to the verified update. The
        // footer is configuration, not a credential; the server URL never goes
        // to GitHub and need not be shown in the loader UI.
        public static void AppendToExecutable(string path, string address)
        {
            string normalized = new ApiClient(address).BaseUrl;
            byte[] payload = Encoding.UTF8.GetBytes(normalized);
            if (payload.Length == 0 || payload.Length > MaxAddressBytes) throw new InvalidOperationException("Настройки подключения слишком велики.");
            using (FileStream stream = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.None))
            using (BinaryWriter writer = new BinaryWriter(stream))
            {
                writer.Write(payload);
                writer.Write((uint)payload.Length);
                writer.Write(Encoding.ASCII.GetBytes(Marker));
            }
        }

        public static string ReadFromExecutable(string path)
        {
            byte[] marker = Encoding.ASCII.GetBytes(Marker);
            using (FileStream stream = File.OpenRead(path))
            {
                if (stream.Length < marker.Length + 4) return DefaultAddress;
                stream.Seek(-marker.Length, SeekOrigin.End);
                byte[] tail = new byte[marker.Length];
                if (stream.Read(tail, 0, tail.Length) != tail.Length) throw new InvalidOperationException("Не удалось прочитать настройки лоадера.");
                for (int i = 0; i < marker.Length; i++) if (tail[i] != marker[i]) return DefaultAddress;
                stream.Seek(-marker.Length - 4, SeekOrigin.End);
                byte[] size = new byte[4];
                if (stream.Read(size, 0, 4) != 4) throw new InvalidOperationException("Настройки лоадера повреждены.");
                uint length = (uint)size[0] | ((uint)size[1] << 8) | ((uint)size[2] << 16) | ((uint)size[3] << 24);
                if (length == 0 || length > MaxAddressBytes || stream.Length < marker.Length + 4L + length)
                    throw new InvalidOperationException("Настройки лоадера повреждены. Обратитесь к администратору.");
                stream.Seek(-marker.Length - 4L - length, SeekOrigin.End);
                byte[] payload = new byte[(int)length];
                if (stream.Read(payload, 0, payload.Length) != payload.Length) throw new InvalidOperationException("Настройки лоадера повреждены.");
                try
                {
                    string value = new UTF8Encoding(false, true).GetString(payload);
                    return new ApiClient(value).BaseUrl;
                }
                catch (Exception) { throw new InvalidOperationException("Настройки подключения повреждены. Обратитесь к администратору."); }
            }
        }
    }

    internal static class DeviceId
    {
        public static string Get()
        {
            string value = null;
            try
            {
                using (RegistryKey root = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64))
                using (RegistryKey key = root.OpenSubKey(@"SOFTWARE\Microsoft\Cryptography", false))
                    if (key != null) value = key.GetValue("MachineGuid") as string;
            }
            catch (Exception) { }
            if (String.IsNullOrWhiteSpace(value))
            {
                try
                {
                    using (RegistryKey key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Cryptography", false))
                        if (key != null) value = key.GetValue("MachineGuid") as string;
                }
                catch (Exception) { }
            }
            if (String.IsNullOrWhiteSpace(value)) throw new InvalidOperationException("Не удалось получить идентификатор Windows для привязки устройства.");
            using (SHA256 sha = SHA256.Create())
            {
                byte[] digest = sha.ComputeHash(Encoding.UTF8.GetBytes("RMacro.Device.v1\0" + value.Trim().ToLowerInvariant()));
                StringBuilder text = new StringBuilder(64);
                foreach (byte b in digest) text.Append(b.ToString("x2"));
                return text.ToString();
            }
        }
    }

    internal sealed class SavedSession
    {
        public string Server, Token;
    }

    internal sealed class SessionStore
    {
        private static readonly byte[] Entropy = Encoding.UTF8.GetBytes("RMacro/session/v1");
        private readonly string file;
        public SessionStore(string directory) { file = Path.Combine(directory, "session.dat"); }
        public SavedSession Load()
        {
            try
            {
                if (!File.Exists(file)) return null;
                byte[] encrypted = File.ReadAllBytes(file);
                if (encrypted.Length > 65536) return null;
                string text = Encoding.UTF8.GetString(ProtectedData.Unprotect(encrypted, Entropy, DataProtectionScope.CurrentUser));
                Dictionary<string, object> values = JsonValues.Object(new JavaScriptSerializer().DeserializeObject(text));
                SavedSession saved = new SavedSession { Server = JsonValues.String(values, "server"), Token = JsonValues.String(values, "token") };
                // An altered URL cannot send a token to public HTTP; RestoreAsync
                // additionally requires an exact match with this build's endpoint.
                new ApiClient(saved.Server);
                if (!Regex.IsMatch(saved.Token, "^[A-Za-z0-9_-]{40,64}$")) return null;
                return saved;
            }
            catch (Exception) { return null; }
        }
        public void Save(string server, string token)
        {
            new ApiClient(server);
            if (!Regex.IsMatch(token ?? "", "^[A-Za-z0-9_-]{40,64}$")) throw new ArgumentException("Invalid session token.");
            Directory.CreateDirectory(Path.GetDirectoryName(file));
            string text = new JavaScriptSerializer().Serialize(ApiClient.Body("server", server, "token", token));
            byte[] bytes = ProtectedData.Protect(Encoding.UTF8.GetBytes(text), Entropy, DataProtectionScope.CurrentUser);
            string temporary = file + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                using (FileStream output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None)) output.Write(bytes, 0, bytes.Length);
                if (File.Exists(file)) File.Replace(temporary, file, null);
                else File.Move(temporary, file);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        public void Delete() { try { if (File.Exists(file)) File.Delete(file); } catch (Exception) { } }
    }

    // Independent of the UI thread: if the server revokes access, or a lease
    // cannot be renewed within 90 seconds, request a stop and deny new starts.
    internal sealed class ProductLease : IDisposable
    {
        private readonly object gate = new object();
        private readonly Stopwatch clock = Stopwatch.StartNew();
        private readonly Func<LeaseInfo> renew;
        private readonly Action<string> revoked;
        private readonly long graceMilliseconds, renewalMilliseconds;
        private System.Threading.Timer timer;
        private long deadline, nextRenewal;
        private bool active, disposed;
        private int renewing;

        public ProductLease(LeaseInfo initial, Func<LeaseInfo> renew, Action<string> revoked)
            : this(initial, renew, revoked, 90000, 30000) { }

        internal ProductLease(LeaseInfo initial, Func<LeaseInfo> renew, Action<string> revoked, long graceMilliseconds, long renewalMilliseconds)
        {
            if (initial == null || renew == null || revoked == null || graceMilliseconds <= 0 || renewalMilliseconds <= 0)
                throw new ArgumentException("Invalid lease configuration.");
            this.renew = renew; this.revoked = revoked;
            this.graceMilliseconds = graceMilliseconds; this.renewalMilliseconds = renewalMilliseconds;
            active = true;
            ApplyLocked(initial);
            if (deadline <= clock.ElapsedMilliseconds) active = false;
        }

        private void ApplyLocked(LeaseInfo lease)
        {
            long seconds = Math.Max(0, Math.Min(lease.ExpiresAt - lease.ServerTime, graceMilliseconds / 1000 + 2));
            long conservative = Math.Max(0, seconds * 1000 - 1000 - Math.Max(0, lease.RoundTripMilliseconds));
            deadline = clock.ElapsedMilliseconds + Math.Min(graceMilliseconds, conservative);
            nextRenewal = clock.ElapsedMilliseconds + renewalMilliseconds;
        }
        public bool IsValid { get { lock (gate) { return active && !disposed && clock.ElapsedMilliseconds < deadline; } } }
        public void Start()
        {
            lock (gate)
            {
                if (disposed) throw new ObjectDisposedException("ProductLease");
                if (timer != null) return;
                timer = new System.Threading.Timer(Tick, null, 250, 250);
            }
        }
        private void Tick(object unused)
        {
            bool expired = false, shouldRenew = false;
            lock (gate)
            {
                if (disposed || !active) return;
                long now = clock.ElapsedMilliseconds;
                if (now >= deadline) expired = true;
                else if (now >= nextRenewal && Interlocked.CompareExchange(ref renewing, 1, 0) == 0)
                { nextRenewal = now + renewalMilliseconds; shouldRenew = true; }
            }
            if (expired) Invalidate("Доступ не подтверждён: подписка истекла или сервер недоступен. Запрошена остановка.");
            if (shouldRenew) ThreadPool.QueueUserWorkItem(delegate(object state) { Renew(); });
        }
        private void Renew()
        {
            try
            {
                LeaseInfo lease = renew();
                bool expired = false;
                lock (gate)
                {
                    if (disposed || !active) return;
                    // A late response cannot resurrect an already expired lease.
                    if (clock.ElapsedMilliseconds >= deadline) expired = true;
                    else { ApplyLocked(lease); expired = deadline <= clock.ElapsedMilliseconds; }
                }
                if (expired) Invalidate("Доступ не подтверждён. Запрошена остановка.");
            }
            catch (ApiException ex)
            {
                if (ex.Status == 401 || ex.Status == 403)
                    Invalidate("Доступ отозван сервером или подписка истекла. Запрошена остановка.");
                // A temporary network failure has only the remaining grace time.
            }
            catch (Exception) { }
            finally { Interlocked.Exchange(ref renewing, 0); }
        }
        private void Invalidate(string reason)
        {
            lock (gate)
            {
                if (disposed || !active) return;
                active = false;
            }
            try { revoked(reason); } catch (Exception) { }
        }
        public void Dispose()
        {
            lock (gate)
            {
                if (disposed) return;
                disposed = true; active = false;
                if (timer != null) { timer.Dispose(); timer = null; }
            }
        }
    }
}
