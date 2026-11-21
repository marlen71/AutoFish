@echo off
setlocal
>"%~dp0STOP.txt" echo STOP
if errorlevel 1 (
    echo Could not create STOP.txt. Trying to close RMFish.exe anyway.
) else (
    echo Stop signal sent. Waiting two seconds for a safe mouse release...
    timeout /t 2 /nobreak >nul
)
taskkill /F /IM RMFish.exe >nul 2>&1
if errorlevel 1 (
    echo RMFish.exe was not found or could not be closed.
    echo If it runs as administrator, run this file as administrator too.
    echo For source mode, STOP.txt is the stop signal.
) else (
    echo RMFish.exe was closed. GTA5 was not closed.
)
echo If the left mouse button appears stuck, press and release it once.
timeout /t 8 /nobreak >nul
