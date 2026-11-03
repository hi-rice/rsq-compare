"""v0.4 (현장 자료용) 기능 자동 검증.

사용법: python tests/verify_v04.py <원본 test 폴더> <임시 작업 폴더> <소하천 목록 xlsx> <v0.3 DB(선택)>

※ 현장 측정 자료가 아직 없어서, 실제 test 자료를 복사해 '가상 현장 세션'을 만든다.
   - 가상 A: .dis의 Station Number에 실제 목록의 시동천 코드(42150340017)를 적고, 수위(Gauge Height)를 T01에만 입력
   - 가상 B: 코드 없음, .sum 위도·경도를 시동천 관측소 근처 값으로 채움(GPS 제안 시험)
   - 외부 자료(FEWP 형식 흉내, AWS 강우)도 모두 가상 값
"""
import re
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from rsq_compare.core import db  # noqa: E402
from rsq_compare.core.batch import import_folder  # noqa: E402
from rsq_compare.core.db_export import export_db  # noqa: E402
from rsq_compare.core.external import extract_series, match_to_transects, read_raw_table  # noqa: E402
from rsq_compare.core.multi import session_summary  # noqa: E402
from rsq_compare.core.sites import nearest_sites, read_catalog_file  # noqa: E402

src, work, cat_file = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
old_db = Path(sys.argv[4]) if len(sys.argv) > 4 else None
if work.exists():
    shutil.rmtree(work)
work.mkdir(parents=True)
res = []
CODE = "42150340017"  # 실제 목록의 시동천(강릉시) — 가상 세션에 붙여 쓰는 용도


def check(name, cond, detail=""):
    res.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def make_session(dst: Path, new_name: str):
    dst.mkdir(parents=True)
    for p in src.iterdir():
        if not p.name.startswith("~$"):
            shutil.copy(p, dst / p.name.replace("test_20261029_105656", new_name))
    return dst


# ---- 가상 A: Station Number = 소하천코드, T01에 RSQ 수위 기록(0.52/0.53), T03은 0(미입력일 수 있음)
A = make_session(work / "현장" / "A_가상", "fieldA_20261029_105656")
dA = next(A.glob("*.dis"))
t = dA.read_text(encoding="utf-8-sig").replace("Station Number; ", f"Station Number; {CODE}")
sup_hdr = "Transect;File Name;Start Gauge Height (m);Start Gauge Height Observation Time (UTC+9);End Gauge Height (m);End Gauge Height Observation Time (UTC+9)"
t = t.replace(sup_hdr, sup_hdr + "\n1;01-Transect_20261029102658;0.52;2026-10-29 10:40:00;0.53;2026-10-29 10:42:00"
                                  "\n3;03-Transect_20261029104534;0;;;")
