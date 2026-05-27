@echo off
cd /d "%~dp0"

where uv >nul 2>&1
if not errorlevel 1 goto :use_uv

where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys; exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1
    if not errorlevel 1 goto :use_python
)

if not exist "python-embed\python.exe" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_python.ps1"
    if errorlevel 1 ( pause & exit /b 1 )
)
goto :use_embed

:use_uv
if not exist ".venv" (
    uv venv --seed
    if errorlevel 1 ( pause & exit /b 1 )
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 ( pause & exit /b 1 )
    .venv\Scripts\python.exe -m playwright install chromium
)
start "" .venv\Scripts\pythonw.exe ui.py
exit /b 0

:use_python
if not exist ".venv" (
    python -m venv .venv
    if errorlevel 1 ( pause & exit /b 1 )
    .venv\Scripts\pip install -r requirements.txt
    if errorlevel 1 ( pause & exit /b 1 )
    .venv\Scripts\python.exe -m playwright install chromium
)
start "" .venv\Scripts\pythonw.exe ui.py
exit /b 0

:use_embed
if not exist "python-embed\Lib\site-packages\playwright" (
    python-embed\python.exe -m pip install -r requirements.txt --no-warn-script-location
    if errorlevel 1 ( pause & exit /b 1 )
    python-embed\python.exe -m playwright install chromium
)
start "" python-embed\pythonw.exe ui.py
exit /b 0
