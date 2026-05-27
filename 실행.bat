@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo =============================================
echo  카카오알림 전송
echo =============================================
echo.

if not exist ".venv" (
    echo [1/3] 가상환경 생성 중...
    python -m venv .venv
    if errorlevel 1 (
        echo [오류] Python이 설치되어 있지 않습니다.
        echo  https://www.python.org 에서 Python 3.11 이상 설치 후 다시 실행하세요.
        pause & exit /b 1
    )

    echo [2/3] 패키지 설치 중 (1~2분 소요)...
    .venv\Scripts\pip install -r requirements.txt --quiet
    if errorlevel 1 (
        echo [오류] 패키지 설치 실패
        pause & exit /b 1
    )

    echo [3/3] 브라우저 설치 중 (수분 소요)...
    .venv\Scripts\python.exe -m playwright install chromium
    if errorlevel 1 (
        echo [오류] 브라우저 설치 실패
        pause & exit /b 1
    )

    echo.
    echo 설치 완료!
    echo.
)

.venv\Scripts\python.exe ui.py
