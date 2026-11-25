@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Assist - AI Workspace
echo Assist: checking local environment...
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
if exist ".assist-venv\assist-ready-v2" goto acceleration
echo Installing/updating core dependencies. Existing GPU PyTorch is preserved.
".assist-venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".assist-venv\Scripts\python.exe" -c "import torch, torchvision" >nul 2>&1
if not errorlevel 1 goto requirements
".assist-venv\Scripts\python.exe" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto failed
:requirements
".assist-venv\Scripts\python.exe" -m pip install -r screen_assist\requirements.txt
if errorlevel 1 goto failed
echo ready>".assist-venv\assist-ready-v2"
:acceleration
if exist ".assist-venv\assist-accel-v2" goto launch
echo Installing optional DXGI and ONNX DirectML dependencies...
call Install_Acceleration.bat quiet
if not errorlevel 1 goto launch
echo Optional acceleration failed. PyTorch/MSS remain usable.
echo See assist_acceleration.log or rerun Install_Acceleration.bat.
:launch
".assist-venv\Scripts\python.exe" Assist.py
if errorlevel 1 goto failed
exit /b 0
:no_python
echo Install Python 3.11 or 3.12 x64 from https://www.python.org/downloads/windows/
echo Enable Add python.exe to PATH, then run this file again.
pause
exit /b 1
:failed
echo Assist could not start. Send the error above for diagnosis.
pause
exit /b 1
