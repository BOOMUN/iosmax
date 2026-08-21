param(
    [switch]$Dev,
    [int]$Port = 8010
)

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "未找到虚拟环境：$python"
}

if ($Dev) {
    Write-Host "后端：http://127.0.0.1:$Port"
    Write-Host "前端：http://127.0.0.1:5173"
    Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "$Port" -WorkingDirectory (Join-Path $projectRoot "backend") -WindowStyle Hidden
    npm.cmd --prefix (Join-Path $projectRoot "frontend") run dev
    exit $LASTEXITCODE
}

& npm.cmd --prefix (Join-Path $projectRoot "frontend") run build
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "iOSMax Control：http://127.0.0.1:$Port"
Set-Location (Join-Path $projectRoot "backend")
& $python -m uvicorn app.main:app --host 127.0.0.1 --port $Port
