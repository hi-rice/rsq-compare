"""실제 첨부 자료로 핵심 요구사항을 자동 검증한다.

사용법:  python tests/verify_sample.py <압축을 푼 데이터 폴더> <임시 작업 폴더> [T07 포함으로 다시 내보낸 .dis]
※ 첨부 test 자료(test_20261029_105656) 전용 검증이다. 기대값이 이 자료에 맞춰져 있다.
각 항목은 PASS/FAIL로 출력되고, 하나라도 실패하면 종료 코드 1.
"""
import hashlib
import math
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from rsq_compare.core.discovery import scan_folder  # noqa: E402
from rsq_compare.core.export import export_all  # noqa: E402
from rsq_compare.core.loader import load_session  # noqa: E402
from rsq_compare.core.tables import selected_stats, sum_with_sections, summary_table  # noqa: E402

data, work = Path(sys.argv[1]), Path(sys.argv[2])
dis_t07 = Path(sys.argv[3]) if len(sys.argv) > 3 else None
work.mkdir(parents=True, exist_ok=True)
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def hashes(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob("*") if p.is_file()}


before = hashes(data)
sessions, scan_checks = scan_folder(data)
check("세션 1개 탐색", len(sessions) == 1, [s.name for s in sessions])
check("임시 파일(~$) 제외", any("~$" in c.target for c in scan_checks))
sd = load_session(sessions[0])
labels = [r.label for r in sd.records]
check("원래 회차 T01~T08 유지", labels == [f"T{i:02d}" for i in range(1, 9)], labels)

# --- .dis 원문과 대조 (탭 표를 직접 다시 읽어 비교)
dis_lines = sessions[0].dis.read_text(encoding="utf-8-sig").splitlines()
hdr_i = next(i for i, ln in enumerate(dis_lines) if ln.startswith("Transect\tFile Name"))
hdr = dis_lines[hdr_i].split("\t")
raw_rows = []
for ln in dis_lines[hdr_i + 1:]:
    if not ln.strip():
        break
    raw_rows.append(dict(zip(hdr, ln.split("\t"))))
by_file_num = {int(r["File Name"][:2]): r for r in raw_rows}
ok = True
for r in sd.records:
    raw = by_file_num.get(r.num)
    if raw is None:
        ok &= (not r.has_summary) and r.total_q is None
        continue
    ok &= r.dis_row_raw["file"] == raw["File Name"]
    ok &= r.total_q == float(raw["Total Q (m ³/s)"])
    ok &= r.dis_values["width"] == float(raw["Width (m)"])
    ok &= r.dis_values["area"] == float(raw["Area (m ²)"])
    ok &= r.dis_values["speed"] == float(raw["Mean Speed (m/s)"])
    ok &= r.dis_row_raw["start"] == raw["Start Time (UTC+9)"]
    ok &= r.dis_row_raw["duration"] == raw["Duration"]
check("요약 숫자가 .dis 원문과 일치(파일명 번호 기준)", ok)
t08 = sd.record(8)
check("T08은 .dis 7번째 행(08-Transect)과 연결", t08.dis_row_raw["transect"] == "7"
      and t08.dis_row_raw["file"].startswith("08-"), t08.dis_row_raw["file"])
t07 = sd.record(7)
check("T07: 상세자료 있음 / 요약 결과 없음", t07.status == "상세자료 있음 / 요약 결과 없음" and t07.total_q is None)
check("T07 유량이 0이나 다른 값으로 채워지지 않음", t07.total_q is None and t07.dis_values == {})
check("T06·T08 값이 서로 밀리지 않음", sd.record(6).total_q == 4.0229 and t08.total_q == 2.9379)

# --- 상세 파일 행 수 / 샘플 번호
n_sum = sum(len(df) for df in sd.sum_dfs.values())
n_vel = sum(len(df) for df in sd.vel_dfs.values())
n_snr = sum(len(df) for df in sd.snr_dfs.values())
check("세 상세 파일 종류 회차별 행 수 일치",
      all(r.n_rows["sum"] == r.n_rows["vel"] == r.n_rows["snr"] for r in sd.records),
      f"합계 sum={n_sum}, vel={n_vel}, snr={n_snr} (사전 설명은 625)")
check("모든 회차 샘플 번호 일치", all(r.sample_check.startswith("일치") for r in sd.records))

# --- 시간: 묵시적 보정 없음
r1 = sd.record(1)
check(".sum 시각 원문 보존(오전 1:40:18)", r1.first_time_raw["sum"] == "2026-10-29 오전 1:40:18")
check(".vel 시각 원문 보존(오전 10:40:18)", r1.first_time_raw["vel"] == "2026-10-29 오전 10:40:18")
check(".sum 표 시간열 원문 그대로", sd.sum_dfs[1]["날짜/시간"].iloc[0] == "2026-10-29 오전 1:40:18")
check("9시간 차이는 점검내역에 '관찰'로만 기록",
      any("+9:00:00" in c.message and "변환하지 않음" in c.message for c in sd.checks))

