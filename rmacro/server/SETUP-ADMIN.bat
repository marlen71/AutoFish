@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
echo Create the first RMacro administrator. There is no default login or password.
call "%~dp0RUN-PYTHON.bat" init-admin
echo.
pause