dA.write_text(t, encoding="utf-8")
# ---- 가상 B: 코드 없음, GPS = 시동천 관측소(37.724945, 128.95219) 근처
B = make_session(work / "현장" / "B_가상", "fieldB_20261029_105656")
for p in B.glob("*.sum"):
    df = pd.read_csv(p, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    df["위도 (DDD.dddd)"] = "37.72520"
    df["경도 (DDD.dddd)"] = "128.95230"
    df.to_csv(p, index=False, encoding="utf-8-sig")

D = work / "v04.db"
print("--- 소하천 목록 ---")
cat, msgs = read_catalog_file(cat_file)
raw_cat = pd.read_excel(cat_file, dtype=str)
check("목록에서 필요한 열만(20개) 읽음", len(cat.columns) == 20 and "서비스 Key" not in cat.columns, msgs[-1])
n = db.save_catalog(D, cat, cat_file)
check("목록 저장", n == len(cat) and n >= 200, f"{n}곳")

print("--- 가져오기·지점 자동 연결 ---")
rep = import_folder(work / "현장", D)
sess = db.sessions_df(D)
a = sess[sess["session_name"] == "fieldA_20261029_105656"].iloc[0]
b = sess[sess["session_name"] == "fieldB_20261029_105656"].iloc[0]
check("A: RSQ Station Number의 소하천코드 자동 연결 → 시동천", a["site_code"] == CODE and a["river_name"] == "시동천"
      and a["site_code_source"] == "RSQ 기록(Station Number)", f"{a['site_code']} {a['river_name']} ({a['site_code_source']})")
check("A: 가까운 AWS 정보 표시(목록 기준)", a["aws_name"] == "옥계" and abs(a["aws_dist_km"] - 1.376) < 1e-9,
      f"{a['aws_name']} {a['aws_dist_km']} km")
check("B: 코드 없음(자동 확정 안 함)", pd.isna(b["site_code"]))
check("B: GPS 중앙값 저장", abs(b["gps_lat"] - 37.7252) < 1e-9 and b["gps_n"] == 525, f"{b['gps_lat']}, {b['gps_lon']}, n={b['gps_n']}")
near = nearest_sites(db.catalog_df(D), b["gps_lat"], b["gps_lon"], 1).iloc[0]
check("B: GPS로 가장 가까운 소하천 '제안' = 시동천(1 km 미만)", near["site_code"] == CODE and near["거리_km"] < 1,
      f"{near['river_name']} {near['거리_km']:.3f} km")
db.set_site_code(D, int(b["id"]), CODE, "GPS 제안 적용(사용자 확인)")
check("B: 제안 적용 후 출처 기록", db.sessions_df(D).set_index("id").loc[int(b["id"]), "site_code_source"] == "GPS 제안 적용(사용자 확인)")
db.set_operator(D, int(a["id"]), "홍길동(가상)")

print("--- 수위: RSQ 기록 우선, 없으면 직접 입력 ---")
trA = db.transects_df(D, [int(a["id"])])
gv = db.gauge_view(trA).set_index("회차")
check("T01: RSQ 기록(시작·끝 평균 0.525) 사용", gv.loc["T01", "사용 수위"] == 0.525 and gv.loc["T01", "출처"].startswith("RSQ 기록"))
check("T03: RSQ 0 기록은 그대로 두고 점검내역에 '확인 필요'",
      gv.loc["T03", "사용 수위"] == 0.0 and any("0으로 기록" in m for m in db.reg_checks_df(D)["내용"]))
check("T02: 기록 없음", gv.loc["T02", "출처"] == "없음" and pd.isna(gv.loc["T02", "사용 수위"]))
tid = lambda lab: int(trA[trA["label"] == lab]["id"].iloc[0])  # noqa: E731
db.set_gauge_manual(D, tid("T02"), 0.61, "2026-10-29 10:44", "현장 수위표 읽음(가상)")
db.set_gauge_manual(D, tid("T01"), 0.60, "", "")
gv = db.gauge_view(db.transects_df(D, [int(a["id"])])).set_index("회차")
check("T02: 직접 입력값 사용", gv.loc["T02", "사용 수위"] == 0.61 and gv.loc["T02", "출처"] == "직접 입력")
check("T01: RSQ와 직접 입력이 다르면 RSQ 사용 + 불일치 표시", gv.loc["T01", "사용 수위"] == 0.525 and "불일치" in gv.loc["T01", "비고"])

print("--- 외부 자료: 열 고르기, 14자리 시각, 소하천코드로만 연결 ---")
fewp = work / "FEWP_가상.csv"
fewp.write_text("SML_RVR_CD,OBSR_DT,WAL,TOT_DISCHA\n" + "\n".join(
    f"{CODE},2026102910{mm:02d}00,{0.50 + mm / 1000:.3f},{3.0 + (mm % 7) / 10:.2f}" for mm in range(36, 56, 2)),
    encoding="utf-8-sig")
raw = read_raw_table(fewp)
vals_q, dropped = extract_series(raw, "OBSR_DT", "TOT_DISCHA")
check("14자리 OBSR_DT 시각 읽기", dropped == 0 and str(vals_q["t"].iloc[0]) == "2026-10-29 10:36:00", str(vals_q["t"].iloc[0]))
sid_q = db.add_series(D, "시동천 유량(가상)", "m³/s", "UTC+9 (한국시간)", [x.strftime("%Y-%m-%d %H:%M:%S") for x in vals_q["t"]],
                      list(vals_q["value"]), fewp, dropped, site_code=CODE, kind="유량")
other = work / "다른하천_가상.csv"
other.write_text("시각,값\n2026-10-29 10:41:00,9.9\n", encoding="utf-8-sig")
vo, _ = extract_series(read_raw_table(other), "시각", "값")
sid_o = db.add_series(D, "다른 하천 수위(가상)", "m", "UTC+9 (한국시간)", [x.strftime("%Y-%m-%d %H:%M:%S") for x in vo["t"]],
                      list(vo["value"]), other, 0, site_code="42150350011", kind="수위")
sess = db.sessions_df(D)
tr = db.transects_df(D)
m = match_to_transects(tr, sess, db.series_values(D, sid_q), "UTC+9 (한국시간)", 0, site_code=CODE, kind="유량", unit="m³/s")
check("같은 소하천코드 세션(A·B)에만 연결", set(m["세션"]) == {"fieldA_20261029_105656", "fieldB_20261029_105656"})
r1 = m[(m["세션"] == "fieldA_20261029_105656") & (m["회차"] == "T01")].iloc[0]
check("유량 자료: 단위 'm³/s' = DIS 'm ³/s'로 보고 RS5 − 외부 차이 계산", r1["RS5 회차 Total Q [DIS]"] == 3.6913
      and abs(r1["RS5 − 외부 평균"] - (3.6913 - r1["평균"])) < 1e-12, f"외부 평균 {r1['평균']}, 차이 {r1['RS5 − 외부 평균']:.4f}")
m_l = match_to_transects(tr, sess, db.series_values(D, sid_q), "UTC+9 (한국시간)", 0, site_code=CODE, kind="유량", unit="L/s")
linked = m_l[m_l["연결"].isin(["연결", "시간창 안 자료 없음(보간하지 않음)"])]
check("단위가 다르면 차이 계산 안 함(연결된 회차 전부)", len(linked) > 0 and linked["RS5 − 외부 평균"].isna().all()
      and linked["비교 안내"].str.contains("단위가 달라").all(), f"연결 회차 {len(linked)}개")
m_o = match_to_transects(tr, sess, db.series_values(D, sid_o), "UTC+9 (한국시간)", 0, site_code="42150350011", kind="수위", unit="m")
check("다른 소하천 자료는 시동천 세션에 안 붙음", "안내" in m_o.columns and len(m_o) == 1, m_o.iloc[0].to_dict())
rain = work / "AWS_가상.csv"
rain.write_text("일시,강수량(mm)\n2026-10-29 10:40,0.5\n2026-10-29 10:41,1.0\n2026-10-29 10:42,\n", encoding="utf-8-sig")
vr, _ = extract_series(read_raw_table(rain), "일시", "강수량(mm)")
sid_r = db.add_series(D, "옥계 AWS 강우(가상)", "mm", "UTC+9 (한국시간)", [x.strftime("%Y-%m-%d %H:%M:%S") for x in vr["t"]],
                      list(vr["value"]), rain, 0, site_code=CODE, kind="강우")
mr = match_to_transects(tr, sess, db.series_values(D, sid_r), "UTC+9 (한국시간)", 0, site_code=CODE, kind="강우", unit="mm")
r = mr[(mr["세션"] == "fieldA_20261029_105656") & (mr["회차"] == "T01")].iloc[0]
check("강우: T01 창(10:40:18~10:42:08) 안 10:41(1.0)+10:42(빈값) → 합계 1.0, 창 밖 10:40은 제외, 빈값은 0 아님",
      r["합계(강우일 때 참고)"] == 1.0 and r["시간창 안 자료 수"] == 2 and r["시간창 안 빈값 수"] == 1)
m_none = match_to_transects(tr, sess, db.series_values(D, sid_r), "UTC+9 (한국시간)", 0, site_code=None, kind="강우")
check("소하천 미지정 자료는 시간만으로 연결 + 표시", (m_none["소하천 일치"] == "소하천 미지정 자료(시간만으로 연결)").all())

print("--- 세션 요약·엑셀·민감정보 ---")
summ = session_summary(sess, tr)
ra = summ[summ["세션"] == "fieldA_20261029_105656"].iloc[0]
check("세션 비교표에 소하천명·AWS·측정자", ra["소하천명[목록]"] == "시동천" and "옥계" in ra["가까운 AWS[목록]"]
      and ra["측정자"] == "홍길동(가상)")
out = export_db(D, list(sess["id"]), work / "결과")
wb = load_workbook(out["files"][0])
check("엑셀: 회차별_수위·측정지점_정보 시트", {"회차별_수위", "측정지점_정보"} <= set(wb.sheetnames))
secret_cols = [c for c in raw_cat.columns if any(k in c for k in ("Key", "IP", "RTSP", "연락처"))]
secrets = {str(v) for c in secret_cols for v in raw_cat[c].dropna() if len(str(v)) >= 6}
text = " ".join(str(c.value) for s in wb.worksheets for row in s.iter_rows() for c in row if c.value is not None)
check("엑셀에 서비스 Key·IP·연락처 값이 하나도 없음", not any(x in text for x in secrets), f"검사한 민감 값 {len(secrets)}개")
blob = D.read_bytes().decode("utf-8", errors="ignore")
check("DB 파일에도 민감 값 없음", not any(x in blob for x in secrets))

print("--- 예전(v0.3) DB 업그레이드 ---")
if old_db and old_db.exists():
    cp = work / "old_v03.db"
    shutil.copy(old_db, cp)
    with sqlite3.connect(cp) as con:
        before = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    db.init_db(cp)
    s2 = db.sessions_df(cp)
    check("v0.3 DB를 열면 새 칸이 추가되고 기존 등록은 그대로", len(s2) == before and "site_code" in s2.columns, f"{before}건")
else:
    print("[SKIP] v0.3 DB가 주어지지 않음")

print(f"\n총 {len(res)}개 중 실패 {res.count(False)}개")
sys.exit(0 if all(res) else 1)
