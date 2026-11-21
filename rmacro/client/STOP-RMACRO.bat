@echo off
setlocal
if not defined LOCALAPPDATA (
  echo LOCALAPPDATA is unavailable. Use F10 or Task Manager to stop RMacro.exe.
  pause
  exit /b 1
)
if not exist "%LOCALAPPDATA%\RMacro\Runtime" mkdir "%LOCALAPPDATA%\RMacro\Runtime" >nul 2>nul
>"%LOCALAPPDATA%\RMacro\Runtime\STOP.txt" echo stop
if errorlevel 1 (
  echo Failed to write the stop signal. Use F10 or Task Manager.
  pause
  exit /b 1
)
echo Stop requested. A blocked Windows call may delay the stop.
timeout /t 2 >nul
