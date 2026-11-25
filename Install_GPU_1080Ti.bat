@echo off
setlocal
cd /d "%~dp0"
title Assist - Optional NVIDIA Pascal GPU setup
echo OPTIONAL GPU SETUP: PyTorch 2.7.1 + CUDA 11.8, torchvision 0.22.1.
echo This changes packages in .assist-venv only and downloads several GB.
echo Close Assist and training before continuing. An NVIDIA driver is required.
echo A separate CUDA Toolkit installation is not required.
if not exist ".assist-venv\Scripts\python.exe" (
    echo Run Start_Assist.bat once first, then close Assist and run this file.
    pause
    exit /b 1
)
choice /C YN /N /M "Install the optional GPU packages? [Y/N] "
if errorlevel 2 exit /b 0
".assist-venv\Scripts\python.exe" -c "import sys; assert (3,10) <= sys.version_info[:2] < (3,13), 'Use Python 3.10, 3.11 or 3.12 for this pinned build'"
if errorlevel 1 goto failed
".assist-venv\Scripts\python.exe" -m pip install --upgrade torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu118
if errorlevel 1 goto failed
".assist-venv\Scripts\python.exe" -c "import torch; assert torch.cuda.is_available(), 'CUDA is unavailable: check NVIDIA driver'; x=torch.randn(1,3,64,64,device='cuda'); w=torch.randn(8,3,3,3,device='cuda'); y=torch.nn.functional.conv2d(x,w); torch.cuda.synchronize(); print('GPU check OK:',torch.cuda.get_device_name(0),'CUDA',torch.version.cuda)"
if errorlevel 1 goto failed
echo GPU check passed. Start Assist normally and choose device auto or 0.
pause
exit /b 0
:failed
echo GPU setup or check failed. Copy the error above for diagnosis.
echo Device auto can still fall back to CPU; do not force device 0 until fixed.
pause
exit /b 1
