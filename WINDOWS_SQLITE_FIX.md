# Windows SQLite 연결 수명 수정

대상 실행: https://github.com/hi-rice/rsq-compare/actions/runs/42135071267
실행 소스: a26d807

## 확인 범위

Actions API 조회는 여전히 Forbidden이지만, 이후 사용자가 붙여넣은 실행 로그를 대조했다.
대상은 Windows Python 3.12.10의 50개 테스트, errors=20 실행이다.
첫 오류는 `test_db_preserves_offset_raw_and_normalization`의 TemporaryDirectory 종료 중
`test.db` 삭제에서 발생한 PermissionError/WinError 32다. 본문 계산 실패를 보여주는 스택은 아니다.

| 구분 | ERROR 테스트 수 | 제공된 상세 스택 |
|---|---:|---|
| ExternalRegression | 2 | test.db / old.db 정리 중 WinError 32 |
| CatalogRegression | 3 | tearDown의 test.db 정리 중 WinError 32 |
| IdentityRegression | 11 | tearDown의 test.db 정리 중 WinError 32 |
| WorkflowTests의 search_last_of_220… | 1 | tearDown의 private.db 정리 중 WinError 32 |
| SiteRevisionTests의 trial_site… / WorkflowTests의 local_site… | 2 | 진행 목록에는 ERROR지만 전용 상세 스택이 붙여넣은 내용에서 빠짐 |
| PackagingTests의 preparation_generates… | 1 | UTF-8 version_info.txt를 기본 CP1252로 디코딩하는 경로에서 실패 |

즉 **17개는 명시적인 DB 잠금 스택**, **1개는 별도의 인코딩 문제**, **2개는 상세 스택 미확인**이다.
패키징 오류 뒤에는 테스트 헤더 없이 private.db 삭제 스택 조각이 붙어 있다.
이 조각을 누락된 두 테스트 중 어느 것인지 임의로 배정하지 않았다.
전체 20개를 하나의 SQLite 원인으로 단정하지 않는다.

상세 스택이 있는 ERROR 항목:

- ExternalRegression: db_preserves_offset_raw_and_normalization,
  legacy_schema_migration_preserves_rows_and_disables_unassigned.
- CatalogRegression: conflict_blocks_auto_join_until_user_selects,
  identical_duplicates_all_retained_but_only_one_safe_site,
  same_code_in_another_file_does_not_overwrite_old_info.
- IdentityRegression: changed_dis_with_same_raw_data_is_related,
  confirmation_does_not_overwrite_inputs_already_on_pending_version,
  confirmed_reprocessing_preserves_old_and_new_annotations,
  details_and_rsqmb_changes_are_linked_versions,
  legacy_copies_need_review_without_guessing_detail_history,
  legacy_unique_constraint_migration_keeps_ids_foreign_keys_and_backup,
  multiple_detail_aliases_are_all_fingerprinted, renamed_copy_not_registered_twice,
  selection_survives_renamed_copy_and_reimport, uncertain_relation_is_not_merged_and_requires_review,
  unused_coordinate_file_included_in_fingerprint.
- WorkflowTests: search_last_of_220_synthetic_sites_assigns_code_without_stale_row.
- PackagingTests: preparation_generates_versioned_icon_without_claiming_windows_build.

Matplotlib의 font cache 생성 메시지는 오류가 아니다.
테스트 단계가 실패해서 Inno Setup/Build installer가 미실행된 것이며,
이 로그에서 Inno Setup 자체나 설치파일 빌드 오류를 확인한 것은 아니다.

## 코드에서 재현한 원인

sqlite3.Connection의 with 범위 종료는 커밋/롤백만 하며 close를 보장하지 않는다.
앱의 backup_upgrade, _prepare_v4와 백업 대상 연결, 일부 테스트/검증 스크립트가
이 패턴을 사용했다. 특히 이미 최신 DB인 경우의 조기 반환도 연결을 남겼다.
중앙 db.connect는 정상/본문 오류에서 닫았지만 PRAGMA 실행 오류는 try 바깥이라 닫지 못했다.

