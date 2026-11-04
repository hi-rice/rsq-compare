# 개발 이어가기

현재 업무 흐름 개선은 [단계별 검증](V05_VALIDATION.md)을 먼저 참고하세요.
최종 사용자 배포 준비와 미실행 Windows 확인은 [Windows 빌드 안내](packaging/windows/README.md)에 있습니다.
앱 제목·Excel·설치 메타데이터 버전은 `rsq_compare/__init__.py`의 APP_VERSION을 사용합니다.
아래 v0.4.x 등록·검증 내용은 과거 작업 기록입니다.

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


## 시간·외부자료·강우 오류 수정 (1~3번)

이번 변경은 시간 처리, 외부자료 연결 범위, 강우 집계만 다룬다.
유량 재계산·회차 자동 제외·합격/불합격 판정은 추가하지 않았다.

확인한 기존 오류:

- 원문 Z/+09:00을 버리거나 혼합 시간대 파싱이 실패했다.
- 연결 코드가 없는 시계열이 시간만 같으면 여러 측정에 모두 붙었다.
- 종류 미확인 강우도 합산했다. 가상 누적값 10,11,13을 34로 표시했다.

변경 동작:

- 시간대가 있는 원문은 그 시간대를 우선하며, 없는 값에만 선택한 기준을 적용한다.
  비교와 그래프는 UTC를 사용한다. 원문·적용 기준·UTC는 DB와 화면·엑셀에서 확인한다.
- 소하천코드 또는 측정 등록ID로 범위를 지정한다. 코드 없는 기존 자료는
  삭제하지 않고 연결을 보류한다. 화면의 **연결 대상 지정**으로 지정할 수 있다.
  시간창 시작·끝(UTC), 앞뒤 여유, 자료·빈값 개수와 가까운 자료의 시간 차를 표시한다.
- 강우 종류는 미확인/구간 강우량/누적 강우량/강우강도로 구분한다.
  강우 단위는 열 이름만으로 mm라고 채우지 않는다.
  구간값은 해당 구간의 끝 시각으로 해석한다. 구간/누적값은 mm 단위와 기록 간격이
  지정되고 시간창 양쪽 경계 및 전체 간격이 정확히 맞을 때만 집계한다.
  구간값은 시작 경계 다음 기록부터 합산하고, 누적값은 끝−시작으로 계산한다.
  초기화·결측·음수·중복·빠진 시각·읽기 실패 시각이 있으면 집계하지 않는다.
  강우강도는 합산하거나 임의로 적분하지 않는다. 경계 보간도 하지 않는다.
- DB 버전 3은 기존 테이블의 자료를 지우지 않고 필요한 열만 추가한다.
  이전 버전이 이미 버린 시간대는 복원할 수 없다. 해당 자료는 원본에서 다시 불러와야 한다.
  기존 강우자료의 종류·간격도 추정하지 않으며, 확인 후 새로 불러와야 한다.

검증 결과:

- **가상 자료**: unittest 회귀 17개 통과. 혼합 시간대, 기준 미확인,
  명시적 연결 범위, 시간창·자료 수, 구간/누적/강도 구분,
  초기화·결측·음수·중복·간격·경계 누락·읽기 실패,
  구버전 DB 이관 반복과 기존 메모·시계열 값 보존, GUI 입력 차단·기본값을 검증했다.
- **실제 첨부 test 자료**: 기존 verify_sample.py 41개 통과, 실패 0개.
  T07 포함 재내보내기 DIS 관련 추가 항목은 생략했다.
- **실제 측정 + 가상 외부자료**: verify_external_real.py 통과.
  실제 측정시각을 Z/+09:00/시간대 없는 값으로 표현한 가상 수위 1,2,3을 사용했다.
  CLI 등록, GUI 기존 자료의 연결 보류→직접 지정, UTC 그래프,
  원문·적용 기준 엑셀 저장, 측정 유량 불변을 확인했다.
  원본 측정자료 전체 파일의 SHA-256이 실행 전후 동일했다.
