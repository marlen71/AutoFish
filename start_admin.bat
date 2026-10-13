@echo off
REM ==========================================================================
REM  Eternal FishMod — запуск ОТ АДМИНИСТРАТОРА в один клик.
REM  Нужен, если сама игра/лаунчер запущены с повышенными правами: без этого
REM  SendInput-клики и DXGI-захват могут «не видеть» окно игры.
REM  Как работает: скрипт смотрит, есть ли уже админ-право; если нет —
REM  просит UAC разрешить запуск самого себя через PowerShell Start-Process -Verb RunAs.
REM ==========================================================================
setlocal

cd /d "%~dp0"

REM --- есть ли админ-право: net session доступен только админу ---
net session >nul 2>&1
if %errorlevel%==0 goto :run

REM --- нет: поднимаем UAC-запрос и выходим (новое окно уже будет с правами) ---
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b 0

:run
chcp 65001 >nul
set "PYCMD=py -3"
where py >nul 2>nul
if errorlevel 1 set "PYCMD=python"
%PYCMD% launch.py --already-elevated --yes %*
if errorlevel 1 pause
endlocal
