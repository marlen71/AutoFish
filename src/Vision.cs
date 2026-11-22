using System;

namespace RMFish
{
    // A top-down BGRA crop of the game client. Coordinates exposed to the
    // detector are always in the 1920x1080 reference space.
    public sealed class PixelFrame
    {
        public const int ReferenceWidth = 1920;
        public const int ReferenceHeight = 1080;
        public const int CropLeft = 620;
        public const int CropTop = 360;
        public const int CropRight = 1161; // exclusive
        public const int CropBottom = 741; // exclusive

        private readonly byte[] pixels;
        private readonly int width, height, stride, clientWidth, clientHeight, originX, originY;

        public PixelFrame(byte[] pixels, int width, int height, int stride,
                          int clientWidth, int clientHeight, int originX, int originY)
        {
            if (pixels == null || width <= 0 || height <= 0 || stride < width * 4 ||
                (long)stride * height > pixels.Length || clientWidth <= 0 || clientHeight <= 0)
                throw new ArgumentException("Invalid frame dimensions.");
            this.pixels = pixels;
            this.width = width;
            this.height = height;
            this.stride = stride;
            this.clientWidth = clientWidth;
            this.clientHeight = clientHeight;
            this.originX = originX;
            this.originY = originY;
        }

        public void Read(int referenceX, int referenceY, out int r, out int g, out int b)
        {
            int x = (int)Math.Round(referenceX * (double)clientWidth / ReferenceWidth) - originX;
            int y = (int)Math.Round(referenceY * (double)clientHeight / ReferenceHeight) - originY;
            if (x < 0 || y < 0 || x >= width || y >= height)
            {
                r = g = b = 0;
                return;
            }
            int i = y * stride + x * 4;
            b = pixels[i];
            g = pixels[i + 1];
            r = pixels[i + 2];
        }
    }

    public sealed class CastInfo
    {
        public int Left { get; private set; }
        public int Right { get; private set; }
        // The narrower, brighter target inside the broad green region. -1 means
        // it could not be identified reliably, so the worker must not click.
        public int TargetLeft { get; private set; }
        public int TargetRight { get; private set; }
        public bool HasTarget { get { return TargetLeft >= 0 && TargetRight >= TargetLeft; } }
        public int Center { get { return HasTarget ? (TargetLeft + TargetRight) / 2 : -1; } }
        // -1 means that the bar is visible but the white hook isn't reliable.
        public int Hook { get; private set; }

        public CastInfo(int left, int right, int hook, int targetLeft, int targetRight)
        {
            Left = left;
            Right = right;
            Hook = hook;
            TargetLeft = targetLeft;
            TargetRight = targetRight;
        }
    }

    public static class Vision
    {
        private static readonly int[] CastRows = new int[] { 493, 499, 506, 513, 519 };
        private const int SearchLeft = 620, SearchRight = 1160;

        private static bool CastGreen(int r, int g, int b)
        {
            // The screenshot's bar is translucent: most green pixels have G ~100,
            // so a strict G > 120 check mistakes the bright overlay for the zone.
            return g >= 70 && g - r >= 25 && g - b >= 20;
        }

        private static bool CastRed(int r, int g, int b)
        {
            return r >= 90 && r - g >= 35 && r - b >= 30;
        }

        private static bool BrightGreen(int r, int g, int b)
        {
            return g > 120 && r < 100 && b < 100;
        }

        private static bool BrightRed(int r, int g, int b)
        {
            return r > 170 && g < 110 && b < 110;
        }

        private static bool White(int r, int g, int b)
        {
            // A dimmed / captured HUD can turn the white hook into neutral
            // grey (for example 178 at 70% brightness). Keep a tight neutral
            // colour constraint and require a compact, tall shape below; the
            // surrounding green/red bar alone must never count as a hook.
            return r >= 155 && g >= 155 && b >= 145 && Math.Max(r, Math.Max(g, b)) - Math.Min(r, Math.Min(g, b)) <= 45;
        }

