@echo off
cd /d "%~dp0"

where uv >nul 2>&1
if not errorlevel 1 goto :use_uv

where python >nul 2>&1
if not errorlevel 1 goto :use_python

echo Python not found. Install from https://www.python.org
pause
exit /b 1

:use_uv
if not exist ".venv" (
    uv venv
    if errorlevel 1 ( pause & exit /b 1 )
    uv pip install -r requirements.txt
    if errorlevel 1 ( pause & exit /b 1 )
    .venv\Scripts\python.exe -m playwright install chromium
    if errorlevel 1 ( pause & exit /b 1 )
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
    if errorlevel 1 ( pause & exit /b 1 )
)
start "" .venv\Scripts\pythonw.exe ui.py
