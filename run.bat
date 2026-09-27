@echo off
setlocal
cd /d "%~dp0"

echo =============================================
echo    CineTag Launcher (Windows)
echo =============================================

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in PATH.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo Creating virtual environment in .venv...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

python app.py %*
pause
