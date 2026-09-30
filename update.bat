@echo off
setlocal
cd /d "%~dp0"

echo =============================================
echo    Updating CineTag (Windows)
echo =============================================

where git >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Git is not installed or not in PATH.
    echo Please install Git for Windows from https://git-scm.com/
    pause
    exit /b 1
)

if not exist ".git" (
    echo [!] No Git repository (.git) detected in this directory.
    echo     (This happens when CineTag is downloaded as a ZIP archive)
    echo.
    echo Connecting this folder to the official CineTag repository...
    git init
    git remote add origin https://github.com/benhayashi/cinetag.git
    git fetch origin main
    git reset --hard origin/main
    git branch -M main
    git branch --set-upstream-to=origin/main main
    if %errorlevel% neq 0 (
        echo Error: Failed to link folder to GitHub repository.
        pause
        exit /b 1
    )
    echo Repository successfully linked to GitHub!
    echo.
) else (
    echo Pulling latest updates from GitHub...
    git pull
)

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
