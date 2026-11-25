@echo off
setlocal
cd /d "%~dp0"
if not exist ".assist-venv\Scripts\python.exe" (
    echo Run Start_Assist.bat once first.
    if /I not "%~1"=="quiet" pause
    exit /b 1
)
echo Assist optional acceleration setup >assist_acceleration.log
".assist-venv\Scripts\python.exe" -m pip install "dxcam>=0.0.5,<1" >>assist_acceleration.log 2>&1
if errorlevel 1 goto failed
".assist-venv\Scripts\python.exe" -c "import onnxruntime as o; print(o.get_available_providers())" >>assist_acceleration.log 2>&1
if errorlevel 1 goto directml
if /I "%~1"=="quiet" goto verify
".assist-venv\Scripts\python.exe" -c "import onnxruntime as o; assert 'DmlExecutionProvider' in o.get_available_providers()" >nul 2>&1
if not errorlevel 1 goto verify
echo An ONNX Runtime is already installed. Replacing it affects ONNX apps in this venv.
echo Close Assist and training before continuing.
choice /C YN /N /M "Replace the current ONNX Runtime with DirectML? [Y/N] "
if errorlevel 2 goto verify
".assist-venv\Scripts\python.exe" -m pip uninstall -y onnxruntime onnxruntime-gpu onnxruntime-directml >>assist_acceleration.log 2>&1
if errorlevel 1 goto failed
:directml
".assist-venv\Scripts\python.exe" -m pip install "onnxruntime-directml>=1.20,<2" >>assist_acceleration.log 2>&1
if errorlevel 1 goto failed
:verify
".assist-venv\Scripts\python.exe" -c "import dxcam, onnxruntime as o; print('Available ONNX providers:', o.get_available_providers())" >>assist_acceleration.log 2>&1
if errorlevel 1 goto failed
echo ready>".assist-venv\assist-accel-v2"
echo Setup finished. Details: assist_acceleration.log
if /I not "%~1"=="quiet" pause
exit /b 0
:failed
echo Optional setup failed. Details: assist_acceleration.log
if /I not "%~1"=="quiet" pause
exit /b 1
