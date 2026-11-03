"""결과 저장 (엑셀 .xlsx + 그래프 .png).

- 원본 폴더의 파일은 건드리지 않고, 선택한 저장 위치 아래에 '새 폴더'를 만들어 저장한다.
- 숫자는 원본 정밀도 그대로 저장한다(화면에서만 반올림).
- '=', '+', '-', '@' 등으로 시작하는 문자열은 엑셀이 수식으로 실행하지 않도록 '문자열'로 고정한다.
- 빈값(NaN)은 빈 셀로 둔다(0으로 바꾸지 않음).
"""
from __future__ import annotations

import hashlib
import math
import platform
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from rsq_compare import APP_NAME, APP_VERSION
from rsq_compare.core.model import SessionData
from rsq_compare.core.plots import fig_depth_speed, fig_q_bar, fig_vel_profile
from rsq_compare.core.tables import (
    STATS_NOTE,
    checks_table,
    dis_info_table,
    selected_stats,
    stats_tables,
    summary_table,
    sum_with_sections,
)

FORMULA_PREFIX = ("=", "+", "-", "@", "\t", "\r")
HEADER_FILL = PatternFill("solid", fgColor="DCE6F1")

PROCESS_CONDITIONS = [
    "회차 연결: .dis 'File Name' 앞 번호(예: 08-Transect → T08)와 상세 파일명 T번호를 연결 (행 순서로 붙이지 않음)",
    "유량·폭·면적·평균 속력: DIS에 기록된 RSQ 결과를 그대로 사용 (재계산·보정·외삽 없음)",
    "시간: 모든 시각은 파일 원문 그대로. UTC/한국시간 변환 등 시간 보정 미적용",
    "결측: 빈칸/#N/A/NaN은 빈 셀로 유지 (0으로 바꾸지 않음)",
    "구간: 시작 Edge/횡단/마침 Edge는 .rsqmb 내부 Configuration.json의 SampleType(RSQ 기록값)을 샘플 번호로 연결해 표시. "
    "샘플 번호가 하나라도 안 맞거나 정보가 없으면 연결하지 않고 전체 기록만 표시 (추정·자동 분류 없음)",
    "품질 판정: SNR·유속 임계값, 합격/불합격, 이상 회차 자동 제외를 적용하지 않음",
    "비교통계: 사용자가 선택한 회차의 DIS 총유량만으로 산술평균·표본표준편차(n−1)·평균 대비 편차율 계산. "
    "참고로 RSQ 요약 패널과 같은 방식의 모표준편차(n)·COV도 함께 표시",
    ".rsqmb: 내부 JSON(Summary.json, DataSessionProperties.json, AdcpData/*/Configuration.json)만 읽음 (바이너리 원시자료 미해석)",
    ".dis: RSQ는 요약 패널에서 체크된 회차만 .dis에 넣고 전체 Total Q도 그 회차들의 평균으로 기록함. 사용한 .dis 파일명은 위 '사용한 .dis' 참고",
]


def _safe(v):
    """엑셀 셀에 넣을 값으로 변환. (값, 문자열강제여부)"""
    if v is None:
        return None, False
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return (None, False) if math.isnan(f) else (f, False)
    if isinstance(v, (np.integer,)):
        return int(v), False
    if isinstance(v, (bool, np.bool_)):
        return bool(v), False
    if isinstance(v, (int, float)):
        return v, False
    if v is pd.NA or v is pd.NaT:
        return None, False
    if isinstance(v, (datetime, pd.Timestamp)):
        return str(v), True
    s = str(v)
    return s, s.startswith(FORMULA_PREFIX)


def write_df(ws, df: pd.DataFrame, start_row: int = 1, autosize: bool = True):
    for j, col in enumerate(df.columns, start=1):
        val, _ = _safe(str(col))
        c = ws.cell(row=start_row, column=j)
        c.value = val
        c.data_type = "s"
        c.font = Font(bold=True)
        c.fill = HEADER_FILL
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for i, row in enumerate(df.itertuples(index=False), start=start_row + 1):
        for j, v in enumerate(row, start=1):
            val, force_str = _safe(v)
            c = ws.cell(row=i, column=j)
            c.value = val
            if force_str or isinstance(val, str):
                c.data_type = "s"  # 수식 실행 방지
    ws.freeze_panes = ws.cell(row=start_row + 1, column=1)
    if autosize:
        for j, col in enumerate(df.columns, start=1):
            sample = [str(col)] + [str(x) for x in df.iloc[:200, j - 1].tolist()]
            width = min(60, max(8, max(len(s) for s in sample) * 1.1 + 2))
            ws.column_dimensions[get_column_letter(j)].width = width


def write_lines(ws, lines: list[tuple], start_row: int = 1) -> int:
    r = start_row
    for line in lines:
        for j, v in enumerate(line, start=1):
            val, force = _safe(v)
            c = ws.cell(row=r, column=j)
            c.value = val
            if force or isinstance(val, str):
                c.data_type = "s"
        r += 1
    return r


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _unique_dir(base: Path) -> Path:
    p = base
    i = 2
    while p.exists():
        p = base.with_name(f"{base.name}_{i}")
        i += 1
    p.mkdir(parents=True)
    return p


