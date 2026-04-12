@echo off
setlocal enabledelayedexpansion

echo.
echo  ====================================
echo   demon-transcribe setup
echo  ====================================
echo.

:: Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python not found. Installing via winget...
    winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    if %errorlevel% neq 0 (
        echo [X] Failed to install Python. Please install Python 3.11+ manually from python.org
        pause
        exit /b 1
    )
    echo [i] Python installed. You may need to restart your terminal.
    echo [i] Close this window, open a new terminal, and run setup.bat again.
    pause
    exit /b 0
)

:: Verify Python version
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [+] Python %PYVER% found

:: Create venv if needed
if not exist "venv" (
    echo [+] Creating virtual environment...
    python -m venv venv
)

:: Activate venv and install deps
echo [+] Installing dependencies...
call venv\Scripts\activate.bat
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [X] Failed to install dependencies
    pause
    exit /b 1
)

:: Download default model
echo [+] Downloading default model (small.en, ~483MB)...
python -c "from faster_whisper import WhisperModel; m = WhisperModel('small.en', device='cpu', compute_type='int8'); print('[+] Model downloaded and verified')"
if %errorlevel% neq 0 (
    echo [!] Model download failed - it will download on first launch instead
)

:: Create desktop + startup shortcuts
echo [+] Creating shortcuts...
set "SCRIPT_DIR=%~dp0"
set "PYTHONW=%SCRIPT_DIR%venv\Scripts\pythonw.exe"
set "LAUNCH=%SCRIPT_DIR%launch.pyw"
set "ICON=%SCRIPT_DIR%demon_transcribe.ico"

:: Find desktop and startup paths (handles OneDrive)
for /f "tokens=*" %%D in ('powershell -Command "[Environment]::GetFolderPath('Desktop')"') do set "DESKTOP=%%D"
for /f "tokens=*" %%S in ('powershell -Command "[Environment]::GetFolderPath('Startup')"') do set "STARTUP=%%S"

:: Create both shortcuts
powershell -Command "$ws = New-Object -ComObject WScript.Shell; foreach ($path in @('%DESKTOP%\Demon Transcribe.lnk','%STARTUP%\Demon Transcribe.lnk')) { $sc = $ws.CreateShortcut($path); $sc.TargetPath = '%PYTHONW%'; $sc.Arguments = '%LAUNCH%'; $sc.WorkingDirectory = '%SCRIPT_DIR%'; $sc.IconLocation = '%ICON%'; $sc.Description = 'Demon Transcribe - Local voice transcription'; $sc.Save() }"

if %errorlevel% equ 0 (
    echo [+] Desktop shortcut created
    echo [+] Startup shortcut created (launches on login)
) else (
    echo [!] Could not create shortcuts - you can run: venv\Scripts\pythonw.exe launch.pyw
)

echo.
echo  ====================================
echo   Setup complete!
echo  ====================================
echo.
echo  To start: double-click "Demon Transcribe" on your desktop
echo  Or run:   venv\Scripts\pythonw.exe launch.pyw
echo.
echo  Usage:
echo    Hold Ctrl+Shift+Space to dictate
echo    Double-tap Ctrl+Shift+Space for extended mode
echo    Click taskbar icon to open dashboard
echo.
pause
