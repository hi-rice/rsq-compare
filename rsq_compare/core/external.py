"""외부 시계열(FEWP 수위·유량, AWS 강우 등) 읽기와 회차 시간창 연결.

입력 파일(CSV 또는 엑셀 첫 시트)은 형식을 고정하지 않는다.
- 불러올 때 '시각 열'과 '값 열(여러 개 가능)'을 사용자가 고른다.
- 시각 형식: 2026-10-29 10:40:00 / 2026/10/29 10:40 / 엑셀 날짜 /
  14자리 20261029104000 또는 12자리 202610291040
  (📘 플랫폼 보고서의 계측 일시 OBSR_DT 는 14자리 문자열)
- 원문 시간대는 보존하며, 시간대 없는 값에만 사용자 기준을 적용한다.

연결 원칙
- 자료에 소하천코드가 지정돼 있으면 '같은 소하천코드'가 입력된 세션에만 연결한다.
  코드가 없으면 사용자가 측정 등록ID를 직접 지정해야 한다.
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
_OFFSET_RE = re.compile(r"^UTC\s*(?:([+-])\s*(\d{1,2}(?:\.\d+)?)(?::(\d{2}))?)?(?:\s+\([^)]*\))?$", re.IGNORECASE)
_DIGITS_RE = re.compile(r"^\d{12}(\d{2})?$")


def parse_offset_hours(basis: str | None) -> float | None:
    """'UTC+9 (…)' → 9.0, 'UTC' → 0.0, 모르면 None."""
    if not basis:
        return None
    m = _OFFSET_RE.fullmatch(str(basis).strip())
    if not m:
        return None
    if not m.group(1):
        return 0.0
    hours, minutes = float(m.group(2)), int(m.group(3) or 0)
    if hours >= 24 or minutes >= 60 or (m.group(3) and not hours.is_integer()):
        return None
    return (hours + minutes / 60) * (-1 if m.group(1) == "-" else 1)


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


def normalize_time(value, basis=None):
    """원문 → UTC. 명시된 시간대가 우선이며 기준은 naive 값에만 적용한다."""
    if value is None or pd.isna(value) or str(value).strip() == "":
        return pd.NaT, "시각 없음"
    text = str(value).strip()
    if _DIGITS_RE.fullmatch(text):
        t = pd.to_datetime(text, format="%Y%m%d%H%M%S" if len(text) == 14 else "%Y%m%d%H%M", errors="coerce")
    else:
        t = parse_rsq_time(text)
    if t is None or pd.isna(t):
        return pd.NaT, "시각 읽기 실패"
    t = pd.Timestamp(t)
    if t.tzinfo is not None:
        return t.tz_convert("UTC"), "원문 시간대"
    off = parse_offset_hours(basis)
    if off is None or abs(off) >= 24:
        return pd.NaT, "시간 기준 미확인"
    from datetime import timezone
    return t.tz_localize(timezone(timedelta(hours=off))).tz_convert("UTC"), f"사용자 기준: {basis}"


def parse_times(s: pd.Series) -> pd.Series:
    # 혼합 시간대도 원문별로 파싱한다. naive 값에 임의의 시간대를 붙이지 않는다.
    def one(v):
        text = str(v).strip()
        if _DIGITS_RE.fullmatch(text):
            return pd.to_datetime(text, format="%Y%m%d%H%M%S" if len(text) == 14 else "%Y%m%d%H%M", errors="coerce")
        return parse_rsq_time(v) or pd.NaT
    return pd.Series([one(v) for v in s], index=s.index, dtype=object)


def normalized_values(values: pd.DataFrame, basis: str) -> pd.DataFrame:
    out = values.copy()
    source = out["t_raw"] if "t_raw" in out else out["t"]
    parsed = [normalize_time(v, basis) for v in source]
    out["t_utc"] = pd.to_datetime([v[0] for v in parsed], utc=True)
    out["time_applied"] = [v[1] for v in parsed]
    return out


RAIN_TYPES = ["미확인", "구간 강우량", "누적 강우량", "강우강도"]


def rain_summary(values, start, end, rain_type, unit, interval_minutes):
    """강우는 종류·단위·구간 전체의 연속성이 확인된 경우에만 합산한다."""
    note = {"강우 종류": rain_type or "미확인", "강우 집계": "합산 안 함"}
    if rain_type == "강우강도":
        note["강우 집계"] = "강우강도: 합산 안 함" if norm_unit(unit) in ("mm/h", "mm/hr") else "단위 미확인"
        return note
    if rain_type not in ("구간 강우량", "누적 강우량") or norm_unit(unit) != "mm":
        note["강우 집계"] = "종류·단위 확인 필요"
        return note
    if interval_minutes is None or not np.isfinite(float(interval_minutes)) or float(interval_minutes) <= 0:
        note["강우 집계"] = "기록 간격 확인 필요"
        return note
    step = pd.Timedelta(minutes=float(interval_minutes))
    # 구간값의 시각은 해당 구간의 끝. 양 경계를 포함해 연속성을 확인한다.
    v = values[(values.t_utc >= start) & (values.t_utc <= end)].sort_values("t_utc")
    if len(v) < 2 or v.t_utc.iloc[0] != start or v.t_utc.iloc[-1] != end:
        note["강우 집계"] = "시간창 경계 자료 없음"
        return note
    if v.t_utc.duplicated().any() or not v.t_utc.diff().iloc[1:].eq(step).all():
        note["강우 집계"] = "중복·빠진 시각 확인 필요"
        return note
    numbers = pd.to_numeric(v.value, errors="coerce")
    required = numbers if rain_type == "누적 강우량" else numbers.iloc[1:]
    if required.isna().any() or not np.isfinite(required).all() or (required < 0).any():
        note["강우 집계"] = "결측·음수 확인 필요"
        return note
    if rain_type == "누적 강우량":
        if numbers.diff().iloc[1:].lt(0).any():
            note["강우 집계"] = "누적값 초기화 확인 필요"
            return note
        total = float(numbers.iloc[-1] - numbers.iloc[0])
    else:
        total = float(required.sum())
    return {**note, "강우 집계": "집계함(전체 구간 확인)", "시간창 강우량(mm)": total}


def extract_series(raw: pd.DataFrame, tcol: str, vcol: str) -> tuple[pd.DataFrame, int]:
    """(시각, 값) 표와 '시각을 못 읽어 뺀 행 수'. 값이 숫자가 아니면 NaN(0으로 안 바꿈)."""
    t = parse_times(raw[tcol])
    v = pd.to_numeric(raw[vcol].replace("", np.nan), errors="coerce")
    ok = t.notna()
    df = pd.DataFrame({"t": t[ok], "t_raw": raw.loc[ok, tcol].astype(str), "value": v[ok]}).reset_index(drop=True)
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
                       unit: str | None = None, target_session_id: int | None = None,
                       rain_type: str | None = None, rain_interval_min: float | None = None,
                       n_dropped: int = 0) -> pd.DataFrame:
    """회차별로 외부값을 요약한다.
    tr: transects_df 결과 / sess: sessions_df 결과 / values: DataFrame[t, value] (외부자료 원래 기준 시각)"""
    if site_code and target_session_id is not None:
        raise ValueError("지점 또는 측정 중 하나만 지정하세요.")
    if not np.isfinite(margin_min) or margin_min < 0:
        raise ValueError("앞뒤 여유는 0 이상이어야 합니다.")
    values = normalized_values(values, series_basis)
    vt = values["t_utc"]
    vv = pd.to_numeric(values["value"], errors="coerce")
    sinfo = sess.set_index("id")
    rows = []
    for _, r in tr.iterrows():
        sid = r["session_id"]
        s_code = sinfo.at[sid, "site_code"] if "site_code" in sinfo.columns and sid in sinfo.index else None
        s_code = None if s_code is None or (isinstance(s_code, float) and pd.isna(s_code)) else s_code
        base = {"등록ID": sid, "세션": r["session_name"], "세션 소하천코드": s_code, "회차": r["label"]}
        if target_session_id is not None:
            if int(sid) != int(target_session_id):
                continue
            base["소하천 일치"] = "측정 직접 지정"
        elif site_code:
            if sid in sinfo.index and sinfo.loc[sid].get('catalog_conflict',0):
                if s_code == site_code:
                    rows.append({**base, '연결': '소하천코드 충돌 확인 필요'})
                continue
            if s_code != site_code:
                continue  # 다른 소하천(또는 코드 미입력) 세션에는 붙이지 않음
            base["소하천 일치"] = "일치"
        else:
            rows.append({**base, "연결": "연결 대상 지정 필요"})
            continue
        d_basis = sinfo.at[sid, "time_basis"] if sid in sinfo.index else None
        raw_start = r["start_time_raw"]
        start, applied = normalize_time(raw_start, d_basis)
        dur = r["duration_s"]
        if pd.isna(start) or dur is None or pd.isna(dur) or not np.isfinite(float(dur)) or float(dur) < 0:
            rows.append({**base, "연결": "시작 시각·시간 기준·소요시간 확인 필요"})
            continue
        how = "UTC로 비교(원문 시간대 우선)"
        t_dis = vt
        w0 = start - timedelta(minutes=margin_min)
        w1 = start + timedelta(seconds=float(dur)) + timedelta(minutes=margin_min)
        inside = (t_dis >= w0) & (t_dis <= w1)
        vals = vv[inside]
        mean = float(vals.mean()) if vals.notna().any() else None
        out = {**base, "연결": "연결", "시간 맞춤": how,
               "시작 시각 원문": raw_start, "시작 시각 적용 기준": applied, "시작 시각 UTC": start.isoformat(),
               "외부 시각 기준": series_basis, "시각 변환 불가 수": int(vt.isna().sum()),
               "시간창 시작 UTC": w0.isoformat(),
               "시간창 끝 UTC": w1.isoformat(),
               "앞뒤 여유(분)": margin_min, "시간창 안 자료 수": int(inside.sum()),
               "시간창 안 빈값 수": int(vals.isna().sum()), "평균": mean,
               "최소": float(vals.min()) if vals.notna().any() else None,
               "최대": float(vals.max()) if vals.notna().any() else None}
        if kind == "강우":
            if n_dropped or vt.isna().any():
                out.update({"강우 종류": rain_type or "미확인", "강우 집계": "읽지 못한 시각 확인 필요"})
            else:
                out.update(rain_summary(values, w0, w1, rain_type, unit, rain_interval_min))
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
            j = int(np.nanargmin(dist.dt.total_seconds().to_numpy()))
            out["참고: 회차 중간에 가장 가까운 자료 시각 UTC"] = t_dis.iloc[j].isoformat()
            out["참고: 자료 시각 원문"] = str(values.iloc[j].get("t_raw", values.iloc[j]["t"]))
            out["참고: 자료 적용 기준"] = values.iloc[j]["time_applied"]
            out["참고: 그 값"] = None if pd.isna(vv.iloc[j]) else float(vv.iloc[j])
            out["참고: 시간 차(분)"] = round(dist.iloc[j].total_seconds() / 60, 2)
        if inside.sum() == 0:
            out["연결"] = "시간창 안 자료 없음(보간하지 않음)"
        rows.append(out)
    if not rows:
        return pd.DataFrame([{"안내": "지정한 연결 대상이 비교 목록에 없습니다."}])
    return pd.DataFrame(rows)