def _source_files(sd: SessionData) -> list[Path]:
    files = [p for p in (sd.dis_path, sd.files.rsqmb) if p]
    for num in sorted(sd.files.details):
        files += [sd.files.details[num][k] for k in ("sum", "vel", "snr") if k in sd.files.details[num]]
    return files


def export_all(sd: SessionData, selected_nums: list[int], out_parent: Path,
               include_vel_plot: bool = True, progress: Callable[[str], None] | None = None) -> dict:
    say = progress or (lambda _m: None)
    out_parent = Path(out_parent)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = _unique_dir(out_parent / f"{sd.files.name}_비교결과_{stamp}")
    png_dir = out / "그래프"
    png_dir.mkdir()

    st = selected_stats(sd, selected_nums)
    stat_sum, stat_det = stats_tables(sd, st)
    summ = summary_table(sd)
    written: list[Path] = []

    # ------------------------------------------------------------ PNG
    say("그래프 저장 중...")
    fig = fig_q_bar(sd, selected_nums, st)
    p = png_dir / "01_회차별_총유량_DIS.png"
    fig.savefig(p, dpi=150)
    written.append(p)
    for r in sd.records:
        if r.num in sd.sum_dfs:
            p = png_dir / f"{r.label}_sum_수심_평균속력.png"
            fig_depth_speed(sd.sum_dfs[r.num], r.label, sd.sections.get(r.num)).savefig(p, dpi=150)
            written.append(p)
        if include_vel_plot and r.num in sd.vel_dfs:
            p = png_dir / f"{r.label}_vel_셀속도분포.png"
            fig_vel_profile(sd.vel_dfs[r.num], r.label, sd.sections.get(r.num))[0].savefig(p, dpi=150)
            written.append(p)

    # ------------------------------------------------------------ XLSX
    say("엑셀 작성 중...")
    wb = Workbook()
    ws = wb.active
    ws.title = "처리정보"
    src = _source_files(sd)
    lines = [
        ("RSQ 회차 비교 결과",),
        ("프로그램", f"{APP_NAME} v{APP_VERSION}"),
        ("생성 시각(이 PC 기준)", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("실행 환경", f"Python {platform.python_version()} / {platform.system()} {platform.release()}"),
        ("세션 이름", sd.files.name),
        ("원본 폴더", str(sd.files.folder)),
        ("비교 선택 회차", ", ".join(st.selected) or "(없음)"),
        ("유량 등 결과 출처", "DIS에 기록된 RSQ 결과"),
        ("사용한 .dis", sd.dis_path.name if sd.dis_path else "(없음)"),
        ("사용한 .dis 경로", str(sd.dis_path) if sd.dis_path else ""),
        ("주의", STATS_NOTE),
        (),
        ("처리 조건",),
    ] + [("", c) for c in PROCESS_CONDITIONS] + [(), ("원본 파일 목록", "파일명", "크기(byte)", "수정 시각", "SHA-256")]
    r = write_lines(ws, lines)
    for p in src:
        say(f"원본 파일 지문 계산: {p.name}")
        stt = p.stat()
        r = write_lines(ws, [("", p.name, stt.st_size,
                              datetime.fromtimestamp(stt.st_mtime).strftime("%Y-%m-%d %H:%M:%S"), _sha256(p))], r)
    ws["A1"].font = Font(bold=True, size=13)
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 70
    ws.column_dimensions["E"].width = 66

    sheets = [
        ("회차요약", summ),
        ("비교통계_선택회차", None),
        ("점검내역", checks_table(sd)),
        ("DIS_설정및결과", dis_info_table(sd)),
    ]
    for name, df in sheets:
        w = wb.create_sheet(name)
        if name == "비교통계_선택회차":
            write_df(w, stat_sum, 1)
            write_df(w, stat_det, len(stat_sum) + 4)
            w.freeze_panes = None
        else:
            write_df(w, df, 1)
    if sd.source_compare is not None:
        w = wb.create_sheet("출처비교_참고")
        nr = write_lines(w, [("※ 참고용 비교. 어느 값이 최종값인지 정하지 않음. 화면·통계는 DIS 값만 사용.",)])
        write_df(w, sd.source_compare, nr + 1)

    for rec in sd.records:
        df = sum_with_sections(sd, rec.num)
        if df is None:
            continue
        say(f"상세자료 시트 작성: {rec.label}")
        w = wb.create_sheet(f"sum_{rec.label}"[:31])
        nr = write_lines(w, [
            ("원본 파일", rec.files["sum"].name),
            ("비고", "원문 그대로(시간 변환·결측 채움 없음). "
                     + ("'구간' 열 = .rsqmb 샘플 타입을 샘플 번호로 연결한 값(이 프로그램이 추가한 열)"
                        if rec.num in sd.sections else "구간 정보 없음 → 전체 기록")),
        ])
        write_df(w, df, nr + 1)

    xlsx = out / f"{sd.files.name}_회차비교.xlsx"
    wb.save(xlsx)
    written.insert(0, xlsx)
    return {"folder": out, "files": written, "stats": st}
