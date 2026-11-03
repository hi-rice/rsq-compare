# 개발 이어가기

## 등록한 소스

`rsq_compare_v0.4.1_source.zip`의 최상위 포장 폴더를 제거해 등록했다.
Python 소스, 기존 테스트, requirements.txt와 배치 파일의 내용은 원본 그대로다.
한글 파일명은 ZIP의 UTF-8 이름을 복원했다.
`rsq_현장기능_데모_v0.4.0.zip`은 DB·엑셀·이미지 자료여서 등록하지 않았다.
`test.zip`도 측정자료이므로 Git에 등록하지 않는다.

## 집에서 시작하기 (Windows)

1. Python 3.12와 Git을 설치한다.
2. 아래 명령으로 내려받은 뒤 `setup.bat`을 실행한다.
3. 설치가 끝나면 `run.bat`을 실행한다.

```powershell
git clone https://github.com/hi-rice/rsq-compare.git
cd rsq-compare
.\setup.bat
.\run.bat
```

이미 내려받았다면 작업을 저장한 뒤 `git pull --ff-only`로 갱신한다.
측정자료와 개인 DB는 저장소 밖에 따로 보관한다. 예: `D:\RSQ-data`.
자료 ZIP을 그곳에 풀고 앱에서 데이터 폴더를 선택한다.
누적 DB도 앱의 DB 파일 선택 버튼으로 개인 경로에 지정한다.

## Linux / 클라우드

```bash
cd /workspace/rsq-compare
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run_app.py /path/to/private/test
```

GUI에는 데스크톱 환경이 필요하다. 화면 없는 실행은 다음과 같다.

```bash
MPLCONFIGDIR=/tmp/rsq-mpl .venv/bin/python -m rsq_compare.cli /path/to/private/test --out /path/to/private/results
```

이 프로젝트는 PySide6 GUI, pandas 데이터 처리, matplotlib 그래프,
openpyxl 엑셀 출력과 Python 표준 sqlite3 DB를 사용한다. npm은 필요 없다.
의존성은 원본 requirements.txt의 최소 버전 조건을 유지한다.

## 등록 시 검증 (2026-11-03)

- Python 3.12.14에서 의존성 설치 및 `pip check` 통과.
- Python 소스와 기존 테스트 `compileall` 통과, 누적 DB CLI 도움말 실행 확인.
- `tests/verify_sample.py`: 실제 test 자료로 41개 통과, 실패 0개.
  원본 자료 불변 확인과 엑셀·그래프 내보내기 포함.
- `tests/gui_smoke.py`: Qt offscreen으로 세션 열기, 탭 전환,
  체크 변경, T07 상세 표시 및 결과 파일 18개 저장까지 통과.
- `tests/gui_smoke_db.py`: 가져오기, 외부 시계열 연결, 비교 유량 직접 입력은
  실행됐으나, 두 번째 등록 행 접근에서 AttributeError로 종료됐다.
  스크립트가 전제하는 두 번째 T07 포함 DIS가 없어 등록 행이 하나뿐이었다.
  전체 통과로 간주하지 않는다.
- T07 포함 DIS 관련 추가 검증과 `verify_db.py`, `gui_smoke_v02.py`는
  해당 재내보내기 자료가 없어 실행하지 못했다.
- `verify_v04.py`, `gui_smoke_v04.py`는 별도 소하천 목록 원본이 없어 실행하지 못했다.
- Windows 배치 파일의 실제 실행과 데스크톱 수동 조작은 검증하지 못했다.
- 클라우드 GUI 기본 DB 경로는 읽기 전용 홈을 가리키므로, 테스트에서는
  별도 XDG_CONFIG_HOME 아래 QSettings(NDMI/RSQCompare)의 db_path를
  저장소 밖의 쓰기 가능한 경로로 지정했다. 앱 코드는 수정하지 않았다.
  한글 폰트가 없는 환경의 그래프 글꼴 경고는 별도 제약이다.

기존 검증 재실행:

```bash
.venv/bin/python tests/verify_sample.py /path/to/private/test /tmp/rsq-verify
# T07 포함으로 RSQ에서 다시 내보낸 DIS가 있을 때만 세 번째 인수를 추가한다.
```

## 커밋 전 확인

`.gitignore`는 측정 파일, DB, 엑셀·CSV 출력, ZIP, 인증정보 파일,
가상환경·캐시·빌드 결과를 제외한다. templates의 명시된 가상 CSV 3개만 허용한다.
새 형식의 개인정보 파일은 확장자만으로 걸러지지 않을 수 있으므로
`git status`와 `git diff --cached`로 올릴 파일을 확인한다.
기능·계산 방식 변경은 별도 작업에서 수행한다.
