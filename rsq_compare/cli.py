"""화면 없이 실행하는 명령줄 버전 (검증·일괄 처리용).

사용 예)
  python -m rsq_compare.cli "D:\\data\\test" --out "D:\\결과" --select T01,T02,T03
  --select 를 생략하면 '요약 결과가 있는 모든 회차'를 비교 대상으로 선택한다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rsq_compare.core.discovery import scan_folder
from rsq_compare.core.export import export_all
from rsq_compare.core.loader import load_session


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="RSQ 회차 비교 도구 (명령줄)")
    ap.add_argument("folder", help="압축을 푼 데이터 폴더")
    ap.add_argument("--out", required=True, help="결과를 저장할 상위 폴더")
    ap.add_argument("--session", help="세션 이름 (여러 세션일 때)")
    ap.add_argument("--select", help="비교할 회차, 예: T01,T02 (생략 시 요약 결과가 있는 전체)")
    ap.add_argument("--dis", help="사용할 .dis 파일 경로 (생략 시 세션 이름과 같은 .dis)")
    ap.add_argument("--no-vel-plot", action="store_true", help=".vel 셀 속도 분포 그림 생략")
    a = ap.parse_args(argv)

    sessions, scan_checks = scan_folder(Path(a.folder))
    if not sessions:
        print("세션을 찾지 못했습니다.")
        return 1
    if a.session:
        sessions = [s for s in sessions if s.name == a.session]
        if not sessions:
            print(f"세션 '{a.session}'을 찾지 못했습니다.")
            return 1
    for s in sessions:
        print(f"[세션] {s.name}  @ {s.folder}")
        sd = load_session(s, progress=lambda m: None, dis_path=Path(a.dis) if a.dis else None)
        sd.checks[:0] = [c for c in scan_checks]
        if a.select:
            want = {x.strip().upper() for x in a.select.split(",") if x.strip()}
            sel = [r.num for r in sd.records if r.label.upper() in want]
        else:
            sel = [r.num for r in sd.records if r.has_summary]
        res = export_all(sd, sel, Path(a.out), include_vel_plot=not a.no_vel_plot, progress=print)
        print(f"  → 저장 폴더: {res['folder']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
