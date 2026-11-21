@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
echo Backups contain private user information. Keep them in a secure place.
call "%~dp0RUN-PYTHON.bat" backup
echo.
pause
