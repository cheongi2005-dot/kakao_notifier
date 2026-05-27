@echo off
cd /d "%~dp0"

if not exist ".venv" (
    python -m venv .venv
    if errorlevel 1 (
        echo Python not found. Install Python 3.11+ from https://www.python.org
        pause
        exit /b 1
    )
    .venv\Scripts\pip install -r requirements.txt
    if errorlevel 1 ( pause & exit /b 1 )
    .venv\Scripts\python.exe -m playwright install chromium
    if errorlevel 1 ( pause & exit /b 1 )
)

.venv\Scripts\pythonw.exe ui.py
