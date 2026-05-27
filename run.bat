@echo off
cd /d "%~dp0"
set PYTHONHOME=
set PYTHONPATH=
set VENV=C:\Users\Public\kakao_notifier_venv
set PLAYWRIGHT_BROWSERS_PATH=C:\Users\Public\kakao_pw_browsers

where uv >nul 2>&1
if not errorlevel 1 goto :use_uv

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

if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set PYEXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe

if not defined PYEXE (
    for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "foreach ($v in '3.13','3.12','3.11') { $r = Get-ItemProperty \"HKCU:\Software\Python\PythonCore\$v\InstallPath\" -EA SilentlyContinue; if ($r) { $b = $r.'(default)'; if (-not $b) { $b = $r.InstallPath }; if ($b -and (Test-Path \"${b}python.exe\")) { Write-Output \"${b}python.exe\"; break } } }"`) do set PYEXE=%%P
)

if not defined PYEXE ( echo ERROR: Python not found. Please install Python 3.11+ from python.org & pause & exit /b 1 )

:use_python
if not exist "%VENV%\Scripts\python.exe" (
    "%PYEXE%" -m venv "%VENV%"
    if errorlevel 1 ( pause & exit /b 1 )
    "%VENV%\Scripts\pip" install -r "%~dp0requirements.txt"
    if errorlevel 1 ( pause & exit /b 1 )
    "%VENV%\Scripts\python.exe" -m playwright install chromium
    if errorlevel 1 ( pause & exit /b 1 )
)
start "" "%VENV%\Scripts\python.exe" "%~dp0ui.py"
exit /b 0

:use_uv
if not exist "%VENV%\Scripts\python.exe" (
    uv venv --seed "%VENV%"
    if errorlevel 1 ( pause & exit /b 1 )
    "%VENV%\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 ( pause & exit /b 1 )
    "%VENV%\Scripts\python.exe" -m playwright install chromium
    if errorlevel 1 ( pause & exit /b 1 )
)
start "" "%VENV%\Scripts\python.exe" "%~dp0ui.py"
exit /b 0
