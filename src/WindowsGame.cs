using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

namespace RMFish
{
    public static class WindowsNative
    {
        [DllImport("user32.dll")] private static extern bool SetProcessDPIAware();
        [DllImport("user32.dll")] private static extern bool SetProcessDpiAwarenessContext(IntPtr value);
        [DllImport("kernel32.dll")] private static extern IntPtr GetConsoleWindow();
        [DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr window, int command);
        [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr handle, out uint processId);
        [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr handle);
        [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr handle, out Rect rect);
        [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr handle, ref Point point);
        [DllImport("user32.dll")] public static extern int GetSystemMetrics(int index);
        [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int key);
        [DllImport("user32.dll")] public static extern bool GetCursorPos(out Point point);
        [DllImport("user32.dll", SetLastError = true)] public static extern bool SetCursorPos(int x, int y);
        [DllImport("user32.dll", SetLastError = true)] public static extern uint SendInput(uint count, Input[] inputs, int size);
        [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);
        [DllImport("user32.dll")] public static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extraInfo);
        [DllImport("user32.dll", SetLastError = true)] public static extern bool RegisterHotKey(IntPtr handle, int id, uint modifiers, uint key);
        [DllImport("user32.dll")] public static extern bool UnregisterHotKey(IntPtr handle, int id);
        [DllImport("user32.dll")] internal static extern bool ReleaseCapture();
        [DllImport("user32.dll")] internal static extern IntPtr SendMessage(IntPtr handle, int message, IntPtr wParam, IntPtr lParam);

        [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
        [StructLayout(LayoutKind.Sequential)] public struct Point { public int X, Y; }
        [StructLayout(LayoutKind.Sequential)] public struct Input { public uint Type; public InputUnion Data; }
        [StructLayout(LayoutKind.Explicit)] public struct InputUnion
        {
            [FieldOffset(0)] public KeyboardInput Keyboard;
            [FieldOffset(0)] public MouseInput Mouse;
        }
        [StructLayout(LayoutKind.Sequential)] public struct KeyboardInput
        { public ushort VirtualKey, Scan; public uint Flags, Time; public UIntPtr ExtraInfo; }
        [StructLayout(LayoutKind.Sequential)] public struct MouseInput
        { public int X, Y; public uint MouseData, Flags, Time; public UIntPtr ExtraInfo; }

        public static bool SendScanKey(ushort scan, bool up)
        {
            Input input = new Input(); input.Type = 1;
            input.Data.Keyboard.Scan = scan;
            input.Data.Keyboard.Flags = 0x0008u | (up ? 0x0002u : 0u); // SCANCODE | KEYUP
            return SendInput(1, new Input[] { input }, Marshal.SizeOf(typeof(Input))) == 1;
        }
        public static bool SendMouse(uint flags)
        {
            Input input = new Input(); input.Type = 0; input.Data.Mouse.Flags = flags;
            return SendInput(1, new Input[] { input }, Marshal.SizeOf(typeof(Input))) == 1;
        }

        public static void HideConsoleWindow()
        {
            // Only the BAT launcher passes -HideConsole; direct PowerShell
            // invocation must not hide the user's existing terminal.
            IntPtr console = GetConsoleWindow();
            if (console != IntPtr.Zero) ShowWindow(console, 0); // SW_HIDE
        }

        public static void EnableDpiAwareness()
        {
            // Must run before any WinForms window is created. Older Windows does
            // not have the per-monitor API, so fall back to system DPI awareness.
            try { if (SetProcessDpiAwarenessContext(new IntPtr(-4))) return; }
            catch (EntryPointNotFoundException) { }
            try { SetProcessDPIAware(); }
            catch (EntryPointNotFoundException) { }
        }
    }

    public sealed class WindowsGamePort : IGamePort
    {
        private readonly string stopFile;
        private CaptureSurface surface, areaSurface;

        public WindowsGamePort(string stopFile) { this.stopFile = stopFile; }

