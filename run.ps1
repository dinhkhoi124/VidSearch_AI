# Chạy đồng thời backend (FastAPI/uvicorn) và frontend (Vite) trên Windows.
# Bản PowerShell của run.sh - Ctrl+C một lần sẽ dừng cả hai.
#
#   .\run.ps1
#   .\run.ps1 -BackendPort 8001 -CondaEnv dynamic
#
# Nếu máy chặn script:
#   powershell -ExecutionPolicy Bypass -File .\run.ps1

param(
    [string]$BackendHost = "0.0.0.0",
    [int]$BackendPort = 8000,
    [string]$CondaEnv = "aic"   # conda env chứa uvicorn/torch/faiss/transformers
)

$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"

$procs = @()

function Stop-Tree($proc, $label) {
    if ($null -eq $proc) { return }
    try { if ($proc.HasExited) { return } } catch { return }
    # uvicorn --reload và vite đều spawn tiến trình con; /T kill cả cây,
    # nếu không sẽ còn process mồ côi giữ port.
    Write-Host "[run] stopping $label (pid $($proc.Id))..."
    try { taskkill /PID $proc.Id /T /F 2>$null | Out-Null } catch { }
}

try {
    # --- Backend ---
    Write-Host "[run] backend  -> http://$($BackendHost):$BackendPort (conda env: $CondaEnv)"
    if (Get-Command conda -ErrorAction SilentlyContinue) {
        $beFile = "conda"
        $beArgs = @(
            "run", "--no-capture-output", "-n", $CondaEnv,
            "uvicorn", "main:app",
            "--host", $BackendHost, "--port", $BackendPort, "--reload"
        )
    } else {
        # fallback: uvicorn trên PATH
        $beFile = "uvicorn"
        $beArgs = @(
            "main:app",
            "--host", $BackendHost, "--port", $BackendPort, "--reload"
        )
    }
    # cwd bắt buộc là backend\ - "main:app" là đường dẫn module tương đối
    $be = Start-Process -FilePath $beFile -ArgumentList $beArgs `
        -WorkingDirectory $BackendDir -NoNewWindow -PassThru
    $procs += , @($be, "backend")

    # --- Frontend ---
    Write-Host "[run] frontend -> Vite (xem URL bên dưới)"
    if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
        Write-Host "[run] node_modules chưa có, chạy npm install..."
        Push-Location $FrontendDir
        try { & npm.cmd install } finally { Pop-Location }
    }
    $fe = Start-Process -FilePath "npm.cmd" -ArgumentList @("run", "dev") `
        -WorkingDirectory $FrontendDir -NoNewWindow -PassThru
    $procs += , @($fe, "frontend")

    Write-Host "[run] đang chạy. Nhấn Ctrl+C để dừng cả hai."
    Wait-Process -Id @($be.Id, $fe.Id)
}
finally {
    Write-Host ""
    Write-Host "[run] stopping..."
    foreach ($entry in $procs) { Stop-Tree $entry[0] $entry[1] }
    Write-Host "[run] stopped."
}
