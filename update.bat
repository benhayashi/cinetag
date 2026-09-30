@echo off
setlocal
cd /d "%~dp0"

echo =============================================
echo    Updating CineTag (Windows)
echo =============================================
echo.

where git >nul 2>nul
if errorlevel 1 goto no_git

if exist ".git" goto do_git_pull

echo [!] No Git repository detected in this directory.
echo     This usually happens when CineTag was downloaded as a ZIP archive.
echo.
echo Connecting this folder to the official CineTag repository...
git init
if errorlevel 1 goto git_fail

git remote add origin https://github.com/benhayashi/cinetag.git 2>nul || git remote set-url origin https://github.com/benhayashi/cinetag.git

echo Fetching latest updates from GitHub...
git fetch origin main
if errorlevel 1 goto git_fail

git reset --hard origin/main
if errorlevel 1 goto git_fail

git branch -M main
git branch --set-upstream-to=origin/main main
echo Repository successfully linked to GitHub!
echo.
goto check_venv

:do_git_pull
echo Pulling latest updates from GitHub...
git remote add origin https://github.com/benhayashi/cinetag.git 2>nul || git remote set-url origin https://github.com/benhayashi/cinetag.git
git fetch origin main
if errorlevel 1 goto git_fail

git branch -M main
git branch --set-upstream-to=origin/main main 2>nul
git reset --hard origin/main
if errorlevel 1 goto git_fail
echo Repository successfully updated!
echo.

:check_venv
if not exist ".venv" goto venv_missing

echo Updating Python dependencies in .venv...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
goto update_done

:venv_missing
echo Virtual environment will be created automatically on next run.bat

:update_done
echo.
echo =============================================
echo Update successful! Run run.bat to start.
echo =============================================
echo.
pause
exit /b 0

:no_git
echo.
echo [Error] Git is not installed or not found in your system PATH.
echo Please install Git for Windows from: https://git-scm.com/
echo (Make sure to check "Add Git to PATH" during installation)
echo.
pause
exit /b 1

:git_fail
echo.
echo [Error] Failed to connect or download updates from GitHub.
echo Please check your internet connection or verify Git is functioning.
echo.
pause
exit /b 1
