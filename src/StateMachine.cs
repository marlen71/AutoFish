using System;

namespace RMFish
{
    public enum FishingPhase { Searching, Casting, WaitingBite, Reeling, Relocating, Paused, Stopped }
    public enum FishingAction { None, CastClick, ReelClick, Stop }
    public enum GameWindowMode { Active, MinimizedExperimental }

    public sealed class EngineOptions
    {
        public int PollMilliseconds = 20;
        public int ReelClickMilliseconds = 35;
        public int WaitTimeoutSeconds = 300; // zero means no separate waiting limit
        public int SessionLimitSeconds = 120; // always bounded, including while paused
        public bool MinimizeOnStart = true;
        public GameWindowMode WindowMode = GameWindowMode.Active;
        public bool AutoRelocate;
        // Relative mouse counts for a 180-degree turn. Zero is uncalibrated;
        // confirmation is invalidated when the value changes in the UI.
        public int Turn180Units;
        public bool Turn180Confirmed;
        public NoticeTemplate Notice;
        public GearMacro Gear;

        public EngineOptions CopyValidated()
        {
            EngineOptions result = new EngineOptions();
            result.PollMilliseconds = Math.Max(20, Math.Min(200, PollMilliseconds));
            result.ReelClickMilliseconds = Math.Max(35, Math.Min(250, ReelClickMilliseconds));
            result.WaitTimeoutSeconds = Math.Max(0, Math.Min(3600, WaitTimeoutSeconds));
            result.SessionLimitSeconds = Math.Max(1, Math.Min(1800, SessionLimitSeconds));
            result.MinimizeOnStart = MinimizeOnStart;
            if (WindowMode != GameWindowMode.Active && WindowMode != GameWindowMode.MinimizedExperimental)
                throw new InvalidOperationException("Неизвестный режим окна игры.");
            result.WindowMode = WindowMode;
            result.AutoRelocate = AutoRelocate;
            result.Turn180Units = Turn180Units >= 1 && Turn180Units <= 10000 ? Turn180Units : 0;
            result.Turn180Confirmed = result.Turn180Units > 0 && Turn180Confirmed;
            result.Notice = Notice;
            result.Gear = Gear;
            return result;
        }
    }

    // Pure state machine: it never takes screenshots or sends input. The worker
    // supplies a monotonic timestamp and executes the returned action only after
    // checking foreground and STOP again.
    public sealed class FishingStateMachine
    {
        private readonly EngineOptions options;
        private bool initialized, castClicked, expectingNextCast, hasLastCastClick;
        private int castSeen, biteSeen, missing;
        private int lastCastLeft = -1, lastCastRight, lastCastY;
        private long phaseSince, lastClick, lastCastClick, targetSeenAt;
        private int targetLeft = -1, targetRight = -1, targetBandLeft, targetBandRight, targetY, stableTargetFrames;
        private const int TargetMemoryMilliseconds = 200;
        private const int NextCastHintMilliseconds = 10000;

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
            expectingNextCast = false;
            biteSeen = missing = 0;
            ResetCast();
            ForgetTarget();
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

            bool ambiguousCast;
            CastInfo cast = Vision.FindCast(frame, out ambiguousCast);
            bool sameCast = TrackCast(cast);
            if (Phase == FishingPhase.Casting && cast != null && !sameCast)
            {
                // A different candidate cannot inherit a pending click or a
                // remembered target from the previous bar.
                castClicked = false;
                ForgetTarget();
            }
            ObserveTarget(cast, nowMilliseconds);
            bool bite = Vision.BiteActive(frame);
            LastDetection = Describe(cast, bite, ambiguousCast);
            biteSeen = bite ? biteSeen + 1 : 0;

