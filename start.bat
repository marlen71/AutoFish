@echo off
REM ==========================================================================
REM  Eternal FishMod — запуск в два клика (двойной клик по этому файлу)
REM  Каждая строка подписана, чтобы файл можно было легко подправить под себя.
REM ==========================================================================

REM --- не выводить сами команды bat (чистая консоль) + локальные переменные ---
setlocal enabledelayedexpansion

REM --- перейти в каталог, где лежит этот .bat (иначе python не найдёт launch.py ---
cd /d "%~dp0"

REM --- UTF-8 в консоли, чтобы русские/украинские буквы лаунчера не превращались в «кракозябры» ---
chcp 65001 >nul

REM --- ищем интерпретатор: сначала «py -3» (официальный лаунчер Windows), потом «python» ---
set "PYCMD=py -3"
where py >nul 2>nul
if errorlevel 1 set "PYCMD=python"
%PYCMD% --version >nul 2>nul
if errorlevel 1 (
    echo [X] Python не найден. Установи его с https://www.python.org/downloads/
    echo     и обязательно поставь галочку "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

REM --- запускаем лаунчер: он проверит библиотеки, права администратора и поднимет бота ---
REM     %* пробрасывает дополнительные аргументы, например: start.bat --yes --restart
%PYCMD% launch.py %*

REM --- если что-то пошло не так — не закрывать окно, чтобы успеть прочитать сообщение ---
if errorlevel 1 (
    echo.
    echo Код возврата: !errorlevel!
    pause
)
endlocal
exit /b %errorlevel%
