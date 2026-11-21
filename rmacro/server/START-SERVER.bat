@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
echo Keep this window open while the server is running.
echo Default admin address: http://127.0.0.1:8765/admin/
echo For remote access, configure HTTPS as described in README-SERVER.md.
echo.
call "%~dp0RUN-PYTHON.bat" serve %*
echo.
echo Server has stopped.
pause
