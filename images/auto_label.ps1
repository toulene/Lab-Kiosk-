# Auto-label frames shot on a plain white background.
# Each frames\<class>\ folder holds one component type, so the class comes from the folder name;
# boxes come from finding pixels darker or more colourful than the local background.
# Writes YOLO .txt labels next to each image, plus frames\data.yaml and frames\classes.txt,
# and box-overlay previews in label_previews\ for checking (not for upload).
#
# Usage: .\auto_label.ps1                      (defaults)
#        .\auto_label.ps1 -Threshold 18 -Dilate 3
param(
    [string]$FramesDir  = "frames",
    [string]$PreviewDir = "label_previews",
    [int]$Threshold     = 22,   # how much darker than background a pixel must be (0-255)
    [int]$SatThreshold  = 35,   # how much more colourful than background (catches orange caps)
    [int]$MinArea       = 30,   # smallest blob kept, in pixels at 480x270
    [int]$Dilate        = 2,    # px grown before grouping, joins thin legs to bodies
    # Per-class darkness threshold. A high value boxes only the dark body and ignores
    # faint silver leads - used for diodes, whose long leads cross each other.
    [hashtable]$ClassThreshold = @{ diode = 70 },
    # Per-class minimum share of the box covered by the part. Diode bodies fill their box;
    # stray lead tips are thin diagonal lines in a mostly empty box.
    [hashtable]$ClassMinFill = @{ diode = 0.4 }
)

Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

public static class AutoLabeler {
    const int W = 480, H = 270, R = 40;

    static int Median(int[] v) {
        int[] hist = new int[256];
        foreach (int x in v) hist[x]++;
        int half = v.Length / 2, acc = 0;
        for (int i = 0; i < 256; i++) { acc += hist[i]; if (acc > half) return i; }
        return 255;
    }

    // Returns boxes as {x0, y0, x1, y1} in 480x270 pixel coords.
    public static List<int[]> Detect(string path, int thr, int satThr, int minArea, int dil, double minFill, string previewPath) {
        Bitmap small = new Bitmap(W, H, PixelFormat.Format24bppRgb);
        using (Bitmap src = new Bitmap(path))
        using (Graphics g = Graphics.FromImage(small)) {
            g.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.HighQualityBilinear;
            // TileFlipXY stops GDI+ blending a dark line into the image border
            using (ImageAttributes ia = new ImageAttributes()) {
                ia.SetWrapMode(System.Drawing.Drawing2D.WrapMode.TileFlipXY);
                g.DrawImage(src, new Rectangle(0, 0, W, H), 0, 0, src.Width, src.Height, GraphicsUnit.Pixel, ia);
            }
        }
        BitmapData bd = small.LockBits(new Rectangle(0, 0, W, H), ImageLockMode.ReadOnly, PixelFormat.Format24bppRgb);
        int stride = bd.Stride;
        byte[] px = new byte[stride * H];
        Marshal.Copy(bd.Scan0, px, 0, px.Length);
        small.UnlockBits(bd);

        int n = W * H;
        int[] gray = new int[n], sat = new int[n];
        for (int y = 0; y < H; y++)
            for (int x = 0; x < W; x++) {
                int o = y * stride + x * 3;
                int b = px[o], gg = px[o + 1], r = px[o + 2];
                gray[y * W + x] = (299 * r + 587 * gg + 114 * b) / 1000;
                sat[y * W + x] = Math.Max(r, Math.Max(gg, b)) - Math.Min(r, Math.Min(gg, b));
            }
        int medGray = Median(gray), medSat = Median(sat);

        // Local background = mean of nearby pixels that are clearly not part of an object.
        long[] sumI = new long[(W + 1) * (H + 1)], cntI = new long[(W + 1) * (H + 1)];
        for (int y = 0; y < H; y++)
            for (int x = 0; x < W; x++) {
                int i = y * W + x;
                bool obj = gray[i] < medGray - 25 || sat[i] - medSat > satThr;
                int k = (y + 1) * (W + 1) + (x + 1);
                sumI[k] = (obj ? 0 : gray[i]) + sumI[k - 1] + sumI[k - W - 1] - sumI[k - W - 2];
                cntI[k] = (obj ? 0 : 1) + cntI[k - 1] + cntI[k - W - 1] - cntI[k - W - 2];
            }

        bool[] mask = new bool[n];
        int[] bgArr = new int[n];
        for (int y = 0; y < H; y++)
            for (int x = 0; x < W; x++) {
                int x0 = Math.Max(0, x - R), x1 = Math.Min(W, x + R + 1);
                int y0 = Math.Max(0, y - R), y1 = Math.Min(H, y + R + 1);
                int a = y0 * (W + 1) + x0, b = y0 * (W + 1) + x1, c = y1 * (W + 1) + x0, d = y1 * (W + 1) + x1;
                long cnt = cntI[d] - cntI[b] - cntI[c] + cntI[a];
                int bg = cnt > 0 ? (int)((sumI[d] - sumI[b] - sumI[c] + sumI[a]) / cnt) : medGray;
                int i = y * W + x;
                bgArr[i] = bg;
                mask[i] = bg - gray[i] > thr || sat[i] - medSat > satThr;
            }

        bool[] grown = new bool[n];
        for (int y = 0; y < H; y++)
            for (int x = 0; x < W; x++) {
                if (!mask[y * W + x]) continue;
                for (int yy = Math.Max(0, y - dil); yy <= Math.Min(H - 1, y + dil); yy++)
                    for (int xx = Math.Max(0, x - dil); xx <= Math.Min(W - 1, x + dil); xx++)
                        grown[yy * W + xx] = true;
            }

        List<int[]> boxes = new List<int[]>();
        bool[] seen = new bool[n];
        Stack<int> st = new Stack<int>();
        for (int s = 0; s < n; s++) {
            if (!grown[s] || seen[s]) continue;
            int bx0 = W, by0 = H, bx1 = -1, by1 = -1, area = 0, strong = 0;
            seen[s] = true; st.Push(s);
            while (st.Count > 0) {
                int i = st.Pop(), x = i % W, y = i / W;
                if (mask[i]) {
                    area++;
                    if (bgArr[i] - gray[i] > 60 || sat[i] - medSat > satThr) strong++;
                    if (x < bx0) bx0 = x; if (x > bx1) bx1 = x;
                    if (y < by0) by0 = y; if (y > by1) by1 = y;
                }
                if (x > 0 && grown[i - 1] && !seen[i - 1]) { seen[i - 1] = true; st.Push(i - 1); }
                if (x < W - 1 && grown[i + 1] && !seen[i + 1]) { seen[i + 1] = true; st.Push(i + 1); }
                if (y > 0 && grown[i - W] && !seen[i - W]) { seen[i - W] = true; st.Push(i - W); }
                if (y < H - 1 && grown[i + W] && !seen[i + W]) { seen[i + W] = true; st.Push(i + W); }
            }
            // Needs some body pixels (very dark or coloured): drops lone leads and shadows
            int boxArea = (bx1 - bx0 + 1) * (by1 - by0 + 1);
            double fill = (double)area / boxArea;
            // Tiny boxes on the frame edge are lead stubs of parts that are mostly out of view
            bool edgeSliver = (bx0 <= 2 || by0 <= 2 || bx1 >= W - 3 || by1 >= H - 3) && boxArea < 600;
            if (area >= minArea && strong >= 8 && fill >= minFill && !edgeSliver) boxes.Add(new int[] { bx0, by0, bx1 + 1, by1 + 1 });
        }

        if (previewPath != null) {
            using (Graphics g = Graphics.FromImage(small))
            using (Pen pen = new Pen(Color.Red, 2))
                foreach (int[] bb in boxes) g.DrawRectangle(pen, bb[0], bb[1], bb[2] - bb[0], bb[3] - bb[1]);
            small.Save(previewPath, ImageFormat.Jpeg);
        }
        small.Dispose();
        return boxes;
    }
}
"@

