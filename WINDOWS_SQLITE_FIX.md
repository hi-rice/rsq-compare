# Windows SQLite 연결 수명 수정

대상 실행: https://github.com/hi-rice/rsq-compare/actions/runs/42135071267
실행 소스: a26d807

## 확인 범위

사용자 제공 결과는 테스트 50개 후 errors=20, 임시 private.db 정리 중 WinError 32다.
이 세션의 Actions API 조회는 Forbidden이며, 실행 웹 페이지도 로그에는 로그인을 요구한다.
따라서 전체 로그의 **첫 오류와 나머지 20개 스택을 직접 분류하지 못했다**.
모든 오류가 같은 원인이라고 단정하지 않는다. 전체 로그가 제공되면 별도로 대조해야 한다.

## 코드에서 재현한 원인

sqlite3.Connection의 with 범위 종료는 커밋/롤백만 하며 close를 보장하지 않는다.
앱의 backup_upgrade, _prepare_v4와 백업 대상 연결, 일부 테스트/검증 스크립트가
이 패턴을 사용했다. 특히 이미 최신 DB인 경우의 조기 반환도 연결을 남겼다.
중앙 db.connect는 정상/본문 오류에서 닫았지만 PRAGMA 실행 오류는 try 바깥이라 닫지 못했다.

새 검증은 연결의 강한 참조를 유지해 GC가 누수를 우연히 감추지 못하게 했다.
수정 전 4개 중 3개 실패: 초기 PRAGMA 오류에서 1개, 반복 초기화에서 4개,
구버전 백업/이관에서 4개의 연결이 닫히지 않은 것을 재현했다.
이는 코드에서 확정한 누수이며 원격 20개 오류의 개별 분류와는 다르다.

## 수정

모든 앱/테스트의 직접 연결을 `with closing(sqlite3.connect(...)) as con, con:`으로
관리한다. 안쪽 Connection context가 트랜잭션을 정리하고 바깥 closing이 실제 연결을 닫는다.
정상 종료·예외·조기 반환·백업 원본/대상을 모두 포함한다.
DB 구조·계산식·테스트의 기존 기대값과 Windows 빌드 단계는 바꾸지 않았다.
테스트 제외, ignore_cleanup_errors, GC 강제 실행, 재시도/대기로 삭제 실패를 숨기지 않았다.

## 검증

- Linux에서 기존 50개 + 신규 4개 = 54개 통과.
- 신규 검증: 연결 종료 후 SELECT가 ProgrammingError인지 확인하고, 테스트 본문에서 파일을 실제 삭제한다.
- 정상 커밋/예외 롤백과 0 보존, 이관 후 기존 ID/메모/비교값, FK·무결성, 전체 백업 보존 검증.
- 첨부 구버전 데모 DB의 임시 복사본: 원래 8개 테이블 열/행 보존, 반복 이관 통과. 원본 DB 해시 불변.
- 실제 첨부 test의 기존 검증 41개 통과. T07 포함 DIS 관련 추가 항목은 자료가 없어 생략.
- 실제 Windows 테스트 통과/설치파일 생성/실제 PC 설치 확인은 별도이며 아직 확인하지 못했다.

## 새 소스로 Windows 빌드

https://github.com/hi-rice/rsq-compare/actions/workflows/windows-package.yml

`Run workflow` → Branch `main` → 초록색 `Run workflow`를 누른다.
실패한 옛 실행의 Re-run jobs는 옛 a26d807을 재실행하므로 이 수정 확인에 사용하지 않는다.
새 실행에서 소스 커밋, 테스트 54개 결과, Ensure Inno Setup, Build installer,
RSQCompare-Windows-installer artifact 생성을 각각 확인한다.
그 뒤 Python 없는 Windows PC에서 설치/실행/가져오기/저장/재실행을 별도로 확인한다.
