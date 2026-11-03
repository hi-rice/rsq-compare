"""누적 DB 명령줄 도구 (자동화용).

예)
  가져오기:  python -m rsq_compare.cli_db import "D:\\측정자료" --db "D:\\RSQ_측정기록.db"
  소하천목록: python -m rsq_compare.cli_db sites 220개소_…xlsx --db ...
  비교유량:  python -m rsq_compare.cli_db ref templates\\비교유량_양식.csv --db ...
  외부자료:  python -m rsq_compare.cli_db ext FEWP.csv --time OBSR_DT --value WAL --kind 수위 --unit m
             --site 42150340017 --name "시동천 수위" --basis "UTC+9 (한국시간)" --db ...
  목록:      python -m rsq_compare.cli_db list --db ...
  내보내기:  python -m rsq_compare.cli_db export --db ... --out "D:\\결과" [--ids 1,2,3] [--margin 5]

'가져오기'를 Windows 작업 스케줄러에 등록하면 새 측정 폴더를 주기적으로 자동 등록할 수 있다
(같은 .dis는 다시 등록되지 않음).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from rsq_compare.core import db
from rsq_compare.core.batch import import_folder
from rsq_compare.core.db_export import export_db
from rsq_compare.core.external import KIND_CHOICES, TIME_BASIS_CHOICES, read_timeseries
from rsq_compare.core.sites import read_catalog_file


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="RSQ 누적 DB 도구")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import", help="폴더 안의 측정 세션을 모두 등록(이미 있는 것은 건너뜀)")
    p.add_argument("folder")
    p.add_argument("--db", required=True)
    p.add_argument("--report", help="가져오기 보고를 CSV로 저장할 경로")
    p = sub.add_parser("sites", help="소하천 목록(220개소 등) 불러오기 — 필요한 열만 저장")
    p.add_argument("file")
    p.add_argument("--db", required=True)
    p = sub.add_parser("ref", help="비교 유량 양식 불러오기")
    p.add_argument("file")
    p.add_argument("--db", required=True)
    p = sub.add_parser("ext", help="외부 시계열(수위·강우 등) 불러오기")
    p.add_argument("file")
    p.add_argument("--db", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--unit", default="")
    p.add_argument("--basis", required=True, help=f"시간 기준. 예: {TIME_BASIS_CHOICES}")
    p.add_argument("--time", help="시각 열 이름(생략 시 자동)")
    p.add_argument("--value", help="값 열 이름(생략 시 '값' 또는 두 번째 열)")
    p.add_argument("--kind", default="기타", help=f"자료 종류: {KIND_CHOICES}")
    p.add_argument("--site", help="소하천코드(지정하면 같은 소하천 세션에만 연결)")
    p = sub.add_parser("list", help="등록된 세션 목록")
    p.add_argument("--db", required=True)
    p = sub.add_parser("export", help="비교 결과 엑셀·그래프 저장")
    p.add_argument("--db", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--ids", help="등록ID 목록(쉼표). 생략 시 전체")
    p.add_argument("--margin", type=float, default=0.0, help="외부 시계열 시간창 앞뒤 여유(분)")
    a = ap.parse_args(argv)
    dbp = Path(a.db)

    if a.cmd == "import":
        rep = import_folder(Path(a.folder), dbp, progress=print)
        print(rep[["세션", "사용한 .dis", "결과"]].to_string(index=False))
        if a.report:
            rep.to_csv(a.report, index=False, encoding="utf-8-sig")
    elif a.cmd == "sites":
        cat, msgs = read_catalog_file(Path(a.file))
        n = db.save_catalog(dbp, cat, Path(a.file))
        print(f"소하천 {n}곳 저장", *msgs, sep="\n  ")
    elif a.cmd == "ref":
        print(db.import_reference_file(dbp, Path(a.file)).to_string(index=False))
    elif a.cmd == "ext":
        vals, dropped, how = read_timeseries(Path(a.file), a.time, a.value)
        sid = db.add_series(dbp, a.name, a.unit, a.basis, [t.strftime("%Y-%m-%d %H:%M:%S") for t in vals["t"]],
                            list(vals["value"]), Path(a.file), dropped, site_code=a.site, kind=a.kind)
        print(f"시계열 #{sid} 저장: {len(vals)}개 값({how}), 시각을 못 읽어 뺀 행 {dropped}개")
    elif a.cmd == "list":
        db.init_db(dbp)
        s = db.sessions_df(dbp)
        print(s[["id", "session_name", "dis_file", "site_code", "river_name", "n_transects_dis", "dis_total_q_raw",
                 "ref_q"]].to_string(index=False)
              if not s.empty else "등록된 세션 없음")
    elif a.cmd == "export":
        s = db.sessions_df(dbp)
        ids = [int(x) for x in a.ids.split(",")] if a.ids else list(s["id"])
        res = export_db(dbp, ids, Path(a.out), a.margin, progress=print)
        print(f"저장 폴더: {res['folder']}")
    return 0


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    sys.exit(main())
