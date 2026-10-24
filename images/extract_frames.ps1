# Extract frames from component videos into <OutDir>\<class>\<clip>_0001.jpg
# The class folder defaults to the clip name; pass -Class when several clips show the same part.
# Usage: .\extract_frames.ps1 -Videos C:\vids\diode.mp4 -Fps 10
#        .\extract_frames.ps1 -Videos C:\vids\mega1.h264, C:\vids\mega2.h264 -Class arduino_mega -OutDir frames_batch2
param(
    [Parameter(Mandatory)][string[]]$Videos,
    [double]$Fps = 10,          # frames kept per second of video (source is 30 fps)
    [string]$OutDir = "frames",
    [string]$Class = "",        # class folder; empty = use each clip's name
    [int]$SourceFps = 30        # only used for raw .h264, which has no timing of its own
)

foreach ($v in $Videos) {
    $name = [IO.Path]::GetFileNameWithoutExtension($v)
    $dest = Join-Path $OutDir $(if ($Class) { $Class } else { $name })
    New-Item -ItemType Directory -Force $dest | Out-Null
    $inArgs = if ([IO.Path]::GetExtension($v) -eq ".h264") { @("-framerate", $SourceFps, "-i", $v) } else { @("-i", $v) }
    ffmpeg -v error -y @inArgs -vf "fps=$Fps" -q:v 2 (Join-Path $dest "${name}_%04d.jpg")
    "{0,-20} {1} frames -> {2}" -f $name, (Get-ChildItem $dest -Filter "${name}_*.jpg").Count, $dest
}