        public bool StopFileExists() { return !String.IsNullOrEmpty(stopFile) && File.Exists(stopFile); }

        public bool TryGetForeground(out GameBounds bounds, out string reason)
        {
            bounds = null;
            IntPtr window = WindowsNative.GetForegroundWindow();
            uint processId;
            WindowsNative.GetWindowThreadProcessId(window, out processId);
            bool isGame = false;
            if (processId != 0)
            {
                try
                {
                    using (Process p = Process.GetProcessById((int)processId))
                        isGame = String.Equals(p.ProcessName, "GTA5", StringComparison.OrdinalIgnoreCase);
                }
                catch (ArgumentException) { }
                catch (InvalidOperationException) { }
                catch (Win32Exception) { }
            }
            if (!isGame || window == IntPtr.Zero || WindowsNative.IsIconic(window))
            {
                bool found = false;
                Process[] processes = Process.GetProcessesByName("GTA5");
                try { found = processes.Length > 0; }
                finally { foreach (Process p in processes) p.Dispose(); }
                reason = found ? "Переключитесь в GTA5. Пока игра не активна, кликов нет." :
                    "Процесс GTA5 не найден. Откройте игру и переключитесь в неё.";
                return false;
            }

            WindowsNative.Rect client;
            WindowsNative.Point topLeft = new WindowsNative.Point();
            if (!WindowsNative.GetClientRect(window, out client) || !WindowsNative.ClientToScreen(window, ref topLeft))
            {
                reason = "Не удалось определить размер окна GTA5.";
                return false;
            }
            int width = client.Right - client.Left, height = client.Bottom - client.Top;
            if (width < 1280 || height < 720 || Math.Abs(width / (double)height - 16.0 / 9.0) > 0.035)
            {
                reason = String.Format("Окно {0}×{1}: нужен формат 16:9 и минимум 1280×720; рекомендуется 1920×1080.", width, height);
                return false;
            }
            int vx = WindowsNative.GetSystemMetrics(76), vy = WindowsNative.GetSystemMetrics(77);
            int vw = WindowsNative.GetSystemMetrics(78), vh = WindowsNative.GetSystemMetrics(79);
            if (topLeft.X < vx || topLeft.Y < vy || topLeft.X + width > vx + vw || topLeft.Y + height > vy + vh)
            {
                reason = "Окно GTA5 частично за пределами экрана. Переместите его целиком на монитор.";
                return false;
            }
            bounds = new GameBounds { Handle = window, X = topLeft.X, Y = topLeft.Y, Width = width, Height = height };
            reason = String.Format("GTA5 в фокусе · {0}×{1}", width, height);
            return true;
        }

        public bool IsForeground(GameBounds bounds)
        {
            if (bounds == null || bounds.Handle == IntPtr.Zero ||
                WindowsNative.GetForegroundWindow() != bounds.Handle || WindowsNative.IsIconic(bounds.Handle)) return false;
            WindowsNative.Rect client;
            WindowsNative.Point topLeft = new WindowsNative.Point();
            return WindowsNative.GetClientRect(bounds.Handle, out client) && WindowsNative.ClientToScreen(bounds.Handle, ref topLeft) &&
                client.Right - client.Left == bounds.Width && client.Bottom - client.Top == bounds.Height &&
                topLeft.X == bounds.X && topLeft.Y == bounds.Y;
        }

        public PixelFrame Capture(GameBounds bounds)
        {
            int left = (int)Math.Floor(PixelFrame.CropLeft * (double)bounds.Width / PixelFrame.ReferenceWidth);
            int top = (int)Math.Floor(PixelFrame.CropTop * (double)bounds.Height / PixelFrame.ReferenceHeight);
            int right = (int)Math.Ceiling(PixelFrame.CropRight * (double)bounds.Width / PixelFrame.ReferenceWidth);
            int bottom = (int)Math.Ceiling(PixelFrame.CropBottom * (double)bounds.Height / PixelFrame.ReferenceHeight);
            int width = right - left, height = bottom - top;
            if (surface == null || surface.Width != width || surface.Height != height)
            {
                if (surface != null) surface.Dispose();
                surface = new CaptureSurface(width, height);
            }
            byte[] pixels = surface.Read(bounds.X + left, bounds.Y + top);
            return new PixelFrame(pixels, width, height, width * 4, bounds.Width, bounds.Height, left, top);
        }

