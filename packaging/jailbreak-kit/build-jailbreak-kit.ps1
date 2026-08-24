param(
    [string]$DopaminePath = "",
    [string]$SideloadlyPath = "",
    [string]$OutputDirectory = "",
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$packagingRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $packagingRoot "..\..")).Path
$manifestPath = Join-Path $packagingRoot "manifest.json"
$guidePath = Join-Path $packagingRoot "INSTALL.zh-CN.md"

if ([string]::IsNullOrWhiteSpace($DopaminePath)) {
    $DopaminePath = Join-Path ([Environment]::GetFolderPath("UserProfile")) "Downloads\Dopamine-3.0.7.ipa"
}
if ([string]::IsNullOrWhiteSpace($SideloadlyPath)) {
    $SideloadlyPath = Join-Path ([Environment]::GetFolderPath("UserProfile")) "Downloads\SideloadlySetup64-0.60.0.exe"
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $projectRoot "artifacts\jailbreak-kit"
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$components = @($manifest.components)
if ($components.Count -ne 2) {
    throw "The jailbreak kit manifest must contain exactly two components."
}

$sourcePaths = @{
    "Dopamine" = [IO.Path]::GetFullPath($DopaminePath)
    "Sideloadly" = [IO.Path]::GetFullPath($SideloadlyPath)
}

foreach ($component in $components) {
    $componentName = [string]$component.name
    $sourcePath = [string]$sourcePaths[$componentName]
    if ([string]::IsNullOrWhiteSpace($sourcePath) -or
        -not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Missing source file for $($component.name): $sourcePath"
    }
    $item = Get-Item -LiteralPath $sourcePath
    if ($item.Length -ne [long]$component.bytes) {
        throw "$($component.name) byte length mismatch: $($item.Length)"
    }
    $actualHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne ([string]$component.sha256).ToLowerInvariant()) {
        throw "$($component.name) SHA-256 mismatch: $actualHash"
    }
}

$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
[IO.Directory]::CreateDirectory($outputRoot) | Out-Null
$archiveName = "iOSMax-Jailbreak-Kit_Dopamine-3.0.7_Sideloadly-0.60.0_Windows.zip"
$archivePath = [IO.Path]::GetFullPath((Join-Path $outputRoot $archiveName))
if (-not $archivePath.StartsWith($outputRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe archive path: $archivePath"
}
if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
    if (-not $Force) {
        throw "Archive already exists; pass -Force to replace it: $archivePath"
    }
    [IO.File]::Delete($archivePath)
}

$stagingPath = [IO.Path]::GetFullPath((Join-Path $outputRoot (".staging-" + [Guid]::NewGuid().ToString("N"))))
if (-not $stagingPath.StartsWith($outputRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe staging path: $stagingPath"
}
[IO.Directory]::CreateDirectory($stagingPath) | Out-Null

try {
    foreach ($component in $components) {
        $componentName = [string]$component.name
        [IO.File]::Copy(
            [string]$sourcePaths[$componentName],
            (Join-Path $stagingPath ([string]$component.filename)),
            $false
        )
    }
    [IO.File]::Copy($manifestPath, (Join-Path $stagingPath "manifest.json"), $false)
    [IO.File]::Copy($guidePath, (Join-Path $stagingPath "INSTALL.zh-CN.md"), $false)

    [string[]]$checksumLines = @(
        $components | ForEach-Object {
            "$(([string]$_.sha256).ToLowerInvariant()) *$([string]$_.filename)"
        }
    )
    [IO.File]::WriteAllLines(
        (Join-Path $stagingPath "SHA256SUMS.txt"),
        $checksumLines,
        [Text.UTF8Encoding]::new($false)
    )

    Compress-Archive -Path (Join-Path $stagingPath "*") -DestinationPath $archivePath -CompressionLevel Optimal
}
finally {
    if (Test-Path -LiteralPath $stagingPath -PathType Container) {
        [IO.Directory]::Delete($stagingPath, $true)
    }
}

$archive = Get-Item -LiteralPath $archivePath
$archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
$checksumPath = "$archivePath.sha256"
[IO.File]::WriteAllText(
    $checksumPath,
    "$archiveHash *$archiveName`n",
    [Text.UTF8Encoding]::new($false)
)

[pscustomobject]@{
    Archive = $archive.FullName
    Bytes = $archive.Length
    SHA256 = $archiveHash
    ChecksumFile = $checksumPath
}
