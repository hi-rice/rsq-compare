@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo RSQ 회차 비교 도구: 설치를 시작합니다. (인터넷 연결 필요 - 처음 1회만)
set "PY=python"
py -3.12 -c "import sys" >nul 2>nul && set "PY=py -3.12"
if not exist ".venv\Scripts\python.exe" (
    echo - 가상환경 .venv 만드는 중...
    %PY% -m venv .venv || goto :fail
)
if exist "wheels" (
    echo - wheels 폴더에서 오프라인 설치 중...
    ".venv\Scripts\python.exe" -m pip install --no-index --find-links wheels -r requirements.txt || goto :fail
) else (
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
)
echo.
echo 설치 완료! 이제 run.bat 을 더블클릭해서 실행하세요.
pause
exit /b 0
:fail
echo.
echo 설치 실패: Python 3.12가 설치되어 있는지, 인터넷이 연결되어 있는지 확인하세요.
echo  - 명령 프롬프트에서 "python --version" 또는 "py -3.12 --version" 으로 확인할 수 있습니다.
pause
exit /b 1
