"""화면과 엑셀에 공통으로 쓰는 표 만들기 + 선택 회차 단순 비교통계."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

import pandas as pd

from rsq_compare.core.model import DETAIL_KINDS, SessionData
from rsq_compare.core.parsers import unit_of

STATS_TITLE = "선택 회차 단순 비교통계"
STATS_NOTE = ("※ 사용자가 체크한 회차의 'DIS에 기록된 RSQ 총유량'을 단순히 비교한 값입니다. "
              "RSQ 공식 최종유량이나 승인된 결과가 아니며, 합격/불합격·이상 회차 판정을 하지 않습니다.")

RSQ_SD_NOTE = ("RSQ 요약 패널의 표준편차는 n으로 나누는 모표준편차입니다(test 자료 8개 회차에서 RSQ 화면 1.164, "
               "COV 0.399와 일치 확인). 표본표준편차(n−1)는 같은 회차라도 값이 더 큽니다.")

KOR = {
    "width": "폭", "area": "면적", "speed": "RSQ 평균 속력", "total_q": "RSQ 총유량",
    "pct": "% Measured", "boat": "보트 속력", "track": "Track", "dmg": "DMG",
}


def dis_label(sd: SessionData, logical: str) -> str:
    h = sd.dis_colmap.get(logical)
    u = unit_of(h) if h else ""
    name = KOR.get(logical, logical)
    return f"{name} ({u}) [DIS]" if u else f"{name} [DIS]"


def q_unit(sd: SessionData) -> str:
    h = sd.dis_colmap.get("total_q")
    return unit_of(h) if h else ""


def time_basis(sd: SessionData) -> str:
    h = sd.dis_colmap.get("start", "")
    u = unit_of(h)
    return f"{u} (DIS 열 머리글 표기)" if u else "DIS에 표기 없음"


def summary_table(sd: SessionData) -> pd.DataFrame:
    rows = []
    for r in sd.records:
        raw = r.dis_row_raw or {}
        v = r.dis_values
        row = {
            "회차(원래 번호)": r.label,
            "상태": r.status,
            "요약 결과 [DIS]": "있음" if r.has_summary else "없음",
            "DIS 요약 행 번호": _int_or_none(raw.get("transect")),
            "측정 파일명 [DIS]": raw.get("file") or None,
            "시작 Edge [DIS]": raw.get("edge") or None,
            "시작 시각 [DIS 원문]": raw.get("start") or None,
            "시간 기준": time_basis(sd) if r.has_summary else None,
            "소요시간 [DIS 원문]": raw.get("duration") or None,
            "소요시간 (s) [DIS 환산]": v.get("duration_s"),
        }
        for lg in ("width", "area", "speed", "total_q", "pct"):
            row[dis_label(sd, lg)] = v.get(lg)
        for kind in DETAIL_KINDS:
            name = {"sum": ".sum", "vel": ".vel", "snr": ".snr"}[kind]
            if kind in r.load_errors:
                st = "읽기 실패"
            elif kind in r.files:
                st = "있음"
            else:
                st = "없음"
            row[f"{name} 파일"] = st
            row[f"{name} 행 수"] = r.n_rows.get(kind)
        row["구간 [rsqmb 샘플 타입]"] = r.section_summary or None
        row["샘플 번호 점검"] = r.sample_check
        row[".sum 첫 샘플 시각 [원문]"] = r.first_time_raw.get("sum")
        row[".vel 첫 샘플 시각 [원문]"] = r.first_time_raw.get("vel")
        row["DIS 시작시각 대비 첫 샘플 시각"] = r.start_time_check
        row[".sum 파일명"] = r.files["sum"].name if "sum" in r.files else None
        row[".vel 파일명"] = r.files["vel"].name if "vel" in r.files else None
        row[".snr 파일명"] = r.files["snr"].name if "snr" in r.files else None
        rows.append(row)
    return pd.DataFrame(rows)


def checks_table(sd: SessionData, extra=None) -> pd.DataFrame:
    items = list(extra or []) + list(sd.checks)
    order = {"오류": 0, "주의": 1, "정보": 2}
    df = pd.DataFrame([{"수준": c.level, "분류": c.category, "대상": c.target, "내용": c.message} for c in items])
    if df.empty:
        return pd.DataFrame(columns=["수준", "분류", "대상", "내용"])
    df["_o"] = df["수준"].map(order).fillna(9)
    return df.sort_values(["_o"], kind="stable").drop(columns="_o").reset_index(drop=True)


def dis_info_table(sd: SessionData) -> pd.DataFrame:
    rows = []
    if sd.dis is None:
        return pd.DataFrame(columns=["구역", "항목", "값(원문)"])
    for sec, kv in sd.dis.sections.items():
        for k, v in kv.items():
            rows.append({"구역": sec, "항목": k, "값(원문)": v})
    for n in sd.dis.notes:
        rows.append({"구역": "(메모)", "항목": "", "값(원문)": n})
    return pd.DataFrame(rows)


@dataclass
class SelStats:
    selected: list[str]
    used: list[tuple[str, float]] = field(default_factory=list)
    excluded: list[tuple[str, str]] = field(default_factory=list)
    n: int = 0
    mean: float | None = None
    std: float | None = None       # 표본표준편차 (n−1) — 이 프로그램 기본
    pstd: float | None = None      # 모표준편차 (n) — RSQ 요약 패널 '표준편차'와 같은 방식
    cov: float | None = None       # 모표준편차 ÷ 평균 — RSQ 요약 패널 'COV'와 같은 방식
    messages: list[str] = field(default_factory=list)
    deviation: dict[str, float | None] = field(default_factory=dict)


def selected_stats(sd: SessionData, selected_nums: list[int]) -> SelStats:
    st = SelStats(selected=[])
    for num in sorted(selected_nums):
        r = sd.record(num)
        if r is None:
            continue
        st.selected.append(r.label)
        q = r.total_q
        if q is None or (isinstance(q, float) and math.isnan(q)):
            st.excluded.append((r.label, "DIS 총유량 없음(요약 결과 없음 또는 빈값)"))
        else:
            st.used.append((r.label, q))
    st.n = len(st.used)
    vals = [q for _l, q in st.used]
    if st.n == 0:
        st.messages.append("유량값이 있는 선택 회차가 없어 통계를 계산하지 않았습니다.")
        return st
    st.mean = statistics.fmean(vals)
    st.pstd = statistics.pstdev(vals)
    if st.mean != 0:
        st.cov = st.pstd / st.mean
    if st.n >= 2:
        st.std = statistics.stdev(vals)  # 표본표준편차 (n-1)
    else:
        st.messages.append("유효 회차가 1개라 표본표준편차는 계산할 수 없습니다(n−1=0).")
    if st.mean == 0:
        st.messages.append("평균이 0이라 평균 대비 편차율과 COV를 계산할 수 없습니다.")
        st.deviation = {lab: None for lab, _q in st.used}
    else:
        st.deviation = {lab: (q - st.mean) / st.mean * 100.0 for lab, q in st.used}
    return st


def stats_tables(sd: SessionData, st: SelStats) -> tuple[pd.DataFrame, pd.DataFrame]:
    u = q_unit(sd)
    qcol = f"RSQ 총유량 ({u}) [DIS]" if u else "RSQ 총유량 [DIS]"
    detail = pd.DataFrame(
        [{"회차": lab, qcol: q, "평균 대비 편차율 (%)": st.deviation.get(lab), "비고": ""} for lab, q in st.used]
        + [{"회차": lab, qcol: None, "평균 대비 편차율 (%)": None, "비고": f"통계 제외: {why}"} for lab, why in st.excluded],
        columns=["회차", qcol, "평균 대비 편차율 (%)", "비고"],
    )
    summary = pd.DataFrame([
        {"항목": "구분", "값": STATS_TITLE},
        {"항목": "선택 회차", "값": ", ".join(st.selected) or "(없음)"},
        {"항목": "통계에 사용한 회차 수 (n)", "값": st.n},
        {"항목": f"산술평균 ({u})", "값": st.mean},
        {"항목": f"표본표준편차 ({u}, n−1로 나눔) — 이 프로그램 기본", "값": st.std},
        {"항목": f"[RSQ 방식] 모표준편차 ({u}, n으로 나눔) — RSQ 요약 패널 '표준편차'와 같은 계산", "값": st.pstd},
        {"항목": "[RSQ 방식] COV (모표준편차 ÷ 평균) — RSQ 요약 패널 'COV'와 같은 계산", "값": st.cov},
        {"항목": "두 표준편차가 다른 이유", "값": RSQ_SD_NOTE},
        {"항목": "편차율 정의", "값": "(회차 값 − 산술평균) / 산술평균 × 100"},
        {"항목": "데이터 출처", "값": "DIS에 기록된 RSQ 결과 (회차별 Total Q)"},
        {"항목": "주의", "값": STATS_NOTE},
    ] + [{"항목": "안내", "값": m} for m in st.messages])
    return summary, detail


def _int_or_none(raw):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


SECTION_COL = "구간 [rsqmb 샘플 타입]"


def sum_with_sections(sd: SessionData, num: int, section: str | None = None) -> pd.DataFrame | None:
    """.sum 표에 '구간' 열을 샘플 번호 기준으로 붙인 '복사본'을 돌려준다(원본 DataFrame은 그대로).
    section 을 주면 그 구간의 행만 남긴다. 구간 정보가 없는 회차는 열을 붙이지 않는다."""
    df = sd.sum_dfs.get(num)
    if df is None:
        return None
    sec = sd.sections.get(num)
    if sec is None:
        return df
    out = df.copy()
    key = out.columns[0]
    out.insert(1, SECTION_COL, out[key].map(sec))
    if section:
        out = out[out[SECTION_COL] == section].reset_index(drop=True)
    return out
