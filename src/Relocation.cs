using System;
using System.IO;
using System.Threading;
using System.Diagnostics;

namespace RMFish
{
    // These are the only keys used by the opt-in route. I is the physical key
    // labelled I/Ш, regardless of the current keyboard language.
    public enum GameKey { Space, Forward, Inventory }

    internal static class CalibrationFiles
    {
        public static void Write(string path, Action<BinaryWriter> write)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                using (FileStream file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                using (BinaryWriter writer = new BinaryWriter(file)) write(writer);
                if (File.Exists(path)) File.Replace(temporary, path, null);
                else File.Move(temporary, path);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }

        public static BinaryReader Open(string path, int maxLength)
        {
            FileStream file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
            if (file.Length > maxLength) { file.Dispose(); throw new InvalidDataException("Слишком большой файл настройки."); }
            return new BinaryReader(file);
        }
    }

    // The user selects the complete, unchanging text of the *actual* empty-fish
    // notice. Only a thresholded text mask is stored, not a screenshot. The
    // mask is matched at the recorded horizontal position and resolution, with
    // both precision and recall requirements. Notifications can shift vertically
    // as other notices appear or disappear, so search the whole notice region;
    // a generic yellow box is never enough.
    public sealed class NoticeTemplate
    {
        public const int RegionLeft = 0, RegionTop = 600, RegionRight = 620, RegionBottom = 1000;
        private const string Magic = "RMFISH-NOTICE-1";
        private readonly byte[] mask;
        private readonly int[] textX, textY;
        public readonly int ClientWidth, ClientHeight, X, Y, Width, Height;
        private readonly int foreground;

        private NoticeTemplate(int clientWidth, int clientHeight, int x, int y, int width, int height, byte[] mask)
        {
            if (clientWidth < 1280 || clientHeight < 720 || clientWidth > 10000 || clientHeight > 10000 ||
                x < RegionLeft || y < RegionTop || width < 70 || width > 600 || height < 8 || height > 80 ||
                x + width > RegionRight || y + height > RegionBottom || mask == null || mask.Length != width * height)
                throw new InvalidDataException("Неверная область текста уведомления.");
            int count = 0;
            foreach (byte value in mask)
            {
                if (value != 0 && value != 1) throw new InvalidDataException("Повреждён образец уведомления.");
                count += value;
            }
            if (count < 50 || count * 100 > mask.Length * 65)
                throw new InvalidDataException("Выделите всю надпись целиком, без значка и больших пустых полей.");
            ClientWidth = clientWidth; ClientHeight = clientHeight; X = x; Y = y; Width = width; Height = height;
            this.mask = (byte[])mask.Clone(); foreground = count;
            textX = new int[count]; textY = new int[count];
            int index = 0;
            // Interleave rows so a different notification is rejected quickly.
            // Every foreground pixel is still considered before a match passes.
            for (int col = 0; col < width; col++)
                for (int row = 0; row < height; row++)
                    if (mask[row * width + col] != 0)
                    { textX[index] = col; textY[index] = row; index++; }
        }

        private static bool TextPixel(int r, int g, int b)
        {
            // White or yellow letters on the dark notification; no assumption
            // that every yellow notification is the one we are looking for.
            return r >= 165 && g >= 160 && (r + g + b >= 390);
        }

        public static NoticeTemplate Create(PixelFrame frame, int x, int y, int width, int height)
        {
            if (frame == null) throw new ArgumentNullException("frame");
            if (width < 70 || width > 600 || height < 8 || height > 80) throw new InvalidDataException("Выделите полную строку текста уведомления.");
            byte[] mask = new byte[checked(width * height)];
            for (int row = 0; row < height; row++)
                for (int col = 0; col < width; col++)
                {
                    int r, g, b; frame.Read(x + col, y + row, out r, out g, out b);
                    mask[row * width + col] = TextPixel(r, g, b) ? (byte)1 : (byte)0;
                }
            return new NoticeTemplate(frame.ClientWidth, frame.ClientHeight, x, y, width, height, mask);
        }

        public bool Matches(PixelFrame frame)
        {
            if (frame == null || frame.ClientWidth != ClientWidth || frame.ClientHeight != ClientHeight) return false;
            // The same message can move between stacked notification slots.
            // Keep the user's X and search only within the explicitly captured
            // notice region, preferring the originally recorded Y.
            if (MatchesAt(frame, Y)) return true;
            int maxOffset = Math.Max(Y - RegionTop, RegionBottom - Height - Y);
            for (int offset = 1; offset <= maxOffset; offset++)
            {
                if (Y - offset >= RegionTop && MatchesAt(frame, Y - offset)) return true;
                if (Y + offset + Height <= RegionBottom && MatchesAt(frame, Y + offset)) return true;
            }
            return false;
        }

