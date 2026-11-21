using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;

namespace RMFish
{
    public sealed class GameBounds
    {
        public IntPtr Handle;
        public int X, Y, Width, Height;
    }

    // Kept behind an interface so the whole worker can be tested without a game
    // or mouse input. All coordinates are physical game-client pixels.
    public interface IGamePort : IDisposable
    {
        bool TryGetForeground(out GameBounds bounds, out string reason);
        bool IsForeground(GameBounds bounds);
        PixelFrame Capture(GameBounds bounds);
        bool Click(GameBounds bounds, WaitHandle stop, out string error);
        bool StopFileExists();
        // Called by the worker on the same thread that captured the frame.
        void ReleaseCapture();
    }

    public sealed class EngineSnapshot
    {
        public bool Running, Stopping;
        public FishingPhase Phase;
        public string Title, Detail, Detection;
        public int Casts, Reels;
        public TimeSpan Elapsed;
    }

    public sealed class FishingEngine : IDisposable
    {
        private readonly IGamePort port;
        private readonly object gate = new object();
        private readonly ManualResetEvent stop = new ManualResetEvent(false);
        private readonly Queue<string> events = new Queue<string>();
        private Thread worker;
        private Stopwatch watch;
        private System.Threading.Timer sessionTimer;
        private int runGeneration;
        private long stopVersion;
        private string requestedStopReason;
        private TimeSpan elapsed;
        private EngineSnapshot current;
        private bool disposing, disposed;

        public FishingEngine(IGamePort port)
        {
            if (port == null) throw new ArgumentNullException("port");
            this.port = port;
            current = new EngineSnapshot
            {
                Running = false, Phase = FishingPhase.Stopped, Title = "Готов к запуску",
                Detail = "Выберите удочку и наживку в игре, затем нажмите «Старт».",
                Detection = "Кадр ещё не проверен."
            };
            Log("RMFish готов к работе.");
        }

        // A start prepared while an emergency stop arrives must not clear it.
        public long StopVersion { get { lock (gate) { return stopVersion; } } }

        public bool Start(EngineOptions requested) { return Start(requested, null); }

        public bool Start(EngineOptions requested, long? expectedStopVersion)
        {
            if (requested == null) throw new ArgumentNullException("requested");
            lock (gate)
            {
                if (disposed || disposing) throw new ObjectDisposedException("FishingEngine");
                if (expectedStopVersion.HasValue && stopVersion != expectedStopVersion.Value) return false;
                if (worker != null && worker.IsAlive) return false;
                EngineOptions options = requested.CopyValidated();
                stop.Reset();
                requestedStopReason = null;
                int generation = ++runGeneration;
                watch = Stopwatch.StartNew();
                elapsed = TimeSpan.Zero;
                current = new EngineSnapshot
                {
                    Running = true, Phase = FishingPhase.Searching, Title = "Запуск",
                    Detail = "Переключитесь в GTA5.", Detection = "Кадр ещё не проверен."
                };
                AddEvent("Запуск. Ожидание активного окна GTA5.");
                try
                {
                    worker = new Thread(delegate() { Run(options); });
                    worker.IsBackground = true;
                    worker.Name = "RMFish worker";
                    // The timer can request a stop even while the worker is in
                    // a native call; it cannot forcibly interrupt that call.
                    // A generation token prevents an old timer stopping a new run.
                    sessionTimer = new System.Threading.Timer(delegate(object ignored)
                    {
                        lock (gate)
                        {
                            if (!disposed && current.Running && runGeneration == generation)
                                SignalStopLocked(SessionLimitReason(options.SessionLimitSeconds));
                        }
                    }, null, options.SessionLimitSeconds * 1000, Timeout.Infinite);
                    worker.Start();
                }
                catch
                {
                    if (sessionTimer != null) { sessionTimer.Dispose(); sessionTimer = null; }
                    worker = null;
                    stop.Set();
                    watch.Stop();
                    elapsed = watch.Elapsed;
                    current.Running = false;
                    current.Stopping = false;
                    current.Phase = FishingPhase.Stopped;
                    current.Title = "Не удалось запустить";
                    current.Detail = "Рабочий поток не запущен. Проверьте журнал.";
                    throw;
                }
                return true;
            }
        }