        public PixelFrame CaptureArea(GameBounds bounds, int left, int top, int right, int bottom)
        {
            if (bounds == null || left < 0 || top < 0 || right > PixelFrame.ReferenceWidth ||
                bottom > PixelFrame.ReferenceHeight || right <= left || bottom <= top)
                throw new ArgumentException("Недопустимая область снимка.");
            int x = (int)Math.Floor(left * (double)bounds.Width / PixelFrame.ReferenceWidth);
            int y = (int)Math.Floor(top * (double)bounds.Height / PixelFrame.ReferenceHeight);
            int width = (int)Math.Ceiling(right * (double)bounds.Width / PixelFrame.ReferenceWidth) - x;
            int height = (int)Math.Ceiling(bottom * (double)bounds.Height / PixelFrame.ReferenceHeight) - y;
            if (areaSurface == null || areaSurface.Width != width || areaSurface.Height != height)
            {
                if (areaSurface != null) areaSurface.Dispose();
                areaSurface = new CaptureSurface(width, height);
            }
            byte[] pixels = areaSurface.Read(bounds.X + x, bounds.Y + y);
            return new PixelFrame(pixels, width, height, width * 4, bounds.Width, bounds.Height, x, y);
        }

        private bool Ready(GameBounds bounds, WaitHandle stop)
        { return !stop.WaitOne(0) && !StopFileExists() && IsForeground(bounds); }

        private static bool Held(int key) { return (WindowsNative.GetAsyncKeyState(key) & 0x8000) != 0; }

        private ClickResult SendClick(GameBounds bounds, bool right, int duration, WaitHandle stop, out string error)
        {
            error = "";
            if (!Ready(bounds, stop)) return ClickResult.Failed;
            // Never release a button that the user is already holding.
            if (Held(1) || (right && Held(2))) return ClickResult.Suppressed;
            if (!Ready(bounds, stop)) return ClickResult.Failed;
            uint downFlag = right ? 0x0008u : 0x0002u, upFlag = right ? 0x0010u : 0x0004u;
            if (!WindowsNative.SendMouse(downFlag))
            {
                error = "Windows отклонила нажатие мыши (возможно, разные права запуска игры и программы).";
                return ClickResult.Failed;
            }
            bool released = false;
            try { stop.WaitOne(duration); }
            finally
            {
                // Always release even after focus loss or an emergency stop.
                released = WindowsNative.SendMouse(upFlag);
                if (!released) WindowsNative.mouse_event(upFlag, 0, 0, 0, UIntPtr.Zero);
            }
            if (!released) { error = "Не удалось подтвердить отпускание мыши. Нажмите и отпустите её вручную."; return ClickResult.Failed; }
            return ClickResult.Sent;
        }

        public ClickResult Click(GameBounds bounds, WaitHandle stop, out string error)
        { return SendClick(bounds, false, 18, stop, out error); }

        private static int ScreenX(GameBounds bounds, int x)
        { return bounds.X + (int)Math.Round(x * (double)bounds.Width / PixelFrame.ReferenceWidth); }
        private static int ScreenY(GameBounds bounds, int y)
        { return bounds.Y + (int)Math.Round(y * (double)bounds.Height / PixelFrame.ReferenceHeight); }

