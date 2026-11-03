"""누적 DB 기능 자동 검증.

사용법: python tests/verify_db.py <원본 test 폴더> <임시 작업 폴더> <T07 포함 .dis>
※ '여러 세션' 상황은 실제 test 자료를 세션 이름만 바꿔 복사한 '가상 세션'으로 시험한다(값은 원본과 동일).
※ 기준유량·외부 시계열 값은 모두 시험용 가상 값이다.
"""
import hashlib
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from rsq_compare import cli_db  # noqa: E402
from rsq_compare.core import db  # noqa: E402
from rsq_compare.core.batch import import_folder  # noqa: E402
from rsq_compare.core.db_export import export_db  # noqa: E402
from rsq_compare.core.external import match_to_transects, read_timeseries  # noqa: E402
from rsq_compare.core.multi import session_summary  # noqa: E402

src, work, dis_t07 = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
if work.exists():
    shutil.rmtree(work)
work.mkdir(parents=True)
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def hashes(folder):
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob("*") if p.is_file()}


# ---- 시험용 폴더: A(원본 + T07 포함 .dis 후보), B(이름만 바꾼 가상 세션, 하위 폴더)
data = work / "측정자료"
shutil.copytree(src, data / "A")
shutil.copy(dis_t07, data / "A" / "test_20261029_105656_T07포함.dis")
(data / "B_가상").mkdir(parents=True)
for p in src.iterdir():
    if p.name.startswith("~$"):
        continue
    target = data / "B_가상" / p.name.replace("test_20261029_105656", "virtual_20261030_090000")
    shutil.copy(p,target)
    if p.suffix in ('.dis','.sum','.snr','.vel'):
        target.write_bytes(target.read_bytes().replace(b'2026-10-29',b'2026-10-30').replace(b'20261029',b'20261030'))
before = hashes(data)
D = work / "누적.db"

print("--- 가져오기 ---")
rep = import_folder(data, D)
check("두 세션 모두 새로 등록", sorted(rep["결과"]) == ["새로 등록", "새로 등록"], rep[["세션", "결과"]].values.tolist())
check("T07 포함 .dis는 '다른 후보'로 보고됨",
      rep.loc[rep["세션"] == "test_20261029_105656", "다른 .dis 후보"].iloc[0] == "test_20261029_105656_T07포함.dis")
rep2 = import_folder(data, D)
check("다시 가져오면 모두 건너뜀(중복 등록 없음)", (rep2["결과"] == "이미 등록됨(건너뜀)").all() and len(db.sessions_df(D)) == 2)

from rsq_compare.core.discovery import scan_folder  # noqa: E402
from rsq_compare.core.loader import load_session  # noqa: E402
sfA = next(s for s in scan_folder(data)[0] if s.name == "test_20261029_105656")
st, sid3, _ = db.register_session(D, load_session(sfA, dis_path=sfA.dis_candidates[1]))
check("다른 .dis는 재처리본으로 이력 보존", st == "version" and len(db.sessions_df(D)) == 3)

sess = db.sessions_df(D)
tr = db.transects_df(D)
summ = session_summary(sess, tr)
row = lambda dis: summ[summ["사용한 .dis"] == dis].iloc[0]  # noqa: E731
mcol = next(c for c in summ.columns if c.startswith("회차 Total Q 산술평균"))
check("원본 .dis 세션: 7개, 평균 3.3320, DIS 원문 3.332",
      row("test_20261029_105656.dis")["DIS 회차 수"] == 7 and round(row("test_20261029_105656.dis")[mcol], 4) == 3.332)
r8 = row("test_20261029_105656_T07포함.dis")
check("T07 포함 세션: 8개, 평균 2.9181, 모SD 1.164, COV 0.399",
      r8["DIS 회차 수"] == 8 and round(r8[mcol], 4) == 2.9181
      and round(r8[next(c for c in summ.columns if c.startswith("[RSQ 방식] 모표준편차"))], 3) == 1.164
      and round(r8["[RSQ 방식] COV"], 3) == 0.399)
t07 = tr[(tr["session_id"] == 1) & (tr["label"] == "T07")].iloc[0]
check("원본 .dis 등록의 T07: Total Q 빈값(NULL), DIS에 없음 표시", pd.isna(t07["total_q"]) and t07["has_summary"] == 0)
check("구간 요약도 저장", tr[(tr["session_id"] == 1) & (tr["label"] == "T01")]["section_summary"].iloc[0].startswith("시작 Edge 289–310"))

print("--- 비교 유량(예전 '기준유량' 열 이름 양식도 읽히는지) ---")
ref_csv = work / "기준_가상.csv"
ref_csv.write_text("세션,사용한_dis,기준유량,단위,출처\n"
                   "test_20261029_105656,test_20261029_105656_T07포함.dis,3.0,m³/s,가상\n"
                   "virtual_20261030_090000,,abc,m³/s,가상\n"
                   "없는세션,,3.1,m³/s,가상\n", encoding="utf-8-sig")
rr = db.import_reference_file(D, ref_csv)
check("양식: 지정한 .dis에만 적용 / 숫자 아님·없는 세션은 건너뜀",
      rr["결과"].tolist() == ["적용(1건)", "건너뜀(비교유량이 숫자가 아님)", "건너뜀(DB에 같은 세션 없음)"], rr["결과"].tolist())
