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
        public bool Running;
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
        private TimeSpan elapsed;
        private EngineSnapshot current;
        private bool disposed;

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

        public bool Start(EngineOptions requested)
        {
            if (requested == null) throw new ArgumentNullException("requested");
            lock (gate)
            {
                if (disposed) throw new ObjectDisposedException("FishingEngine");
                if (worker != null && worker.IsAlive) return false;
                EngineOptions options = requested.CopyValidated();
                stop.Reset();
                watch = Stopwatch.StartNew();
                elapsed = TimeSpan.Zero;
                current = new EngineSnapshot
                {
                    Running = true, Phase = FishingPhase.Searching, Title = "Запуск",
                    Detail = "Переключитесь в GTA5.", Detection = "Кадр ещё не проверен."
                };
                AddEvent("Запуск. Ожидание активного окна GTA5.");
                worker = new Thread(delegate() { Run(options); });
                worker.IsBackground = true;
                worker.Name = "RMFish worker";
                worker.Start();
                return true;
            }
        }

        public void RequestStop()
        {
            lock (gate) { if (!disposed) stop.Set(); }
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
                    Running = current.Running, Phase = current.Phase, Title = current.Title,
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
                    PixelFrame frame = port.Capture(bounds);
                    FishingAction action = machine.Step(frame, watch.ElapsedMilliseconds);
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
                // GetDC/ReleaseDC are thread-affine. Release before the worker
                // exits so a later Start creates its own capture surface.
                try { port.ReleaseCapture(); }
                catch (Exception ex) { Log("Ошибка освобождения снимка: " + ex.Message); }
                lock (gate)
                {
                    if (watch != null)
                    {
                        watch.Stop();
                        elapsed = watch.Elapsed;
                    }
                    current.Running = false;
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
                stop.Set();
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
