using System;

namespace RMFish
{
    public enum FishingPhase { Searching, Casting, WaitingBite, Reeling, Paused, Stopped }
    public enum FishingAction { None, CastClick, ReelClick, Stop }

    public sealed class EngineOptions
    {
        public int PollMilliseconds = 20;
        public int ReelClickMilliseconds = 35;
        public int WaitTimeoutSeconds = 300; // zero means no separate waiting limit
        public int SessionLimitSeconds = 120; // always bounded, including while paused
        public bool MinimizeOnStart = true;

        public EngineOptions CopyValidated()
        {
            EngineOptions result = new EngineOptions();
            result.PollMilliseconds = Math.Max(20, Math.Min(200, PollMilliseconds));
            result.ReelClickMilliseconds = Math.Max(35, Math.Min(250, ReelClickMilliseconds));
            result.WaitTimeoutSeconds = Math.Max(0, Math.Min(3600, WaitTimeoutSeconds));
            result.SessionLimitSeconds = Math.Max(1, Math.Min(1800, SessionLimitSeconds));
            result.MinimizeOnStart = MinimizeOnStart;
            return result;
        }
    }

    // Pure state machine: it never takes screenshots or sends input. The worker
    // supplies a monotonic timestamp and executes the returned action only after
    // checking foreground and STOP again.
    public sealed class FishingStateMachine
    {
        private readonly EngineOptions options;
        private bool initialized, castClicked;
        private int castSeen, biteSeen, missing;
        private long phaseSince, lastClick;

        public FishingPhase Phase { get; private set; }
        public string Title { get; private set; }
        public string Detail { get; private set; }
        public string LastDetection { get; private set; }
        public string StopReason { get; private set; }
        public int Casts { get; private set; }
        // This is the number of completed reeling phases, not confirmed catches.
        public int Reels { get; private set; }

        public FishingStateMachine(EngineOptions options)
        {
            if (options == null) throw new ArgumentNullException("options");
            this.options = options.CopyValidated();
            Phase = FishingPhase.Searching;
            Title = "Ожидание рыбалки";
            Detail = "Подготовьте удочку и вернитесь в GTA5.";
            LastDetection = "Кадр ещё не проверен.";
            StopReason = "";
        }

        public void Pause()
        {
            // Reacquiring the game always starts by inspecting the current screen;
            // no pending click or timeout survives a focus loss.
            initialized = false;
            castClicked = false;
            castSeen = biteSeen = missing = 0;
            Phase = FishingPhase.Searching;
            Title = "Ожидание рыбалки";
            Detail = "Проверяем экран игры.";
        }

