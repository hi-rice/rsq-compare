# Windows 오프라인 설치파일 빌드

앱 버전은 rsq_compare/__init__.py의 APP_VERSION 한 곳에서 읽는다.
설치파일 이름/Windows 리소스/앱 제목/Excel은 이 값을 사용한다.

## 현재 상태

Linux에서 `build.py --prepare-only`(아이콘·버전·라이선스 수집)와 Python 검증을 실행했다.
Windows exe/설치파일 빌드 및 Python 없는 PC 실사용은 아직 실행하지 못했다.
GitHub Actions API 조회가 Forbidden으로 거절되어 이 세션에서 Windows 작업을 실행할 수 없었다.
Linux 준비 산출물은 Windows 실행파일이 아니다.

## GitHub에서 빌드

1. Actions → **Windows installer (manual)** → Run workflow → main을 선택한다.
2. 성공한 실행의 Artifacts → **RSQCompare-Windows-installer**를 내려받는다.
3. 압축 안의 `RSQCompare-Setup-<버전>-x64.exe`, SHA256.txt와 build-manifest.json을 확인한다.
4. 아래 Windows 수동 확인을 마친 뒤 팀 내부에 전달한다.

자동 push 빌드/Release/외부 배포는 설정하지 않았다. 워크플로는 수동 실행이며 저장소 읽기 권한만 사용한다.
빌드 성공 시에만 artifact를 올린다. 실행이 실패하거나 없으면 설치파일이 준비됐다고 간주하지 않는다.
artifact 보관 기간은 14일이며 접근은 저장소/Actions 권한을 따른다.

## Windows 개발 PC에서 직접 빌드

개발용 Python 3.12 x64와 Inno Setup 6.4.3을 준비한다. 최종 사용자에게는 Python/Git이 필요 없다.
저장소 루트에서:

```powershell
py -3.12 -m venv .build-venv
.\.build-venv\Scripts\python.exe -m pip install -r packaging\windows\build-requirements.txt
.\.build-venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.build-venv\Scripts\python.exe packaging\windows\build.py
```

ISCC 설치 위치가 다르면 `ISCC_EXE`로 실행파일 경로를 지정한다.
빌드 결과는 `dist/installer/`. 설치 프로그램은 Qt/Python/실행 의존성을 모두 포함하는 onedir 배포를 묶으며,
최종 PC 설치·실행에는 다운로드 과정이 없다. 빌드 PC 의존성 설치에는 인터넷이 필요하다.
런타임 라이브러리와 PyInstaller 버전은 잠금 파일로 고정했다. 실제 Python/플랫폼은 빌드 manifest에 기록한다.
동일 소스·절차를 재실행하는 설정이며 타임스탬프까지 같은 바이너리를 보장하지 않는다.

## 저장 위치와 업데이트

- 설치: 일반 사용자 `%LOCALAPPDATA%\Programs\RSQCompare` (관리자 권한 불필요).
- 새 사용자 DB/로그: `%LOCALAPPDATA%\RSQCompare` 아래. 기존 QSettings(NDMI/RSQCompare) 선택 경로는 유지.
- 설정이 없고 기존 Documents/RSQ_측정기록.db가 있으면 그 파일을 계속 사용.
- 기존 선택 DB가 없으면 위치 확인을 요구하며 새 빈 DB로 자동 대체하지 않는다.
- 업데이트·제거 스크립트는 연구자료·DB·설정·로그 폴더를 삭제하지 않는다.
- 코드/아이콘/버전은 동일 제품 ID와 파일명으로 유지한다. 설치파일은 코드서명하지 않았으므로
  기관 정책에 따른 서명/신뢰 검토는 별도 작업이다. 공개 배포는 하지 않았다.

## Python 없는 Windows 10/11 x64 PC 수동 확인 (미실행)

- 인터넷 끊기, Python/Git 없는 일반 사용자로 설치. 시작 메뉴/바탕화면 아이콘으로 실행.
- 검은 콘솔 없이 앱과 작업표시줄 아이콘/버전이 표시되는지 확인.
- 한글·공백 경로의 실제 측정 폴더 가져오기 → 실제 지점 지정 → 회차 선택 → Excel/PNG 저장.
- 1366×768/1920×1080 및 100%/125%/150%에서 글자·탭·표·그래프의 겹침/잘림 확인.
- Excel 결과 요약/내장 차트/선택 회차/통계/누락·0 구분/한글 출력과 인쇄 확인.
- 앱 종료·재실행 후 DB 위치/지점/수위 기준면/입력/선택 보존.
- 기존 사용자 DB를 지정한 상태로 새 설치파일 실행(업데이트), 재실행해 DB/입력 보존.
- 기존 DB가 있는 이동식 드라이브를 분리하고 실행: 새 DB가 조용히 생기지 않는지 확인.
- 앱 제거 후 원래 DB·원본 측정·설정·로그가 보존되는지 확인.
- 잘못된 파일/저장 권한 오류가 앱 안내와 로그에 남고, 로그에 원본 값·인증정보가 없는지 확인.

이 절차를 마치기 전 Windows 설치·업데이트가 검증됐다고 표현하지 않는다.
