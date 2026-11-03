"""누적 DB 비교 결과를 엑셀(+PNG)로 저장."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font

from rsq_compare import APP_NAME, APP_VERSION
from rsq_compare.core import db
from rsq_compare.core.catalog import catalog_review
from rsq_compare.core.export import _unique_dir, write_df, write_lines
from rsq_compare.core.external import match_to_transects
from rsq_compare.core.multi import (
    NOTE_MULTI,
    fig_external,
    fig_reference,
    fig_sessions,
    reference_by_transect,
    session_summary,
)


def external_tables(db_path: Path, sess: pd.DataFrame, tr: pd.DataFrame, margin_min: float):
    """외부 시계열마다 (정보, 연결표, 값) 목록."""
    out = []
    for _, s in db.series_df(db_path).iterrows():
        vals = db.series_values(db_path, int(s["id"]))
        m = match_to_transects(tr, sess, vals, s["time_basis"], margin_min, site_code=_nn(s.get("site_code")),
                               kind=_nn(s.get("kind")), unit=_nn(s.get("unit")),
                               target_session_id=_nn(s.get("target_session_id")),
                               rain_type=_nn(s.get("rain_type")), rain_interval_min=_nn(s.get("rain_interval_min")),
                               n_dropped=int(_nn(s.get("n_dropped")) or 0))
        out.append((s, m, vals))
    return out


def export_db(db_path: Path, ids: list[int], out_parent: Path, margin_min: float = 0.0,
              progress: Callable[[str], None] | None = None) -> dict:
    from rsq_compare.core.identity import validate_comparison
    db.init_db(db_path)
    allsess = db.sessions_df(db_path)
    sess = allsess[allsess['id'].isin(ids)].reset_index(drop=True)
    validate_comparison(sess)
    say = progress or (lambda _m: None)
    out = _unique_dir(Path(out_parent) / f"누적비교_{datetime.now():%Y%m%d_%H%M%S}")
    png = out / "그래프"
    png.mkdir()
    tr = db.transects_df(db_path, list(sess["id"]))
    tr = tr[tr.compare_selected.fillna(1) == 1]
    summ = session_summary(sess, tr)
    files = []
    say("그래프 저장 중...")
    p = png / "01_세션별_총유량.png"
    fig_sessions(sess, tr).savefig(p, dpi=150)
    files.append(p)
    p = png / "02_비교유량_비교.png"
    fig_reference(summ).savefig(p, dpi=150)
    files.append(p)
    ext = external_tables(db_path, sess, tr, margin_min)
    for k, (s, m, vals) in enumerate(ext, start=1):
        shift = 0
        note = "UTC 기준 · 원문 시간대 우선"
        p = png / f"{k + 2:02d}_외부_{_safe_name(s['name'])}.png"
        fig_external(vals, m, s["name"], s["unit"] or "", note, shift).savefig(p, dpi=150)
        files.append(p)

    say("엑셀 작성 중...")
    wb = Workbook()
    ws = wb.active
    ws.title = "처리정보"
    lines = [
        ("RSQ 누적 비교 결과",), ("프로그램", f"{APP_NAME} v{APP_VERSION}"),
        ("생성 시각", f"{datetime.now():%Y-%m-%d %H:%M:%S}"), ("누적 DB 파일", str(db_path)),
        ("비교한 세션(등록ID)", ", ".join(str(i) for i in sess["id"])),
        ("유량 출처", "각 세션에 등록된 .dis의 회차별 Total Q (DIS에 기록된 RSQ 결과, 재계산 없음)"),
        ("주의", NOTE_MULTI),
        ("비교 유량", "사용자가 입력하거나 양식 파일로 불러온 값(예: 같은 시간 스마트 계측 유량). 차이·차이율만 계산, 판정 없음"),
        ("수위", "RSQ에 입력된 수위(.dis Supplemental Data)가 있으면 그 값을, 없으면 직접 입력값을 사용. 출처 표시"),
        ("소하천 정보", "사용자가 불러온 소하천 목록에서 필요한 열만 사용(서비스 Key·IP·연락처 등은 저장·출력하지 않음)"),
        ("외부 시계열", f"회차 시간창(DIS 시작~시작+소요시간, 앞뒤 여유 {margin_min}분) 안의 값만 요약. 보간 없음. "
                     "원문 시간대 우선, 시간대 없는 값에만 사용자 기준 적용. UTC로 비교"),
    ]
    write_lines(ws, lines)
    ws["A1"].font = Font(bold=True, size=13)
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 100
    for name, df in [("세션비교", summ), ("회차전체", _tr_view(tr)),
                     ("회차선택", _tr_view(db.transects_df(db_path,list(sess.id)))),
                     ("비교유량_회차별", reference_by_transect(sess, tr)),
                     ("회차별_수위", db.gauge_view(tr).drop(columns=["회차ID"], errors="ignore")),
                     ("측정지점_정보", _site_sheet(db_path, sess)),
                     ("측정버전_이력", allsess),
                     ("코드확인", catalog_review(db_path)),
                     ("등록시_점검내역", _checks(db_path, list(sess["id"])))]:
        w = wb.create_sheet(name)
        write_df(w, df if not df.empty else pd.DataFrame({"안내": ["자료 없음"]}), 1)
    for s, m, vals in ext:
        w = wb.create_sheet(f"외부_{_safe_name(s['name'])}"[:31])
        nr = write_lines(w, [("시계열 이름", s["name"]), ("자료 종류", s.get("kind")),
                             ("소하천코드", s.get("site_code") or "미지정(연결 대상 확인 필요)"),
                             ("연결할 측정ID", _nn(s.get("target_session_id"))),
                             ("강우 종류", _nn(s.get("rain_type")) or "미확인"),
                             ("강우 기록 간격(분)", _nn(s.get("rain_interval_min"))),
                             ("단위", s["unit"]), ("시간대 없는 값의 기준", s["time_basis"]),
                             ("원본 파일", s["source_file"]), ("값 개수 / 시각 못 읽어 뺀 행", f"{s['n_values']} / {s['n_dropped']}")])
        write_df(w, m if not m.empty else pd.DataFrame({"안내": ["연결할 회차 없음"]}), nr + 1)
        audit = vals.copy()
        audit["t_utc"] = audit["t_utc"].map(lambda t: None if pd.isna(t) else t.isoformat())
        w = wb.create_sheet(f"시각원문_{int(s['id'])}")
        write_df(w, audit, 1)
    xlsx = out / "누적비교.xlsx"
    wb.save(xlsx)
    return {"folder": out, "files": [xlsx] + files}


def _tr_view(tr: pd.DataFrame) -> pd.DataFrame:
    if tr.empty:
        return tr
    m = {"compare_selected": "비교에 선택(1/0)", "session_id": "등록ID", "session_name": "세션", "dis_file": "사용한 .dis", "label": "회차",
         "has_summary": "DIS에 있음(1/0)", "file_name": "측정 파일명", "start_edge": "시작 Edge",
         "start_time_raw": "시작 시각(DIS 원문)", "duration_raw": "소요시간", "duration_s": "소요시간(s)",
         "width": "폭 [DIS]", "area": "면적 [DIS]", "mean_speed": "평균 속력 [DIS]", "total_q": "Total Q [DIS]",
         "pct_measured": "% Measured [DIS]", "n_samples": ".sum 샘플 수", "section_summary": "구간 [rsqmb]"}
    return tr[list(m)].rename(columns=m)


def _checks(db_path, ids):
    df = db.reg_checks_df(db_path)
    return df[df["등록ID"].isin(ids)]


def _safe_name(s: str) -> str:
    return "".join(ch if ch not in '\\/:*?"<>|[]' else "_" for ch in str(s))[:20]


def _nn(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else v


def _site_sheet(db_path, sess: pd.DataFrame) -> pd.DataFrame:
    from rsq_compare.core.sites import KOR_LABEL
    codes = [c for c in sess.get("site_code", pd.Series(dtype=str)).dropna().unique()]
    cat = db.catalog_df(db_path)
    if cat.empty or not codes:
        return pd.DataFrame({"안내": ["소하천코드가 입력된 세션이 없거나 소하천 목록을 불러오지 않았습니다."]})
    c = cat[cat["site_code"].isin(codes)].drop(columns=["source_file", "imported_at"], errors="ignore")
    return c.rename(columns=KOR_LABEL)
