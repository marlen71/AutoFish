@echo off
setlocal
cd /d "%~dp0"
title Assist - Build Windows Application
echo Close Assist and training before building.
if not exist ".assist-venv\Scripts\python.exe" (
    echo Run Start_Assist.bat once, close Assist, then run this file again.
    pause
    exit /b 1
)
".assist-venv\Scripts\python.exe" -m pip install "pyinstaller>=6,<7"
if errorlevel 1 goto failed
".assist-venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed --name Assist --workpath .assist-build --specpath .assist-build --distpath Assist_app --collect-all ultralytics --collect-all mss --collect-all torch --collect-all torchvision --collect-all onnx --collect-all onnxruntime --collect-all dxcam --add-data "%CD%\game_detector_final.pt;." Assist.py >assist_build.log 2>&1
if errorlevel 1 goto failed
copy /Y screen_assist\README.md Assist_app\Assist\README.md >nul
echo Application built: Assist_app\Assist\Assist.exe
echo Keep the entire Assist folder, including _internal. Python is not needed to run it.
pause
exit /b 0
:failed
echo Build failed. See assist_build.log and the error above.
pause
exit /b 1