        public void RequestStop() { RequestStop("Остановлено пользователем."); }

        public void RequestStop(string reason)
        {
            lock (gate)
            {
                if (!disposed) SignalStopLocked(reason);
            }
        }

        // gate must be held. Do not report that a blocked native call has
        // finished: a stop is only a request until the worker really exits.
        private void SignalStopLocked(string reason)
        {
            unchecked { stopVersion++; }
            if (current.Running && !stop.WaitOne(0))
            {
                requestedStopReason = String.IsNullOrEmpty(reason) ? "Остановлено пользователем." : reason;
                current.Stopping = true;
                current.Title = "Остановка…";
                current.Detail = requestedStopReason + " Ожидание завершения операции.";
                AddEvent("Запрос остановки: " + requestedStopReason);
            }
            stop.Set();
        }

        private static string SessionLimitReason(int seconds)
        {
            return String.Format("Истёк лимит сессии ({0} с). Запрошена остановка.", seconds);
        }

        public bool WaitForStop(int milliseconds)
        {
            Thread thread;
            lock (gate) { thread = worker; }
            return thread == null || !thread.IsAlive || thread.Join(milliseconds);
        }

        public EngineSnapshot Snapshot()
        {
            lock (gate)
            {
                return new EngineSnapshot
                {
                    Running = current.Running, Stopping = current.Stopping, Phase = current.Phase, Title = current.Title,
                    Detail = current.Detail, Detection = current.Detection,
                    Casts = current.Casts, Reels = current.Reels,
                    Elapsed = current.Running && watch != null ? watch.Elapsed : elapsed
                };
            }
        }

        public string[] Events()
        {
            lock (gate) { return events.ToArray(); }
        }

        public void Log(string text)
        {
            lock (gate) { AddEvent(text); }
        }

        private void AddEvent(string text)
        {
            events.Enqueue(DateTime.Now.ToString("HH:mm:ss") + "  " + text);
            while (events.Count > 100) events.Dequeue();
        }

        private void Publish(FishingStateMachine machine, bool paused, string pauseReason)
        {
            lock (gate)
            {
                // Do not replace the visible stop request with a stale frame.
                if (stop.WaitOne(0)) return;
                FishingPhase next = paused ? FishingPhase.Paused : machine.Phase;
                string title = paused ? "Пауза · игра не активна" : machine.Title;
                string detail = paused ? pauseReason : machine.Detail;
                if (current.Phase != next || current.Title != title)
                    AddEvent(title + ": " + detail);
                current.Phase = next;
                current.Title = title;
                current.Detail = detail;
                current.Detection = machine.LastDetection;
                current.Casts = machine.Casts;
                current.Reels = machine.Reels;
            }
        }

