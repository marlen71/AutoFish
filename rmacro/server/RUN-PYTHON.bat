@echo off
setlocal
set "PY_CMD="
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
  if not errorlevel 1 set "PY_CMD=py -3"
)
if not defined PY_CMD (
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
  )
)
if not defined PY_CMD (
  echo Python 3.9 or newer was not found. Install Python 3 for Windows and enable the Python launcher.
  exit /b 1
)
%PY_CMD% "%~dp0server.py" %*
exit /b %ERRORLEVEL%
