using System;
using System.Diagnostics;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Runtime.InteropServices;
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

    private static byte[] FixturePixels(string name, int clientWidth)
    {
        using (FileStream file = File.OpenRead(Path.Combine(fixtures, name + "-" + clientWidth + ".bgra.gz")))
        using (GZipStream gzip = new GZipStream(file, CompressionMode.Decompress))
        using (MemoryStream output = new MemoryStream())
        {
            gzip.CopyTo(output);
            return output.ToArray();
        }
    }

    private static PixelFrame Fixture(string name, int clientWidth, int clientHeight)
    {
        int left = (int)Math.Floor(PixelFrame.CropLeft * (double)clientWidth / 1920);
        int top = (int)Math.Floor(PixelFrame.CropTop * (double)clientHeight / 1080);
        int right = (int)Math.Ceiling(PixelFrame.CropRight * (double)clientWidth / 1920);
        int bottom = (int)Math.Ceiling(PixelFrame.CropBottom * (double)clientHeight / 1080);
        byte[] pixels = FixturePixels(name, clientWidth);
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
        return SyntheticCast(hookX, redEnds, true);
    }

    private static PixelFrame SyntheticCast(int hookX, bool redEnds, bool brightTarget)
    {
        return SyntheticCast(hookX, redEnds, brightTarget ? 860 : -1, brightTarget ? 915 : -1);
    }

    private static PixelFrame SyntheticCast(int hookX, bool redEnds, int targetLeft, int targetRight)
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
                else if (x >= targetLeft && x <= targetRight) Set(data, x, y, 20, 150, 20);
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

    // Move the actual white hook pixels from the supplied boat screenshot onto
    // its reconstructed bar; this is a synthetic sequence, not a game video.
    private static PixelFrame BoatWithHook(int hookX)
    {
        int width = PixelFrame.CropRight - PixelFrame.CropLeft;
        int height = PixelFrame.CropBottom - PixelFrame.CropTop;
        byte[] original = FixturePixels("cast-boat", 1920);
        byte[] data = (byte[])original.Clone();
        int offset = hookX - 656;
        for (int y = 488; y <= 521; y++)
            for (int x = 645; x <= 665; x++)
            {
                int i = ((y - PixelFrame.CropTop) * width + x - PixelFrame.CropLeft) * 4;
                int b = original[i], g = original[i + 1], r = original[i + 2];
                bool white = r >= 200 && g >= 190 && b >= 175 &&
                    Math.Max(r, Math.Max(g, b)) - Math.Min(r, Math.Min(g, b)) <= 65;
                if (!white) continue;
                if (x < 655) Set(data, x, y, 12, 18, 18);
                else Set(data, x, y, 145, 25, 15);
                if (hookX >= 0) Set(data, x + offset, y, r, g, b);
            }
        return new PixelFrame(data, width, height, width * 4, 1920, 1080, PixelFrame.CropLeft, PixelFrame.CropTop);
    }

    // The user supplied only the HUD crop, not a full screen: place it at the
    // expected reference coordinates and move its actual hook pixels. This is
    // a synthetic sweep, not evidence of in-game timing or HUD placement.
    private static PixelFrame UserBarWithHook(int hookX, double brightness)
    {
        int width = PixelFrame.CropRight - PixelFrame.CropLeft;
        int height = PixelFrame.CropBottom - PixelFrame.CropTop;
        byte[] original = FixturePixels("cast-user", 1920), data = (byte[])original.Clone();
        for (int y = 488; y <= 521; y++)
            for (int x = 776; x <= 797; x++)
            {
                int source = ((y - PixelFrame.CropTop) * width + 774 - PixelFrame.CropLeft) * 4;
                int dest = ((y - PixelFrame.CropTop) * width + x - PixelFrame.CropLeft) * 4;
                Array.Copy(original, source, data, dest, 4);
            }
        if (hookX >= 0)
        {
            for (int y = 488; y <= 521; y++)
                for (int x = 776; x <= 797; x++)
                {
                    int i = ((y - PixelFrame.CropTop) * width + x - PixelFrame.CropLeft) * 4;
                    int b = original[i], g = original[i + 1], r = original[i + 2];
                    if (r >= 200 && g >= 190 && b >= 175 && Math.Max(r, Math.Max(g, b)) - Math.Min(r, Math.Min(g, b)) <= 65)
                        Set(data, x + hookX - 785, y, r, g, b);
                }
        }
        for (int y = 486; y <= 523; y++)
            for (int x = 655; x < 1122; x++)
            {
                int i = ((y - PixelFrame.CropTop) * width + x - PixelFrame.CropLeft) * 4;
                data[i] = (byte)(data[i] * brightness); data[i + 1] = (byte)(data[i + 1] * brightness); data[i + 2] = (byte)(data[i + 2] * brightness);
            }
        return new PixelFrame(data, width, height, width * 4, 1920, 1080, PixelFrame.CropLeft, PixelFrame.CropTop);
    }

    // The latest user screenshot contains the whole HUD, at its observed Y
    // rather than the reconstructed position of cast-user. Move just its real
    // hook pixels to exercise later parts of the bar; this is not game video.
    private static PixelFrame DockWithHook(int hookX)
    {
        int width = PixelFrame.CropRight - PixelFrame.CropLeft;
        int height = PixelFrame.CropBottom - PixelFrame.CropTop;
        byte[] original = FixturePixels("cast-dock", 1920), data = (byte[])original.Clone();
        for (int y = 411; y <= 447; y++)
            for (int x = 673; x <= 694; x++)
            {
                int i = ((y - PixelFrame.CropTop) * width + x - PixelFrame.CropLeft) * 4;
                int b = original[i], g = original[i + 1], r = original[i + 2];
                bool white = r >= 155 && g >= 155 && b >= 145 &&
                    Math.Max(r, Math.Max(g, b)) - Math.Min(r, Math.Min(g, b)) <= 45;
                if (!white) continue;
                int replacement = ((y - PixelFrame.CropTop) * width + 700 - PixelFrame.CropLeft) * 4;
                Array.Copy(original, replacement, data, i, 4);
                if (hookX >= 0) Set(data, x + hookX - 683, y, r, g, b);
            }
        return new PixelFrame(data, width, height, width * 4, 1920, 1080, PixelFrame.CropLeft, PixelFrame.CropTop);
    }

    // The user supplied a partial screenshot after a catch. Only the HUD crop
    // is stored. The original client geometry is unknown: placing its observed
    // image coordinates in a 1920x1080 frame is a test assumption, not proof of
    // where the HUD appeared in the actual game window.
    private static PixelFrame AfterCatch(int hookX, int offsetX, int offsetY)
    {
        const int left = 800, top = 380, width = 510, height = 70;
        byte[] original;
        using (FileStream file = File.OpenRead(Path.Combine(fixtures, "cast-after-catch.bgra.gz")))
        using (GZipStream gzip = new GZipStream(file, CompressionMode.Decompress))
        using (MemoryStream output = new MemoryStream())
        {
            gzip.CopyTo(output);
            original = output.ToArray();
        }
        byte[] data = (byte[])original.Clone();
        // -2 retains the actual screenshot; other values move the real hook's
        // white pixels. This is a synthetic sweep, not a recorded game video.
        if (hookX != -2)
        {
            for (int y = 400; y <= 429; y++)
                for (int x = 934; x <= 950; x++)
                {
                    int i = ((y - top) * width + x - left) * 4;
                    int b = original[i], g = original[i + 1], r = original[i + 2];
                    bool white = r >= 155 && g >= 155 && b >= 145 &&
                        Math.Max(r, Math.Max(g, b)) - Math.Min(r, Math.Min(g, b)) <= 45;
                    if (!white) continue;
                    int replacement = ((y - top) * width + 958 - left) * 4;
                    Array.Copy(original, replacement, data, i, 4);
                    if (hookX >= 0)
                    {
                        int destination = ((y - top) * width + x + hookX - 943 - left) * 4;
                        Array.Copy(original, i, data, destination, 4);
                    }
                }
        }
        return new PixelFrame(data, width, height, width * 4, 1920, 1080, left + offsetX, top + offsetY);
    }

    private static void SetWide(byte[] data, int x, int y, int r, int g, int b)
    {
        int width = PixelFrame.HudRight - PixelFrame.HudLeft;
        int i = ((y - PixelFrame.HudTop) * width + x - PixelFrame.HudLeft) * 4;
        data[i] = (byte)b; data[i + 1] = (byte)g; data[i + 2] = (byte)r; data[i + 3] = 255;
    }

    private static PixelFrame WideFrame(byte[] data)
    {
        int width = PixelFrame.HudRight - PixelFrame.HudLeft, height = PixelFrame.HudBottom - PixelFrame.HudTop;
        return new PixelFrame(data, width, height, width * 4, 1920, 1080, PixelFrame.HudLeft, PixelFrame.HudTop);
    }

    private static void DrawWideBar(byte[] data, int dx, int dy)
    {
        for (int y = 488; y <= 521; y++)
            for (int x = 660; x <= 1115; x++)
            {
                if (x < 750 || x > 1020) SetWide(data, x + dx, y + dy, 145, 35, 30);
                else if (x >= 860 && x <= 915) SetWide(data, x + dx, y + dy, 20, 150, 20);
                else SetWide(data, x + dx, y + dy, 45, 100, 45);
            }
        for (int y = 493; y <= 516; y++)
        {
            SetWide(data, 880 + dx, y + dy, 250, 250, 245);
            SetWide(data, 882 + dx, y + dy, 250, 250, 245);
        }
        for (int x = 880; x <= 888; x++) SetWide(data, x + dx, 516 + dy, 250, 250, 245);
    }

    private static PixelFrame WideBars(bool two, int firstDx, int secondDx, int secondDy)
    {
        int width = PixelFrame.HudRight - PixelFrame.HudLeft, height = PixelFrame.HudBottom - PixelFrame.HudTop;
        byte[] data = new byte[width * height * 4];
        DrawWideBar(data, firstDx, 0);
        if (two) DrawWideBar(data, secondDx, secondDy);
        return WideFrame(data);
    }

    private static PixelFrame AfterCatchWithGreenDistractor()
    {
        int width = PixelFrame.HudRight - PixelFrame.HudLeft, height = PixelFrame.HudBottom - PixelFrame.HudTop;
        byte[] data = new byte[width * height * 4];
        PixelFrame screenshot = AfterCatch(-2, 0, 0);
        for (int y = 380; y < 450; y++)
            for (int x = 800; x < 1310; x++)
            {
                int r, g, b; screenshot.Read(x, y, out r, out g, out b);
                SetWide(data, x, y, r, g, b);
            }
        // A larger green patch without a left red end must not hide the HUD.
        for (int y = 390; y <= 440; y++)
            for (int x = 400; x <= 720; x++) SetWide(data, x, y, 45, 100, 45);
        return WideFrame(data);
    }

    private static PixelFrame ShiftCast(PixelFrame frame, int offset)
    {
        int width = PixelFrame.CropRight - PixelFrame.CropLeft;
        int height = PixelFrame.CropBottom - PixelFrame.CropTop;
        byte[] data = new byte[width * height * 4];
        for (int y = 488; y <= 521; y++)
            for (int x = 620; x <= 1160; x++)
            {
                int r, g, b; frame.Read(x - offset, y, out r, out g, out b); Set(data, x, y, r, g, b);
            }
        return new PixelFrame(data, width, height, width * 4, 1920, 1080, PixelFrame.CropLeft, PixelFrame.CropTop);
    }

    private static PixelFrame ScaleTo720(PixelFrame frame)
    {
        int left = (int)Math.Floor(PixelFrame.CropLeft * 1280.0 / 1920);
        int top = (int)Math.Floor(PixelFrame.CropTop * 720.0 / 1080);
        int right = (int)Math.Ceiling(PixelFrame.CropRight * 1280.0 / 1920);
        int bottom = (int)Math.Ceiling(PixelFrame.CropBottom * 720.0 / 1080);
        int width = right - left, height = bottom - top;
        byte[] data = new byte[width * height * 4];
        for (int y = 0; y < height; y++)
            for (int x = 0; x < width; x++)
            {
                int r, g, b;
                frame.Read((int)Math.Round((x + left) * 1920.0 / 1280),
                    (int)Math.Round((y + top) * 1080.0 / 720), out r, out g, out b);
                int i = (y * width + x) * 4;
                data[i] = (byte)b; data[i + 1] = (byte)g; data[i + 2] = (byte)r; data[i + 3] = 255;
            }
        return new PixelFrame(data, width, height, width * 4, 1280, 720, left, top);
    }

    private static PixelFrame ScaleWideTo720(PixelFrame frame)
    {
        int left = (int)Math.Floor(PixelFrame.HudLeft * 1280.0 / 1920);
        int top = (int)Math.Floor(PixelFrame.HudTop * 720.0 / 1080);
        int right = (int)Math.Ceiling(PixelFrame.HudRight * 1280.0 / 1920);
        int bottom = (int)Math.Ceiling(PixelFrame.HudBottom * 720.0 / 1080);
        int width = right - left, height = bottom - top;
        byte[] data = new byte[width * height * 4];
        for (int y = 0; y < height; y++)
            for (int x = 0; x < width; x++)
            {
                int r, g, b;
                frame.Read((int)Math.Round((x + left) * 1920.0 / 1280),
                    (int)Math.Round((y + top) * 1080.0 / 720), out r, out g, out b);
                int i = (y * width + x) * 4;
                data[i] = (byte)b; data[i + 1] = (byte)g; data[i + 2] = (byte)r; data[i + 3] = 255;
            }
        return new PixelFrame(data, width, height, width * 4, 1280, 720, left, top);
    }

    private static void VisionTests()
    {
        PixelFrame cast = Fixture("cast", 1920, 1080);
        CastInfo info = Vision.FindCast(cast);
        Check(info != null, "the real cast screenshot is recognized");
        Check(info.Left >= 740 && info.Left <= 770, "the translucent green zone starts near x=754");
        Check(info.Right >= 1000 && info.Right <= 1035, "the translucent green zone ends near x=1018");
        Check(info.Hook >= 1045 && info.Hook <= 1070, "the white hook is located in the screenshot");
        Check(info.HasTarget && info.TargetLeft >= 855 && info.TargetLeft <= 865 &&
            info.TargetRight >= 910 && info.TargetRight <= 922, "the brighter target is identified separately from the wide green band");
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
        Check(small.HasTarget && small.TargetLeft >= 855 && small.TargetRight <= 922, "bright target scales with a 720p screenshot");
        CastInfo boat = Vision.FindCast(Fixture("cast-boat", 1920, 1080));
        Check(boat != null && boat.Hook >= 650 && boat.Hook <= 660, "the user's white hook on the left is recognized");
        Check(boat.HasTarget && boat.TargetLeft >= 855 && boat.TargetLeft <= 865 &&
            boat.TargetRight >= 910 && boat.TargetRight <= 922, "the user's bright green target is recognized over the boat");
        CastInfo smallBoat = Vision.FindCast(Fixture("cast-boat", 1280, 720));
        Check(smallBoat != null && smallBoat.HasTarget && smallBoat.Hook >= 650 && smallBoat.Hook <= 660,
            "the reconstructed boat screenshot also scales to 720p");
        for (int x = 840; x <= 930; x += 15)
        {
            CastInfo moved = Vision.FindCast(BoatWithHook(x));
            Check(moved != null && moved.Hook >= x - 2 && moved.Hook <= x + 2 && moved.HasTarget,
                "real white hook pixels remain identifiable at x=" + x + " over the translucent bar");
        }
        CastInfo movedSmall = Vision.FindCast(ScaleTo720(BoatWithHook(888)));
        Check(movedSmall != null && movedSmall.HasTarget && movedSmall.Hook >= 884 && movedSmall.Hook <= 892,
            "the white hook remains detectable over the bright target after 720p scaling");
        CastInfo user = Vision.FindCast(Fixture("cast-user", 1920, 1080));
        Check(user != null && user.HasTarget && user.Hook >= 780 && user.Hook <= 795 &&
            user.TargetLeft >= 850 && user.TargetRight <= 925, "new user screenshot recognizes the hook and the central bright patch");
        CastInfo dock = Vision.FindCast(Fixture("cast-dock", 1920, 1080));
        Check(dock != null && dock.Y >= 420 && dock.Y <= 440 && dock.Hook >= 678 && dock.Hook <= 690 &&
            dock.HasTarget && dock.TargetLeft >= 815 && dock.TargetRight <= 880,
            "latest full-HUD screenshot is recognized at its actual higher vertical position");
        CastInfo dockSmall = Vision.FindCast(ScaleTo720(Fixture("cast-dock", 1920, 1080)));
        Check(dockSmall != null && dockSmall.Y >= 420 && dockSmall.Y <= 440 && dockSmall.HasTarget &&
            dockSmall.Hook >= 676 && dockSmall.Hook <= 692, "higher bar survives simulated 720p scaling");
        CastInfo dockMoved = Vision.FindCast(DockWithHook(850));
        Check(dockMoved != null && dockMoved.HasTarget && dockMoved.Hook >= 846 && dockMoved.Hook <= 854,
            "the real dock hook can be located inside its bright target");
        PixelFrame afterCatch = AfterCatch(-2, 0, 0);
        CastInfo shifted = Vision.FindCast(afterCatch);
        Check(shifted != null && shifted.Y >= 405 && shifted.Y <= 425 && shifted.Left >= 910 && shifted.Right >= 1175 &&
            shifted.HasTarget && shifted.TargetLeft >= 1015 && shifted.TargetRight <= 1085 && shifted.Hook >= 936 && shifted.Hook <= 950,
            "the newer after-catch HUD is recognized beyond the old right crop");
        CastInfo afterCatchSmall = Vision.FindCast(ScaleWideTo720(afterCatch));
        Check(afterCatchSmall != null && afterCatchSmall.HasTarget && afterCatchSmall.Hook >= 935 && afterCatchSmall.Hook <= 952,
            "the shifted after-catch HUD survives simulated 720p scaling");
        CastInfo afterCatchMoved = Vision.FindCast(AfterCatch(1047, 0, 0));
        Check(afterCatchMoved != null && afterCatchMoved.HasTarget && afterCatchMoved.Hook >= 1040 && afterCatchMoved.Hook <= 1055,
            "real hook pixels moved synthetically onto the new bright target remain recognizable");
        Check(Vision.FindCast(AfterCatch(-1, 0, 0)).Hook < 0,
            "the after-catch background alone is not mistaken for its removed hook");
        CastInfo leftAndHigh = Vision.FindCast(AfterCatch(-2, -280, -65));
        Check(leftAndHigh != null && leftAndHigh.HasTarget && leftAndHigh.Y >= 345 && leftAndHigh.Y <= 360 &&
            leftAndHigh.Hook >= 655 && leftAndHigh.Hook <= 670, "shifted real HUD is found on the left and higher up");
        CastInfo low = Vision.FindCast(AfterCatch(-2, 0, 145));
        Check(low != null && low.HasTarget && low.Y >= 550 && low.Y <= 570,
            "shifted real HUD is found lower in the expanded search area");
        CastInfo distractor = Vision.FindCast(AfterCatchWithGreenDistractor());
        Check(distractor != null && distractor.Hook >= 936 && distractor.Hook <= 950 && distractor.HasTarget,
            "a larger unrelated green region does not hide the real bar");
        bool ambiguous;
        Check(Vision.FindCast(WideBars(true, -260, 400, 0), out ambiguous) == null && ambiguous,
            "two separate complete bars on one row are ambiguous and fail closed");
        Check(Vision.FindCast(WideBars(true, -260, 400, 70), out ambiguous) == null && ambiguous,
            "two separate complete bars on different rows are ambiguous and fail closed");
        Check(Vision.FindCast(WideBars(true, 0, 0, 45), out ambiguous) == null && ambiguous,
            "two vertically separated bars at the same horizontal position are ambiguous");
        Check(Vision.Describe(WideBars(true, -260, 400, 0)).Contains("несколько похожих"),
            "F9 explains ambiguous candidates instead of claiming that no bar exists");
        foreach (double brightness in new double[] { 1.0, 0.85, 0.70 })
        {
            PixelFrame frame = UserBarWithHook(890, brightness);
            foreach (PixelFrame sample in new PixelFrame[] { frame, ScaleTo720(frame) })
            {
                CastInfo dimmed = Vision.FindCast(sample);
                Check(dimmed != null && dimmed.HasTarget && dimmed.Hook >= 884 && dimmed.Hook <= 897,
                    "dimmed user hook is detected at " + brightness + " for " + (sample == frame ? "1080p" : "720p"));
            }
            CastInfo missingHook = Vision.FindCast(UserBarWithHook(-1, brightness));
            Check(missingHook != null && missingHook.Hook < 0, "pale border alone is not a hook at brightness " + brightness);
        }
        Check(Vision.BiteActive(Fixture("bite", 1280, 720)), "bite coordinates scale to 1280x720");
        Check(Vision.FindCast(SyntheticCast(880, false)) == null, "green without red ends is not a cast");
        CastInfo covered = Vision.FindCast(SyntheticCast(880, true));
        Check(covered != null && covered.Hook >= 880 && covered.Hook <= 888 && covered.HasTarget,
            "hook covering the bright target does not split the target or the green zone");
        CastInfo noTarget = Vision.FindCast(SyntheticCast(880, true, false));
        Check(noTarget != null && !noTarget.HasTarget, "a uniform green band does not invent a bright target");
        CastInfo offCenter = Vision.FindCast(SyntheticCast(770, true, 755, 790));
        Check(offCenter != null && !offCenter.HasTarget, "a bright green patch at the far edge is not mistaken for the centre target");
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
        machine.ConfirmClick(FishingAction.CastClick, 60);
        Check(machine.Step(cast, 100) == FishingAction.None, "cast click is not immediately repeated");
        Check(machine.Step(wait, 200) == FishingAction.None, "one missing cast frame is tolerated");
        machine.Step(wait, 230); machine.Step(wait, 260);
        Check(machine.Phase == FishingPhase.WaitingBite && machine.Casts == 1, "cast disappearance increments exactly once");
        Check(machine.Step(bite, 500) == FishingAction.None, "bite needs two frames");
        Check(machine.Step(bite, 530) == FishingAction.ReelClick, "confirmed bite starts clicking");
        machine.ConfirmClick(FishingAction.ReelClick, 530);
        Check(machine.Step(bite, 550) == FishingAction.None, "reel click interval is respected");
        Check(machine.Step(bite, 590) == FishingAction.ReelClick, "reel repeats while the bar is visible");
        machine.ConfirmClick(FishingAction.ReelClick, 590);
        Check(machine.Step(wait, 610) == FishingAction.None, "stop clicking on the first missing bite frame");
        machine.Step(wait, 640); machine.Step(wait, 670);
        Check(machine.Reels == 1 && machine.Phase == FishingPhase.Searching, "completed reeling phase is counted once");
        Check(machine.Step(DockWithHook(815), 700) == FishingAction.None, "next higher cast is observed without a blind click");
        Check(machine.Step(DockWithHook(850), 730) == FishingAction.CastClick, "next cast can fire after a completed reel");
        machine.ConfirmClick(FishingAction.CastClick, 730);
        machine.Step(wait, 760); machine.Step(wait, 790); machine.Step(wait, 820);
        Check(machine.Casts == 2 && machine.Phase == FishingPhase.WaitingBite, "second cast is counted once after actual input");

        machine = new FishingStateMachine(options);
        machine.Step(bite, 0);
        Check(machine.Step(bite, 30) == FishingAction.ReelClick, "reel phase starts for immediate transition test");
        machine.ConfirmClick(FishingAction.ReelClick, 30);
        Check(machine.Step(DockWithHook(815), 60) == FishingAction.None, "no reeling click when the next cast appears");
        Check(machine.Step(DockWithHook(850), 90) == FishingAction.CastClick && machine.Reels == 1 &&
            machine.Phase == FishingPhase.Casting, "two cast frames transition straight from reeling and allow the click");
        machine.ConfirmClick(FishingAction.CastClick, 90);
        machine.Step(wait, 120); machine.Step(wait, 150); machine.Step(wait, 180);
        Check(machine.Casts == 1 && machine.Reels == 1, "direct reeling-to-cast transition counts each phase once");

        machine = new FishingStateMachine(options);
        machine.Step(bite, 0);
        Check(machine.Step(bite, 30) == FishingAction.ReelClick, "reeling starts before the new screenshot test");
        machine.ConfirmClick(FishingAction.ReelClick, 30);
        Check(machine.Step(AfterCatch(-2, 0, 0), 60) == FishingAction.None,
            "newer after-catch frame stops reeling and does not cast outside the target");
        Check(machine.Step(AfterCatch(1047, 0, 0), 90) == FishingAction.CastClick && machine.Reels == 1,
            "the same shifted bar can cast when the real hook pixels are moved onto its target");
        machine.ConfirmClick(FishingAction.CastClick, 90);
        machine.Step(wait, 120); machine.Step(wait, 150); machine.Step(wait, 180);
        Check(machine.Casts == 1 && machine.Phase == FishingPhase.WaitingBite,
            "the shifted after-catch cast is counted only after a sent click and disappearance");

        PixelFrame leftBar = WideBars(false, -260, 0, 0), rightBar = WideBars(false, 400, 0, 0);
        machine = new FishingStateMachine(options);
        Check(machine.Step(leftBar, 0) == FishingAction.None && machine.Step(rightBar, 30) == FishingAction.None,
            "different candidate bars in consecutive frames cannot satisfy two-frame confirmation");
        Check(machine.Step(rightBar, 60) == FishingAction.CastClick,
            "a second observation of the same shifted bar permits a verified cast");
        machine = new FishingStateMachine(options);
        machine.Step(leftBar, 0);
        Check(machine.Step(leftBar, 30) == FishingAction.CastClick, "first bar can be confirmed");
        Check(machine.Step(rightBar, 60) == FishingAction.None,
            "a different bar during casting must be confirmed again");
        Check(machine.Step(rightBar, 90) == FishingAction.CastClick,
            "the replacement bar is allowed only after its second observation");
        machine = new FishingStateMachine(options);
        machine.Step(leftBar, 0); machine.Step(leftBar, 30); machine.ConfirmClick(FishingAction.CastClick, 30);
        Check(machine.Step(rightBar, 60) == FishingAction.None && machine.Step(rightBar, 90) == FishingAction.None,
            "switching bars cannot bypass the cooldown for an already-sent cast click");
        Check(machine.Step(rightBar, 380) == FishingAction.CastClick,
            "a confirmed new bar may be clicked after the last sent cast cooldown");
        machine = new FishingStateMachine(options);
        machine.Step(leftBar, 0);
        PixelFrame ambiguousBars = WideBars(true, -260, 400, 0);
        Check(machine.Step(ambiguousBars, 30) == FishingAction.None && machine.LastDetection.Contains("несколько похожих"),
            "ambiguous bars prevent a cast and are reported");
        Check(machine.Step(leftBar, 60) == FishingAction.None && machine.Step(leftBar, 90) == FishingAction.CastClick,
            "an ambiguous frame resets cast confirmation");

        machine = new FishingStateMachine(options);
        machine.Step(bite, 0); machine.Step(bite, 30); machine.ConfirmClick(FishingAction.ReelClick, 30);
        machine.Step(wait, 60); machine.Step(wait, 90); machine.Step(wait, 120);
        Check(machine.Step(wait, 10119) == FishingAction.None && machine.Title != "Следующая шкала не найдена",
            "the post-reel hint waits for ten seconds without clicking");
        Check(machine.Step(wait, 10120) == FishingAction.None && machine.Title == "Следующая шкала не найдена" &&
            machine.Detail.Contains("F9"), "a missing next cast produces an actionable diagnostic, not a blind recovery click");
        Check(machine.Step(AfterCatch(-2, 0, 0), 10150) == FishingAction.None &&
            machine.Step(AfterCatch(1047, 0, 0), 10180) == FishingAction.CastClick,
            "normal casting still resumes after the diagnostic hint");
        machine.Pause(); machine.Step(wait, 20000); machine.Step(wait, 31000);
        Check(machine.Title != "Следующая шкала не найдена", "focus loss clears the post-reel hint context");

        machine = new FishingStateMachine(options);
        machine.Step(cast, 0); machine.Step(cast, 30); machine.ConfirmClick(FishingAction.CastClick, 30);
        machine.Step(wait, 60);
        Check(machine.Step(cast, 90) == FishingAction.None && machine.Step(cast, 120) == FishingAction.None,
            "one missing frame requires confirmation again and retains the actual click cooldown");
        machine.Step(wait, 150); machine.Step(wait, 180); machine.Step(wait, 210);
        Check(machine.Casts == 1 && machine.Phase == FishingPhase.WaitingBite,
            "a brief missing frame does not erase an already-sent cast");
        Check(machine.Step(wait, 11000) == FishingAction.None && machine.Phase == FishingPhase.WaitingBite &&
            machine.Title == "Ожидание клёва", "normal waiting for a bite is not labelled as a missing next cast");

        machine = new FishingStateMachine(options);
        machine.Step(cast, 0);
        Check(machine.Step(cast, 30) == FishingAction.CastClick, "cast action can be requested before input confirmation");
        machine.ClickSuppressed();
        Check(machine.Detail.Contains("не отправлен"), "suppressed input is explained honestly");
        Check(machine.Step(cast, 60) == FishingAction.CastClick, "suppressed click is requested again while the hook is visible");
        machine.Step(wait, 90); machine.Step(wait, 120); machine.Step(wait, 150);
        Check(machine.Casts == 0 && machine.Phase == FishingPhase.Searching,
            "disappearance without an actual click must not count as a cast");
        machine.Step(cast, 180);
        Check(machine.Step(cast, 210) == FishingAction.CastClick, "a later cast can still be requested after suppression");
        machine.ConfirmClick(FishingAction.CastClick, 210);
        machine.Step(wait, 240); machine.Step(wait, 270); machine.Step(wait, 300);
        Check(machine.Casts == 1, "a subsequently sent click is counted");

        machine = new FishingStateMachine(options);
        machine.Step(edge, 0);
        Check(machine.Step(edge, 30) == FishingAction.None, "dark green edge is rejected");
        Check(machine.Step(edge, 10040) == FishingAction.None, "waiting never relaxes the bright-target requirement");
        machine = new FishingStateMachine(options);
        PixelFrame noTarget = SyntheticCast(880, true, false);
        machine.Step(noTarget, 0);
        Check(machine.Step(noTarget, 30) == FishingAction.None && machine.Step(noTarget, 10040) == FishingAction.None,
            "a hook without a detected bright target never causes a blind click");
        Check(machine.Step(noTarget, 18031) == FishingAction.Stop, "missing bright target times out safely");

        // Synthetic motion made from the real white-hook sprite. The actual game
        // speed and latency are not established by these still-image tests.
        machine = new FishingStateMachine(options);
        Check(machine.Step(BoatWithHook(760), 0) == FishingAction.None, "moving hook starts outside target");
        Check(machine.Step(BoatWithHook(800), 20) == FishingAction.None, "left dark green is rejected");
        Check(machine.Step(BoatWithHook(840), 40) == FishingAction.None, "wide green near the target is still rejected");
        Check(machine.Step(BoatWithHook(880), 60) == FishingAction.CastClick, "moving hook in the bright centre triggers the cast");
        machine = new FishingStateMachine(options);
        machine.Step(BoatWithHook(1000), 0);
        Check(machine.Step(BoatWithHook(930), 20) == FishingAction.None, "right dark green is rejected");
        Check(machine.Step(BoatWithHook(900), 40) == FishingAction.CastClick, "the hook can enter the target from the right");
        machine = new FishingStateMachine(options);
        machine.Step(ScaleTo720(BoatWithHook(840)), 0);
        Check(machine.Step(ScaleTo720(BoatWithHook(888)), 30) == FishingAction.CastClick,
            "the centred white hook triggers the cast after 720p scaling");
        machine = new FishingStateMachine(options);
        machine.Step(BoatWithHook(840), 0);
        Check(machine.Step(BoatWithHook(930), 30) == FishingAction.None, "do not guess a click when frames jump over the target");
        for (int x = 800; x <= 970; x += 5)
        {
            PixelFrame full = BoatWithHook(x);
            for (int size = 0; size <= 1; size++)
            {
                PixelFrame sample = size == 0 ? full : ScaleTo720(full);
                FishingStateMachine sweep = new FishingStateMachine(options);
                sweep.Step(sample, 0);
                FishingAction action = sweep.Step(sample, 30);
                if (x >= 875 && x <= 900)
                    Check(action == FishingAction.CastClick, "centred hook is not missed in the reconstructed sweep at x=" + x + " size=" + size);
                else if (x < 859 || x > 917)
                    Check(action == FishingAction.None, "reconstructed sweep never clicks outside the bright strip at x=" + x + " size=" + size);
            }
        }
        foreach (double brightness in new double[] { 1.0, 0.85, 0.70 })
        {
            for (int size = 0; size < 2; size++)
            {
                PixelFrame outside = UserBarWithHook(840, brightness), inside = UserBarWithHook(890, brightness);
                if (size == 1) { outside = ScaleTo720(outside); inside = ScaleTo720(inside); }
                machine = new FishingStateMachine(options);
                machine.Step(outside, 0);
                Check(machine.Step(outside, 20) == FishingAction.None, "dimmed user hook outside bright patch must not click");
                Check(machine.Step(inside, 40) == FishingAction.CastClick, "dimmed user hook inside bright patch clicks");
            }
        }
        // A visually confirmed target may survive a brief occlusion, but it
        // must not survive a different bar, a missing bar, a pause or age-out.
        machine = new FishingStateMachine(options);
        machine.Step(SyntheticCast(800, true), 0);
        Check(machine.Step(SyntheticCast(880, true, false), 20) == FishingAction.None, "one target frame is not enough to establish memory");
        machine = new FishingStateMachine(options);
        machine.Step(SyntheticCast(800, true), 0); machine.Step(SyntheticCast(830, true), 20);
        Check(machine.Step(SyntheticCast(-1, true, false), 40) == FishingAction.None, "remembered target without a visible hook never clicks");
        Check(machine.Step(SyntheticCast(880, true, false), 40) == FishingAction.CastClick, "temporarily occluded verified target stays usable");
        machine = new FishingStateMachine(options);
        machine.Step(SyntheticCast(800, true), 0); machine.Step(SyntheticCast(830, true), 20);
        Check(machine.Step(SyntheticCast(880, true, false), 220) == FishingAction.CastClick, "memory remains valid through its 200 millisecond boundary");
        machine = new FishingStateMachine(options);
        machine.Step(SyntheticCast(800, true), 0); machine.Step(SyntheticCast(830, true), 20);
        Check(machine.Step(SyntheticCast(880, true, false), 221) == FishingAction.None, "old target is never used after the short window");
        machine = new FishingStateMachine(options);
        machine.Step(SyntheticCast(800, true), 0); machine.Step(SyntheticCast(830, true), 20);
        Check(machine.Step(ShiftCast(SyntheticCast(845, true, false), 35), 40) == FishingAction.None, "target is not reused on a shifted bar");
        machine = new FishingStateMachine(options);
        machine.Step(SyntheticCast(800, true), 0); machine.Step(SyntheticCast(830, true), 20); machine.Pause();
        machine.Step(SyntheticCast(880, true, false), 40);
        Check(machine.Step(SyntheticCast(880, true, false), 60) == FishingAction.None, "pause clears target memory");
        machine = new FishingStateMachine(options);
        machine.Step(SyntheticCast(800, true), 0); machine.Step(SyntheticCast(830, true), 20); machine.Step(wait, 30);
        Check(machine.Step(SyntheticCast(880, true, false), 40) == FishingAction.None, "missing bar clears target memory");

        machine = new FishingStateMachine(options);
        machine.Step(noHook, 0);
        Check(machine.Step(noHook, 30) == FishingAction.None, "no white hook means no click");
        Check(machine.Step(noHook, 18031) == FishingAction.Stop, "an unrecognized hook eventually stops");
        machine = new FishingStateMachine(options);
        machine.Step(AfterCatch(-1, 0, 0), 0);
        Check(machine.Step(AfterCatch(-1, 0, 0), 30) == FishingAction.None &&
            machine.Step(AfterCatch(-1, 0, 0), 10000) == FishingAction.None,
            "the shifted real background with its hook removed never prompts a cast");
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
        public int Clicks, Attempts, Captures, CaptureThread, ReleaseThread, Releases;
        public volatile bool SuppressClick;
        public int BlockAtCapture, BlockAtAreaCapture, AreaCaptures;
        public ManualResetEvent CaptureEntered, ContinueCapture, AreaEntered, ContinueArea, ClickEntered, ContinueClick;
        public volatile PixelFrame Frame, Area, NoticeArea;
        public readonly List<GameKey> Keys = new List<GameKey>();
        public int RouteClicks, CursorMoves, FailKeyAt = -1;
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
            PixelFrame result = Frame;
            int captured = Interlocked.Increment(ref Captures);
            if (captured == BlockAtCapture && CaptureEntered != null && ContinueCapture != null)
            {
                CaptureEntered.Set();
                ContinueCapture.WaitOne();
            }
            return result;
        }
        public ClickResult Click(GameBounds bounds, WaitHandle stop, out string error)
        {
            error = "";
            if (!Focus || StopFile || stop.WaitOne(0)) return ClickResult.Failed;
            Interlocked.Increment(ref Attempts);
            if (SuppressClick) return ClickResult.Suppressed;
            Interlocked.Increment(ref Clicks);
            if (ClickEntered != null && ContinueClick != null)
            {
                ClickEntered.Set();
                ContinueClick.WaitOne();
            }
            return ClickResult.Sent;
        }
        public PixelFrame CaptureArea(GameBounds bounds, int left, int top, int right, int bottom)
        {
            PixelFrame result = left == NoticeTemplate.RegionLeft && NoticeArea != null ? NoticeArea : Area;
            int captured = Interlocked.Increment(ref AreaCaptures);
            if (captured == BlockAtAreaCapture && AreaEntered != null && ContinueArea != null)
            {
                AreaEntered.Set(); ContinueArea.WaitOne();
            }
            return result;
        }
        public bool MoveCursor(GameBounds bounds, int x, int y, WaitHandle stop, out string error)
        {
            error = "";
            if (!Focus || StopFile || stop.WaitOne(0)) { error = "not ready"; return false; }
            CursorMoves++; return true;
        }
        public ClickResult ClickAt(GameBounds bounds, int x, int y, bool right, WaitHandle stop, out string error)
        {
            error = "";
            if (!Focus || StopFile || stop.WaitOne(0)) return ClickResult.Failed;
            RouteClicks++; return ClickResult.Sent;
        }
        public bool HoldKey(GameBounds bounds, GameKey key, int milliseconds, WaitHandle stop, out string error)
        {
            error = "";
            if (!Focus || StopFile || stop.WaitOne(0) || Keys.Count == FailKeyAt) { error = "interrupted"; return false; }
            Keys.Add(key); return true;
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
        Check(FishingEngine.EffectivePollPeriod(20, true) == 15 && FishingEngine.EffectivePollPeriod(150, true) == 15,
            "casting temporarily increases sampling frequency");
        Check(FishingEngine.EffectivePollPeriod(150, false) == 150, "configured non-casting polling is respected");
        Check(FishingEngine.NextPollDelay(20, 7, true) == 13, "casting poll accounts for capture and processing time");
        Check(FishingEngine.NextPollDelay(20, 25, true) == 1, "a slow casting cycle yields briefly instead of adding a full poll delay");
        Check(FishingEngine.NextPollDelay(20, 7, false) == 20, "non-casting polling cadence is unchanged");
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

        FakePort held = new FakePort { Frame = SyntheticCast(880, true), Focus = true, SuppressClick = true };
        using (FishingEngine engine = new FishingEngine(held))
        {
            Check(engine.Start(new EngineOptions()), "worker starts while user holds LMB");
            Check(WaitUntil(delegate { return held.Attempts >= 2; }, 2000), "held LMB suppresses click attempts");
            held.Frame = Fixture("waiting", 1920, 1080);
            Check(WaitUntil(delegate { return engine.Snapshot().Phase == FishingPhase.Searching; }, 2000),
                "worker returns to searching after a suppressed cast vanishes");
            Check(held.Clicks == 0 && engine.Snapshot().Casts == 0, "no suppressed input is counted as a cast");
            held.SuppressClick = false;
            held.Frame = SyntheticCast(880, true);
            Check(WaitUntil(delegate { return held.Clicks == 1; }, 2000), "worker can click once LMB is released");
            held.Frame = Fixture("waiting", 1920, 1080);
            Check(WaitUntil(delegate { return engine.Snapshot().Casts == 1; }, 2000), "sent cast is counted when the bar disappears");
            engine.RequestStop();
            Check(engine.WaitForStop(2000), "held-LMB worker stops normally");
        }

        FakePort moving = new FakePort { Frame = BoatWithHook(840), Focus = true };
        using (FishingEngine engine = new FishingEngine(moving))
        {
            Check(engine.Start(new EngineOptions()), "worker starts for moving-hook test");
            Check(WaitUntil(delegate { return moving.Captures >= 3; }, 2000), "worker sees several dark-green frames");
            Check(moving.Clicks == 0, "worker does not click the broad green band outside the bright target");
            moving.Frame = BoatWithHook(888);
            Check(WaitUntil(delegate { return moving.Clicks > 0; }, 2000), "worker clicks when the white hook reaches the bright target");
            engine.RequestStop();
            Check(engine.WaitForStop(2000), "moving-hook worker stops normally");
        }

        foreach (PixelFrame candidate in new PixelFrame[] { SyntheticCast(880, true), Fixture("bite", 1920, 1080) })
        using (ManualResetEvent entered = new ManualResetEvent(false))
        using (ManualResetEvent proceed = new ManualResetEvent(false))
        {
            FakePort slow = new FakePort { Frame = candidate, Focus = true,
                BlockAtCapture = 2, CaptureEntered = entered, ContinueCapture = proceed };
            using (FishingEngine engine = new FishingEngine(slow))
            {
                try
                {
                    Check(engine.Start(new EngineOptions()), "worker starts before delayed-frame test");
                    Check(entered.WaitOne(2000), "second fishing-bar capture can be delayed");
                    Thread.Sleep(FishingEngine.MaxFrameAgeMilliseconds + 80);
                    slow.Frame = Fixture("waiting", 1920, 1080);
                }
                finally { proceed.Set(); }
                Check(WaitUntil(delegate { return slow.Captures >= 4; }, 2000), "worker continues after delayed capture");
                Check(slow.Attempts == 0 && slow.Clicks == 0,
                    "a stale captured fishing bar is discarded instead of causing a click");
                Check(String.Join("\n", engine.Events()).Contains("больше 100 мс"), "delayed capture is explained in the log");
                slow.Frame = candidate;
                Check(WaitUntil(delegate { return slow.Clicks > 0; }, 2000), "fresh confirmed frames can still trigger a click");
                engine.RequestStop();
                Check(engine.WaitForStop(2000), "worker stops after delayed-frame test");
            }
        }
    }

    private static PixelFrame NoticeFixture()
    {
        using (FileStream file = File.OpenRead(Path.Combine(fixtures, "notice-cast.bgra.gz")))
        using (GZipStream gzip = new GZipStream(file, CompressionMode.Decompress))
        using (MemoryStream output = new MemoryStream())
        {
            gzip.CopyTo(output);
            return new PixelFrame(output.ToArray(), 390, 75, 390 * 4, 1920, 1080, 20, 735);
        }
    }

    private static PixelFrame GearFrame(bool changed, int clientWidth, int clientHeight)
    {
        const int width = 240, height = 120, originX = 400, originY = 350;
        byte[] data = new byte[width * height * 4];
        for (int y = 0; y < height; y++)
            for (int x = 0; x < width; x++)
            {
                int i = (y * width + x) * 4;
                byte value = changed ? (byte)15 : (byte)(((x / 4 + y / 3) % 2 == 0) ? 210 : 35);
                data[i] = value; data[i + 1] = value; data[i + 2] = value; data[i + 3] = 255;
            }
        return new PixelFrame(data, width, height, width * 4, clientWidth, clientHeight, originX, originY);
    }

    private static void RelocationTests()
    {
        PixelFrame noticeFrame = NoticeFixture();
        NoticeTemplate notice = NoticeTemplate.Create(noticeFrame, 69, 768, 165, 24);
        Check(notice.Matches(noticeFrame), "a recorded notification matches its own text mask");
        Check(!notice.Matches(Fixture("waiting", 1920, 1080)), "unrelated screens do not match a notification");
        try { NoticeTemplate.Create(noticeFrame, 21, 740, 30, 20); throw new Exception("small notice selection accepted"); }
        catch (InvalidDataException) { Check(true, "a short or ambiguous selection is rejected"); }

        string temp = Path.Combine(Path.GetTempPath(), "rmfish-calibration-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temp);
        try
        {
            string noticePath = Path.Combine(temp, "notice.dat"), gearPath = Path.Combine(temp, "gear.dat");
            notice.Save(noticePath); notice = NoticeTemplate.Load(noticePath);
            Check(notice.Matches(noticeFrame), "notice calibration survives persistence");
            NoticeTemplate.Create(noticeFrame, 69, 768, 165, 24).Save(noticePath);
            Check(NoticeTemplate.Load(noticePath).Matches(noticeFrame), "notice calibration is atomically replaced");
            File.WriteAllBytes(noticePath, new byte[] { 1, 2, 3 });
            bool bad = false;
            try { NoticeTemplate.Load(noticePath); } catch (Exception) { bad = true; }
            Check(bad, "damaged notification calibration fails closed");

            PixelFrame gearFrame = GearFrame(false, 1920, 1080), changed = GearFrame(true, 1920, 1080);
            GearPoint one = GearPoint.Create(gearFrame, 480, 400, true);
            GearPoint two = GearPoint.Create(gearFrame, 520, 400, false);
            GearPoint three = GearPoint.Create(gearFrame, 560, 400, false);
            Check(one.Matches(gearFrame) && !one.Matches(changed), "inventory target must visually match before clicking");
            Check(!one.Matches(GearFrame(false, 1280, 720)), "inventory samples reject a different client resolution");
            try { GearPoint.Create(changed, 480, 400, false); throw new Exception("uniform gear target accepted"); }
            catch (InvalidDataException) { Check(true, "empty inventory pixels cannot become a click target"); }
            GearMacro gear = new GearMacro(one, two, three);
            gear.Save(gearPath); gear = GearMacro.Load(gearPath);
            Check(gear.Point(0).RightButton && !gear.Point(1).RightButton && gear.ClientWidth == 1920,
                "all three inventory actions and button types survive persistence");

            NoticeGate gate = new NoticeGate();
            Check(!gate.Observe(true, 0) && !gate.Observe(true, 120) && gate.Observe(true, 240), "notice needs three timed confirmations");
            Check(!gate.Observe(true, 60000) && !gate.Observe(true, 80000), "the same persistent notice cannot repeat the route");
            Check(!gate.Observe(false, 80100) && !gate.Observe(false, 82200), "notice must be absent before rearming");
            Check(!gate.Observe(true, 82300) && !gate.Observe(true, 82420) && gate.Observe(true, 82540),
                "a later distinct notice can rearm after the cooldown");
            gate = new NoticeGate(); gate.Observe(true, 0); gate.Pause();
            Check(!gate.Observe(true, 120) && !gate.Observe(true, 240) && gate.Observe(true, 360),
                "focus loss discards partial notice confirmations");

            GameBounds bounds = new GameBounds { Handle = new IntPtr(42), Width = 1920, Height = 1080 };
            RelocationTimings timing = new RelocationTimings { Open = 1, Hover = 1, Between = 1 };
            using (ManualResetEvent stop = new ManualResetEvent(false))
            {
                FakePort ok = new FakePort { Focus = true, Area = gearFrame };
                string error;
                Check(RelocationRunner.Execute(ok, bounds, stop, gear, timing, delegate(string ignored) { }, out error), "calibrated route completes");
                Check(ok.Keys.Count == 4 && ok.Keys[0] == GameKey.Space && ok.Keys[1] == GameKey.Back &&
                    ok.Keys[2] == GameKey.Forward && ok.Keys[3] == GameKey.Inventory,
                    "route sends exactly one space, then S, W and I in order");
                Check(timing.Walk == 7000 && ok.RouteClicks == 3, "route uses seven seconds per direction and three guarded clicks");
                FakePort interrupted = new FakePort { Focus = true, Area = gearFrame, FailKeyAt = 2 };
                Check(!RelocationRunner.Execute(interrupted, bounds, stop, gear, timing, delegate(string ignored) { }, out error) &&
                    interrupted.Keys.Count == 2 && interrupted.RouteClicks == 0,
                    "an interrupted walk never starts the return or inventory sequence");
                FakePort mismatch = new FakePort { Focus = true, Area = changed };
                Check(!RelocationRunner.Execute(mismatch, bounds, stop, gear, timing, delegate(string ignored) { }, out error) &&
                    mismatch.RouteClicks == 0 && error.Contains("не совпал"), "unexpected inventory contents stop before the first click");
                stop.Set();
                FakePort stopped = new FakePort { Focus = true, Area = gearFrame };
                Check(!RelocationRunner.Execute(stopped, bounds, stop, gear, timing, delegate(string ignored) { }, out error) &&
                    stopped.Keys.Count == 0, "an already-requested stop forbids every route action");
            }

            FakePort automatic = new FakePort { Focus = true, Frame = Fixture("waiting", 1920, 1080), Area = gearFrame, NoticeArea = noticeFrame };
            using (FishingEngine engine = new FishingEngine(automatic))
            {
                Check(engine.Start(new EngineOptions { AutoRelocate = true, Notice = notice, Gear = gear, SessionLimitSeconds = 30 }),
                    "opt-in worker starts with both calibrations");
                Check(WaitUntil(delegate { return automatic.RouteClicks == 3; }, 9000), "worker detects a stable calibrated notice and runs the guarded route");
                Thread.Sleep(500);
                Check(automatic.Keys.Count == 4 && automatic.Keys[0] == GameKey.Space, "persistent notification does not repeat space");
                engine.RequestStop(); Check(engine.WaitForStop(2000), "auto-relocation worker stops");
            }
            using (ManualResetEvent entered = new ManualResetEvent(false))
            using (ManualResetEvent proceed = new ManualResetEvent(false))
            {
                FakePort slowNotice = new FakePort { Focus = true, Frame = Fixture("waiting", 1920, 1080),
                    Area = gearFrame, NoticeArea = noticeFrame, BlockAtAreaCapture = 2, AreaEntered = entered, ContinueArea = proceed };
                using (FishingEngine engine = new FishingEngine(slowNotice))
                {
                    try
                    {
                        Check(engine.Start(new EngineOptions { AutoRelocate = true, Notice = notice, Gear = gear }),
                            "worker starts for delayed notice test");
                        Check(entered.WaitOne(2000), "second notice capture can be delayed");
                        Thread.Sleep(FishingEngine.MaxFrameAgeMilliseconds + 80);
                        slowNotice.NoticeArea = Fixture("waiting", 1920, 1080);
                    }
                    finally { proceed.Set(); }
                    Check(WaitUntil(delegate { return slowNotice.AreaCaptures >= 3; }, 2000), "notice checks continue after the delay");
                    Check(slowNotice.Keys.Count == 0 && slowNotice.RouteClicks == 0,
                        "an old notice observation cannot initiate the movement route");
                    Check(String.Join("\n", engine.Events()).Contains("больше 100 мс"), "the delayed notice is reported");
                    engine.RequestStop(); Check(engine.WaitForStop(2000), "delayed notice worker stops");
                }
            }
            using (FishingEngine engine = new FishingEngine(new FakePort()))
            {
                bool refused = false;
                try { engine.Start(new EngineOptions { AutoRelocate = true }); } catch (InvalidOperationException) { refused = true; }
                Check(refused, "auto-relocation is refused without both calibrations");
            }
        }
        finally { Directory.Delete(temp, true); }
    }

    private sealed class FakeKeys
    {
        private readonly int[] states = new int[256];
        public volatile bool Fail;
        public bool Read(int key)
        {
            if (Fail) throw new InvalidOperationException("simulated key-state failure");
            return Interlocked.CompareExchange(ref states[key], 0, 0) != 0;
        }
        public void Set(int key, bool down) { Interlocked.Exchange(ref states[key], down ? 1 : 0); }
    }

    private static void KeySafetyTests()
    {
        CooldownGate debounce = new CooldownGate(300);
        Check(debounce.TryClaim(0), "first diagnostic request is accepted");
        Check(!debounce.TryClaim(50), "duplicate F9 messages are suppressed");
        Check(debounce.TryClaim(301), "a later F9 request is accepted");

        FakeKeys keys = new FakeKeys();
        FakePort port = new FakePort { Frame = SyntheticCast(880, true), Focus = false };
        int f9 = 0, f10 = 0, escape = 0, mouse = 0, faults = 0, callbackThread = 0, observedF9Up = 0;
        using (FishingEngine engine = new FishingEngine(port))
        using (SafetyKeyMonitor monitor = new SafetyKeyMonitor(
            delegate(int key)
            {
                bool down = keys.Read(key);
                if (key == SafetyKeyMonitor.F9 && !down) Interlocked.Increment(ref observedF9Up);
                return down;
            },
            delegate(EmergencySignal signal, bool first)
            {
                callbackThread = Thread.CurrentThread.ManagedThreadId;
                engine.RequestStop("emergency " + signal);
                if (first && signal == EmergencySignal.F10) Interlocked.Increment(ref f10);
                if (first && signal == EmergencySignal.EscapeHeld) Interlocked.Increment(ref escape);
                if (first && signal == EmergencySignal.MouseButtonsHeld) Interlocked.Increment(ref mouse);
            },
            delegate { Interlocked.Increment(ref f9); },
            delegate(Exception ex) { Interlocked.Increment(ref faults); engine.RequestStop("key monitor failed"); }, 5, 120))
        {
            monitor.Start();
            keys.Set(SafetyKeyMonitor.F9, true);
            Check(WaitUntil(delegate { return f9 == 1; }, 1000), "F9 is detected without WM_HOTKEY");
            Thread.Sleep(60);
            Check(f9 == 1, "holding F9 produces one diagnostic request");
            int readsBeforeRelease = Interlocked.CompareExchange(ref observedF9Up, 0, 0);
            keys.Set(SafetyKeyMonitor.F9, false);
            Check(WaitUntil(delegate { return Interlocked.CompareExchange(ref observedF9Up, 0, 0) > readsBeforeRelease; }, 1000),
                "poller observes F9 release before the next press");
            keys.Set(SafetyKeyMonitor.F9, true);
            Check(WaitUntil(delegate { return f9 == 2; }, 1000), "F9 works again after release");
            keys.Set(SafetyKeyMonitor.F9, false);

            Check(engine.Start(new EngineOptions()), "worker starts for F10 fallback test");
            keys.Set(SafetyKeyMonitor.F10, true);
            Check(WaitUntil(delegate { return !engine.Snapshot().Running; }, 1000), "F10 polling stops worker without UI messages");
            Check(engine.WaitForStop(1000) && WaitUntil(delegate { return f10 == 1; }, 1000), "F10 press produces one first-press notification");
            Check(callbackThread != Thread.CurrentThread.ManagedThreadId, "emergency callback runs independently of UI thread");
            Check(monitor.StopHeld, "held F10 is exposed as a start blocker");
            Check(engine.Start(new EngineOptions()), "test can force a restart while F10 remains held");
            Check(WaitUntil(delegate { return !engine.Snapshot().Running; }, 1000), "held F10 reasserts stop after a forced restart");
            Check(engine.WaitForStop(1000) && f10 == 1, "held F10 is not repeatedly reported as a new press");
            keys.Set(SafetyKeyMonitor.F10, false);
            Check(WaitUntil(delegate { return !monitor.StopHeld; }, 1000), "releasing F10 clears the hold blocker");

            Check(engine.Start(new EngineOptions()), "worker starts for escape hold test");
            keys.Set(SafetyKeyMonitor.Escape, true);
            Thread.Sleep(50);
            Check(engine.Snapshot().Running, "a short Escape press does not stop the worker");
            Check(WaitUntil(delegate { return !engine.Snapshot().Running; }, 1000), "holding Escape stops the worker");
            Check(engine.WaitForStop(1000) && WaitUntil(delegate { return escape == 1; }, 1000), "Escape hold triggers once");
            keys.Set(SafetyKeyMonitor.Escape, false);
            Check(WaitUntil(delegate { return !monitor.StopHeld; }, 1000), "releasing Escape clears the hold blocker");

            Check(engine.Start(new EngineOptions()), "worker starts for mouse hold test");
            keys.Set(SafetyKeyMonitor.LeftMouse, true);
            Thread.Sleep(180);
            Check(engine.Snapshot().Running, "holding left mouse alone is not an emergency stop");
            keys.Set(SafetyKeyMonitor.RightMouse, true);
            Check(WaitUntil(delegate { return !engine.Snapshot().Running; }, 1000), "holding both mouse buttons stops the worker");
            Check(engine.WaitForStop(1000) && WaitUntil(delegate { return mouse == 1; }, 1000), "mouse hold triggers once");
            keys.Set(SafetyKeyMonitor.LeftMouse, false);
            keys.Set(SafetyKeyMonitor.RightMouse, false);
            Check(WaitUntil(delegate { return !monitor.StopHeld; }, 1000), "releasing mouse buttons clears the hold blocker");
            Check(faults == 0, "normal polling has no faults");

            Check(engine.Start(new EngineOptions()), "worker starts for key monitor fault test");
            keys.Fail = true;
            Check(WaitUntil(delegate { return faults == 1 && !engine.Snapshot().Running; }, 1000), "key monitor fault requests a fail-closed stop");
            Check(engine.WaitForStop(1000), "worker exits after monitor failure");
        }
    }

    private static void BackgroundProbeSafetyTests()
    {
        using (ManualResetEvent entered = new ManualResetEvent(false))
        using (ManualResetEvent proceed = new ManualResetEvent(false))
        using (ManualResetEvent completed = new ManualResetEvent(false))
        {
            int calls = 0, faults = 0;
            BackgroundProbe probe = new BackgroundProbe(
                delegate
                {
                    Interlocked.Increment(ref calls);
                    entered.Set();
                    proceed.WaitOne();
                    completed.Set();
                },
                delegate(Exception ex) { Interlocked.Increment(ref faults); });
            FakeKeys keys = new FakeKeys();
            FakePort port = new FakePort { Frame = SyntheticCast(880, true), Focus = false };
            using (FishingEngine engine = new FishingEngine(port))
            using (SafetyKeyMonitor monitor = new SafetyKeyMonitor(keys.Read,
                delegate(EmergencySignal signal, bool first) { engine.RequestStop("emergency while probing"); },
                delegate { probe.TryStart(); },
                delegate(Exception ex) { Interlocked.Increment(ref faults); engine.RequestStop(); }, 5, 120))
            {
                try
                {
                    monitor.Start();
                    Check(engine.Start(new EngineOptions()), "worker starts for blocked diagnostic test");
                    keys.Set(SafetyKeyMonitor.F9, true);
                    Check(entered.WaitOne(2000), "F9 starts a background capture");
                    Check(!probe.TryStart() && calls == 1, "a blocked probe cannot spawn unlimited capture threads");
                    keys.Set(SafetyKeyMonitor.F10, true);
                    Check(WaitUntil(delegate { return !engine.Snapshot().Running; }, 2000), "F10 still stops while the diagnostic capture is blocked");
                    Check(engine.WaitForStop(1000) && faults == 0, "the key monitor remains healthy during a blocked diagnostic");
                }
                finally { proceed.Set(); }
                Check(completed.WaitOne(2000), "background diagnostic exits after being released");
            }
        }
        using (ManualResetEvent failed = new ManualResetEvent(false))
        {
            BackgroundProbe failing = new BackgroundProbe(delegate { throw new InvalidOperationException("probe failure"); },
                delegate(Exception ex) { if (ex.Message == "probe failure") failed.Set(); });
            Check(failing.TryStart() && failed.WaitOne(2000), "diagnostic exceptions are contained and reported");
        }
    }

    private static void InFlightStopTests()
    {
        FakePort idle = new FakePort { Frame = SyntheticCast(880, true), Focus = false };
        using (FishingEngine engine = new FishingEngine(idle))
        {
            long beforeStop = engine.StopVersion;
            engine.RequestStop("F10 during start preparation");
            Check(!engine.Start(new EngineOptions(), beforeStop), "an emergency during start preparation cancels that start");
            Check(engine.Start(new EngineOptions(), engine.StopVersion), "a fresh start after the stop is allowed");
            engine.RequestStop();
            Check(engine.WaitForStop(2000), "the fresh start stops normally");
        }

        // A signal cannot interrupt an arbitrary native call. The snapshot must
        // say 'stopping' until it returns, and no further click may start.
        using (ManualResetEvent entered = new ManualResetEvent(false))
        using (ManualResetEvent proceed = new ManualResetEvent(false))
        {
            FakePort port = new FakePort { Frame = SyntheticCast(880, true), Focus = true,
                ClickEntered = entered, ContinueClick = proceed };
            using (FishingEngine engine = new FishingEngine(port))
            {
                try
                {
                    Check(engine.Start(new EngineOptions()), "worker starts before in-flight click");
                    Check(entered.WaitOne(2000), "a simulated mouse call can be held");
                    engine.RequestStop("F10 test");
                    EngineSnapshot pending = engine.Snapshot();
                    Check(pending.Running && pending.Stopping && pending.Detail.Contains("F10"), "in-flight click reports a pending stop");
                    Check(port.Clicks == 1, "only the in-flight mouse call has begun");
                }
                finally { proceed.Set(); }
                Check(engine.WaitForStop(2000), "worker stops when the in-flight mouse call returns");
                Check(port.Clicks == 1 && !engine.Snapshot().Stopping, "no new click starts after the stop request");
            }
        }

        using (ManualResetEvent entered = new ManualResetEvent(false))
        using (ManualResetEvent proceed = new ManualResetEvent(false))
        {
            FakePort port = new FakePort { Frame = Fixture("bite", 1920, 1080), Focus = true,
                BlockAtCapture = 2, CaptureEntered = entered, ContinueCapture = proceed };
            FishingEngine engine = new FishingEngine(port);
            Thread closer = null;
            try
            {
                Check(engine.Start(new EngineOptions()), "worker starts before close-race test");
                Check(entered.WaitOne(2000), "capture is blocked during close-race test");
                closer = new Thread(engine.Dispose);
                closer.IsBackground = true;
                closer.Start();
                Check(WaitUntil(delegate { return engine.Snapshot().Stopping; }, 2000), "close requests a stop before waiting");
                bool refused = false;
                try { engine.Start(new EngineOptions()); }
                catch (ObjectDisposedException) { refused = true; }
                Check(refused, "a concurrent restart is refused while disposal waits");
            }
            finally
            {
                proceed.Set();
                if (closer != null) closer.Join(5000);
                engine.Dispose();
            }
            Check(closer != null && !closer.IsAlive && port.Clicks == 0, "close completes without a stale click");
        }
    }

    private static void SessionSafetyTests()
    {
        Check(new EngineOptions { SessionLimitSeconds = 0 }.CopyValidated().SessionLimitSeconds == 1,
            "session limit cannot be disabled");
        Check(new EngineOptions { SessionLimitSeconds = 9999 }.CopyValidated().SessionLimitSeconds == 1800,
            "session limit has an upper bound");
        FakePort paused = new FakePort { Frame = SyntheticCast(880, true), Focus = false };
        using (FishingEngine engine = new FishingEngine(paused))
        {
            Check(engine.Start(new EngineOptions { SessionLimitSeconds = 1 }), "bounded session starts");
            Check(WaitUntil(delegate { return !engine.Snapshot().Running; }, 2500), "session expires even while game is unfocused");
            Check(engine.Snapshot().Detail.Contains("лимит"), "session timeout reason is visible");
            Check(engine.WaitForStop(1000), "timed-out worker exits");
            Check(engine.Start(new EngineOptions { SessionLimitSeconds = 1 }), "short session starts before manual stop");
            Thread.Sleep(100);
            engine.RequestStop();
            Check(engine.WaitForStop(1000), "short session stops manually");
            Check(engine.Start(new EngineOptions { SessionLimitSeconds = 5 }), "new session starts after previous timer");
            Thread.Sleep(1200);
            Check(engine.Snapshot().Running, "previous timer cannot stop a later session");
            engine.RequestStop();
            Check(engine.WaitForStop(1000), "later session stops on request");
        }

        using (ManualResetEvent entered = new ManualResetEvent(false))
        using (ManualResetEvent proceed = new ManualResetEvent(false))
        {
            FakePort blocked = new FakePort { Frame = Fixture("bite", 1920, 1080), Focus = true,
                BlockAtCapture = 2, CaptureEntered = entered, ContinueCapture = proceed };
            using (FishingEngine engine = new FishingEngine(blocked))
            {
                try
                {
                    Check(engine.Start(new EngineOptions { SessionLimitSeconds = 1 }), "session starts before blocked capture");
                    Check(entered.WaitOne(2000), "second capture can be held in the test");
                    Check(WaitUntil(delegate { return engine.Snapshot().Stopping; }, 3500), "timer requests a stop while capture is blocked");
                    EngineSnapshot pending = engine.Snapshot();
                    Check(pending.Running && pending.Detail.Contains("лимит"), "a blocked worker is reported as stopping, not stopped");
                    Check(blocked.Clicks == 0, "the blocked capture has not sent a click");
                }
                finally { proceed.Set(); }
                Check(WaitUntil(delegate { return !engine.Snapshot().Running; }, 1500), "timer stops after a blocked capture returns");
                Check(engine.WaitForStop(1000) && blocked.Clicks == 0, "no stale click is sent after the session limit");
                Check(engine.Snapshot().Detail.Contains("лимит") && !engine.Snapshot().Stopping, "blocked capture reports the completed session stop");
            }
        }
    }

    [DllImport("user32.dll")] private static extern short GetAsyncKeyState(int key);
    [DllImport("user32.dll")] private static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);
    [DllImport("user32.dll")] private static extern bool RegisterHotKey(IntPtr window, int id, uint modifiers, uint key);
    [DllImport("user32.dll")] private static extern bool UnregisterHotKey(IntPtr window, int id);

    private static void WindowsKeyIntegrationTests()
    {
        // Synthetic system-wide keystrokes are opt-in for the isolated CI VM;
        // the normal developer test command must not affect an active desktop.
        if (Environment.GetEnvironmentVariable("RMFISH_TEST_NATIVE_KEYS") != "1") return;
        Check(Environment.OSVersion.Platform == PlatformID.Win32NT, "native-key test runs only on Windows");
        // Reserve the hotkeys on this thread without dispatching its messages.
        // The monitor must still see the key state on its own thread.
        bool reservedF9 = RegisterHotKey(IntPtr.Zero, 8501, 0, SafetyKeyMonitor.F9);
        bool reservedF10 = RegisterHotKey(IntPtr.Zero, 8502, 0, SafetyKeyMonitor.F10);
        int f9 = 0, faults = 0;
        FakePort port = new FakePort { Frame = SyntheticCast(880, true), Focus = false };
        using (FishingEngine engine = new FishingEngine(port))
        using (SafetyKeyMonitor monitor = new SafetyKeyMonitor(
            delegate(int key) { return (GetAsyncKeyState(key) & 0x8000) != 0; },
            delegate(EmergencySignal signal, bool first) { engine.RequestStop("native key fallback"); },
            delegate { Interlocked.Increment(ref f9); },
            delegate(Exception ex) { Interlocked.Increment(ref faults); engine.RequestStop("native key failure"); }, 10, 200))
        {
            try
            {
                keybd_event(SafetyKeyMonitor.F9, 0, 2, UIntPtr.Zero);
                keybd_event(SafetyKeyMonitor.F10, 0, 2, UIntPtr.Zero);
                monitor.Start();
                Thread.Sleep(80);
                keybd_event(SafetyKeyMonitor.F9, 0, 0, UIntPtr.Zero);
                Check(WaitUntil(delegate { return f9 > 0; }, 1000), "Windows key-state fallback receives F9 without a message pump");
                keybd_event(SafetyKeyMonitor.F9, 0, 2, UIntPtr.Zero);
                Check(engine.Start(new EngineOptions()), "worker starts for native F10 test");
                keybd_event(SafetyKeyMonitor.F10, 0, 0, UIntPtr.Zero);
                Check(WaitUntil(delegate { return !engine.Snapshot().Running; }, 1000), "Windows key-state fallback stops on F10 without a message pump");
                Check(engine.WaitForStop(1000) && faults == 0, "native F10 stop completed without errors");
                if (Environment.GetEnvironmentVariable("GITHUB_ACTIONS") == "true")
                    Console.WriteLine("::notice title=Synthetic Windows keys::F9 and F10 observed by key-state poller; registrations F9=" + reservedF9 + " F10=" + reservedF10 + ". This does not test GTA5 or a physical keyboard.");
            }
            finally
            {
                keybd_event(SafetyKeyMonitor.F9, 0, 2, UIntPtr.Zero);
                keybd_event(SafetyKeyMonitor.F10, 0, 2, UIntPtr.Zero);
                if (reservedF9) UnregisterHotKey(IntPtr.Zero, 8501);
                if (reservedF10) UnregisterHotKey(IntPtr.Zero, 8502);
            }
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
            RelocationTests();
            KeySafetyTests();
            BackgroundProbeSafetyTests();
            InFlightStopTests();
            SessionSafetyTests();
            WindowsKeyIntegrationTests();
            Console.WriteLine("PASS: " + assertions + " assertions (vision, state machine, keyboard and stop safety). ");
            if (Environment.GetEnvironmentVariable("GITHUB_ACTIONS") == "true")
                Console.WriteLine("::notice title=RMFish tests::PASS " + assertions + " assertions.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.ToString());
            if (Environment.GetEnvironmentVariable("GITHUB_ACTIONS") == "true")
                Console.WriteLine("::error title=RMFish tests::" + ex.Message.Replace("%", "%25").Replace("\r", "%0D").Replace("\n", "%0A"));
            return 1;
        }
    }
}