        public static CastInfo FindCast(PixelFrame frame)
        {
            if (frame == null) throw new ArgumentNullException("frame");
            int n = SearchRight - SearchLeft + 1;
            bool[] green = new bool[n];
            bool[] red = new bool[n];
            int[] chroma = new int[n], rowChroma = new int[CastRows.Length];
            for (int x = SearchLeft; x <= SearchRight; x++)
            {
                int greens = 0, reds = 0;
                for (int row = 0; row < CastRows.Length; row++)
                {
                    int r, g, b;
                    frame.Read(x, CastRows[row], out r, out g, out b);
                    if (CastGreen(r, g, b)) greens++;
                    if (CastRed(r, g, b)) reds++;
                    // Relative green strength is less sensitive than raw green
                    // brightness to the translucent background behind the HUD.
                    rowChroma[row] = Math.Min(g - r, g - b);
                }
                Array.Sort(rowChroma);
                chroma[x - SearchLeft] = rowChroma[rowChroma.Length / 2];
                green[x - SearchLeft] = greens >= 3;
                red[x - SearchLeft] = reds >= 3;
            }

            // The hook can cover the zone. Merge small holes rather than treating
            // each visible green fragment as a separate target.
            int bestLeft = -1, bestRight = -1, bestCount = 0;
            int start = -1, last = -1, count = 0;
            for (int i = 0; i <= n; i++)
            {
                bool marked = i < n && green[i];
                if (marked)
                {
                    if (start < 0) { start = i; count = 0; }
                    else if (i - last > 21)
                    {
                        ConsiderRun(start, last, count, ref bestLeft, ref bestRight, ref bestCount);
                        start = i;
                        count = 0;
                    }
                    last = i;
                    count++;
                }
                else if (i == n && start >= 0)
                {
                    ConsiderRun(start, last, count, ref bestLeft, ref bestRight, ref bestCount);
                }
            }
            if (bestLeft < 0) return null;

            int left = bestLeft + SearchLeft, right = bestRight + SearchLeft;
            int leftRed = 0, rightRed = 0, barLeft = left, barRight = right;
            for (int x = Math.Max(SearchLeft, left - 160); x < left - 5; x++)
                if (red[x - SearchLeft]) { leftRed++; barLeft = Math.Min(barLeft, x); }
            for (int x = right + 6; x <= Math.Min(SearchRight, right + 160); x++)
                if (red[x - SearchLeft]) { rightRed++; barRight = Math.Max(barRight, x); }
            // Red ends plus a wide green middle identify a candidate bar. The
            // worker still requires a white hook and a bright target before clicking.
            if (leftRed < 12 || rightRed < 12) return null;

            // Exclude pale pixels outside the red ends (e.g. the crop or
            // overlay border) so they cannot outrank the actual hook.
            int hook = FindHook(frame, barLeft, barRight);
            int targetLeft, targetRight;
            FindBrightTarget(green, chroma, left, right, out targetLeft, out targetRight);
            return new CastInfo(left, right, hook, targetLeft, targetRight);
        }

        // The HUD's bright centre is substantially greener than the surrounding
        // translucent green band. Use its local median as a baseline, rather
        // than assuming that the whole wide green band is an accurate target.
        private static void FindBrightTarget(bool[] green, int[] chroma, int left, int right,
                                             out int targetLeft, out int targetRight)
        {
            targetLeft = targetRight = -1;
            int zoneWidth = right - left + 1;
            int[] levels = new int[zoneWidth];
            int valid = 0;
            for (int x = left; x <= right; x++)
            {
                int i = x - SearchLeft;
                if (green[i]) levels[valid++] = chroma[i];
            }
            if (valid < 35) return;
            Array.Sort(levels, 0, valid);
            int baseline = levels[valid / 2];
            int threshold = Math.Max(65, baseline + 20);
            int start = -1, last = -1, count = 0, peak = 0, strength = 0, bestStrength = 0;
            for (int x = left; x <= right + 27; x++)
            {
                bool marked = x <= right && green[x - SearchLeft] && chroma[x - SearchLeft] >= threshold;
                if (marked)
                {
                    if (start < 0) { start = x; count = peak = strength = 0; }
                    else if (x - last > 27)
                    {
                        ConsiderTarget(start, last, count, peak, strength, baseline, left, right,
                            ref targetLeft, ref targetRight, ref bestStrength);
                        start = x;
                        count = peak = strength = 0;
                    }
                    last = x;
                    count++;
                    int level = chroma[x - SearchLeft];
                    peak = Math.Max(peak, level);
                    strength += level - baseline;
                }
                else if (start >= 0 && x - last > 27)
                {
                    ConsiderTarget(start, last, count, peak, strength, baseline, left, right,
                        ref targetLeft, ref targetRight, ref bestStrength);
                    start = -1;
                    count = peak = strength = 0;
                }
            }
            if (start >= 0)
                ConsiderTarget(start, last, count, peak, strength, baseline, left, right,
                    ref targetLeft, ref targetRight, ref bestStrength);
        }

