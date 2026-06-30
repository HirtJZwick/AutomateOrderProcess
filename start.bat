@echo off
cd /d "%~dp0"

REM ── Check setup has been run ──────────────────────────────────────────────
if not exist "venv\Scripts\python.exe" (
    echo.
    echo  Setup has not been run yet.
    echo  Please double-click install.bat first, then try again.
    echo.
    pause
    exit /b 1
)

echo Starting Order Tracker...

REM ── Start the server in a new window ─────────────────────────────────────
start "Order Tracker Server" cmd /k "venv\Scripts\python.exe -m uvicorn webapp.backend.app:app --host 127.0.0.1 --port 8000"

REM ── Wait until the server responds ───────────────────────────────────────
echo Waiting for server to start...
:wait_for_server
timeout /t 1 /nobreak >nul
powershell -Command "try { Invoke-WebRequest -Uri http://localhost:8000 -UseBasicParsing -TimeoutSec 1 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 goto wait_for_server

REM ── Open the browser ─────────────────────────────────────────────────────
echo Server is ready. Opening browser...
start "" http://localhost:8000