        private bool MatchesAt(PixelFrame frame, int y)
        {
            int matches = 0, missed = 0;
            int maximumMissed = foreground - (foreground * 92 + 99) / 100;
            for (int i = 0; i < foreground; i++)
            {
                int r, g, b; frame.Read(X + textX[i], y + textY[i], out r, out g, out b);
                if (TextPixel(r, g, b)) matches++;
                else if (++missed > maximumMissed) return false;
            }
            int actual = 0;
            for (int row = 0; row < Height; row++)
                for (int col = 0; col < Width; col++)
                {
                    int r, g, b; frame.Read(X + col, y + row, out r, out g, out b);
                    if (TextPixel(r, g, b)) actual++;
                }
            return actual >= 50 && matches * 100 >= foreground * 92 && matches * 100 >= actual * 92;
        }

        public void Save(string path)
        {
            CalibrationFiles.Write(path, delegate(BinaryWriter w)
            {
                w.Write(Magic); w.Write(ClientWidth); w.Write(ClientHeight);
                w.Write(X); w.Write(Y); w.Write(Width); w.Write(Height); w.Write(mask.Length); w.Write(mask);
            });
        }

        public static NoticeTemplate Load(string path)
        {
            using (BinaryReader r = CalibrationFiles.Open(path, 100000))
            {
                if (r.ReadString() != Magic) throw new InvalidDataException("Неизвестный формат уведомления.");
                int cw = r.ReadInt32(), ch = r.ReadInt32(), x = r.ReadInt32(), y = r.ReadInt32();
                int width = r.ReadInt32(), height = r.ReadInt32(), length = r.ReadInt32();
                if (width < 70 || width > 600 || height < 8 || height > 80 || length != width * height)
                    throw new InvalidDataException("Повреждён образец уведомления.");
                byte[] mask = r.ReadBytes(length);
                if (mask.Length != length || r.BaseStream.Position != r.BaseStream.Length)
                    throw new InvalidDataException("Повреждён образец уведомления.");
                return new NoticeTemplate(cw, ch, x, y, width, height, mask);
            }
        }
    }

    // The three inventory targets are explicitly recorded by the user. Each
    // target includes a small visual guard, not just a blind screen coordinate.
    public sealed class GearPoint
    {
        public const int HalfWidth = 20, HalfHeight = 14;
        private const int Width = HalfWidth * 2, Height = HalfHeight * 2;
        private readonly byte[] pixels;
        public readonly int X, Y, ClientWidth, ClientHeight;
        public readonly bool RightButton;

        internal GearPoint(int clientWidth, int clientHeight, int x, int y, bool right, byte[] pixels)
        {
            if (clientWidth < 1280 || clientHeight < 720 || clientWidth > 10000 || clientHeight > 10000 ||
                x < HalfWidth || x >= 1920 - HalfWidth || y < HalfHeight || y >= 1080 - HalfHeight ||
                pixels == null || pixels.Length != Width * Height * 3)
                throw new InvalidDataException("Повреждён образец кнопки инвентаря.");
            int min = 255, max = 0, edges = 0;
            for (int i = 0; i < pixels.Length; i += 3)
            {
                int v = (pixels[i] + pixels[i + 1] + pixels[i + 2]) / 3;
                min = Math.Min(min, v); max = Math.Max(max, v);
                if (i >= 3)
                {
                    int prev = (pixels[i - 3] + pixels[i - 2] + pixels[i - 1]) / 3;
                    if (Math.Abs(v - prev) >= 18) edges++;
                }
            }
            if (max - min < 35 || edges < 20)
                throw new InvalidDataException("Подведите курсор к значку или тексту, а не к пустому месту.");
            ClientWidth = clientWidth; ClientHeight = clientHeight; X = x; Y = y; RightButton = right;
            this.pixels = (byte[])pixels.Clone();
        }

        public static GearPoint Create(PixelFrame frame, int x, int y, bool right)
        {
            if (frame == null) throw new ArgumentNullException("frame");
            byte[] sample = new byte[Width * Height * 3];
            int i = 0;
            for (int row = -HalfHeight; row < HalfHeight; row++)
                for (int col = -HalfWidth; col < HalfWidth; col++)
                {
                    int r, g, b; frame.Read(x + col, y + row, out r, out g, out b);
                    sample[i++] = (byte)r; sample[i++] = (byte)g; sample[i++] = (byte)b;
                }
            return new GearPoint(frame.ClientWidth, frame.ClientHeight, x, y, right, sample);
        }