- **실제 첨부자료 GUI**: 기존 gui_smoke.py offscreen 실행과 결과 18개 저장 통과.
- compileall과 Git 공백 검사 통과.
- **미실행**: 실제 외부 관측 시계열·실제 강우자료, Windows 수동 조작,
  T07 포함 DIS가 필요한 verify_db.py/gui_smoke_v02.py/gui_smoke_db.py 전체 완료,
  별도 소하천 목록이 필요한 verify_v04.py/gui_smoke_v04.py.
  verify_db.py와 verify_v04.py의 기대 동작은 새 안전 규칙에 맞췄지만 이번에 실행하지 못했다.

재현 명령 (측정자료와 작업 결과는 Git에 넣지 않는다):

```bash
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/rsq-mpl .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
MPLCONFIGDIR=/tmp/rsq-mpl .venv/bin/python tests/verify_external_real.py /path/to/private/test
```

`--gui`를 추가하면 GUI 연결 대상 지정도 검증한다. 클라우드에서는 앞서 안내한
쓰기 가능한 Qt DB 설정과 QT_QPA_PLATFORM=offscreen을 먼저 준비한다.

다음 작업으로 남긴 문제:

- 4번: DIS 외 상세파일·rsqmb 변경 감지, 복사본 중복 감지,
  재처리 이력과 비교 중복 방지, 관련 DB 이관.
- 5번: 소하천 중복코드 충돌 보존·표시·사용자 확인.


## 중복·변경 감지와 소하천코드 충돌 수정 (4~5번)

1~3번 수정 커밋 `3a4eaeb`는 원격 main에 fast-forward 일반 푸시했다.
이번 변경도 원본 측정파일을 읽기만 하며 유량 공식·품질 판정을 바꾸지 않는다.

측정과 버전:

- 선택한 DIS, 해당 세션의 모든 상세파일(미사용 좌표계 포함), rsqmb의 파일별
  SHA-256·크기·경로와 내용 지문을 저장한다. 파일명과 폴더를 바꿔도 동일 입력이면
  같은 등록으로 판단한다. 사용자 체크·입력을 초기화하지 않는다.
- 같은 상세 원본이 확인되거나 같은 입력 경로의 DIS가 그대로인 상태에서
  상세/rsqmb가 달라지면 재처리본으로 연결한다. 이전 등록과 측정 묶음 ID,
  바뀐 파일을 기록한다. 이전 행을 덮어쓰지 않는다.
- 이름·시각 등 후보 근거만 같고 동일 측정인지 확실하지 않으면 합치지 않는다.
  새 행을 '확인 필요'로 보존하고 기본 비교 체크를 끈다. 사용자가 별도 측정이나
  이전 등록의 재처리본으로 확인한다. 최신 버전을 자동 선택하지 않는다.
- 같은 측정의 여러 버전을 체크하거나 확인 전 자료를 체크하면 비교·저장을 막고
  안내한다. 새 버전은 기본 미선택이며 기존 사용자의 비교 체크를 유지한다.
- 회차 선택은 UI 설정과 등록된 DB에 보존한다. 재처리본은 회차 번호가 대응되는
  선택·직접 입력 수위·메모·측정자·비교 유량을 이어 받는다. 새 버전에서 이미 입력한
  값은 덮어쓰지 않는다. 이전 등록을 단독 삭제해 버전 관계를 끊는 것도 막는다.

DB 이관:

- 구버전 DB 전체를 `.before-v4.bak`로 백업한 뒤, 같은 세션/DIS로도 상세 변경본을
  보존할 수 있도록 기존 고유 제약을 제거한다. ID·외래키·원래 열·행·인덱스·트리거와
  자동 증가 순번을 보존한다. 새 DB 스키마 버전은 4다.
- 구버전에는 상세/rsqmb 해시가 없으므로 과거 상태를 추정해서 채우지 않는다.
  같은 DIS나 원래 측정 식별자가 겹친 기존 등록은 관계 확인 대상으로 표시한다.
  기존에 저장되지 않았던 일시적 체크 상태는 복구할 수 없다.

