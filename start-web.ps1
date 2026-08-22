param(
    [int]$Port = 8010,
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendRoot = Join-Path $projectRoot "backend"
$python = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$healthUrl = "http://127.0.0.1:$Port/api/health"
$webUrl = "http://127.0.0.1:$Port/"
$launcherMutex = [System.Threading.Mutex]::new($false, "Local\iOSMaxWebLauncher-$Port")
$hasMutex = $false

function Test-WebHealth {
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
        return $response.status -eq "ok"
    }
    catch {
        return $false
    }
}

function Wait-WebHealth([int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (Test-WebHealth) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Open-WebConsole {
    if ($NoBrowser) {
        return
    }
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $webUrl
    $startInfo.UseShellExecute = $true
    [void][System.Diagnostics.Process]::Start($startInfo)
}

function Show-LauncherError([string]$Message) {
    try {
        $shell = New-Object -ComObject WScript.Shell
        [void]$shell.Popup($Message, 15, "iOSMax Web startup failed", 16)
    }
    catch {
        # The shortcut runs hidden, so there may be no console to report to.
    }
}

try {
    $hasMutex = $launcherMutex.WaitOne([TimeSpan]::FromSeconds(70))
    if (-not $hasMutex) {
        throw "Another iOSMax startup task did not finish in time."
    }

    if (-not (Test-WebHealth)) {
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($listener) {
            if (-not (Wait-WebHealth 20)) {
                throw "Port $Port is occupied, but the iOSMax health check failed."
            }
        }
        else {
            if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
                $python = Join-Path $projectRoot ".venv\Scripts\python.exe"
            }
            if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
                throw "The Python virtual environment was not found."
            }

            $arguments = @(
                "-m", "uvicorn", "app.main:app",
                "--host", "127.0.0.1",
                "--port", "$Port"
            )
            $server = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru

            if (-not (Wait-WebHealth 60)) {
                if ($server.HasExited) {
                    throw "The iOSMax server exited with code $($server.ExitCode)."
                }
                throw "The iOSMax server did not pass its health check within 60 seconds."
            }
        }
    }

    Open-WebConsole
}
catch {
    Show-LauncherError $_.Exception.Message
    exit 1
}
finally {
    if ($hasMutex) {
        $launcherMutex.ReleaseMutex()
    }
    $launcherMutex.Dispose()
}
