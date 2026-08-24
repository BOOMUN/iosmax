param(
    [string]$ConfigPath = "",
    [string]$IProxyPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $projectRoot "data\usb_tunnels.json"
}
if ([string]::IsNullOrWhiteSpace($IProxyPath)) {
    $IProxyPath = Join-Path $projectRoot ".tmp\libimobiledevice-win-x64\iproxy.exe"
}
$deviceIdTool = Join-Path (Split-Path -Parent $IProxyPath) "idevice_id.exe"

if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    return
}
if (-not (Test-Path -LiteralPath $IProxyPath -PathType Leaf)) {
    throw "iproxy was not found: $IProxyPath"
}
if (-not (Test-Path -LiteralPath $deviceIdTool -PathType Leaf)) {
    throw "idevice_id was not found: $deviceIdTool"
}

$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$tunnels = @($config.tunnels)
$connectedIds = @(
    & $deviceIdTool -l 2>$null |
        ForEach-Object { ([string]$_).Trim() } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
)
$seenPorts = @{}

foreach ($tunnel in $tunnels) {
    $name = [string]$tunnel.name
    $deviceUdid = [string]$tunnel.device_udid
    $jailbreakType = [string]$tunnel.jailbreak_type
    if ([string]::IsNullOrWhiteSpace($name) -or
        [string]::IsNullOrWhiteSpace($deviceUdid)) {
        throw "Every USB tunnel needs a name and device_udid."
    }
    if ($jailbreakType -notin @("rootless", "roothide")) {
        throw "USB tunnel '$name' has an invalid jailbreak_type."
    }

    foreach ($forward in @($tunnel.forwards)) {
        $localPort = [int]$forward.local_port
        $devicePort = [int]$forward.device_port
        if ($localPort -lt 1 -or $localPort -gt 65535 -or
            $devicePort -lt 1 -or $devicePort -gt 65535) {
            throw "USB tunnel '$name' has an invalid port mapping."
        }
        if ($seenPorts.ContainsKey($localPort)) {
            throw "USB local port $localPort is duplicated by '$name' and '$($seenPorts[$localPort])'."
        }
        $seenPorts[$localPort] = $name
    }

    if ($connectedIds -notcontains $deviceUdid) {
        [pscustomobject]@{
            Device = $name
            Status = "offline"
            LocalPort = $null
            DevicePort = $null
            ProcessId = $null
        }
        continue
    }

    foreach ($forward in @($tunnel.forwards)) {
        $localPort = [int]$forward.local_port
        $devicePort = [int]$forward.device_port
        $listener = Get-NetTCPConnection -LocalPort $localPort -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1

        if ($listener) {
            $owner = Get-Process -Id $listener.OwningProcess -ErrorAction Stop
            $processRecord = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
            $commandLine = [string]$processRecord.CommandLine
            $localPattern = "(?<!\d)$([regex]::Escape([string]$localPort))(?!\d)"
            $devicePattern = "(?<!\d)$([regex]::Escape([string]$devicePort))(?!\d)"
            $matchesMapping = $owner.ProcessName -eq "iproxy" -and
                $commandLine.Contains($deviceUdid) -and
                $commandLine -match $localPattern -and
                $commandLine -match $devicePattern
            if (-not $matchesMapping) {
                throw "USB local port $localPort is already owned by a different process or mapping."
            }
            [pscustomobject]@{
                Device = $name
                Status = "existing"
                LocalPort = $localPort
                DevicePort = $devicePort
                ProcessId = $listener.OwningProcess
            }
            continue
        }

        $process = Start-Process -FilePath $IProxyPath -ArgumentList @(
            "-u", $deviceUdid, [string]$localPort, [string]$devicePort
        ) -WindowStyle Hidden -PassThru
        $deadline = (Get-Date).AddSeconds(5)
        do {
            Start-Sleep -Milliseconds 200
            $process.Refresh()
            if ($process.HasExited) {
                throw "iproxy exited while starting '$name' on local port $localPort."
            }
            $listener = Get-NetTCPConnection -LocalPort $localPort -State Listen -ErrorAction SilentlyContinue |
                Where-Object { $_.OwningProcess -eq $process.Id } |
                Select-Object -First 1
        } while (-not $listener -and (Get-Date) -lt $deadline)

        if (-not $listener) {
            throw "iproxy did not listen on local port $localPort for '$name'."
        }
        [pscustomobject]@{
            Device = $name
            Status = "started"
            LocalPort = $localPort
            DevicePort = $devicePort
            ProcessId = $process.Id
        }
    }
}