        public FishingAction Step(PixelFrame frame, long nowMilliseconds)
        {
            if (Phase == FishingPhase.Stopped) return FishingAction.Stop;
            if (!initialized)
            {
                initialized = true;
                phaseSince = nowMilliseconds;
            }

            CastInfo cast = Vision.FindCast(frame);
            bool bite = Vision.BiteActive(frame);
            LastDetection = Describe(cast, bite);
            biteSeen = bite ? biteSeen + 1 : 0;

            if (Phase == FishingPhase.Reeling)
            {
                if (!bite)
                {
                    // Never click on the first missing frame. A few missing frames
                    // confirm the end so one bad screenshot doesn't end the cycle.
                    missing++;
                    if (missing >= 3)
                    {
                        Reels++;
                        EnterSearching(nowMilliseconds, "Вываживание завершено. Ждём следующий заброс.");
                    }
                    return FishingAction.None;
                }
                missing = 0;
                if (nowMilliseconds - phaseSince >= 45000)
                    return Stop("Шкала вываживания не исчезла за 45 секунд. Проверьте игру.");
                if (nowMilliseconds - lastClick >= options.ReelClickMilliseconds)
                {
                    lastClick = nowMilliseconds;
                    return FishingAction.ReelClick;
                }
                return FishingAction.None;
            }

            // A visible bite takes priority, even when the app starts mid-fishing.
            if (biteSeen >= 2)
            {
                if (Phase == FishingPhase.Casting && castClicked) Casts++;
                Phase = FishingPhase.Reeling;
                Title = "Вываживание";
                Detail = "Шкала видна — нажимаем ЛКМ до её исчезновения.";
                phaseSince = nowMilliseconds;
                lastClick = nowMilliseconds;
                missing = castSeen = 0;
                castClicked = false;
                return FishingAction.ReelClick;
            }
            if (bite) return FishingAction.None; // wait for the second confirmation

            if (Phase == FishingPhase.Casting)
            {
                if (cast == null)
                {
                    missing++;
                    if (missing >= 3)
                    {
                        if (castClicked)
                        {
                            Casts++;
                            Phase = FishingPhase.WaitingBite;
                            Title = "Ожидание клёва";
                            Detail = "Заброс выполнен. Ждём вертикальную шкалу.";
                        }
                        else
                        {
                            Phase = FishingPhase.Searching;
                            Title = "Ожидание рыбалки";
                            Detail = "Шкала заброса исчезла без нажатия. Ждём её снова.";
                        }
                        phaseSince = nowMilliseconds;
                        missing = castSeen = 0;
                        castClicked = false;
                    }
                    return FishingAction.None;
                }
                missing = 0;
                if (nowMilliseconds - phaseSince >= 18000)
                    return Stop("Не удалось завершить заброс за 18 секунд. Проверьте игру и диагностику F9.");
                return TryCast(cast, nowMilliseconds);
            }

            if (cast != null)
            {
                castSeen++;
                if (castSeen >= 2)
                {
                    Phase = FishingPhase.Casting;
                    Title = "Заброс";
                    phaseSince = nowMilliseconds;
                    missing = 0;
                    castClicked = false;
                    return TryCast(cast, nowMilliseconds);
                }
                return FishingAction.None;
            }
            castSeen = 0;
            if (options.WaitTimeoutSeconds > 0 && nowMilliseconds - phaseSince >= options.WaitTimeoutSeconds * 1000L)
                return Stop("Слишком долго нет шкалы. Проверьте наживку и запустите заново.");
            return FishingAction.None;
        }

        private FishingAction TryCast(CastInfo cast, long now)
        {
            if (!cast.HasTarget)
            {
                Detail = "Светлый зелёный участок не найден — ожидаем, не нажимая.";
                return FishingAction.None;
            }
            if (cast.Hook < 0)
            {
                Detail = "Светлый участок найден, ищем белый крючок.";
                return FishingAction.None;
            }
            Detail = String.Format("Крючок {0} · светлый участок {1}–{2} · центр {3}.",
                cast.Hook, cast.TargetLeft, cast.TargetRight, cast.Center);
            // Prefer the inner portion of the observed bright target, never the
            // broad dark-green band or a guessed position after a timeout.
            int margin = Math.Max(2, (cast.TargetRight - cast.TargetLeft) / 6);
            bool insideTarget = cast.Hook >= cast.TargetLeft + margin && cast.Hook <= cast.TargetRight - margin;
            if (insideTarget && (!castClicked || now - lastClick >= 350))
            {
                castClicked = true;
                lastClick = now;
                return FishingAction.CastClick;
            }
            return FishingAction.None;
        }

        private void EnterSearching(long now, string detail)
        {
            Phase = FishingPhase.Searching;
            Title = "Ожидание следующего заброса";
            Detail = detail;
            phaseSince = now;
            castSeen = biteSeen = missing = 0;
            castClicked = false;
        }

        private FishingAction Stop(string reason)
        {
            Phase = FishingPhase.Stopped;
            Title = "Остановлено";
            Detail = reason;
            StopReason = reason;
            return FishingAction.Stop;
        }

        private static string Describe(CastInfo cast, bool bite)
        {
            string s = cast == null ? "нет" : String.Format("зелёная {0}–{1}, светлая {2}, крючок {3}",
                cast.Left, cast.Right, cast.HasTarget ? cast.TargetLeft + "–" + cast.TargetRight : "не найдена",
                cast.Hook < 0 ? "не найден" : cast.Hook.ToString());
            return "Заброс: " + s + " · Вываживание: " + (bite ? "да" : "нет");
        }
    }
}