새 검증은 연결의 강한 참조를 유지해 GC가 누수를 우연히 감추지 못하게 했다.
수정 전 4개 중 3개 실패: 초기 PRAGMA 오류에서 1개, 반복 초기화에서 4개,
구버전 백업/이관에서 4개의 연결이 닫히지 않은 것을 재현했다.
이는 코드에서 확정한 연결 누수다. 제공된 원격 잠금 스택과 일치하지만, Windows 재실행 결과는 별도 확인해야 한다.

## 수정

모든 앱/테스트의 직접 연결을 `with closing(sqlite3.connect(...)) as con, con:`으로
관리한다. 안쪽 Connection context가 트랜잭션을 정리하고 바깥 closing이 실제 연결을 닫는다.
정상 종료·예외·조기 반환·백업 원본/대상을 모두 포함한다.
DB 구조·계산식·테스트의 기존 기대값과 Windows 빌드 단계는 바꾸지 않았다.
테스트 제외, ignore_cleanup_errors, GC 강제 실행, 재시도/대기로 삭제 실패를 숨기지 않았다.

## 별도 인코딩 수정

빌더는 버전 파일·JSON·로그를 UTF-8로 쓰지만 패키징 테스트의 read_text()가
Windows 기본 CP1252를 사용했다. 버전 문자열 앞뒤에 한글 제품명이 있어 실패했다.
CP1252 기본 읽기를 모사한 새 검증에서 수정 전 동일 위치의 UnicodeDecodeError
(byte 0x90)를 재현했다. UTF-8을 명시하고 한글 제품명 자체와 JSON 이름도 확인한다.
Git 상태/커밋 텍스트를 읽는 빌더 subprocess에도 UTF-8을 명시했다.
오류 무시 디코딩이나 로캘 강제 변경으로 테스트를 우회하지 않았다.

## 검증

- 연결 수명 수정 당시 Linux 기존 50개 + 신규 4개 = 54개 통과.
- 인코딩 보완 후 Linux 기존 50개 + 연결 수명 4개 + CP1252 1개 = **55개 통과**.
- 신규 검증: 연결 종료 후 SELECT가 ProgrammingError인지 확인하고, 테스트 본문에서 파일을 실제 삭제한다.
- 정상 커밋/예외 롤백과 0 보존, 이관 후 기존 ID/메모/비교값, FK·무결성, 전체 백업 보존 검증.
- 첨부 구버전 데모 DB의 임시 복사본: 원래 8개 테이블 열/행 보존, 반복 이관 통과. 원본 DB 해시 불변.
- 실제 첨부 test의 기존 검증 41개 통과. T07 포함 DIS 관련 추가 항목은 자료가 없어 생략.
- 실제 Windows 테스트 통과/설치파일 생성/실제 PC 설치 확인은 별도이며 아직 확인하지 못했다.

## 새 소스로 Windows 빌드

https://github.com/hi-rice/rsq-compare/actions/workflows/windows-package.yml

`Run workflow` → Branch `main` → 초록색 `Run workflow`를 누른다.
실패한 옛 실행의 Re-run jobs는 옛 a26d807을 재실행하므로 이 수정 확인에 사용하지 않는다.
새 실행에서 소스 커밋, 테스트 58개 결과, Ensure Inno Setup, Build installer,
RSQCompare-Windows-installer artifact 생성을 각각 확인한다.
그 뒤 Python 없는 Windows PC에서 설치/실행/가져오기/저장/재실행을 별도로 확인한다.

## 이후 단계: Chocolatey Inno Setup 버전 오류

후속 제공 로그는 Ensure Inno Setup에서 패키지 `innosetup` 버전 6.4.3을
공급원에서 찾지 못해 종료된 기록이다. SQLite나 앱 계산 오류가 아니다.
공급원 확인 없이 고정했던 이 버전을 제거했다.
공식 windows-2022 러너 README의 기본 InnoSetup 6.7.1 제공을 확인하고,
기존 컴파일러를 먼저 탐색·검증하며 없을 때만 패키지를 설치하도록 수정했다.
강제 재설치/다운그레이드와 검증 우회는 사용하지 않는다.
선택한 컴파일러 경로·버전·해시를 기록하고 빌드 단계에 전달한다.
새 경로 검증 3개를 포함해 Linux 테스트 58개가 통과했다.
PowerShell 스크립트/실제 Windows 컴파일·설치 검증은 이 환경에서 실행하지 못했다.
