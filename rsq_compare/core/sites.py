"""소하천 목록(예: 220개소_…_AWS_특성정보포함.xlsx)과 측정 지점 연결.

- 목록 파일에서 '필요한 열만' 골라 DB에 저장한다.
  서비스 Key, IP, RTSP URL, 담당자·업체 연락처 같은 민감 정보는 읽지도 저장하지도 않는다.
- 소하천코드로 소하천명·위치·계측기·가까운 AWS 관측소를 찾는다.
- RS5 .sum 에 GPS(위도·경도)가 있으면 가장 가까운 소하천을 '제안'만 한다(자동 확정하지 않음).
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import pandas as pd

# (DB 열, 목록 파일 머리글 후보들) — 머리글은 공백 무시하고 비교
CATALOG_COLUMNS = [
    ("site_code", ["소하천코드", "소하천 관리코드"]),
    ("river_name", ["소하천명"]),
    ("sido", ["시도"]), ("sigungu", ["시군구"]), ("emd", ["읍면동"]),
    ("obs_address", ["계측지점 주소"]),
    ("obs_lat", ["관측소 위도"]), ("obs_lon", ["관측소 경도"]),
    ("sensor_type", ["계측기 종류"]),
    ("install_date", ["계측기 설치일"]),
    ("interval_min", ["측정 시간간격"]), ("n_points", ["측점수"]),
    ("aws_id", ["AWS관측소번호"]), ("aws_name", ["AWS관측소명"]),
    ("aws_lat", ["AWS위도"]), ("aws_lon", ["AWS경도"]), ("aws_dist_km", ["AWS거리_km"]),
    ("slope", ["하상경사"]), ("length_km", ["소하천 연장 km", "소하천연장"]),
    ("area_km2", ["유역 면적 km²", "유역면적"]),
]
KOR_LABEL = {
    "site_code": "소하천코드", "river_name": "소하천명", "sido": "시도", "sigungu": "시군구", "emd": "읍면동",
    "obs_address": "계측지점 주소", "obs_lat": "관측소 위도", "obs_lon": "관측소 경도", "sensor_type": "계측기 종류",
    "install_date": "계측기 설치일", "interval_min": "측정 시간간격(분)", "n_points": "측점수",
    "aws_id": "AWS 관측소번호", "aws_name": "AWS 관측소명", "aws_lat": "AWS 위도", "aws_lon": "AWS 경도",
    "aws_dist_km": "AWS 거리(km)", "slope": "하상경사", "length_km": "소하천 연장(km)", "area_km2": "유역면적(km²)",
}
CODE_RE = re.compile(r"^\d{11}$")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s))


def read_catalog_file(path: Path) -> tuple[pd.DataFrame, list[str]]:
    """목록 파일(엑셀/CSV)을 읽어 필요한 열만 돌려준다. 반환: (표, 안내 메시지)"""
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm", ".xls"):
        raw = pd.read_excel(path, dtype=str)
    else:
        raw = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    by_norm = {_norm(c): c for c in raw.columns}
    # Excel에 숫자로 저장했어도 명시된 11자리 표시 형식의 선행 0은 보존한다.
    if path.suffix.lower() in ('.xlsx','.xlsm'):
        from openpyxl import load_workbook
        wb = load_workbook(path,read_only=True,data_only=True)
        try:
            sheet = wb.worksheets[0]
            candidates = {_norm(c) for c in CATALOG_COLUMNS[0][1]}
            columns = [i for i,c in enumerate(raw.columns) if _norm(c) in candidates]
            for row,cells in enumerate(sheet.iter_rows(min_row=2)):
                if row >= len(raw):
                    break
                for col in columns:
                    cell = cells[col]
                    if isinstance(cell.value,(int,float)) and float(cell.value).is_integer() and re.fullmatch(r'0{11}',cell.number_format):
                        raw.iat[row,col] = f'{int(cell.value):011d}'
        finally:
            wb.close()
    out = pd.DataFrame()
    msgs = []
    for key, cands in CATALOG_COLUMNS:
        src = next((by_norm[_norm(c)] for c in cands if _norm(c) in by_norm), None)
        out[key] = raw[src].map(lambda v: None if pd.isna(v) or str(v).strip() == "" else str(v).strip()) if src else None
        if src is None:
            msgs.append(f"목록에 '{cands[0]}' 열이 없어 빈값으로 둠")
    if out["site_code"].isna().all():
        raise ValueError("목록에서 '소하천코드' 열을 찾지 못했습니다.")
    out = out[out["site_code"].notna()]
    source_rows = [int(i)+2 for i in out.index]
    out = out.reset_index(drop=True)
    raw_rows = out.where(out.notna(), None).to_dict("records")
    for k in ("obs_lat", "obs_lon", "aws_lat", "aws_lon", "aws_dist_km", "slope", "length_km", "area_km2"):
        out[k] = pd.to_numeric(out[k], errors="coerce")
    counts = out.groupby('site_code',dropna=False).size()
    if (counts > 1).any():
        msgs.append(f"중복 코드 {(counts > 1).sum()}개: 모든 행을 보존하며 코드 확인 표에 표시합니다.")
    out.attrs['raw_rows'] = raw_rows
    out.attrs['source_rows'] = source_rows
    used = [c for c in raw.columns if any(_norm(c) == _norm(x) for _k, cs in CATALOG_COLUMNS for x in cs)]
    msgs.append(f"가져온 열 {len(used)}개 / 전체 {len(raw.columns)}개 "
                "(서비스 Key·IP·연락처 등 나머지 열은 읽지 않음)")
    return out, msgs


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def gps_from_sum(sum_dfs: dict) -> tuple[float | None, float | None, int]:
    """.sum 의 '위도'/'경도' 열에서 값이 있는 샘플의 중앙값. 반환: (위도, 경도, 사용한 샘플 수)"""
    lats, lons = [], []
    for df in sum_dfs.values():
        la = next((c for c in df.columns if str(c).startswith("위도")), None)
        lo = next((c for c in df.columns if str(c).startswith("경도")), None)
        if la is None or lo is None:
            continue
        d = pd.DataFrame({"a": pd.to_numeric(df[la], errors="coerce"), "o": pd.to_numeric(df[lo], errors="coerce")}).dropna()
        d = d[(d["a"].between(-90, 90)) & (d["o"].between(-180, 180)) & ~((d["a"] == 0) & (d["o"] == 0))]
        lats += d["a"].tolist()
        lons += d["o"].tolist()
    if not lats:
        return None, None, 0
    return float(pd.Series(lats).median()), float(pd.Series(lons).median()), len(lats)


def nearest_sites(catalog: pd.DataFrame, lat: float, lon: float, k: int = 3) -> pd.DataFrame:
    c = catalog.dropna(subset=["obs_lat", "obs_lon"]).copy()
    if c.empty:
        return c
    c["거리_km"] = [haversine_km(lat, lon, a, o) for a, o in zip(c["obs_lat"], c["obs_lon"])]
    return c.sort_values("거리_km").head(k)


def site_text(row) -> str:
    """지점 정보 한 덩어리 설명(화면 표시용)."""
    if row is None:
        return ""
    g = lambda k: "" if row.get(k) is None or (isinstance(row.get(k), float) and pd.isna(row.get(k))) else row.get(k)  # noqa: E731
    parts = [f"{g('river_name')} ({g('site_code')}) — {g('sido')} {g('sigungu')} {g('emd')}".strip(),
             f"계측기: {g('sensor_type')} · 측정 간격 {g('interval_min')}분 · 측점 {g('n_points')}",
             f"가까운 AWS: {g('aws_name')} (번호 {g('aws_id')}, 거리 {g('aws_dist_km')} km)"]
    return "\n".join(parts)
