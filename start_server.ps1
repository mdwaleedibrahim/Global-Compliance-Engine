# GCE Control Center GUI Server One-Touch Launcher (PowerShell)

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

# Add ~/.local/bin to PATH if present
$LocalBin = Join-Path $env:USERPROFILE ".local\bin"
if (Test-Path $LocalBin) {
    $env:PATH = "$LocalBin;$env:PATH"
}

$PythonCmd = $null

if (Test-Path "$LocalBin\uv.exe") {
    Write-Host "[INFO] Found uv package manager." -ForegroundColor Green
    & "$LocalBin\uv.exe" pip install -r gui\requirements.txt | Out-Null
    $PythonCmd = { & "$LocalBin\uv.exe" run python gui/server.py }
} elseif (Test-Path "$LocalBin\python3.14.exe") {
    $PythonCmd = { & "$LocalBin\python3.14.exe" gui/server.py }
} elseif (Test-Path "$ProjectRoot\.venv\Scripts\python.exe") {
    $PythonCmd = { & "$ProjectRoot\.venv\Scripts\python.exe" gui/server.py }
} else {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $PythonCmd = { py gui/server.py }
    } else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($python) {
            $PythonCmd = { python gui/server.py }
        }
    }
}

if (-not $PythonCmd) {
    Write-Host "[ERROR] Could not locate Python environment or uv." -ForegroundColor Red
    exit 1
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Starting GCE Control Center GUI Server" -ForegroundColor Cyan
Write-Host "  Dashboard: http://localhost:5050" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

& $PythonCmd
