using System;
using System.Diagnostics;
using System.Threading;

namespace RMFish
{
    public enum EmergencySignal { F10, EscapeHeld, MouseButtonsHeld }

    // An independent background poller: unlike WM_HOTKEY it can still ask the
    // engine to stop if the WinForms message loop is busy. Windows/the game can
    // still prevent key state from being observed, so this is only a fallback.
    public sealed class SafetyKeyMonitor : IDisposable
    {
        public const int LeftMouse = 0x01, RightMouse = 0x02, Escape = 0x1B;
        public const int F9 = 0x78, F10 = 0x79;
        public const int DefaultPollMilliseconds = 20, DefaultHoldMilliseconds = 2000;

        private readonly Func<int, bool> isDown;
        private readonly Action<EmergencySignal, bool> emergency;
        private readonly Action diagnose;
        private readonly Action<Exception> fault;
        private readonly int pollMilliseconds, holdMilliseconds;
        private readonly object gate = new object();
        private readonly ManualResetEvent quit = new ManualResetEvent(false);
        private Thread thread;
        private bool disposed;
        private volatile bool stopHeld;

        public bool StopHeld { get { return stopHeld; } }

        public SafetyKeyMonitor(Func<int, bool> isDown, Action<EmergencySignal, bool> emergency,
            Action diagnose, Action<Exception> fault)
            : this(isDown, emergency, diagnose, fault, DefaultPollMilliseconds, DefaultHoldMilliseconds) { }

        // The timing overload makes the polling logic testable without waiting
        // for the production two-second hold on every test run.
        public SafetyKeyMonitor(Func<int, bool> isDown, Action<EmergencySignal, bool> emergency,
            Action diagnose, Action<Exception> fault, int pollMilliseconds, int holdMilliseconds)
        {
            if (isDown == null) throw new ArgumentNullException("isDown");
            if (emergency == null) throw new ArgumentNullException("emergency");
            if (diagnose == null) throw new ArgumentNullException("diagnose");
            if (fault == null) throw new ArgumentNullException("fault");
            if (pollMilliseconds < 1 || holdMilliseconds < pollMilliseconds)
                throw new ArgumentOutOfRangeException("pollMilliseconds");
            this.isDown = isDown;
            this.emergency = emergency;
            this.diagnose = diagnose;
            this.fault = fault;
            this.pollMilliseconds = pollMilliseconds;
            this.holdMilliseconds = holdMilliseconds;
        }

        public void Start()
        {
            lock (gate)
            {
                if (disposed) throw new ObjectDisposedException("SafetyKeyMonitor");
                if (thread != null) return;
                thread = new Thread(Run);
                thread.IsBackground = true;
                thread.Name = "RMFish emergency keys";
                try { thread.Start(); }
                catch { thread = null; throw; }
            }
        }

        private void Run()
        {
            bool wasF9 = false, wasF10 = false, escapeActive = false, mouseActive = false;
            long escapeSince = -1, mouseSince = -1;
            Stopwatch clock = Stopwatch.StartNew();
            try
            {
                while (!quit.WaitOne(pollMilliseconds))
                {
                    bool f9 = isDown(F9), f10 = isDown(F10), escape = isDown(Escape);
                    bool bothMouse = isDown(LeftMouse) && isDown(RightMouse);
                    long now = clock.ElapsedMilliseconds;
                    bool firstEscape = false, firstMouse = false;
                    if (!escape) { escapeSince = -1; escapeActive = false; }
                    else if (escapeSince < 0) escapeSince = now;
                    else if (!escapeActive && now - escapeSince >= holdMilliseconds)
                    { escapeActive = true; firstEscape = true; }
                    if (!bothMouse) { mouseSince = -1; mouseActive = false; }
                    else if (mouseSince < 0) mouseSince = now;
                    else if (!mouseActive && now - mouseSince >= holdMilliseconds)
                    { mouseActive = true; firstMouse = true; }

                    // Repeat the stop request while a stop key is held. This
                    // prevents an F8 restart from undoing an emergency stop.
                    stopHeld = f10 || escapeActive || mouseActive;
                    if (f10) emergency(EmergencySignal.F10, !wasF10);
                    if (escapeActive) emergency(EmergencySignal.EscapeHeld, firstEscape);
                    if (mouseActive) emergency(EmergencySignal.MouseButtonsHeld, firstMouse);
                    if (f9 && !wasF9) diagnose();
                    wasF9 = f9;
                    wasF10 = f10;
                }
            }
            catch (Exception ex)
            {
                try { fault(ex); } catch { }
            }
            finally { stopHeld = false; }
        }

        public void Dispose()
        {
            Thread running;
            lock (gate)
            {
                if (disposed) return;
                disposed = true;
                quit.Set();
                running = thread;
            }
            // Never dispose the wait handle while a slow callback still uses it.
            if (running == null || (running != Thread.CurrentThread && running.Join(1000))) quit.Dispose();
        }
    }

    // A diagnostic capture may block inside GDI. Run it away from both the UI
    // and safety-key threads and never spawn another while one is in flight.
    public sealed class BackgroundProbe
    {
        private readonly Action capture;
        private readonly Action<Exception> fault;
        private int running;

        public BackgroundProbe(Action capture, Action<Exception> fault)
        {
            if (capture == null) throw new ArgumentNullException("capture");
            if (fault == null) throw new ArgumentNullException("fault");
            this.capture = capture;
            this.fault = fault;
        }

        public bool TryStart()
        {
            if (Interlocked.CompareExchange(ref running, 1, 0) != 0) return false;
            try
            {
                Thread worker = new Thread(delegate()
                {
                    try { capture(); }
                    catch (Exception ex) { try { fault(ex); } catch { } }
                    finally { Interlocked.Exchange(ref running, 0); }
                });
                worker.IsBackground = true;
                worker.Name = "RMFish screen diagnostics";
                worker.Start();
                return true;
            }
            catch
            {
                Interlocked.Exchange(ref running, 0);
                throw;
            }
        }
    }

    // Avoid duplicate F9 operations when both the Windows hotkey message and
    // the independent key-state poll observe the same press.
    public sealed class CooldownGate
    {
        private readonly object gate = new object();
        private readonly long milliseconds;
        private bool hasValue;
        private long last;
        public CooldownGate(long milliseconds)
        {
            if (milliseconds < 0) throw new ArgumentOutOfRangeException("milliseconds");
            this.milliseconds = milliseconds;
        }
        public bool TryClaim(long now)
        {
            lock (gate)
            {
                if (hasValue && now >= last && now - last < milliseconds) return false;
                hasValue = true;
                last = now;
                return true;
            }
        }
    }
}