소하천 목록:

- 필요한 20개 열만 저장하되 모든 행·원본 파일·행 번호를 보존한다. 이전 목록도
  덮어 지우지 않으며, 같은 파일 내용의 반복 가져오기는 다시 쌓지 않는다.
- 모든 필드가 같은 중복은 '완전 중복', 다른 정보가 있는 코드는 '정보 충돌'로
  표시하고 다른 항목을 보여준다. 코드 충돌은 사용자 확인 전까지 지점 정보,
  GPS 제안과 코드 기준 외부자료 연결에서 제외한다.
- '코드 행 선택'으로 사용할 행을 명시하면 해당 확인과 대상 정보를 저장한다.
  같은 코드에 새로운 충돌 정보가 추가되면 기존 확인을 무효로 하고 재확인한다.
- 코드 문자열과 선행 0을 보존한다. Excel 숫자 셀은 명시적인 11자리 0 표시 형식이
  있을 때만 이를 복원한다. 형식 불명인 코드를 임의로 0 채우기하지 않는다.
- 이전 버전이 이미 버린 목록 중복 행은 복원할 수 없다. 원래 목록을 다시 가져와야 한다.

이번 검증:

- **가상 자료 회귀 34개 통과**(기존 시간/외부/강우 17개 포함).
  이름 변경 중복, DIS·상세·rsqmb·미사용 좌표계 변경, 불확실한 관계의 확인,
  버전별 비교 차단, 원래 입력과 새 입력 보존, 별칭의 회차 선택 보존,
  구버전 ID·외래키·백업·인덱스·트리거·순번 보존을 검증했다.
  코드 완전중복/충돌, 재가져오기, 확인 후 새 충돌, 민감 열 제외,
  CSV·Excel 선행 0, 임의 지점/외부 연결 차단도 검증했다.
- **실제 첨부 test 측정자료**: 기존 verify_sample.py 41개 통과, 실패 0.
  기존 gui_smoke.py offscreen 실행과 결과 파일 18개 저장 통과.
- **실제 측정 + 임시 복사본의 가상 변경/가상 목록**: verify_identity_real.py --gui 통과.
  이름 변경 중복 방지, 상세·rsqmb 변경 감지, 선택·메모 보존, 한 버전 결과 저장,
  GUI 재열기 선택 보존, 여러 버전 비교 차단, 코드 모든 행 표시와 사용자 선택 확인.
  원본 측정자료 전체 SHA-256 불변.
- **실제 측정 + 가상 외부자료**: verify_external_real.py --gui 통과.
  기존 시간대/명시적 연결/원문 추적/결과 저장 동작을 재검증했다.
- **첨부 v0.4.0 데모 DB(가상 자료)**: verify_legacy_db.py로 임시 복사본 이관 통과.
  8개 기존 테이블의 원래 열·행, 반복 이관, 전체 백업, FK·무결성 확인.
  원본 DB SHA-256 불변. 실제 개인 DB를 검증했다고 간주하지 않는다.
- compileall, Git 공백 검사 통과.
- **미검증**: 실제 개인 DB 전체 사례, 실제 충돌 소하천 목록, Windows 수동 GUI.
  T07 포함 재내보내기 DIS와 원본 소하천 목록이 없어 verify_db.py/verify_v04.py 및
  관련 GUI 전체 검증은 실행하지 못했다. 이 두 스크립트의 가상 복사본 생성과 기대 동작은
  새 규칙에 맞췄지만 통과로 계산하지 않았다. 실제 외부·강우 원본 자료 검증도 미실행이다.

재실행:

```bash
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/rsq-mpl .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/rsq-mpl .venv/bin/python tests/verify_identity_real.py /path/to/private/test --gui
.venv/bin/python tests/verify_legacy_db.py /path/to/private/old.db
```

클라우드 GUI 검증에는 앞서 설명한 쓰기 가능한 XDG_CONFIG_HOME/Qt 기본 DB 설정도 필요하다.