# --- 결측값 0 변환 없음
raw_sum = pd.read_csv(sd.files.details[1]["sum"], encoding="utf-8-sig", dtype=str, keep_default_na=False)
n_blank = int((raw_sum == "").sum().sum())
n_nan = int(sd.sum_dfs[1].isna().sum().sum())
check("T01 .sum 원본 빈칸 수 = 읽은 뒤 NaN 수", n_blank == n_nan, f"빈칸 {n_blank}, NaN {n_nan}")

# --- 선택 회차 통계
st = selected_stats(sd, [1, 2, 7])
check("선택 회차만 통계에 포함(T07은 제외 사유 표시)",
      [lab for lab, _ in st.used] == ["T01", "T02"] and st.excluded[0][0] == "T07")
check("산술평균·표본표준편차 계산", math.isclose(st.mean, (3.6913 + 3.5992) / 2)
      and math.isclose(st.std, abs(3.6913 - 3.5992) / math.sqrt(2)))
st1 = selected_stats(sd, [3])
check("유효 회차 1개 → 표준편차 미계산 안내", st1.std is None and st1.n == 1 and st1.messages)
st0 = selected_stats(sd, [7])
check("유효 회차 0개 → 통계 미계산 안내", st0.mean is None and st0.messages)

# --- 저장
res = export_all(sd, [1, 2, 3, 4, 5, 6, 8], work / "out")
xlsx = res["files"][0]
wb = load_workbook(xlsx)
check("엑셀 저장 및 시트 구성", {"처리정보", "회차요약", "비교통계_선택회차", "점검내역", "sum_T01", "sum_T07"} <= set(wb.sheetnames),
      ", ".join(wb.sheetnames))
pngs = [p for p in res["files"] if p.suffix == ".png"]
check("PNG 그래프 저장", len(pngs) == 17 and all(p.stat().st_size > 10000 for p in pngs), f"{len(pngs)}개")
ws = wb["sum_T01"]
hdr_row = [c.value for c in ws[4]]
col = hdr_row.index("평균 속력 (m/s)") + 1
check("엑셀 숫자 원본 정밀도 유지", ws.cell(row=5, column=col).value == 1.024, ws.cell(row=5, column=col).value)
blank_cells = sum(1 for row in ws.iter_rows(min_row=5) for c in row if c.value is None)
check("엑셀 결측은 빈 셀(0 아님)", blank_cells == n_blank, f"빈 셀 {blank_cells}")
check("엑셀에 수식 셀 없음", all(c.data_type != "f" for s in wb.worksheets for row in s.iter_rows() for c in row))
summ = pd.read_excel(xlsx, sheet_name="회차요약")
check("엑셀 요약 T07 유량 빈칸", pd.isna(summ.loc[summ["회차(원래 번호)"] == "T07", "RSQ 총유량 (m ³/s) [DIS]"]).all())

# --- 원본 불변
check("원본 파일 변경 없음(SHA-256 비교)", hashes(data) == before)

# --- 오류 내성: 사본 폴더에서 파일 누락·손상·수식 문자열
bad = work / "bad_copy"
if bad.exists():
    shutil.rmtree(bad)
