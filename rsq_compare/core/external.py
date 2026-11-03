"""외부 시계열(FEWP 수위·유량, AWS 강우 등) 읽기와 회차 시간창 연결.

입력 파일(CSV 또는 엑셀 첫 시트)은 형식을 고정하지 않는다.
- 불러올 때 '시각 열'과 '값 열(여러 개 가능)'을 사용자가 고른다.
- 시각 형식: 2026-10-29 10:40:00 / 2026/10/29 10:40 / 엑셀 날짜 /
  14자리 20261029104000 또는 12자리 202610291040
  (📘 플랫폼 보고서의 계측 일시 OBSR_DT 는 14자리 문자열)
- 시간 기준(UTC+9 / UTC)은 파일에 없으므로 사용자가 지정한다.

연결 원칙
- 자료에 소하천코드가 지정돼 있으면 '같은 소하천코드'가 입력된 세션에만 연결한다.
  지정이 없으면 시간만으로 연결하되, 표에 '소하천 미지정'이라고 표시한다.
- 회차 시간창 = DIS 시작시각 ~ 시작시각 + 소요시간(+앞뒤 여유). 그 안의 값만 요약, 보간 없음.
- 자료 종류가 '유량'이고 단위가 RS5와 같으면 RS5 회차 Total Q와의 차이·차이율을 보여준다(판정 없음).
"""
from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from rsq_compare.core.parsers import ENCODINGS, parse_rsq_time

TIME_BASIS_CHOICES = ["UTC+9 (한국시간)", "UTC"]
KIND_CHOICES = ["수위", "유량", "강우", "유속", "기타"]
_OFFSET_RE = re.compile(r"UTC\s*([+-]\s*\d+(?:\.\d+)?)?", re.IGNORECASE)
_DIGITS_RE = re.compile(r"^\d{12}(\d{2})?$")


def parse_offset_hours(basis: str | None) -> float | None:
    """'UTC+9 (…)' → 9.0, 'UTC' → 0.0, 모르면 None."""
    if not basis:
        return None
    m = _OFFSET_RE.search(basis)
    if not m:
        return None
    return float(m.group(1).replace(" ", "")) if m.group(1) else 0.0


def norm_unit(u: str | None) -> str:
    """단위 비교용: 공백 제거, ³→3, 대소문자 무시. 'm ³/s' == 'm³/s' == 'm3/s'."""
    if not u:
        return ""
    s = str(u).replace(" ", "").replace("³", "3").replace("²", "2").lower()
    return {"cms": "m3/s"}.get(s, s)


def read_raw_table(path: Path) -> pd.DataFrame:
    """파일을 문자열 표로 읽는다(열 고르기 화면용)."""
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm", ".xls"):
        df = pd.read_excel(path, dtype=str)
    else:
        df, last = None, None
        for enc in ENCODINGS:
            try:
                df = pd.read_csv(path, encoding=enc, dtype=str, keep_default_na=False)
                break
            except UnicodeDecodeError as e:
                last = e
        if df is None:
            raise ValueError(f"글자 인코딩을 알 수 없습니다: {last}")
    df.columns = [str(c).strip() for c in df.columns]
    if df.shape[1] < 2:
        raise ValueError("열이 2개 이상 필요합니다(시각, 값).")
    return df


def guess_time_column(df: pd.DataFrame) -> str:
    for c in df.columns:
        if any(k in c for k in ("시각", "일시", "시간", "날짜", "OBSR_DT", "datetime", "time", "date", "Time", "Date")):
            return c
    return df.columns[0]


