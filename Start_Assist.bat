@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Assist - Launcher
echo Assist: preparing application...
if exist ".assist-venv\Scripts\python.exe" goto install
py -3 --version >nul 2>&1
if not errorlevel 1 (
    py -3 -m venv .assist-venv
) else (
    python --version >nul 2>&1
    if errorlevel 1 goto no_python
    python -m venv .assist-venv
)
if errorlevel 1 goto failed
:install
if exist ".assist-venv\assist-ready-v1" goto launch
echo First launch: downloading dependencies. Please wait.
".assist-venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".assist-venv\Scripts\python.exe" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto failed
".assist-venv\Scripts\python.exe" -m pip install -r screen_assist\requirements.txt
if errorlevel 1 goto failed
echo ready>".assist-venv\assist-ready-v1"
:launch
".assist-venv\Scripts\python.exe" Assist.py
if errorlevel 1 goto failed
exit /b 0
:no_python
echo.
echo Python not found. Install Python 3.11 or 3.12, 64-bit:
echo https://www.python.org/downloads/windows/
echo Enable "Add python.exe to PATH" during installation.
echo Then run this file again.
pause
exit /b 1
:failed
echo.
echo Assist could not start. Copy the error above and send it for diagnosis.
pause
exit /b 1
