param(
    [string]$ShortcutName = "iOSMax Web"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ShortcutName) -or
    $ShortcutName.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0) {
    throw "ShortcutName is empty or contains invalid filename characters."
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $projectRoot "start-web.ps1"
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "The iOSMax Web launcher was not found: $launcher"
}

$desktop = [Environment]::GetFolderPath("Desktop")
if ([string]::IsNullOrWhiteSpace($desktop)) {
    throw "The Windows desktop directory could not be resolved."
}

$shortcutPath = Join-Path $desktop "$ShortcutName.lnk"
$powershellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$edgeCandidates = @(
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
)
$iconPath = $edgeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $iconPath) {
    $iconPath = Join-Path $env:SystemRoot "System32\shell32.dll"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $powershellPath
$shortcut.Arguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $launcher + '"'
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = "Start iOSMax Web control console"
$shortcut.IconLocation = "$iconPath,0"
$shortcut.WindowStyle = 7
$shortcut.Save()

if (-not (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) {
    throw "The desktop shortcut could not be created."
}

Write-Output "Shortcut created: $shortcutPath"
