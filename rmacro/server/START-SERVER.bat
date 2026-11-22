@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
echo Eternal Core: keep this window open while the server is running.
echo Default LAN address: http://192.168.0.105:8765/admin/
echo WARNING: LAN HTTP does NOT encrypt passwords, tokens or keys.
echo Do not expose port 8765 to the internet. See README-SERVER.md.
echo.
call "%~dp0RUN-PYTHON.bat" serve %*
echo.
echo Server has stopped.
pause
