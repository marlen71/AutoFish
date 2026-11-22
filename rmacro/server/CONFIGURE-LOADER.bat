@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
echo Create a client EXE configured for your server. The original EXE is not modified.
call "%~dp0RUN-PYTHON.bat" configure-client
echo.
pause