        public bool Matches(PixelFrame frame)
        {
            if (frame == null || frame.ClientWidth != ClientWidth || frame.ClientHeight != ClientHeight) return false;
            int close = 0, i = 0, totalError = 0;
            for (int row = -HalfHeight; row < HalfHeight; row++)
                for (int col = -HalfWidth; col < HalfWidth; col++)
                {
                    int r, g, b; frame.Read(X + col, Y + row, out r, out g, out b);
                    int dr = Math.Abs(r - pixels[i++]), dg = Math.Abs(g - pixels[i++]), db = Math.Abs(b - pixels[i++]);
                    totalError += dr + dg + db;
                    if (dr <= 35 && dg <= 35 && db <= 35) close++;
                }
            return close * 100 >= Width * Height * 90 && totalError <= Width * Height * 3 * 16;
        }

        internal void Write(BinaryWriter w)
        {
            w.Write(ClientWidth); w.Write(ClientHeight); w.Write(X); w.Write(Y); w.Write(RightButton);
            w.Write(pixels.Length); w.Write(pixels);
        }
        internal static GearPoint Read(BinaryReader r)
        {
            int cw = r.ReadInt32(), ch = r.ReadInt32(), x = r.ReadInt32(), y = r.ReadInt32();
            bool right = r.ReadBoolean(); int length = r.ReadInt32();
            if (length != Width * Height * 3) throw new InvalidDataException("Повреждён образец инвентаря.");
            byte[] bytes = r.ReadBytes(length);
            if (bytes.Length != length) throw new InvalidDataException("Повреждён образец инвентаря.");
            return new GearPoint(cw, ch, x, y, right, bytes);
        }
    }

    public sealed class GearMacro
    {
        private const string Magic = "RMFISH-GEAR-1";
        private readonly GearPoint[] points;
        public int ClientWidth { get { return points[0].ClientWidth; } }
        public int ClientHeight { get { return points[0].ClientHeight; } }
        public GearPoint Point(int index) { return points[index]; }

        public GearMacro(GearPoint first, GearPoint second, GearPoint third)
        {
            if (first == null || second == null || third == null ||
                first.ClientWidth != second.ClientWidth || first.ClientWidth != third.ClientWidth ||
                first.ClientHeight != second.ClientHeight || first.ClientHeight != third.ClientHeight)
                throw new InvalidDataException("Все три шага инвентаря нужно записать при одном разрешении.");
            points = new GearPoint[] { first, second, third };
        }
        public void Save(string path)
        {
            CalibrationFiles.Write(path, delegate(BinaryWriter w)
            {
                w.Write(Magic); foreach (GearPoint point in points) point.Write(w);
            });
        }
        public static GearMacro Load(string path)
        {
            using (BinaryReader r = CalibrationFiles.Open(path, 20000))
            {
                if (r.ReadString() != Magic) throw new InvalidDataException("Неизвестный формат инвентаря.");
                GearPoint a = GearPoint.Read(r), b = GearPoint.Read(r), c = GearPoint.Read(r);
                if (r.BaseStream.Position != r.BaseStream.Length) throw new InvalidDataException("Повреждён образец инвентаря.");
                return new GearMacro(a, b, c);
            }
        }
    }

    // Three observations over at least 160 ms; after firing, the exact notice
    // must be absent for 2 s and a 60 s cooldown must pass before another route.
    internal sealed class NoticeGate
    {
        private bool armed = true;
        private int hits;
        private long first, absentSince = -1, cooldownUntil;
        public void Pause() { hits = 0; absentSince = -1; }
        public bool Observe(bool match, long now)
        {
            if (!armed)
            {
                if (match) absentSince = -1;
                else if (absentSince < 0) absentSince = now;
                if (absentSince >= 0 && now - absentSince >= 2000 && now >= cooldownUntil)
                { armed = true; hits = 0; }
                return false;
            }
            if (!match) { hits = 0; return false; }
            if (hits == 0 || now < first || now - first > 1500) { hits = 1; first = now; }
            else hits++;
            if (hits < 3 || now - first < 160) return false;
            armed = false; hits = 0; absentSince = -1; cooldownUntil = now + 60000;
            return true;
        }
    }

