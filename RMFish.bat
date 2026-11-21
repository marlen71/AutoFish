@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0RMFish.exe" (
    start "" "%~dp0RMFish.exe"
    exit /b 0
)
if not exist "%~dp0RMFish.ps1" (
    echo RMFish.exe and RMFish.ps1 were not found. Extract the complete program folder.
    pause
    exit /b 1
)
where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo Windows PowerShell 5.1 was not found.
    pause
    exit /b 1
)
start "RMFish" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0RMFish.ps1" -HideConsole
exit /b 0