        private void Run(EngineOptions options)
        {
            FishingStateMachine machine = new FishingStateMachine(options);
            string finalReason = "Остановлено пользователем.";
            bool wasFocused = false;
            try
            {
                while (!stop.WaitOne(0))
                {
                    // This independent check backs up the timer if the thread
                    // pool is delayed; the limit also counts time while paused.
                    if (watch.ElapsedMilliseconds >= options.SessionLimitSeconds * 1000L)
                    {
                        finalReason = SessionLimitReason(options.SessionLimitSeconds);
                        break;
                    }
                    if (port.StopFileExists())
                    {
                        finalReason = "Обнаружен STOP.txt. Для нового запуска нажмите «Старт».";
                        break;
                    }
                    GameBounds bounds;
                    string reason;
                    if (!port.TryGetForeground(out bounds, out reason))
                    {
                        if (wasFocused) machine.Pause();
                        wasFocused = false;
                        Publish(machine, true, reason);
                        stop.WaitOne(125);
                        continue;
                    }
                    wasFocused = true;
                    if (stop.WaitOne(0)) break;
                    PixelFrame frame = port.Capture(bounds);
                    // A stop may have arrived during the native capture. Do not
                    // analyze or act on a frame obtained before that request.
                    if (stop.WaitOne(0)) break;
                    FishingAction action = machine.Step(frame, watch.ElapsedMilliseconds);
                    if (stop.WaitOne(0)) break;
                    Publish(machine, false, null);
                    if (action == FishingAction.Stop)
                    {
                        finalReason = machine.StopReason;
                        break;
                    }
                    if (action == FishingAction.CastClick || action == FishingAction.ReelClick)
                    {
                        // Check again after capture: the user may have Alt-Tabbed
                        // while the frame was being analyzed.
                        if (stop.WaitOne(0)) break;
                        if (watch.ElapsedMilliseconds >= options.SessionLimitSeconds * 1000L)
                        {
                            finalReason = SessionLimitReason(options.SessionLimitSeconds);
                            break;
                        }
                        if (port.StopFileExists())
                        {
                            finalReason = "Обнаружен STOP.txt. Для нового запуска нажмите «Старт».";
                            break;
                        }
                        if (!port.IsForeground(bounds))
                        {
                            machine.Pause();
                            wasFocused = false;
                            Publish(machine, true, "Вернитесь в GTA5 — клики приостановлены.");
                            continue;
                        }
                        if (watch.ElapsedMilliseconds >= options.SessionLimitSeconds * 1000L)
                        {
                            finalReason = SessionLimitReason(options.SessionLimitSeconds);
                            break;
                        }
                        string inputError;
                        if (!port.Click(bounds, stop, out inputError))
                        {
                            if (stop.WaitOne(0)) break;
                            if (port.StopFileExists())
                            {
                                finalReason = "Обнаружен STOP.txt. Для нового запуска нажмите «Старт».";
                                break;
                            }
                            if (!port.IsForeground(bounds))
                            {
                                machine.Pause();
                                wasFocused = false;
                                continue;
                            }
                            finalReason = "Не удалось отправить ЛКМ: " + inputError;
                            break;
                        }
                    }
                    stop.WaitOne(options.PollMilliseconds);
                }
            }
            catch (Exception ex)
            {
                finalReason = "Ошибка: " + ex.Message;
            }
            finally
            {
                // Report a pending stop even if releasing GDI later blocks.
                lock (gate)
                {
                    if (!stop.WaitOne(0)) SignalStopLocked(finalReason);
                    if (finalReason == "Остановлено пользователем." && !String.IsNullOrEmpty(requestedStopReason))
                        finalReason = requestedStopReason;
                }
                // GetDC/ReleaseDC are thread-affine. Release before the worker
                // exits so a later Start creates its own capture surface.
                try { port.ReleaseCapture(); }
                catch (Exception ex) { Log("Ошибка освобождения снимка: " + ex.Message); }
                lock (gate)
                {
                    if (sessionTimer != null) { sessionTimer.Dispose(); sessionTimer = null; }
                    if (watch != null)
                    {
                        watch.Stop();
                        elapsed = watch.Elapsed;
                    }
                    current.Running = false;
                    current.Stopping = false;
                    current.Phase = FishingPhase.Stopped;
                    current.Title = "Остановлено";
                    current.Detail = finalReason;
                    current.Casts = machine.Casts;
                    current.Reels = machine.Reels;
                    current.Detection = machine.LastDetection;
                    AddEvent(finalReason);
                }
            }
        }

        public void Dispose()
        {
            lock (gate)
            {
                if (disposed) return;
                // Block a concurrent restart while waiting for the worker.
                // A stuck native call may outlive this bounded wait.
                disposing = true;
                SignalStopLocked("Закрытие RMFish.");
            }
            // The worker owns the capture surface. Don't dispose it while it is
            // still capturing, even if a Windows API call is unusually slow.
            if (!WaitForStop(2000)) return;
            lock (gate)
            {
                if (disposed) return;
                disposed = true;
                port.Dispose();
                stop.Dispose();
            }
        }
    }
}
