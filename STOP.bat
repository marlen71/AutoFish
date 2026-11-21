@echo off
setlocal
>"%~dp0STOP.txt" echo STOP
if errorlevel 1 (
    echo Could not create STOP.txt. Extract RMFish to a writable folder.
    pause
    exit /b 1
)
echo Stop signal sent. RMFish will stop automatically.
echo To start again, use the Start button or F8 in RMFish.
timeout /t 3 /nobreak >nul
