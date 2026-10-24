# Build a train/valid/test YOLO dataset from auto-labelled frame folders, split by time
# blocks within each clip instead of random frames, so near-identical neighbouring frames
# don't end up on both sides of the split.
#
# Each clip is cut into 10 consecutive blocks (~1 s each at 10 fps). Blocks 2 and 7 go to
# valid, block 5 to test, the rest to train. Frames next to a block boundary between
# different splits are dropped as a buffer.
#
# Usage: .\make_dataset.ps1 -FramesDirs frames, frames_batch2 -OutDir dataset_v2
param(
    [string[]]$FramesDirs = @("frames", "frames_batch2"),
    [string]$OutDir = "dataset_v2",
    [int]$Blocks = 10,
    [int[]]$ValidBlocks = @(2, 7),
    [int[]]$TestBlocks = @(5),
    [int]$Buffer = 2            # frames dropped on each side of a train/valid/test boundary
)

# One class list across all folders, so labels from different batches line up.
$sources = foreach ($dir in $FramesDirs) {
    $local = Get-Content (Join-Path $dir "classes.txt")
    foreach ($cls in (Get-ChildItem $dir -Directory)) {
        [pscustomobject]@{ Dir = $cls.FullName; Class = $cls.Name; LocalId = [array]::IndexOf($local, $cls.Name) }
    }
}
$classes = $sources.Class | Sort-Object -Unique
if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
foreach ($s in "train", "valid", "test") {
    New-Item -ItemType Directory -Force (Join-Path $OutDir "$s\images"), (Join-Path $OutDir "$s\labels") | Out-Null
}

$stats = @{}
foreach ($src in $sources) {
    $newId = [array]::IndexOf($classes, $src.Class)
    $clips = Get-ChildItem $src.Dir -Filter *.jpg | Group-Object { $_.BaseName -replace '_\d{4}$', '' }
    foreach ($clip in $clips) {
        $frames = $clip.Group | Sort-Object Name
        $n = $frames.Count
        $role = for ($i = 0; $i -lt $n; $i++) {
            $b = [math]::Floor($i * $Blocks / $n)
            if ($ValidBlocks -contains $b) { "valid" } elseif ($TestBlocks -contains $b) { "test" } else { "train" }
        }
        for ($i = 0; $i -lt $n; $i++) {
            $lo = [math]::Max(0, $i - $Buffer); $hi = [math]::Min($n - 1, $i + $Buffer)
            if (@($role[$lo..$hi] | Select-Object -Unique).Count -gt 1) { continue }   # near a boundary
            $split = $role[$i]
            $img = $frames[$i]
            Copy-Item $img.FullName (Join-Path $OutDir "$split\images\$($img.Name)")
            $lines = @(Get-Content ([IO.Path]::ChangeExtension($img.FullName, ".txt")) |
                Where-Object { $_.Trim() } |
                ForEach-Object { $p = $_ -split ' '; if ([int]$p[0] -ne $src.LocalId) { throw "unexpected class in $($img.Name)" }; (@($newId) + $p[1..4]) -join ' ' })
            Set-Content -Encoding ascii (Join-Path $OutDir "$split\labels\$($img.BaseName).txt") $lines
            $key = "$($src.Class)|$split"
            if (-not $stats[$key]) { $stats[$key] = @(0, 0) }
            $stats[$key] = @(($stats[$key][0] + 1), ($stats[$key][1] + $lines.Count))
        }
    }
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

"{0,-18}{1,16}{2,16}{3,16}" -f "class", "train img/box", "valid img/box", "test img/box"
foreach ($c in $classes) {
    $cells = foreach ($s in "train", "valid", "test") { $v = $stats["$c|$s"]; if ($v) { "$($v[0]) / $($v[1])" } else { "0 / 0" } }
    "{0,-18}{1,16}{2,16}{3,16}" -f $c, $cells[0], $cells[1], $cells[2]
}
