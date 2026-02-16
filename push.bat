@echo off
title FilePortal - Auto Git Push & Deploy
color 0B

echo ==========================================
echo      FILEPORTAL - SECURE DEPLOYMENT
echo ==========================================
echo.

:: Go to script directory
cd /d "%~dp0"

:: Check if git exists
where git >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Git is not installed or not in PATH.
    pause
    exit /b
)

:: Check if git repo exists
if not exist ".git" (
    echo [ERROR] This folder is not initialized as a Git repository.
    echo Run 'git init' first.
    pause
    exit /b
)

:: Detect current branch
for /f "tokens=*" %%i in ('git branch --show-current') do set branch=%%i
if "%branch%"=="" (
    set branch=main
)

echo [INFO] Current Branch: %branch%
echo [INFO] Preparing to sync with GitHub...
echo.

:: Pull latest changes first to prevent conflicts
echo Step 1: Pulling latest changes from GitHub...
git pull origin %branch% --rebase
echo.

:: Add all changes
echo Step 2: Staging new changes...
git add .

:: Check if there are actually any changes to commit
git diff --cached --quiet
if %errorlevel%==0 (
    echo.
    echo ==========================================
    echo       STATUS: NOTHING NEW TO PUSH
    echo ==========================================
    pause
    exit /b
)

:: Auto commit message with date & time
set msg=FilePortal Update: %date% %time%

echo Step 3: Committing changes...
echo Message: %msg%
git commit -m "%msg%"

echo.
echo Step 4: Pushing to GitHub...
git push origin %branch%

if %errorlevel% equ 0 (
    echo.
    echo ==========================================
    echo      SUCCESS: CODE SYNCED SUCCESSFULLY
    echo ==========================================
    echo.
    echo [ACTION] Render is now building your update!
    echo [URL] Check here: https://fileportal.onrender.com
    echo.
) else (
    echo.
    echo [ERROR] Something went wrong during the push.
    echo Check your internet connection or GitHub credentials.
)

echo ==========================================
pause