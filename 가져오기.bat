@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem ================================================================
rem  새 측정 자료 자동 가져오기 (누적 DB에 등록)
rem  아래 두 줄만 자기 환경에 맞게 바꿔서 쓰세요.
rem   DATA : RSQ에서 내보낸 폴더들을 모아두는 폴더 (하위 폴더까지 찾음)
rem   DB   : 누적 DB 파일 위치 (없으면 새로 만듦)
rem ================================================================
set "DATA=D:\RSQ_측정자료"
set "DB=%USERPROFILE%\Documents\RSQ_측정기록.db"

if not exist ".venv\Scripts\python.exe" (
    echo 먼저 setup.bat 을 실행해 설치를 완료하세요.
    if /i not "%~1"=="auto" pause
    exit /b 1
)
".venv\Scripts\python.exe" -m rsq_compare.cli_db import "%DATA%" --db "%DB%" --report "%DB%_마지막가져오기보고.csv"
echo.
echo 가져오기 보고: %DB%_마지막가져오기보고.csv
rem 작업 스케줄러에서 자동 실행할 때는 인수로 auto 를 주면 창이 멈추지 않습니다.
if /i not "%~1"=="auto" pause
