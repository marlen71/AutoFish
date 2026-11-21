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
        [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);
        [DllImport("user32.dll", SetLastError = true)] public static extern bool RegisterHotKey(IntPtr handle, int id, uint modifiers, uint key);
        [DllImport("user32.dll")] public static extern bool UnregisterHotKey(IntPtr handle, int id);
        [DllImport("user32.dll")] internal static extern bool ReleaseCapture();
        [DllImport("user32.dll")] internal static extern IntPtr SendMessage(IntPtr handle, int message, IntPtr wParam, IntPtr lParam);

        [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
        [StructLayout(LayoutKind.Sequential)] public struct Point { public int X, Y; }

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
        private CaptureSurface surface;

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

        public bool Click(GameBounds bounds, WaitHandle stop, out string error)
        {
            error = "";
            // The last check is immediately before the down event, not just
            // before the screenshot. Never move the user's cursor.
            if (stop.WaitOne(0) || StopFileExists() || !IsForeground(bounds)) return false;
            // Do not release a mouse button that the person is physically holding.
            if ((WindowsNative.GetAsyncKeyState(1) & 0x8000) != 0) return true;
            bool down = false;
            try
            {
                WindowsNative.mouse_event(0x0002, 0, 0, 0, UIntPtr.Zero);
                down = true;
                stop.WaitOne(18);
                return true;
            }
            finally
            {
                if (down) WindowsNative.mouse_event(0x0004, 0, 0, 0, UIntPtr.Zero);
            }
        }

        public void ReleaseCapture()
        {
            if (surface != null) { surface.Dispose(); surface = null; }
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