            if (Phase == FishingPhase.Reeling)
            {
                if (!bite)
                {
                    // Stop reeling immediately. The next cast may already be
                    // visible while the previous bar is disappearing: preserve
                    // those observations rather than discarding three frames.
                    missing++;
                    if (castSeen >= 2)
                    {
                        Reels++;
                        Phase = FishingPhase.Casting;
                        Title = "Заброс";
                        phaseSince = nowMilliseconds;
                        missing = 0;
                        castClicked = false;
                        expectingNextCast = false;
                        return TryCast(cast, nowMilliseconds);
                    }
                    if (missing >= 3)
                    {
                        Reels++;
                        EnterSearching(nowMilliseconds, "Вываживание завершено. Ждём следующий заброс.");
                        if (cast != null) TrackCast(cast);
                    }
                    return FishingAction.None;
                }
                missing = 0;
                ResetCast();
                if (nowMilliseconds - phaseSince >= 45000)
                    return Stop("Шкала вываживания не исчезла за 45 секунд. Проверьте игру.");
                if (nowMilliseconds - lastClick >= options.ReelClickMilliseconds)
                    return FishingAction.ReelClick;
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
                // The worker confirms the actual input separately; a physically
                // held LMB or a lost focus is not a successful click.
                lastClick = nowMilliseconds - options.ReelClickMilliseconds;
                missing = 0;
                ResetCast();
                castClicked = false;
                expectingNextCast = false;
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
                        missing = 0;
                        ResetCast();
                        castClicked = false;
                        expectingNextCast = false;
                    }
                    return FishingAction.None;
                }
                missing = 0;
                if (nowMilliseconds - phaseSince >= 18000)
                    return Stop("Не удалось завершить заброс за 18 секунд. Проверьте игру и диагностику F9.");
                if (castSeen < 2)
                {
                    Detail = "Подтверждаем положение шкалы в двух кадрах — пока не нажимаем.";
                    return FishingAction.None;
                }
                return TryCast(cast, nowMilliseconds);
            }

            if (cast != null)
            {
                if (castSeen >= 2)
                {
                    Phase = FishingPhase.Casting;
                    Title = "Заброс";
                    phaseSince = nowMilliseconds;
                    missing = 0;
                    castClicked = false;
                    expectingNextCast = false;
                    return TryCast(cast, nowMilliseconds);
                }
                return FishingAction.None;
            }
            if (expectingNextCast && nowMilliseconds - phaseSince >= NextCastHintMilliseconds)
            {
                Title = "Следующая шкала не найдена";
                Detail = "Проверьте игру. Если шкала видна, остановите бота и нажмите F9; если нет — подготовьте заброс вручную.";
            }
            if (options.WaitTimeoutSeconds > 0 && nowMilliseconds - phaseSince >= options.WaitTimeoutSeconds * 1000L)
                return Stop("Слишком долго не видна шкала рыбалки. Проверьте игру и подготовьте удочку. Наживка автоматически не проверяется.");
            return FishingAction.None;
        }

        // Confirm the same bar across consecutive frames, rather than two
        // unrelated HUD-like objects elsewhere in the larger search area.
        // A single missing frame resets confirmation but retains the geometry
        // briefly; three missing frames or a pause clear it completely.
        private void ResetCast()
        {
            castSeen = 0;
            lastCastLeft = -1;
        }
        private bool TrackCast(CastInfo cast)
        {
            if (cast == null) { castSeen = 0; return false; }
            bool same = lastCastLeft >= 0 && Math.Abs(cast.Left - lastCastLeft) <= 18 &&
                Math.Abs(cast.Right - lastCastRight) <= 18 && Math.Abs(cast.Y - lastCastY) <= 15;
            castSeen = same ? Math.Min(2, castSeen + 1) : 1;
            lastCastLeft = cast.Left; lastCastRight = cast.Right; lastCastY = cast.Y;
            return same;
        }

        // A white hook can temporarily obscure a narrow patch. Remember only
        // a target seen in two matching frames on the same bar, for 200 ms;
        // never invent a target from the wide green region or a timer.
        private void ForgetTarget()
        {
            targetLeft = targetRight = -1; stableTargetFrames = 0; targetSeenAt = 0;
        }
        private void ObserveTarget(CastInfo cast, long now)
        {
            if (cast == null) { ForgetTarget(); return; }
            if (!cast.HasTarget) return;
            bool same = targetLeft >= 0 && now >= targetSeenAt && now - targetSeenAt <= TargetMemoryMilliseconds &&
                Math.Abs(cast.Left - targetBandLeft) <= 12 && Math.Abs(cast.Right - targetBandRight) <= 12 &&
                Math.Abs(cast.Y - targetY) <= 12 &&
                Math.Abs(cast.TargetLeft - targetLeft) <= 12 && Math.Abs(cast.TargetRight - targetRight) <= 12;
            stableTargetFrames = same ? Math.Min(2, stableTargetFrames + 1) : 1;
            targetLeft = cast.TargetLeft; targetRight = cast.TargetRight;
            targetBandLeft = cast.Left; targetBandRight = cast.Right; targetY = cast.Y; targetSeenAt = now;
        }

        private FishingAction TryCast(CastInfo cast, long now)
        {
            int left = cast.TargetLeft, right = cast.TargetRight;
            bool remembered = false;
            if (!cast.HasTarget)
            {
                remembered = stableTargetFrames >= 2 && now >= targetSeenAt && now - targetSeenAt <= TargetMemoryMilliseconds &&
                    Math.Abs(cast.Left - targetBandLeft) <= 12 && Math.Abs(cast.Right - targetBandRight) <= 12 &&
                    Math.Abs(cast.Y - targetY) <= 12;
                if (!remembered)
                {
                    Detail = "Светлый зелёный участок не найден — ожидаем, не нажимая.";
                    return FishingAction.None;
                }
                left = targetLeft; right = targetRight;
            }
            if (cast.Hook < 0)
            {
                Detail = "Светлый участок найден, ищем белый крючок.";
                return FishingAction.None;
            }
            Detail = String.Format("Крючок {0} · светлый участок {1}–{2}{3}.",
                cast.Hook, left, right, remembered ? " (последние кадры)" : "");
            // A small inset still stays entirely within the observed light strip,
            // while allowing more sampling time than the old one-sixth inset.
            int margin = Math.Max(2, (right - left) / 10);
            bool insideTarget = cast.Hook >= left + margin && cast.Hook <= right - margin;
            // A changed or briefly lost bar must not bypass the cooldown of an
            // actually sent cast click. Suppressed requests do not start it.
            if (insideTarget && (!hasLastCastClick || now - lastCastClick >= 350))
                return FishingAction.CastClick;
            return FishingAction.None;
        }

        // An action is only a request. Commit it after the input port reports
        // that it actually sent a click, never when LMB was merely held down.
        public void ConfirmClick(FishingAction action, long nowMilliseconds)
        {
            if (action == FishingAction.CastClick && Phase == FishingPhase.Casting)
            {
                castClicked = true;
                hasLastCastClick = true;
                lastCastClick = lastClick = nowMilliseconds;
            }
            else if (action == FishingAction.ReelClick && Phase == FishingPhase.Reeling)
                lastClick = nowMilliseconds;
        }

        public void ClickSuppressed()
        {
            Detail = "ЛКМ удерживается пользователем. Отпустите кнопку: автоматический клик не отправлен.";
        }

        private void EnterSearching(long now, string detail)
        {
            Phase = FishingPhase.Searching;
            Title = "Ожидание следующего заброса";
            Detail = detail;
            phaseSince = now;
            biteSeen = missing = 0;
            ResetCast();
            expectingNextCast = true;
            castClicked = false; ForgetTarget();
        }

        private FishingAction Stop(string reason)
        {
            Phase = FishingPhase.Stopped;
            Title = "Остановлено";
            Detail = reason;
            StopReason = reason;
            return FishingAction.Stop;
        }

        private static string Describe(CastInfo cast, bool bite, bool ambiguous)
        {
            string s = cast == null ? (ambiguous ? "несколько похожих шкал, заброс заблокирован" : "нет") : String.Format("зелёная {0}–{1}, Y={2}, светлая {3}, крючок {4}",
                cast.Left, cast.Right, cast.Y, cast.HasTarget ? cast.TargetLeft + "–" + cast.TargetRight : "не найдена",
                cast.Hook < 0 ? "не найден" : cast.Hook.ToString());
            return "Заброс: " + s + " · Вываживание: " + (bite ? "да" : "нет");
        }
    }
}
