@echo off
title File Transfer App - Git Push
color 0A

echo ==========================================
echo        FILE TRANSFER APP - GIT PUSH
echo ==========================================
echo.

:: Go to script directory
cd /d "%~dp0"

echo Current Folder:
cd
echo.

:: Check if git exists
where git >nul 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Git is not installed or not in PATH.
    pause
    exit /b
)

:: Check if this is a git repo
if not exist ".git" (
    echo ERROR: This folder is not a git repository.
    echo Run: git init
    pause
    exit /b
)

echo Checking status...
git status
echo.

echo Adding files...
git add .

echo.
set /p msg=Enter commit message: 

:: Check empty message
if "%msg%"=="" (
    echo.
    echo ERROR: Commit message cannot be empty.
    pause
    exit /b
)

echo.
echo Committing...
git commit -m "%msg%"

echo.
echo Detecting branch...

for /f "tokens=*" %%i in ('git branch --show-current') do set branch=%%i

if "%branch%"=="" (
    set branch=main
)

echo Current branch: %branch%
echo.

echo Pushing to GitHub...
git push -u origin %branch%

echo.
echo ==========================================
echo        PUSH COMPLETED SUCCESSFULLY
echo ==========================================
pause