        public bool MoveCursor(GameBounds bounds, int x, int y, WaitHandle stop, out string error)
        {
            error = "";
            if (x < 0 || x >= PixelFrame.ReferenceWidth || y < 0 || y >= PixelFrame.ReferenceHeight || !Ready(bounds, stop))
            { error = "Нет фокуса игры или недопустимая позиция курсора."; return false; }
            if (Held(1) || Held(2)) { error = "Отпустите кнопки мыши перед автоотходом."; return false; }
            if (!WindowsNative.SetCursorPos(ScreenX(bounds, x), ScreenY(bounds, y)))
            { error = "Не удалось переместить курсор в инвентаре."; return false; }
            return true;
        }

        public ClickResult ClickAt(GameBounds bounds, int x, int y, bool right, WaitHandle stop, out string error)
        {
            error = "";
            WindowsNative.Point cursor;
            if (!Ready(bounds, stop) || !WindowsNative.GetCursorPos(out cursor) ||
                Math.Abs(cursor.X - ScreenX(bounds, x)) > 1 || Math.Abs(cursor.Y - ScreenY(bounds, y)) > 1)
            { error = "Курсор или фокус изменился до клика по инвентарю."; return ClickResult.Failed; }
            if (Held(1) || Held(2)) return ClickResult.Suppressed;
            return SendClick(bounds, right, 50, stop, out error);
        }

        public bool HoldKey(GameBounds bounds, GameKey key, int milliseconds, WaitHandle stop, out string error)
        {
            error = "";
            if (milliseconds < 1 || milliseconds > 7000 || !Ready(bounds, stop))
            { error = "Остановка или потеря фокуса перед нажатием клавиши."; return false; }
            ushort scan; byte vk;
            switch (key)
            {
                case GameKey.Space: scan = 0x39; vk = 0x20; break;
                case GameKey.Back: scan = 0x1f; vk = 0x53; break;
                case GameKey.Forward: scan = 0x11; vk = 0x57; break;
                case GameKey.Inventory: scan = 0x17; vk = 0x49; break;
                default: error = "Неизвестная клавиша маршрута."; return false;
            }
            // Refuse to start while a person is operating the same controls.
            if (Held(0x20) || Held(0x53) || Held(0x57) || Held(0x49) || Held(1) || Held(2))
            { error = "Отпустите пробел, W, S, I и кнопки мыши."; return false; }
            if (!Ready(bounds, stop)) { error = "Фокус игры изменился."; return false; }
            if (!WindowsNative.SendScanKey(scan, false))
            { error = "Windows отклонила клавишу. Проверьте права игры и программы."; return false; }
            bool released = false, completed = false;
            try
            {
                Stopwatch watch = Stopwatch.StartNew();
                while (watch.ElapsedMilliseconds < milliseconds)
                {
                    if (!Ready(bounds, stop)) break;
                    int delay = (int)Math.Min(30L, Math.Max(1L, milliseconds - watch.ElapsedMilliseconds));
                    if (stop.WaitOne(delay)) break;
                }
                completed = watch.ElapsedMilliseconds >= milliseconds && Ready(bounds, stop);
            }
            finally
            {
                released = WindowsNative.SendScanKey(scan, true);
                if (!released) WindowsNative.keybd_event(vk, (byte)scan, 0x0002, UIntPtr.Zero);
            }
            if (!released) { error = "Не удалось подтвердить отпускание клавиши. Нажмите и отпустите её вручную."; return false; }
            if (!completed) { error = "Остановлено или потерян фокус во время движения; проверьте положение персонажа."; return false; }
            return true;
        }

        public void ReleaseCapture()
        {
            if (surface != null) { surface.Dispose(); surface = null; }
            if (areaSurface != null) { areaSurface.Dispose(); areaSurface = null; }
        }

        public void Dispose() { ReleaseCapture(); }
    }

    // A reusable top-down DIB is much cheaper than allocating a full-screen
    // Bitmap on every poll. It reads the visible desktop, not game memory.
    internal sealed class CaptureSurface : IDisposable
    {
        [StructLayout(LayoutKind.Sequential)] private struct BitmapInfoHeader
        {
            public uint Size;
            public int Width, Height;
            public ushort Planes, BitCount;
            public uint Compression, SizeImage;
            public int XPelsPerMeter, YPelsPerMeter;
            public uint ClrUsed, ClrImportant;
        }
        [StructLayout(LayoutKind.Sequential)] private struct BitmapInfo { public BitmapInfoHeader Header; public uint Colors; }