shutil.copytree(data, bad)
sess_dir = next(p.parent for p in bad.rglob("*.dis"))
(next(sess_dir.glob("*_T03.snr"))).unlink()
(next(sess_dir.glob("*_T05.sum"))).write_bytes(b"\xff\xfe\x00garbage\x00\x81")
t06 = next(sess_dir.glob("*_T06.sum"))
t06_lines = t06.read_text(encoding="utf-8-sig").splitlines(keepends=True)
t06.write_text("".join(t06_lines[:-1]), encoding="utf-8")  # 마지막 샘플 1개 삭제
dis_p = next(sess_dir.glob("*.dis"))
txt = dis_p.read_text(encoding="utf-8-sig").replace("Left Bank", "=HYPERLINK(\"x\")", 1)
dis_p.write_text(txt, encoding="utf-8")
s2, _ = scan_folder(bad)
sd2 = load_session(s2[0])
check("파일 누락 기록(T03 .snr)", any(c.target == "T03" and ".snr" in c.message for c in sd2.checks))
check("손상 파일 기록 후 나머지 계속(T05 .sum)", "sum" in sd2.record(5).load_errors and len(sd2.sum_dfs) == 7)
r2 = export_all(sd2, [1, 2], work / "out_bad")
wb2 = load_workbook(r2["files"][0])
cell = next(c for row in wb2["회차요약"].iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=HYPERLINK"))
check("수식처럼 보이는 문자열을 문자열로 저장", cell.data_type == "s")
check("샘플 번호가 1개라도 다르면 구간 연결 안 함(T06)", 6 not in sd2.sections
      and any(c.target == "T06" and "구간" in c.category for c in sd2.checks))

# ================================================================ v0.2 추가 검증
print("\n--- v0.2: 구간 정보 ---")
check("8개 회차 모두 구간 연결", sorted(sd.sections) == list(range(1, 9)))
check("T01 구간 = 시작 Edge 289–310 / 횡단 311–386 / 마침 Edge 387–398",
      sd.record(1).section_summary == "시작 Edge 289–310 (22개) / 횡단 섹션 311–386 (76개) / 마침 Edge 387–398 (12개)",
      sd.record(1).section_summary)
check("RSQ 화면 교차확인: T01 샘플 312 = 횡단 섹션", sd.sections[1][312] == "횡단 섹션")
check("구간 수 합 = 각 회차 .sum 행 수", all(len(sd.sections[n]) == len(sd.sum_dfs[n]) for n in sd.sections))
v = sum_with_sections(sd, 1, "횡단 섹션")
check("구간 필터(T01 횡단 76행), 원본 표는 변경 없음", len(v) == 76 and "구간 [rsqmb 샘플 타입]" not in sd.sum_dfs[1].columns)
check("구간 열은 엑셀 sum 시트에 추가", "구간 [rsqmb 샘플 타입]" in [c.value for c in wb["sum_T01"][4]])

print("\n--- v0.2: RSQ 방식 표준편차 ---")
st7 = selected_stats(sd, [r.num for r in sd.records])
check("원본 .dis 7개: 표본SD·모SD 모두 계산", st7.n == 7 and st7.std > st7.pstd > 0,
      f"표본 {st7.std:.4f}, 모 {st7.pstd:.4f}, COV {st7.cov:.4f}")
st1b = selected_stats(sd, [3])
check("회차 1개: 모표준편차 0, 표본표준편차 계산 불가", st1b.pstd == 0 and st1b.std is None)

print("\n--- v0.2: .dis 선택 / 회차 포함·제외 설명 ---")
check("원본 .dis: 전체 Total Q = 7개 평균 점검 기록",
      any(c.category == "회차 포함/제외" and "3.332 =" in c.message and "7개" in c.message for c in sd.checks))
check("T07 요약 없음 안내에 재내보내기 방법 포함",
      any(c.target == "T07" and "유량 요약" in c.message for c in sd.checks))
check("사용한 .dis 엑셀 처리정보에 기록",
      any(row[0].value == "사용한 .dis" and row[1].value == "test_20261029_105656.dis" for row in wb["처리정보"].iter_rows()))
if dis_t07 is None:
    print("[SKIP] T07 포함 .dis가 주어지지 않아 해당 검증 생략")
else:
    alt = work / "alt_copy"
    if alt.exists():
        shutil.rmtree(alt)
    shutil.copytree(data, alt)
    alt_dir = next(p.parent for p in alt.rglob("*.dis"))
    shutil.copy(dis_t07, alt_dir / "test_20261029_105656_T07포함.dis")
    s3, _ = scan_folder(alt)
    check("다른 이름 .dis는 같은 세션의 후보로 묶임", len(s3) == 1 and len(s3[0].dis_candidates) == 2,
          [p.name for p in s3[0].dis_candidates] if s3 else "")
    sd3 = load_session(s3[0], dis_path=s3[0].dis_candidates[1])
    check("T07 포함 .dis: T07 연결(0.0208), T08 행 번호 8",
          sd3.record(7).total_q == 0.0208 and sd3.record(8).dis_row_raw["transect"] == "8")
    st8 = selected_stats(sd3, list(range(1, 9)))
    check("8개 평균 = RSQ 화면 2.9181", round(st8.mean, 4) == 2.9181, f"{st8.mean:.5f}")
    check("모표준편차 = RSQ 화면 1.164, COV = 0.399", round(st8.pstd, 3) == 1.164 and round(st8.cov, 3) == 0.399,
          f"모SD {st8.pstd:.4f}, COV {st8.cov:.4f}, 표본SD {st8.std:.4f}")
    check("후보 .dis 비교 점검 기록(7개/8개)",
          sum(1 for c in sd3.checks if c.category == ".dis 후보" and ("회차 7개" in c.message or "회차 8개" in c.message)) == 2)
    check("T07 포함 .dis: 전체 Total Q = 8개 평균 점검",
          any(c.category == "회차 포함/제외" and "2.9181 =" in c.message and "8개" in c.message for c in sd3.checks))
    r3 = export_all(sd3, list(range(1, 9)), work / "out_t07")
    wb3 = load_workbook(r3["files"][0])
    used = [row[1].value for row in wb3["처리정보"].iter_rows() if row[0].value == "사용한 .dis"]
    check("엑셀 처리정보에 T07 포함 .dis 기록", used == ["test_20261029_105656_T07포함.dis"], used)
    check("원본 test 폴더 여전히 변경 없음", hashes(data) == before)

print()
n_fail = sum(1 for _n, ok in results if not ok)
print(f"총 {len(results)}개 중 실패 {n_fail}개")
sys.exit(1 if n_fail else 0)