def parse_times(s: pd.Series) -> pd.Series:
    def one(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return pd.NaT
        t = str(v).strip()
        if _DIGITS_RE.match(t):
            return pd.to_datetime(t, format="%Y%m%d%H%M%S" if len(t) == 14 else "%Y%m%d%H%M", errors="coerce")
        return pd.to_datetime(t, errors="coerce")
    out = s.map(one)
    out = pd.to_datetime(out, errors="coerce")
    if getattr(out.dt, "tz", None) is not None:
        out = out.dt.tz_localize(None)
    return out


def extract_series(raw: pd.DataFrame, tcol: str, vcol: str) -> tuple[pd.DataFrame, int]:
    """(시각, 값) 표와 '시각을 못 읽어 뺀 행 수'. 값이 숫자가 아니면 NaN(0으로 안 바꿈)."""
    t = parse_times(raw[tcol])
    v = pd.to_numeric(raw[vcol].replace("", np.nan), errors="coerce")
    ok = t.notna()
    df = pd.DataFrame({"t": t[ok], "value": v[ok]}).sort_values("t").reset_index(drop=True)
    return df, int((~ok).sum())


def read_timeseries(path: Path, tcol: str | None = None, vcol: str | None = None) -> tuple[pd.DataFrame, int, str]:
    """간단 사용(명령줄 등): 시각/값 열을 안 주면 '시각'·'값' 또는 앞 두 열."""
    raw = read_raw_table(path)
    cols = list(raw.columns)
    tcol = tcol or ("시각" if "시각" in cols else guess_time_column(raw))
    vcol = vcol or ("값" if "값" in cols else next(c for c in cols if c != tcol))
    df, dropped = extract_series(raw, tcol, vcol)
    return df, dropped, f"시각='{tcol}', 값='{vcol}'"


def match_to_transects(tr: pd.DataFrame, sess: pd.DataFrame, values: pd.DataFrame, series_basis: str,
                       margin_min: float = 0.0, site_code: str | None = None, kind: str | None = None,
                       unit: str | None = None) -> pd.DataFrame:
    """회차별로 외부값을 요약한다.
    tr: transects_df 결과 / sess: sessions_df 결과 / values: DataFrame[t, value] (외부자료 원래 기준 시각)"""
    s_off = parse_offset_hours(series_basis)
    vt = pd.to_datetime(values["t"], errors="coerce")
    vv = pd.to_numeric(values["value"], errors="coerce")
    sinfo = sess.set_index("id")
    rows = []
    for _, r in tr.iterrows():
        sid = r["session_id"]
        s_code = sinfo.at[sid, "site_code"] if "site_code" in sinfo.columns and sid in sinfo.index else None
        s_code = None if s_code is None or (isinstance(s_code, float) and pd.isna(s_code)) else s_code
        base = {"등록ID": sid, "세션": r["session_name"], "세션 소하천코드": s_code, "회차": r["label"]}
        if site_code:
            if s_code != site_code:
                continue  # 다른 소하천(또는 코드 미입력) 세션에는 붙이지 않음
            base["소하천 일치"] = "일치"
        else:
            base["소하천 일치"] = "소하천 미지정 자료(시간만으로 연결)"
        start = parse_rsq_time(r["start_time_raw"]) if r["start_time_raw"] else None
        dur = r["duration_s"]
        d_basis = sinfo.at[sid, "time_basis"] if sid in sinfo.index else None
        d_off = parse_offset_hours(d_basis)
        if start is None or dur is None or pd.isna(dur):
            rows.append({**base, "연결": "연결 안 함(이 .dis에 회차 요약 없음 → 시작시각·소요시간 모름)"})
            continue
        if d_off is None or s_off is None:
            rows.append({**base, "연결": f"연결 안 함(시간 기준 불명: DIS='{d_basis}', 외부='{series_basis}')"})
            continue
        shift = d_off - s_off
        how = "같은 시간 기준, 변환 없음" if shift == 0 else (
            f"외부자료 {series_basis} → DIS {str(d_basis).split(' ')[0]}: {shift:+g}시간 이동(두 기준 모두 명시된 경우만)")
        t_dis = vt + pd.to_timedelta(shift, unit="h")
        w0 = start - timedelta(minutes=margin_min)
        w1 = start + timedelta(seconds=float(dur)) + timedelta(minutes=margin_min)
        inside = (t_dis >= w0) & (t_dis <= w1)
        vals = vv[inside]
        mean = float(vals.mean()) if vals.notna().any() else None
        out = {**base, "연결": "연결", "시간 맞춤": how,
               "시간창 시작(DIS 기준)": w0.strftime("%Y-%m-%d %H:%M:%S"),
               "시간창 끝(DIS 기준)": w1.strftime("%Y-%m-%d %H:%M:%S"),
               "앞뒤 여유(분)": margin_min, "시간창 안 자료 수": int(inside.sum()),
               "시간창 안 빈값 수": int(vals.isna().sum()), "평균": mean,
               "최소": float(vals.min()) if vals.notna().any() else None,
               "최대": float(vals.max()) if vals.notna().any() else None}
        if kind == "강우" and vals.notna().any():
            out["합계(강우일 때 참고)"] = float(vals.sum())
        if kind == "유량":
            q = r.get("total_q")
            q = None if q is None or pd.isna(q) else float(q)
            out["RS5 회차 Total Q [DIS]"] = q
            q_unit = sinfo.at[sid, "q_unit"] if sid in sinfo.index else None
            if norm_unit(unit) and norm_unit(unit) == norm_unit(q_unit):
                if q is not None and mean is not None:
                    out["RS5 − 외부 평균"] = q - mean
                    out["(RS5 − 외부) / 외부 (%)"] = (q - mean) / mean * 100 if mean != 0 else None
            else:
                out["RS5 − 외부 평균"] = None
                out["비교 안내"] = f"단위가 달라 차이를 계산하지 않음(RS5 '{q_unit}', 외부 '{unit or '미입력'}')"
        if vt.notna().any():
            mid = start + timedelta(seconds=float(dur) / 2)
            dist = (t_dis - mid).abs()
            j = int(np.nanargmin(dist.values.astype("timedelta64[s]").astype(float)))
            out["참고: 회차 중간에 가장 가까운 자료 시각(DIS 기준)"] = t_dis.iloc[j].strftime("%Y-%m-%d %H:%M:%S")
            out["참고: 그 값"] = None if pd.isna(vv.iloc[j]) else float(vv.iloc[j])
            out["참고: 시간 차(분)"] = round(dist.iloc[j].total_seconds() / 60, 2)
        if inside.sum() == 0:
            out["연결"] = "시간창 안 자료 없음(보간하지 않음)"
        rows.append(out)
    if not rows:
        return pd.DataFrame([{"안내": f"이 자료의 소하천코드({site_code})가 입력된 세션이 비교 대상에 없습니다."}])
    return pd.DataFrame(rows)
