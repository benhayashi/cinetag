@echo off
setlocal
cd /d "%~dp0"

echo =============================================
echo    Updating CineTag (Windows)
echo =============================================

where git >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Git is not installed or not in PATH.
    pause
    exit /b 1
)

echo Pulling latest updates from GitHub...
git pull

if exist ".venv" (
    echo Updating Python dependencies in .venv...
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
) else (
    echo Virtual environment will be created automatically on next run.bat
)

echo =============================================
echo Update successful! Run run.bat to start.
echo =============================================
pause
