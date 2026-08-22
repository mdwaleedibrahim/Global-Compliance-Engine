@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo   Starting GCE Control Center GUI Server
echo ============================================================

:: Resolve project root directory (directory containing this script)
set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

:: Add user local bin to PATH if present
if exist "%USERPROFILE%\.local\bin" (
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

:: Find python / uv executable
set "PYTHON_CMD="
if exist "%USERPROFILE%\.local\bin\uv.exe" (
    echo [INFO] Found uv package manager.
    set "PYTHON_CMD=%USERPROFILE%\.local\bin\uv.exe run python"
    echo [INFO] Verifying dependencies...
    "%USERPROFILE%\.local\bin\uv.exe" pip install -r gui\requirements.txt >nul 2>&1
) else if exist "%USERPROFILE%\.local\bin\python3.14.exe" (
    set "PYTHON_CMD=%USERPROFILE%\.local\bin\python3.14.exe"
) else if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
    set "PYTHON_CMD=%PROJECT_ROOT%\.venv\Scripts\python.exe"
) else (
    where py >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD=py"
    ) else (
        where python >nul 2>&1
        if !errorlevel! equ 0 (
            set "PYTHON_CMD=python"
        )
    )
)

if "%PYTHON_CMD%"=="" (
    echo [ERROR] Python environment not found! Please ensure Python or uv is installed.
    pause
    exit /b 1
)

echo [INFO] Using Python command: %PYTHON_CMD%
echo [INFO] Server starting at http://localhost:5050
echo ============================================================

%PYTHON_CMD% gui\server.py

pause
