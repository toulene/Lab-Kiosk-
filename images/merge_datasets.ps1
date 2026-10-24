# Merge downloaded Roboflow YOLO exports (plus our own dataset_v2) into one train/valid/test
# YOLO dataset, renaming every source's classes to ours with class_map.csv.
#
# Each source is a folder with data.yaml and train|valid|test\images + \labels, i.e. a Roboflow
# "YOLOv8" export unzipped into datasets_raw\<name>. class_map.csv says, per source folder name,
# what each of its class names becomes:
#   <our class>   keep the box under that name
#   (not listed)  drop the box but keep the image - only for parts we don't detect (IC, Wemos...)
#   !skip         drop the whole image - for labels that hide one of our parts (a generic "Arduino")
# Roboflow's parent class / annotation group (e.g. "Electronic-Components") is just left out.
#
# Downloaded images are re-split by original photo: Roboflow names augmented copies
# <photo>_jpg.rf.<hash>.jpg, so every copy of a photo within a source lands in the same split.
# A photo already taken from one source is not added again from another (forks and aggregator
# datasets share photos). That match is by content - a 16x16 brightness fingerprint - not by name,
# since many sources reuse generic names like frame_0000.
# Sources in -KeepSplits (our own frames, already split by time block) keep their splits.
#
# Usage: .\merge_datasets.ps1 -DownloadsDir datasets_raw -Extra dataset_v2 -OutDir dataset_v3
param(
    [string]$DownloadsDir = "datasets_raw",
    [string[]]$Extra = @("dataset_v2"),
    [string[]]$KeepSplits = @("dataset_v2"),
    [string]$MapFile = "class_map.csv",
    [string]$OutDir = "dataset_v3",
    [int]$ValidPct = 10,
    [int]$TestPct = 10,
    # Downloaded images left with no boxes (only other boards/parts in them) are kept as negatives,
    # but only this share of them - otherwise Raspberry Pi / STM32 shots make up half the dataset.
    [int]$BackgroundKeepPct = 15
)

$ErrorActionPreference = "Stop"
$inv = [Globalization.CultureInfo]::InvariantCulture
$md5 = [Security.Cryptography.MD5]::Create()

function Get-Bucket([string]$s) {
    $h = $md5.ComputeHash([Text.Encoding]::UTF8.GetBytes($s.ToLower()))
    [BitConverter]::ToUInt32($h, 0) % 100
}

# Content fingerprint: shrink to 16x16 grey, one bit per pixel brighter than the mean.
# Survives re-encoding and resizing, so the same photo exported by two projects matches.
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @"
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Text;
public static class Fingerprint {
    public static string Of(string path) {
        using (var src = Image.FromFile(path))
        using (var bmp = new Bitmap(16, 16)) {
            using (var g = Graphics.FromImage(bmp)) {
                g.InterpolationMode = InterpolationMode.HighQualityBilinear;
                g.DrawImage(src, 0, 0, 16, 16);
            }
            var v = new int[256]; long sum = 0;
            for (int y = 0; y < 16; y++)
                for (int x = 0; x < 16; x++) {
                    var c = bmp.GetPixel(x, y);
                    v[y * 16 + x] = (c.R * 299 + c.G * 587 + c.B * 114) / 1000;
                    sum += v[y * 16 + x];
                }
            int mean = (int)(sum / 256);
            var sb = new StringBuilder(64);
            for (int i = 0; i < 256; i += 4) {
                int n = 0;
                for (int k = 0; k < 4; k++) if (v[i + k] > mean) n |= 1 << k;
                sb.Append(n.ToString("x"));
            }
            return sb.ToString();
        }
    }
}
"@

function Get-Fingerprint([string]$path) {
    try { [Fingerprint]::Of($path) }
    catch { [BitConverter]::ToString($md5.ComputeHash([IO.File]::ReadAllBytes($path))) }   # unreadable format: exact bytes
}

