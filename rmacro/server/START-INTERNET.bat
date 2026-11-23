@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
echo Eternal Core: keep this window open while the internet gateway is running.
echo Stop the old START-SERVER.bat before starting this gateway.
echo Do not share the data folder or private certificate keys.
echo.
call "%~dp0RUN-PYTHON.bat" internet-serve %*
echo.
echo Internet gateway has stopped.
pause
