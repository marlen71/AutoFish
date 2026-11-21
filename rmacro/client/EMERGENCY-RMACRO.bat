@echo off
setlocal
if defined LOCALAPPDATA (
  if not exist "%LOCALAPPDATA%\RMacro\Runtime" mkdir "%LOCALAPPDATA%\RMacro\Runtime" >nul 2>nul
  >"%LOCALAPPDATA%\RMacro\Runtime\STOP.txt" echo stop
)
echo Stop requested. RMacro.exe will now be terminated, not GTA5.exe.
timeout /t 2 >nul
taskkill /f /im RMacro.exe >nul 2>nul
if errorlevel 1 (
  echo RMacro.exe was not closed. If it is running as administrator, run this BAT as administrator too.
  pause
  exit /b 1
)
echo RMacro.exe was closed.
echo If the left mouse button seems held, press and release it once.
timeout /t 3 >nul
