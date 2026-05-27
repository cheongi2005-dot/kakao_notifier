@echo off
cd /d "%~dp0"
set PYTHONHOME=C:\fake\broken\path
set PYTHONPATH=C:\fake\broken\path

if exist "python-embed" (
    rmdir /s /q "python-embed"
    echo Removed old python-embed
)

echo Running setup_python.ps1...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_python.ps1"
if errorlevel 1 ( echo SETUP FAILED & pause & exit /b 1 )

set PYTHONHOME=
set PYTHONPATH=

echo.
echo Testing python-embed\python.exe...
python-embed\python.exe -c "import encodings; print('encodings OK')"
if errorlevel 1 ( echo ENCODINGS IMPORT FAILED & pause & exit /b 1 )

python-embed\python.exe -c "import sys; print('Python', sys.version)"
echo.
echo SUCCESS
pause
