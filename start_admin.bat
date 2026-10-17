@echo off
REM ==========================================================================
REM  Eternal FishMod - launch elevated (double-click this file).
REM
REM  KEEP THIS FILE PURE ASCII WITH CRLF LINE ENDINGS AND NO BOM (see the note
REM  in start.bat: non-ASCII bytes or LF endings make cmd.exe execute garbage).
REM
REM  Needed when the game itself runs as administrator: without equal or higher
REM  privileges SendInput clicks and the DXGI capture cannot "see" that window.
REM  How it works: if we are already admin, run start.bat; otherwise ask UAC to
REM  relaunch this very file with the "runas" verb (through PowerShell, so no
REM  extra helper .exe is needed) and close this unelevated window right away.
REM ==========================================================================
setlocal enableextensions

cd /d "%~dp0"

REM --- "net session" is allowed for administrators only - a cheap elevation test
net session >nul 2>&1
if not errorlevel 1 goto :run

powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
endlocal & exit /b 0

:run
REM --- already elevated: tell launch.py not to start a second UAC round
call "%~dp0start.bat" --already-elevated --yes %*
set "RC=%errorlevel%"
endlocal & exit /b %RC%