summ = session_summary(db.sessions_df(D), db.transects_df(D))
r8 = summ[summ["사용한 .dis"] == "test_20261029_105656_T07포함.dis"].iloc[0]
check("차이·차이율 = (2.918137−3.0), −2.73%", round(r8["(평균 − 비교 유량) / 비교 유량 (%)"], 2) == -2.73, r8["(평균 − 비교 유량) / 비교 유량 (%)"])
check("비교 유량 없는 세션은 차이 빈값", pd.isna(summ[summ["세션"] == "virtual_20261030_090000"]["(평균 − 비교 유량) / 비교 유량 (%)"].iloc[0]))
db.set_reference(D, sid3, None)
check("비교 유량 지우기", pd.isna(db.sessions_df(D).set_index("id").loc[sid3, "ref_q"]))
db.set_reference(D, sid3, 3.0, "m³/s", "가상")

print("--- 외부 시계열 ---")
ext = work / "수위_UTC_가상.csv"
ext.write_text("시각,값\n2026-10-29 01:40:00,0.81\n2026-10-29 01:41:00,\n2026-10-29 01:42:00,0.83\n"
               "잘못된시각,9\n2026-10-29 01:45:00,0.79\n", encoding="utf-8-sig")
vals, dropped, _ = read_timeseries(ext)
check("시각 못 읽는 행 1개 제외, 빈값은 NaN 유지", dropped == 1 and vals["value"].isna().sum() == 1)
sid_s = db.add_series(D, "수위(가상)", "m", "UTC", [t.strftime("%Y-%m-%d %H:%M:%S") for t in vals["t"]],
                      list(vals["value"]), ext, dropped, target_session_id=sid3)
sess = db.sessions_df(D)
tr3 = db.transects_df(D, [sid3])
m = match_to_transects(tr3, sess, db.series_values(D, sid_s), "UTC", target_session_id=sid3)
t01 = m[m["회차"] == "T01"].iloc[0]
check("UTC로 비교해서 T01(10:40:18~10:42:08)에 연결",
      t01["시간창 안 자료 수"] == 2 and "UTC" in t01["시간 맞춤"] and t01["시간창 안 빈값 수"] == 1,
      f"{t01['시간창 안 자료 수']}개, {t01['시간 맞춤']}")
check("시간창 평균은 빈값 제외(0으로 안 바꿈): 0.83", t01["평균"] == 0.83)
check("T02(10:44:19~10:45:33) 안의 10:45:00(UTC 01:45) 자료 1개 연결", m[m["회차"] == "T02"]["시간창 안 자료 수"].iloc[0] == 1)
t03 = m[m["회차"] == "T03"].iloc[0]
check("자료 없는 회차(T03)는 '보간하지 않음' + 가장 가까운 값만 참고로", t03["시간창 안 자료 수"] == 0
      and "보간하지 않음" in t03["연결"] and t03["참고: 그 값"] == 0.79)
m_bad = match_to_transects(tr3, sess, db.series_values(D, sid_s), "모름", target_session_id=sid3)
check("시간 기준을 모르면 연결 안 함", (m_bad["시간창 안 자료 수"].fillna(0) == 0).all() and (m_bad["시각 변환 불가 수"].fillna(0) > 0).all())
m_same = match_to_transects(tr3, sess, db.series_values(D, sid_s), "UTC+9 (한국시간)", target_session_id=sid3)
check("기준을 UTC+9로 잘못 고르면 어긋남(자료 0개) → 기준 선택이 중요", (m_same["시간창 안 자료 수"].fillna(0) == 0).all())
m_mg = match_to_transects(tr3, sess, db.series_values(D, sid_s), "UTC", margin_min=5, target_session_id=sid3)
check("앞뒤 여유 5분이면 T03에도 자료 포함", m_mg[m_mg["회차"] == "T03"]["시간창 안 자료 수"].iloc[0] >= 1)

print("--- 엑셀 내보내기 / CLI ---")
chosen_ids = [sid3] + list(sess.loc[sess.session_name == "virtual_20261030_090000", "id"])
res = export_db(D, chosen_ids, work / "결과")
wb = load_workbook(res["files"][0])
check("시트 구성", {"처리정보", "세션비교", "회차전체", "비교유량_회차별", "등록시_점검내역", "외부_수위(가상)"} <= set(wb.sheetnames),
      wb.sheetnames)
check("엑셀에 수식 셀 없음", all(c.data_type != "f" for s in wb.worksheets for r in s.iter_rows() for c in r))
check("PNG 3개 이상 저장", sum(1 for p in res["files"] if p.suffix == ".png") >= 3)
code = cli_db.main(["import", str(data), "--db", str(work / "cli.db"), "--report", str(work / "보고.csv")])
check("CLI 가져오기", code == 0 and len(db.sessions_df(work / "cli.db")) == 2 and (work / "보고.csv").exists())
code = cli_db.main(["export", "--db", str(work / "cli.db"), "--out", str(work / "cli_out")])
check("CLI 내보내기", code == 0 and any((work / "cli_out").rglob("누적비교.xlsx")))

print("--- 삭제 / 원본 보존 ---")
db.delete_sessions(D, [sid3])
with sqlite3.connect(D) as con:
    left = con.execute("SELECT COUNT(*) FROM transects WHERE session_id=?", (sid3,)).fetchone()[0]
    leftr = con.execute("SELECT COUNT(*) FROM reference_q WHERE session_id=?", (sid3,)).fetchone()[0]
check("등록 삭제 시 회차·기준유량도 함께 삭제", left == 0 and leftr == 0 and len(db.sessions_df(D)) == 2)
check("측정 원본 파일 변경 없음(SHA-256)", hashes(data) == before)

print(f"\n총 {len(results)}개 중 실패 {results.count(False)}개")
sys.exit(0 if all(results) else 1)
