@echo off
chcp 65001 >nul
cd /d "%~dp0"
if "%~1"=="" (
    echo 사용법: verify.bat "압축을 푼 데이터 폴더" ["T07 포함으로 다시 내보낸 .dis"]
    pause
    exit /b 1
)
".venv\Scripts\python.exe" tests\verify_sample.py "%~1" "%TEMP%\rsq_compare_verify" %2
pause