$classes = Get-ChildItem $FramesDir -Directory | Sort-Object Name | ForEach-Object Name
New-Item -ItemType Directory -Force $PreviewDir | Out-Null
$inv = [Globalization.CultureInfo]::InvariantCulture

for ($c = 0; $c -lt $classes.Count; $c++) {
    $cls = $classes[$c]
    $imgs = Get-ChildItem (Join-Path $FramesDir $cls) -Filter *.jpg
    $counts = @{}
    $thr = if ($ClassThreshold.ContainsKey($cls)) { $ClassThreshold[$cls] } else { $Threshold }
    $fill = if ($ClassMinFill.ContainsKey($cls)) { $ClassMinFill[$cls] } else { 0.0 }
    foreach ($img in $imgs) {
        $preview = Join-Path (Resolve-Path $PreviewDir) $img.Name
        $boxes = [AutoLabeler]::Detect($img.FullName, $thr, $SatThreshold, $MinArea, $Dilate, $fill, $preview)
        $lines = foreach ($b in $boxes) {
            $cx = ($b[0] + $b[2]) / 2 / 480; $cy = ($b[1] + $b[3]) / 2 / 270
            $w = ($b[2] - $b[0]) / 480;      $h = ($b[3] - $b[1]) / 270
            "{0} {1} {2} {3} {4}" -f $c, $cx.ToString("0.000000", $inv), $cy.ToString("0.000000", $inv), $w.ToString("0.000000", $inv), $h.ToString("0.000000", $inv)
        }
        Set-Content -Encoding ascii ([IO.Path]::ChangeExtension($img.FullName, ".txt")) $lines
        $counts[$boxes.Count] = 1 + $counts[$boxes.Count]
    }
    $summary = ($counts.Keys | Sort-Object | ForEach-Object { "$($_) boxes x$($counts[$_])" }) -join ", "
    "{0,-12} {1}" -f $cls, $summary
}

Set-Content -Encoding ascii (Join-Path $FramesDir "classes.txt") $classes
$yaml = @("nc: $($classes.Count)", "names: [$(($classes | ForEach-Object { "'$_'" }) -join ', ')]")
Set-Content -Encoding ascii (Join-Path $FramesDir "data.yaml") $yaml
