using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Threading;
using RMFish;

public static class TestRunner
{
    private static int assertions;
    private static string fixtures;

    private static void Check(bool condition, string message)
    {
        assertions++;
        if (!condition) throw new Exception("FAIL: " + message);
    }

    private static PixelFrame Fixture(string name, int clientWidth, int clientHeight)
    {
        int left = (int)Math.Floor(PixelFrame.CropLeft * (double)clientWidth / 1920);
        int top = (int)Math.Floor(PixelFrame.CropTop * (double)clientHeight / 1080);
        int right = (int)Math.Ceiling(PixelFrame.CropRight * (double)clientWidth / 1920);
        int bottom = (int)Math.Ceiling(PixelFrame.CropBottom * (double)clientHeight / 1080);
        byte[] pixels;
        using (FileStream file = File.OpenRead(Path.Combine(fixtures, name + "-" + clientWidth + ".bgra.gz")))
        using (GZipStream gzip = new GZipStream(file, CompressionMode.Decompress))
        using (MemoryStream output = new MemoryStream())
        {
            gzip.CopyTo(output);
            pixels = output.ToArray();
        }
        return new PixelFrame(pixels, right - left, bottom - top, (right - left) * 4,
                              clientWidth, clientHeight, left, top);
    }

    private static void Set(byte[] data, int x, int y, int r, int g, int b)
    {
        int width = PixelFrame.CropRight - PixelFrame.CropLeft;
        int i = ((y - PixelFrame.CropTop) * width + x - PixelFrame.CropLeft) * 4;
        data[i] = (byte)b; data[i + 1] = (byte)g; data[i + 2] = (byte)r; data[i + 3] = 255;
    }

    private static PixelFrame SyntheticCast(int hookX, bool redEnds)
    {
        int width = PixelFrame.CropRight - PixelFrame.CropLeft;
        int height = PixelFrame.CropBottom - PixelFrame.CropTop;
        byte[] data = new byte[width * height * 4];
        for (int y = 488; y <= 521; y++)
            for (int x = 660; x <= 1115; x++)
            {
                if (x < 750 || x > 1020)
                {
                    if (redEnds) Set(data, x, y, 145, 35, 30);
                }
                else Set(data, x, y, 45, 100, 45);
            }
        if (hookX >= 0)
        {
            for (int y = 493; y <= 516; y++)
            {
                Set(data, hookX, y, 250, 250, 245);
                Set(data, hookX + 2, y, 250, 250, 245);
            }
            for (int x = hookX; x <= hookX + 8; x++) Set(data, x, 516, 250, 250, 245);
        }
        return new PixelFrame(data, width, height, width * 4, 1920, 1080, PixelFrame.CropLeft, PixelFrame.CropTop);
    }

    private static void VisionTests()
    {
        PixelFrame cast = Fixture("cast", 1920, 1080);
        CastInfo info = Vision.FindCast(cast);
        Check(info != null, "the real cast screenshot is recognized");
        Check(info.Left >= 740 && info.Left <= 770, "the translucent green zone starts near x=754");
        Check(info.Right >= 1000 && info.Right <= 1035, "the translucent green zone ends near x=1018");
        Check(info.Hook >= 1045 && info.Hook <= 1070, "the white hook is located in the screenshot");
        Check(!Vision.BiteActive(cast), "the cast bar is not a bite bar");

        PixelFrame bite = Fixture("bite", 1920, 1080);
        Check(Vision.BiteActive(bite), "real green/red reeling bar is recognized");
        Check(Vision.FindCast(bite) == null, "the bite bar is not a cast bar");
        PixelFrame wait = Fixture("waiting", 1920, 1080);
        PixelFrame inv = Fixture("inventory", 1920, 1080);
        Check(Vision.FindCast(wait) == null && !Vision.BiteActive(wait), "waiting screen produces no actions");
        Check(Vision.FindCast(inv) == null && !Vision.BiteActive(inv), "inventory produces no actions");
        CastInfo small = Vision.FindCast(Fixture("cast", 1280, 720));
        Check(small != null && small.Hook >= 1040 && small.Hook <= 1075, "cast coordinates scale to 1280x720");
        Check(Vision.BiteActive(Fixture("bite", 1280, 720)), "bite coordinates scale to 1280x720");
        Check(Vision.FindCast(SyntheticCast(880, false)) == null, "green without red ends is not a cast");
        CastInfo covered = Vision.FindCast(SyntheticCast(880, true));
        Check(covered != null && covered.Hook >= 880 && covered.Hook <= 888, "hook covering the green zone does not split the zone");
        Check(Vision.FindCast(SyntheticCast(-1, true)).Hook == -1, "a missing hook is explicitly reported");
    }