# Class names from a data.yaml, in id order: names: ['a', 'b'] or a "- a" / "0: a" block.
function Get-YoloNames([string]$yamlPath) {
    $lines = Get-Content $yamlPath
    $inline = $lines | Where-Object { $_ -match '^names:\s*\[(.*)\]' } | Select-Object -First 1
    if ($inline) {
        $body = ($inline -replace '^names:\s*\[', '') -replace '\]\s*$', ''
        $quoted = [regex]::Matches($body, "'([^']*)'|`"([^`"]*)`"")
        if ($quoted.Count) { return @($quoted | ForEach-Object { if ($_.Groups[1].Success) { $_.Groups[1].Value } else { $_.Groups[2].Value } }) }
        return @($body -split ',' | ForEach-Object { $_.Trim() })
    }
    $start = [array]::IndexOf(@($lines | ForEach-Object { $_ -match '^names:\s*$' }), $true)
    if ($start -lt 0) { throw "no names: in $yamlPath" }
    $names = @()
    foreach ($l in $lines[($start + 1)..($lines.Count - 1)]) {
        if ($l -notmatch '^\s*(-|\d+:)\s*(.+)$') { break }
        $names += $Matches[2].Trim().Trim("'", '"')
    }
    $names
}

$map = @{}
foreach ($row in Import-Csv $MapFile) {
    if ($row.dataset.StartsWith('#')) { continue }
    $map["$($row.dataset)|$($row.source_class)".ToLower()] = "$($row.target_class)".Trim()
}
$classes = @($map.Values | Where-Object { $_ -and $_ -ne '!skip' } | Sort-Object -Unique)

$sources = @()
if (Test-Path $DownloadsDir) { $sources += Get-ChildItem $DownloadsDir -Directory | ForEach-Object FullName }
$sources += $Extra | Where-Object { Test-Path $_ } | ForEach-Object { (Resolve-Path $_).Path }

if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
foreach ($s in "train", "valid", "test") {
    New-Item -ItemType Directory -Force (Join-Path $OutDir "$s\images"), (Join-Path $OutDir "$s\labels") | Out-Null
}

$stats = @{}          # "class|split" -> images, boxes
$owner = @{}          # image fingerprint -> source it was taken from
$report = @()
foreach ($src in $sources) {
    $name = Split-Path $src -Leaf
    $names = @(Get-YoloNames (Join-Path $src "data.yaml"))
    if (-not $names.Count) { throw "no class names read from $src\data.yaml" }
    $targets = @(foreach ($n in $names) { $t = $map["$name|$n".ToLower()]; if ($null -eq $t) { "" } else { $t } })
    $unmapped = @(for ($i = 0; $i -lt $names.Count; $i++) { if (-not $map.ContainsKey("$name|$($names[$i])".ToLower())) { $names[$i] } })
    $kept = 0; $skipped = 0; $dupes = 0; $bgDropped = 0
    $splitOf = @{}    # this source's photo name / fingerprint -> split, so twins share a split

    foreach ($split in "train", "valid", "test") {
        $imgDir = Join-Path $src "$split\images"
        if (-not (Test-Path $imgDir)) { continue }
        foreach ($img in Get-ChildItem $imgDir -File | Where-Object { $_.Extension -match '^\.(jpe?g|png|bmp|webp)$' }) {
            $photo = $img.BaseName -replace '_(jpe?g|png|bmp|webp)\.rf\.[0-9a-f]+$', ''
            $print = Get-Fingerprint $img.FullName
            if ($owner.ContainsKey($print) -and $owner[$print] -ne $name) { $dupes++; continue }

            $labelFile = Join-Path $src "$split\labels\$($img.BaseName).txt"
            $lines = @(); $skip = $false
            if (Test-Path $labelFile) {
                foreach ($line in Get-Content $labelFile) {
                    $p = $line.Trim() -split '\s+'
                    if ($p.Count -lt 5) { continue }
                    $t = $targets[[int]$p[0]]
                    if ($t -eq '!skip') { $skip = $true; break }
                    if (-not $t) { continue }
                    if ($p.Count -eq 5) { $box = $p[1..4] }
                    else {
                        # segmentation polygon -> bounding box
                        $v = $p[1..($p.Count - 1)] | ForEach-Object { [double]::Parse($_, $inv) }
                        $xs = for ($k = 0; $k -lt $v.Count; $k += 2) { $v[$k] }
                        $ys = for ($k = 1; $k -lt $v.Count; $k += 2) { $v[$k] }
                        $x0 = ($xs | Measure-Object -Minimum).Minimum; $x1 = ($xs | Measure-Object -Maximum).Maximum
                        $y0 = ($ys | Measure-Object -Minimum).Minimum; $y1 = ($ys | Measure-Object -Maximum).Maximum
                        $box = (($x0 + $x1) / 2), (($y0 + $y1) / 2), ($x1 - $x0), ($y1 - $y0) | ForEach-Object { $_.ToString("0.######", $inv) }
                    }
                    $lines += (@([array]::IndexOf($classes, $t)) + $box) -join ' '
                }
            }
            if ($skip) { $skipped++; continue }
            if (-not $lines.Count -and $KeepSplits -notcontains $name -and (Get-Bucket "bg|$name|$photo") -ge $BackgroundKeepPct) { $bgDropped++; continue }

            if ($KeepSplits -contains $name) { $out = $split }
            elseif ($splitOf.ContainsKey("p|$print")) { $out = $splitOf["p|$print"] }    # near-identical shot
            elseif ($splitOf.ContainsKey("n|$photo")) { $out = $splitOf["n|$photo"] }    # augmented copy
            else {
                $b = Get-Bucket "$name|$photo"
                $out = if ($b -lt $TestPct) { "test" } elseif ($b -lt $TestPct + $ValidPct) { "valid" } else { "train" }
            }
            $splitOf["p|$print"] = $out; $splitOf["n|$photo"] = $out
            $owner[$print] = $name
            Copy-Item $img.FullName (Join-Path $OutDir "$out\images\$name`_$($img.Name)")
            Set-Content -Encoding ascii (Join-Path $OutDir "$out\labels\$name`_$($img.BaseName).txt") $lines
            $kept++
            foreach ($g in $lines | Group-Object { [int]($_ -split ' ')[0] }) {
                $key = "$($classes[[int]$g.Name])|$out"
                if (-not $stats[$key]) { $stats[$key] = @(0, 0) }
                $stats[$key] = @(($stats[$key][0] + 1), ($stats[$key][1] + $g.Count))
            }
        }
    }
    $report += [pscustomobject]@{ Source = $name; Kept = $kept; Skipped = $skipped; Duplicates = $dupes; NoBoxDropped = $bgDropped; Unmapped = ($unmapped -join ', ') }
}

$yaml = @(
    "train: ../train/images",
    "val: ../valid/images",
    "test: ../test/images",
    "",
    "nc: $($classes.Count)",
    "names: [$(($classes | ForEach-Object { "'$_'" }) -join ', ')]"
)
Set-Content -Encoding ascii (Join-Path $OutDir "data.yaml") $yaml

$report | Format-Table -AutoSize -Wrap | Out-String -Width 200
"Unmapped classes above were dropped (boxes only). Add them to $MapFile if one is a part we detect."
""
"{0,-18}{1,16}{2,16}{3,16}" -f "class", "train img/box", "valid img/box", "test img/box"
foreach ($c in $classes) {
    $cells = foreach ($s in "train", "valid", "test") { $v = $stats["$c|$s"]; if ($v) { "$($v[0]) / $($v[1])" } else { "0 / 0" } }
    "{0,-18}{1,16}{2,16}{3,16}" -f $c, $cells[0], $cells[1], $cells[2]
}
