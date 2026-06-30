@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo =============================================
echo  Order Tracker - First-Time Setup
echo =============================================
echo.

REM ── 1. Locate Python ──────────────────────────────────────────────────────
set "PYTHON_EXE="

REM Check for python in PATH first
where python >nul 2>&1
if %errorlevel% == 0 (
    for /f "delims=" %%i in ('where python') do (
        if not defined PYTHON_EXE set "PYTHON_EXE=%%i"
    )
    echo Found Python: %PYTHON_EXE%
    goto :have_python
)

REM Check common install locations
for %%P in (
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python310\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
) do (
    if exist %%P (
        set "PYTHON_EXE=%%~P"
        echo Found Python: !PYTHON_EXE!
        goto :have_python
    )
)

REM ── 2. Python not found – download and install silently ───────────────────
echo Python not found. Downloading Python 3.12 installer...
echo (This may take a minute depending on your internet connection.)
echo.

set "INSTALLER=%TEMP%\python312_installer.exe"
set "PYTHON_URL=https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe"

REM Use PowerShell to download
powershell -Command "Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%INSTALLER%' -UseBasicParsing"
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Could not download Python. Check your internet connection and try again.
    pause
    exit /b 1
)

echo Installing Python 3.12 for current user (no admin required)...
"%INSTALLER%" /quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Python installation failed. Please install Python 3.12 manually from:
    echo   https://www.python.org/downloads/
    echo Then run this script again.
    del "%INSTALLER%" >nul 2>&1
    pause
    exit /b 1
)
del "%INSTALLER%" >nul 2>&1

REM Re-locate the newly installed Python
for %%P in (
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python310\python.exe"
) do (
    if exist %%P (
        set "PYTHON_EXE=%%~P"
        echo Python installed: !PYTHON_EXE!
        goto :have_python
    )
)

echo.
echo ERROR: Could not find Python after installation. Please restart this script.
pause
exit /b 1

:have_python
echo.

REM ── 3. Create local virtual environment ──────────────────────────────────
if exist "venv\Scripts\python.exe" (
    echo Virtual environment already exists. Skipping creation.
) else (
    echo Creating virtual environment...
    "%PYTHON_EXE%" -m venv venv
    if %errorlevel% neq 0 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo Virtual environment created.
)
echo.

REM ── 4. Install Python dependencies ───────────────────────────────────────
echo Installing required packages (this takes about 30-60 seconds)...
venv\Scripts\python.exe -m pip install --upgrade pip --quiet
venv\Scripts\python.exe -m pip install fastapi "uvicorn[standard]" python-docx pdfplumber openpyxl pydantic openai --quiet
if %errorlevel% neq 0 (
    echo ERROR: Package installation failed.
    pause
    exit /b 1
)
echo Packages installed.
echo.

REM ── 5. Done ───────────────────────────────────────────────────────────────
echo =============================================
echo  Setup complete!
echo =============================================
echo.
echo  To start the Order Tracker, double-click:
echo    start.bat
echo.
pause