    private static void StateTests()
    {
        EngineOptions options = new EngineOptions();
        PixelFrame cast = SyntheticCast(880, true);
        PixelFrame edge = SyntheticCast(760, true);
        PixelFrame noHook = SyntheticCast(-1, true);
        PixelFrame wait = Fixture("waiting", 1920, 1080);
        PixelFrame bite = Fixture("bite", 1920, 1080);
        FishingStateMachine machine = new FishingStateMachine(options);
        Check(machine.Step(wait, 0) == FishingAction.None, "idle never clicks");
        Check(machine.Step(cast, 30) == FishingAction.None, "cast is confirmed across two frames");
        Check(machine.Step(cast, 60) == FishingAction.CastClick, "hook near center triggers cast");
        Check(machine.Step(cast, 100) == FishingAction.None, "cast click is not immediately repeated");
        Check(machine.Step(wait, 200) == FishingAction.None, "one missing cast frame is tolerated");
        machine.Step(wait, 230); machine.Step(wait, 260);
        Check(machine.Phase == FishingPhase.WaitingBite && machine.Casts == 1, "cast disappearance increments exactly once");
        Check(machine.Step(bite, 500) == FishingAction.None, "bite needs two frames");
        Check(machine.Step(bite, 530) == FishingAction.ReelClick, "confirmed bite starts clicking");
        Check(machine.Step(bite, 550) == FishingAction.None, "reel click interval is respected");
        Check(machine.Step(bite, 590) == FishingAction.ReelClick, "reel repeats while the bar is visible");
        Check(machine.Step(wait, 610) == FishingAction.None, "stop clicking on the first missing bite frame");
        machine.Step(wait, 640); machine.Step(wait, 670);
        Check(machine.Reels == 1 && machine.Phase == FishingPhase.Searching, "completed reeling phase is counted once");

        machine = new FishingStateMachine(options);
        machine.Step(edge, 0);
        Check(machine.Step(edge, 30) == FishingAction.None, "edge is initially rejected");
        Check(machine.Step(edge, 10040) == FishingAction.CastClick, "after ten seconds any safe green position works");
        machine = new FishingStateMachine(options);
        machine.Step(noHook, 0);
        Check(machine.Step(noHook, 30) == FishingAction.None, "no white hook means no click");
        Check(machine.Step(noHook, 18031) == FishingAction.Stop, "an unrecognized hook eventually stops");
        machine = new FishingStateMachine(options);
        machine.Step(cast, 0); machine.Step(cast, 30);
        machine.Pause();
        Check(machine.Step(wait, 100000) == FishingAction.None && machine.Casts == 0,
            "focus loss cancels pending cast and resets the timeout");
        Check(machine.Step(bite, 100030) == FishingAction.None && machine.Step(bite, 100060) == FishingAction.ReelClick,
            "can start in the middle of a bite");
        Check(machine.Step(bite, 145061) == FishingAction.Stop, "stuck bite stops instead of clicking indefinitely");
        options.WaitTimeoutSeconds = 1;
        machine = new FishingStateMachine(options);
        machine.Step(wait, 0);
        Check(machine.Step(wait, 1000) == FishingAction.Stop, "waiting timeout is enforced");
        options.WaitTimeoutSeconds = 0;
        machine = new FishingStateMachine(options);
        machine.Step(wait, 0);
        Check(machine.Step(wait, 9999999) == FishingAction.None, "waiting timeout can be disabled");
    }