        [DllImport("user32.dll")] private static extern IntPtr GetDC(IntPtr window);
        [DllImport("user32.dll")] private static extern int ReleaseDC(IntPtr window, IntPtr dc);
        [DllImport("gdi32.dll", SetLastError = true)] private static extern IntPtr CreateCompatibleDC(IntPtr dc);
        [DllImport("gdi32.dll", SetLastError = true)] private static extern bool DeleteDC(IntPtr dc);
        [DllImport("gdi32.dll", SetLastError = true)] private static extern IntPtr CreateDIBSection(IntPtr dc, ref BitmapInfo info, uint usage, out IntPtr bits, IntPtr section, uint offset);
        [DllImport("gdi32.dll", SetLastError = true)] private static extern IntPtr SelectObject(IntPtr dc, IntPtr obj);
        [DllImport("gdi32.dll", SetLastError = true)] private static extern bool DeleteObject(IntPtr obj);
        [DllImport("gdi32.dll", SetLastError = true)] private static extern bool BitBlt(IntPtr dst, int x, int y, int width, int height, IntPtr src, int sx, int sy, uint operation);
        [DllImport("gdi32.dll")] private static extern bool GdiFlush();

        private IntPtr screen, memory, bitmap, oldBitmap, bits;
        private readonly byte[] buffer;
        public int Width { get; private set; }
        public int Height { get; private set; }

        public CaptureSurface(int width, int height)
        {
            Width = width;
            Height = height;
            buffer = new byte[checked(width * height * 4)];
            try
            {
                screen = GetDC(IntPtr.Zero);
                if (screen == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error(), "Не удалось получить экран.");
                memory = CreateCompatibleDC(screen);
                if (memory == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error(), "Не удалось создать контекст снимка.");
                BitmapInfo info = new BitmapInfo();
                info.Header.Size = (uint)Marshal.SizeOf(typeof(BitmapInfoHeader));
                info.Header.Width = width;
                info.Header.Height = -height;
                info.Header.Planes = 1;
                info.Header.BitCount = 32;
                info.Header.Compression = 0;
                bitmap = CreateDIBSection(screen, ref info, 0, out bits, IntPtr.Zero, 0);
                if (bitmap == IntPtr.Zero || bits == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error(), "Не удалось создать снимок.");
                oldBitmap = SelectObject(memory, bitmap);
                if (oldBitmap == IntPtr.Zero || oldBitmap == new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error(), "Не удалось подготовить снимок.");
            }
            catch { Dispose(); throw; }
        }

        public byte[] Read(int x, int y)
        {
            const uint SRCCOPY = 0x00CC0020;
            const uint CAPTUREBLT = 0x40000000;
            if (!BitBlt(memory, 0, 0, Width, Height, screen, x, y, SRCCOPY | CAPTUREBLT))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "Не удалось снять экран. Попробуйте оконный режим без рамки.");
            // Flush the calling thread's GDI batch before reading DIB memory.
            if (!GdiFlush()) throw new InvalidOperationException("Не удалось завершить снимок экрана.");
            Marshal.Copy(bits, buffer, 0, buffer.Length);
            return buffer;
        }

        public void Dispose()
        {
            if (memory != IntPtr.Zero && oldBitmap != IntPtr.Zero && oldBitmap != new IntPtr(-1)) SelectObject(memory, oldBitmap);
            if (bitmap != IntPtr.Zero) DeleteObject(bitmap);
            if (memory != IntPtr.Zero) DeleteDC(memory);
            if (screen != IntPtr.Zero) ReleaseDC(IntPtr.Zero, screen);
            screen = memory = bitmap = oldBitmap = bits = IntPtr.Zero;
        }
    }
}