    internal sealed class RelocationTimings
    {
        public int Space = 65, Walk = 7000, TurnSettle = 250, Inventory = 65, Open = 1200, Hover = 300, Between = 900;
    }

    internal static class RelocationRunner
    {
        private static bool WaitSafe(IGamePort port, GameBounds bounds, WaitHandle stop, int milliseconds)
        {
            Stopwatch watch = Stopwatch.StartNew();
            do
            {
                if (stop.WaitOne(0) || port.StopFileExists() || !port.IsForeground(bounds)) return false;
                int delay = (int)Math.Min(40, Math.Max(1, milliseconds - watch.ElapsedMilliseconds));
                if (stop.WaitOne(delay)) return false;
            } while (watch.ElapsedMilliseconds < milliseconds);
            return !stop.WaitOne(0) && !port.StopFileExists() && port.IsForeground(bounds);
        }

        public static bool Execute(IGamePort port, GameBounds bounds, WaitHandle stop, GearMacro gear, int turnUnits,
                                   RelocationTimings timings, Action<string> status, out string error)
        {
            error = "";
            if (gear == null || gear.ClientWidth != bounds.Width || gear.ClientHeight != bounds.Height)
            { error = "Разрешение игры отличается от записи инвентаря."; return false; }
            if (turnUnits < 1 || turnUnits > 10000)
            { error = "Поворот камеры не откалиброван."; return false; }
            status("Останавливаем рыбалку одним коротким пробелом.");
            if (!port.HoldKey(bounds, GameKey.Space, timings.Space, stop, out error)) return false;
            if (!WaitSafe(port, bounds, stop, timings.TurnSettle)) { error = "Прервано после остановки рыбалки."; return false; }
            status("Разворачиваем камеру и идём вперёд W, 7 секунд.");
            if (!port.TurnCamera(bounds, turnUnits, stop, out error)) return false;
            if (!WaitSafe(port, bounds, stop, timings.TurnSettle)) { error = "Прервано после поворота камеры."; return false; }
            if (!port.HoldKey(bounds, GameKey.Forward, timings.Walk, stop, out error)) return false;
            // Allow the injected W-up event to reach Windows before checking
            // held controls and beginning another camera turn.
            if (!WaitSafe(port, bounds, stop, timings.TurnSettle)) { error = "Прервано после движения."; return false; }
            status("Разворачиваем камеру ещё раз и возвращаемся W, 7 секунд. Возврат приблизительный.");
            if (!port.TurnCamera(bounds, turnUnits, stop, out error)) return false;
            if (!WaitSafe(port, bounds, stop, timings.TurnSettle)) { error = "Прервано после поворота камеры."; return false; }
            if (!port.HoldKey(bounds, GameKey.Forward, timings.Walk, stop, out error)) return false;
            if (!WaitSafe(port, bounds, stop, timings.TurnSettle)) { error = "Прервано после движения."; return false; }
            status("Открываем инвентарь и проверяем записанные элементы.");
            if (!port.HoldKey(bounds, GameKey.Inventory, timings.Inventory, stop, out error)) return false;
            if (!WaitSafe(port, bounds, stop, timings.Open)) { error = "Прервано до проверки инвентаря."; return false; }
            for (int i = 0; i < 3; i++)
            {
                GearPoint point = gear.Point(i);
                if (!port.MoveCursor(bounds, point.X, point.Y, stop, out error)) return false;
                if (!WaitSafe(port, bounds, stop, timings.Hover)) { error = "Прервано перед проверкой элемента."; return false; }
                PixelFrame sample = port.CaptureArea(bounds, point.X - GearPoint.HalfWidth, point.Y - GearPoint.HalfHeight,
                    point.X + GearPoint.HalfWidth, point.Y + GearPoint.HalfHeight);
                if (stop.WaitOne(0) || port.StopFileExists() || !port.IsForeground(bounds))
                { error = "Фокус или сигнал стоп изменился во время снимка."; return false; }
                if (!point.Matches(sample))
                { error = "Элемент инвентаря " + (i + 1) + " не совпал с записью. Никаких дальнейших кликов."; return false; }
                ClickResult click = port.ClickAt(bounds, point.X, point.Y, point.RightButton, stop, out error);
                if (click != ClickResult.Sent)
                {
                    if (click == ClickResult.Suppressed) error = "Кнопка мыши удерживается пользователем.";
                    return false;
                }
                if (!WaitSafe(port, bounds, stop, timings.Between)) { error = "Прервано после клика в инвентаре."; return false; }
            }
            return true;
        }
    }
}
