@echo off
cd /d "%~dp0"
set PYTHONHOME=
set PYTHONPATH=

where uv >nul 2>&1
if not errorlevel 1 goto :use_uv

:find_python
set PYEXE=

where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys;exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1
    if not errorlevel 1 set PYEXE=python
)

if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set PYEXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe

if defined PYEXE goto :use_python

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_python.ps1"
if errorlevel 1 ( pause & exit /b 1 )
goto :find_python

:use_python
if not defined PYEXE ( echo ERROR: Python not found & pause & exit /b 1 )
if not exist ".venv" (
    "%PYEXE%" -m venv .venv
    if errorlevel 1 ( pause & exit /b 1 )
    .venv\Scripts\pip install -r requirements.txt
    if errorlevel 1 ( pause & exit /b 1 )
    .venv\Scripts\python.exe -m playwright install chromium
    if errorlevel 1 ( pause & exit /b 1 )
)
start "" .venv\Scripts\python.exe ui.py
exit /b 0

:use_uv
if not exist ".venv" (
    uv venv --seed
    if errorlevel 1 ( pause & exit /b 1 )
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 ( pause & exit /b 1 )
    .venv\Scripts\python.exe -m playwright install chromium
    if errorlevel 1 ( pause & exit /b 1 )
)
start "" .venv\Scripts\python.exe ui.py
exit /b 0
