@echo off
REM ==========================================================================
REM  Eternal FishMod - launcher (double-click this file).
REM
REM  KEEP THIS FILE PURE ASCII WITH CRLF LINE ENDINGS AND NO BOM.
REM  cmd.exe reads .bat files byte-by-byte and remembers file offsets: a single
REM  non-ASCII byte (Cyrillic letters, em-dash, arrows) or LF-only line endings
REM  shifts those offsets and the parser starts executing chopped fragments of
REM  the following lines ("'el' is not recognized as an internal or external
REM  command", "'--restart' is not recognized", exit code 9009). Russian and
REM  Ukrainian text is printed by launch.py instead - Python handles UTF-8
REM  properly, cmd.exe does not.
REM ==========================================================================
setlocal enableextensions enabledelayedexpansion

REM --- run from the folder that holds this .bat, else python won't find launch.py
cd /d "%~dp0"

REM --- UTF-8 codepage so the Cyrillic output of launch.py renders correctly
chcp 65001 >nul 2>&1

REM --- find a working interpreter: "py -3" (official Windows launcher) first,
REM     then "python" / "python3". The probe really runs Python, so the empty
REM     "python" stub from the Microsoft Store (exit code 9009) gets rejected.
set "PYCMD="
for %%P in ("py -3" "python" "python3") do if not defined PYCMD (
    %%~P -c "import sys" >nul 2>nul && set "PYCMD=%%~P"
)
if defined PYCMD goto :launch

echo [X] Python not found in PATH.
echo     Install it from https://www.python.org/downloads/ and tick
echo     "Add Python to PATH" on the first setup screen, then run this
echo     file again. Python 3.9 .. 3.12 is recommended.
echo.
pause
exit /b 9009

:launch
if exist "%~dp0launch.py" goto :run

echo [X] launch.py is missing next to this .bat file.
echo     Unpack the whole archive into a single folder: start.bat, launch.py,
echo     eternal_fishmod.py and requirements.txt must stay side by side.
echo.
pause
exit /b 2

:run
REM --- -X utf8 keeps the launcher output UTF-8 even when it is piped to a file
REM     %* passes extra arguments through, e.g.  start.bat --yes --restart
%PYCMD% -X utf8 "%~dp0launch.py" %*
set "RC=!errorlevel!"

REM --- keep the window open after a failure, so the message can be read
if "!RC!"=="0" goto :finish
echo.
echo [x] Launcher finished with exit code !RC!
echo     Read the lines above. If a library could not be installed, run:
echo         %PYCMD% -m pip install -r "%~dp0requirements.txt"
echo.
pause

:finish
endlocal & exit /b %RC%