        private static void ConsiderTarget(int start, int end, int count, int peak, int strength,
                                           int baseline, int greenLeft, int greenRight,
                                           ref int bestLeft, ref int bestRight, ref int bestStrength)
        {
            int width = end - start + 1, zoneWidth = greenRight - greenLeft + 1;
            int maximumWidth = Math.Min(120, zoneWidth * 3 / 5);
            if (width < 15 || width > maximumWidth || count < 12 || count * 100 < width * 55 ||
                peak < baseline + 30 || Math.Abs((start + end) / 2 - (greenLeft + greenRight) / 2) > zoneWidth / 3)
                return;
            if (strength > bestStrength)
            {
                bestLeft = start;
                bestRight = end;
                bestStrength = strength;
            }
        }

        private static void ConsiderRun(int start, int last, int count,
                                        ref int bestLeft, ref int bestRight, ref int bestCount)
        {
            int width = last - start + 1;
            if (width >= 70 && width <= 370 && count * 100 >= width * 65 && count > bestCount)
            {
                bestLeft = start;
                bestRight = last;
                bestCount = count;
            }
        }

        private static int FindHook(PixelFrame frame, int left, int right)
        {
            int bestHook = -1, bestScore = 0;
            int runStart = -1, last = -1, pixels = 0, sumX = 0, top = 1000, bottom = -1;
            for (int x = left; x <= right + 3; x++)
            {
                int columnCount = 0, columnTop = 1000, columnBottom = -1;
                if (x <= right)
                {
                    for (int y = 488; y <= 521; y++)
                    {
                        int r, g, b;
                        frame.Read(x, y, out r, out g, out b);
                        if (White(r, g, b))
                        {
                            columnCount++;
                            columnTop = Math.Min(columnTop, y);
                            columnBottom = Math.Max(columnBottom, y);
                        }
                    }
                }
                if (columnCount > 0)
                {
                    if (runStart < 0) runStart = x;
                    else if (x - last > 3)
                    {
                        ConsiderHook(runStart, last, pixels, sumX, top, bottom, ref bestHook, ref bestScore);
                        runStart = x;
                        pixels = sumX = 0;
                        top = 1000;
                        bottom = -1;
                    }
                    last = x;
                    pixels += columnCount;
                    sumX += x * columnCount;
                    top = Math.Min(top, columnTop);
                    bottom = Math.Max(bottom, columnBottom);
                }
                else if (runStart >= 0 && x - last > 3)
                {
                    ConsiderHook(runStart, last, pixels, sumX, top, bottom, ref bestHook, ref bestScore);
                    runStart = -1;
                    pixels = sumX = 0;
                    top = 1000;
                    bottom = -1;
                }
            }
            if (runStart >= 0)
                ConsiderHook(runStart, last, pixels, sumX, top, bottom, ref bestHook, ref bestScore);
            return bestHook;
        }

        private static void ConsiderHook(int start, int end, int pixels, int sumX, int top, int bottom,
                                         ref int bestHook, ref int bestScore)
        {
            int width = end - start + 1, height = bottom - top + 1;
            // The sprite is a thin outline. Reject solid pale borders or
            // rectangular highlights that can otherwise outrank the hook.
            if (width < 3 || width > 36 || height < 8 || pixels < 8 || pixels * 100 > width * height * 65) return;
            int score = pixels + height * 2;
            if (score > bestScore)
            {
                bestScore = score;
                bestHook = sumX / pixels;
            }
        }

        public static bool BiteActive(PixelFrame frame)
        {
            if (frame == null) throw new ArgumentNullException("frame");
            int matchingColumns = 0;
            for (int x = 895; x <= 940; x += 3)
            {
                int green = 0, red = 0;
                for (int d = -4; d <= 4; d += 4)
                {
                    int r, g, b;
                    frame.Read(x, 400 + d, out r, out g, out b);
                    if (BrightGreen(r, g, b)) green++;
                    frame.Read(x, 680 + d, out r, out g, out b);
                    if (BrightRed(r, g, b)) red++;
                }
                if (green >= 2 && red >= 2) matchingColumns++;
            }
            return matchingColumns >= 6;
        }

        public static string Describe(PixelFrame frame)
        {
            CastInfo cast = FindCast(frame);
            bool bite = BiteActive(frame);
            string castText = cast == null ? "не найдена" :
                String.Format("зелёная зона {0}–{1}, светлый участок {2}, крючок {3}", cast.Left, cast.Right,
                    cast.HasTarget ? cast.TargetLeft + "–" + cast.TargetRight : "не найден",
                    cast.Hook < 0 ? "не найден" : cast.Hook.ToString());
            return "Заброс: " + castText + "; вываживание: " + (bite ? "найдено" : "не найдено") + ".";
        }
    }
}
