@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo 먼저 setup.bat 을 실행해 설치를 완료하세요.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" run_app.py %*
if errorlevel 1 (
    echo.
    echo 프로그램이 오류로 종료되었습니다. 위 메시지를 확인하세요.
    pause
)
