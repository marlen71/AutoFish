@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
echo Reset an existing administrator password on this server computer.
call "%~dp0RUN-PYTHON.bat" reset-admin
echo.
pause