    private sealed class FakePort : IGamePort
    {
        public volatile bool Focus, StopFile;
        public int Clicks, Captures, CaptureThread, ReleaseThread, Releases;
        public PixelFrame Frame;
        public bool TryGetForeground(out GameBounds bounds, out string reason)
        {
            bounds = Focus ? new GameBounds { Handle = new IntPtr(42), Width = 1920, Height = 1080 } : null;
            reason = Focus ? "ready" : "not focused";
            return Focus;
        }
        public bool IsForeground(GameBounds bounds) { return Focus; }
        public PixelFrame Capture(GameBounds bounds)
        {
            CaptureThread = Thread.CurrentThread.ManagedThreadId;
            Interlocked.Increment(ref Captures);
            return Frame;
        }
        public bool Click(GameBounds bounds, WaitHandle stop, out string error)
        {
            error = "";
            if (!Focus || StopFile || stop.WaitOne(0)) return false;
            Interlocked.Increment(ref Clicks);
            return true;
        }
        public bool StopFileExists() { return StopFile; }
        public void ReleaseCapture()
        {
            ReleaseThread = Thread.CurrentThread.ManagedThreadId;
            Interlocked.Increment(ref Releases);
        }
        public void Dispose() { }
    }

    private static bool WaitUntil(Func<bool> condition, int milliseconds)
    {
        Stopwatch watch = Stopwatch.StartNew();
        while (!condition() && watch.ElapsedMilliseconds < milliseconds) Thread.Sleep(10);
        return condition();
    }

    private static void EngineTests()
    {
        FakePort port = new FakePort { Frame = SyntheticCast(880, true), Focus = false };
        using (FishingEngine engine = new FishingEngine(port))
        {
            Check(engine.Start(new EngineOptions()), "worker starts");
            Check(!engine.Start(new EngineOptions()), "worker cannot be started twice");
            Thread.Sleep(220);
            Check(port.Clicks == 0 && port.Captures == 0, "unfocused game receives no capture or click");
            Check(engine.Snapshot().Phase == FishingPhase.Paused, "unfocused game is shown as paused");
            port.Focus = true;
            Check(WaitUntil(delegate { return port.Clicks >= 1; }, 1500), "focused game is allowed to cast");
            port.Focus = false;
            Thread.Sleep(80);
            int afterPause = port.Clicks;
            Thread.Sleep(250);
            Check(port.Clicks == afterPause, "clicks stop after focus loss");
            port.StopFile = true;
            Check(WaitUntil(delegate { return !engine.Snapshot().Running; }, 1500), "STOP sentinel stops the worker");
            Check(engine.Snapshot().Detail.Contains("STOP.txt"), "stop reason is visible");
            Check(engine.WaitForStop(1000), "worker has exited");
            Check(port.Releases == 1 && port.ReleaseThread == port.CaptureThread, "capture is released on its owning worker thread");
            port.StopFile = false;
            Check(engine.Start(new EngineOptions()), "worker can be restarted after stopping");
            engine.RequestStop();
            Check(engine.WaitForStop(1000), "manual stop wakes the worker immediately");
            Check(port.Releases == 2, "each run releases its capture resources");
            Check(!engine.Snapshot().Running, "manual stop updates status");
        }
    }

    public static int Main(string[] args)
    {
        try
        {
            fixtures = args.Length == 0 ? Path.Combine("tests", "fixtures") : args[0];
            VisionTests();
            StateTests();
            EngineTests();
            Console.WriteLine("PASS: " + assertions + " assertions (vision, state machine, worker safety). ");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.ToString());
            return 1;
        }
    }
}
