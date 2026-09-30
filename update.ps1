# CineTag Updater for Windows PowerShell
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "   Updating CineTag (PowerShell)" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "[Error] Git is not installed or not in PATH." -ForegroundColor Red
    Write-Host "Please install Git for Windows from https://git-scm.com/"
    Write-Host "Press Enter to exit..."
    Read-Host
    exit 1
}

if (-not (Test-Path ".git")) {
    Write-Host "[!] No Git repository (.git) detected in this directory." -ForegroundColor Yellow
    Write-Host "    (This happens when CineTag is downloaded as a ZIP archive)"
    Write-Host ""
    Write-Host "Connecting this folder to the official CineTag repository..." -ForegroundColor Cyan
    git init
    git remote add origin https://github.com/benhayashi/cinetag.git 2>$null
    if ($LASTEXITCODE -ne 0) {
        git remote set-url origin https://github.com/benhayashi/cinetag.git
    }
    git fetch origin main
    git reset --hard origin/main
    git branch -M main
    git branch --set-upstream-to=origin/main main
    Write-Host "Repository successfully linked to GitHub!" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "Pulling latest updates from GitHub..." -ForegroundColor Cyan
    git pull
}

if (Test-Path ".venv\Scripts\Activate.ps1") {
    Write-Host "Updating Python dependencies in .venv..." -ForegroundColor Cyan
    & .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
} else {
    Write-Host "Virtual environment will be created automatically on next run.bat" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=============================================" -ForegroundColor Green
Write-Host "Update successful! Run run.bat or run.sh to start." -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
Write-Host "Press Enter to exit..."
Read-Host
