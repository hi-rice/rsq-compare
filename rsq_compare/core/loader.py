"""세션 읽기와 회차 연결.

핵심 원칙
1) .dis 회차표의 행 순서로 T01~T08을 붙이지 않는다.
   → .dis 'File Name' 앞 번호(예: '08-Transect_...'의 08)와
     상세 파일명의 T번호(예: ..._T08.sum)를 연결 키로 쓴다.
   → 추가로 .dis 시작시각과 상세 파일 첫 샘플 시각을 '비교만' 해서 점검내역에 남긴다.
2) 상세 파일끼리(.sum/.vel/.snr)는 행 수가 같다는 이유로 결합하지 않고,
   샘플 번호(첫 열) 값의 중복·일치 여부를 확인해 기록한다.
3) 시간대 변환/보정은 하지 않는다. 관찰된 차이만 기록한다.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Callable

import pandas as pd

from rsq_compare.core.model import (
    DETAIL_KINDS,
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_WARN,
    CheckItem,
    SessionData,
    SessionFiles,
    TransectRecord,
)
from rsq_compare.core.parsers import (
    unit_of,
    dis_overview,
    parse_dis,
    parse_hms,
    parse_rsq_time,
    read_detail_csv,
    read_rsqmb_json,
    read_rsqmb_sections,
    to_number,
)

# .dis 회차표에서 찾을 열 (논리이름, 머리글 접두어). 단위는 실제 머리글에서 읽는다.
DIS_COLUMNS = [
    ("transect", "Transect"),
    ("file", "File Name"),
    ("edge", "Start Edge"),
    ("start", "Start Time"),
    ("duration", "Duration"),
    ("track", "Track"),
    ("dmg", "DMG"),
    ("width", "Width"),
    ("area", "Area"),
    ("boat", "Boat Speed"),
    ("speed", "Mean Speed"),
    ("total_q", "Total Q"),
    ("mb_q", "Moving Bed Corrected Q"),
    ("pct", "% Measured"),
]
DIS_NUMERIC = {"track", "dmg", "width", "area", "boat", "speed", "total_q", "mb_q", "pct"}
FILE_NUM_RE = re.compile(r"^\s*(\d+)\s*-")

ProgressCb = Callable[[str], None]


def _match_header(header: list[str], prefix: str) -> str | None:
    for h in header:
        hs = h.strip()
        if hs == prefix or hs.startswith(prefix + " ") or hs.startswith(prefix + "("):
            return hs
    return None


def find_transect_table(dis):
    for t in dis.tables:
        if _match_header(t.header, "File Name") and _match_header(t.header, "Total Q") and t.rows:
            return t
    for t in dis.tables:  # 행이 없더라도 머리글이 맞으면 사용
        if _match_header(t.header, "File Name") and _match_header(t.header, "Total Q"):
            return t
    return None


def load_session(sf: SessionFiles, progress: ProgressCb | None = None,
                 dis_path: Path | None = None) -> SessionData:
    """세션 읽기. dis_path 를 주면 그 .dis 를 사용한다(다른 이름으로 다시 내보낸 .dis 선택용)."""
    say = progress or (lambda _m: None)
    checks: list[CheckItem] = list(sf.notes)
    dis_file = Path(dis_path) if dis_path else sf.dis

    # ------------------------------------------------------------ .dis
    dis = None
    colmap: dict[str, str] = {}
    dis_rows_by_num: dict[int, dict[str, str]] = {}
    if dis_file is not None:
        say(f".dis 읽는 중: {dis_file.name}")
        checks.append(CheckItem(LEVEL_INFO, "사용한 .dis", dis_file.name,
                                f"요약 결과는 이 .dis 파일에서 읽음: {dis_file}"))
        try:
            dis = parse_dis(dis_file)
            for w in dis.warnings:
                checks.append(CheckItem(LEVEL_WARN, ".dis 구조", dis_file.name, w))
        except Exception as e:  # noqa: BLE001
            checks.append(CheckItem(LEVEL_ERROR, "읽기 실패", dis_file.name, f".dis를 읽지 못함: {e}"))
    if dis is not None:
        table = find_transect_table(dis)
        if table is None:
            checks.append(CheckItem(LEVEL_WARN, ".dis 구조", dis_file.name,
                                    "회차별 결과표('File Name', 'Total Q' 열)를 찾지 못함"))
        else:
            for logical, prefix in DIS_COLUMNS:
                h = _match_header(table.header, prefix)
                if h:
                    colmap[logical] = h
            missing = [p for lg, p in DIS_COLUMNS if lg not in colmap and lg != "mb_q"]
            if missing:
                checks.append(CheckItem(LEVEL_INFO, ".dis 구조", dis_file.name,
                                        f"회차표에 없는 열(빈값으로 표시): {', '.join(missing)}"))
            idx = {h: i for i, h in enumerate(h.strip() for h in table.header)}
            seen: Counter = Counter()
            parsed: list[tuple[int | None, dict[str, str]]] = []
            for row_i, cells in enumerate(table.rows, start=1):
                raw = {lg: (cells[idx[h]].strip() if idx[h] < len(cells) else "") for lg, h in colmap.items()}
                m = FILE_NUM_RE.match(raw.get("file", ""))
                num = int(m.group(1)) if m else None
                if num is None:
                    checks.append(CheckItem(LEVEL_WARN, "회차 연결", f".dis {row_i}행",
                                            f"파일명 '{raw.get('file', '')}'에서 회차 번호를 찾지 못해 연결하지 않음"))
                else:
                    seen[num] += 1
                parsed.append((num, raw))
            for num, raw in parsed:
                if num is None:
                    continue
                if seen[num] > 1:
                    checks.append(CheckItem(LEVEL_WARN, "회차 연결", f"T{num:02d}",
                                            f".dis 파일명 번호 {num:02d}가 {seen[num]}번 나와 어느 행인지 확정할 수 없어 연결하지 않음"))
                    continue
                dis_rows_by_num[num] = raw
                tr = raw.get("transect", "")
                if tr and tr.isdigit() and int(tr) != num:
                    checks.append(CheckItem(LEVEL_INFO, "회차 연결", f"T{num:02d}",
                                            f".dis 요약 행 번호({tr})와 원래 회차 번호({num})가 다름 → 파일명 번호 기준으로 연결"))

    gauge_by_num = _read_gauge_heights(dis, checks, dis_file) if dis is not None else {}

    # ------------------------------------------------------------ 상세 파일
    sum_dfs: dict[int, pd.DataFrame] = {}
    vel_dfs: dict[int, pd.DataFrame] = {}
    snr_dfs: dict[int, pd.DataFrame] = {}
    store = {"sum": sum_dfs, "vel": vel_dfs, "snr": snr_dfs}

    all_nums = sorted(set(sf.details) | set(dis_rows_by_num))
    records: list[TransectRecord] = []
    for num in all_nums:
        label = sf.labels.get(num, f"T{num:02d}")
        rec = TransectRecord(num=num, label=label)
        rec.files = dict(sf.details.get(num, {}))
        for kind in DETAIL_KINDS:
            p = rec.files.get(kind)
            rec.n_rows[kind] = None
            rec.first_time_raw[kind] = None
            if p is None:
                continue
            say(f"읽는 중: {p.name}")
            try:
                df = read_detail_csv(p)
                store[kind][num] = df
                rec.n_rows[kind] = len(df)
                tcol = _time_col(df)
                if tcol and len(df):
                    v = df[tcol].iloc[0]
                    rec.first_time_raw[kind] = None if pd.isna(v) else str(v)
            except Exception as e:  # noqa: BLE001
                rec.load_errors[kind] = str(e)
                checks.append(CheckItem(LEVEL_ERROR, "읽기 실패", p.name, f"파일을 읽지 못함: {e}"))
        for kind in DETAIL_KINDS:
            if kind not in rec.files:
                checks.append(CheckItem(LEVEL_WARN, "파일 누락", label, f"{_kind_name(kind)} 파일 없음"))

        raw = dis_rows_by_num.get(num)
        if raw is not None:
            rec.dis_row_raw = raw
            rec.dis_values = {lg: to_number(raw.get(lg)) for lg in DIS_NUMERIC if lg in raw}
            rec.dis_values["duration_s"] = parse_hms(raw.get("duration"))
        rec.gauge = gauge_by_num.get(num, {})
        rec.sample_check = _check_samples(rec, store, checks)
        rec.start_time_check = _check_start_time(rec, checks)
        rec.status = _status(rec)
        if not rec.has_summary and rec.files:
            checks.append(CheckItem(LEVEL_WARN, "요약 결과 없음", label,
                                    "상세자료는 있으나 사용한 .dis 회차표에 이 회차 번호의 행이 없음 "
                                    "(유량을 0이나 다른 값으로 채우지 않음). "
                                    "RSQ는 요약 패널(Ctrl+S)에서 체크된 회차만 .dis에 넣으므로, 내보낼 때 이 회차가 "
                                    "체크 해제돼 있었을 수 있음(test 세션 T07에서 재내보내기로 확인된 동작). "
                                    "포함하려면 RSQ 요약 패널에서 체크 → 내보내기 > 유량 요약으로 새 .dis를 만들고 "
                                    "상단 'DIS 파일'에서 선택"))
        records.append(rec)

    _check_time_offsets(records, store, checks)
    if dis is not None:
        _check_dis_total(dis, dis_rows_by_num, dis_file, checks)
    if len(sf.dis_candidates) > 1:
        _compare_dis_candidates(sf.dis_candidates, dis_file, checks)

    # ------------------------------------------------------------ .rsqmb (참고)
    summary = props = None
    compare = None
    if sf.rsqmb is not None:
        say(f".rsqmb 참고정보 읽는 중: {sf.rsqmb.name}")
        summary, props, msgs = read_rsqmb_json(sf.rsqmb)
        for m in msgs:
            checks.append(CheckItem(LEVEL_INFO, ".rsqmb 참고", sf.rsqmb.name, m))
        if props and props.get("DataCollectionLocalTimeUtcOffset"):
            checks.append(CheckItem(LEVEL_INFO, "시간 기준", sf.rsqmb.name,
                                    f"DataSessionProperties.json에 DataCollectionLocalTimeUtcOffset="
                                    f"{props['DataCollectionLocalTimeUtcOffset']} 기록 있음 "
                                    "(참고로만 표시, 어떤 시간 변환에도 사용하지 않음)"))
        if summary:
            compare = _source_compare(dis, colmap, dis_rows_by_num, summary, checks, sf)
        say("구간 정보(시작 Edge/횡단/마침 Edge) 읽는 중...")
        sections = _link_sections(sf, records, store, checks)
    else:
        sections = {}
        checks.append(CheckItem(LEVEL_INFO, "구간 정보", sf.name,
                                ".rsqmb 파일이 없어 시작 Edge/횡단/마침 Edge 구간 정보를 표시할 수 없음 → 전체 기록 표시"))

    return SessionData(
        files=sf, dis=dis, dis_colmap=colmap, records=records,
        sum_dfs=sum_dfs, vel_dfs=vel_dfs, snr_dfs=snr_dfs, checks=checks,
        rsqmb_summary=summary, rsqmb_props=props, source_compare=compare,
        dis_path=dis_file, sections=sections,
    )


# ---------------------------------------------------------------- 보조 함수
def _kind_name(kind: str) -> str:
    return {"sum": ".sum", "vel": ".vel", "snr": ".snr"}[kind]


def _time_col(df: pd.DataFrame) -> str | None:
    for c in df.columns:
        if "날짜" in str(c) or "시간" in str(c) or "time" in str(c).lower():
            return c
    return None


def sample_col(df: pd.DataFrame) -> str:
    """샘플 번호 열 = 첫 번째 열 (.sum '샘플 수', .vel/.snr '스테이션 번호'로 이름이 다름)."""
    return df.columns[0]


def _check_samples(rec: TransectRecord, store, checks: list[CheckItem]) -> str:
    sets = {}
    for kind in DETAIL_KINDS:
        df = store[kind].get(rec.num)
        if df is None or df.empty:
            continue
        s = df[sample_col(df)]
        dup = int(s.duplicated().sum())
        if dup:
            checks.append(CheckItem(LEVEL_WARN, "샘플 번호", rec.label,
                                    f"{_kind_name(kind)}에 중복 샘플 번호 {dup}개"))
        if s.isna().any():
            checks.append(CheckItem(LEVEL_WARN, "샘플 번호", rec.label,
                                    f"{_kind_name(kind)}에 비어 있는 샘플 번호 {int(s.isna().sum())}개"))
        sets[kind] = list(s)
    if len(sets) < 2:
        return "비교 대상 부족"
    base_kind = next(iter(sets))
    base = sets[base_kind]
    problems = []
    for kind, vals in sets.items():
        if kind == base_kind:
            continue
        if len(vals) != len(base):
            problems.append(f"{_kind_name(kind)} 행 수 {len(vals)} ≠ {_kind_name(base_kind)} {len(base)}")
        if set(vals) != set(base):
            only_a = len(set(base) - set(vals))
            only_b = len(set(vals) - set(base))
            problems.append(f"{_kind_name(base_kind)}↔{_kind_name(kind)} 샘플 번호 불일치(한쪽에만 {only_a}/{only_b}개)")
        elif vals != base:
            problems.append(f"{_kind_name(kind)} 샘플 순서가 {_kind_name(base_kind)}와 다름")
    if problems:
        for p in problems:
            checks.append(CheckItem(LEVEL_WARN, "샘플 번호", rec.label, p))
        return "불일치: " + "; ".join(problems)
    kinds = "/".join(_kind_name(k) for k in sets)
    return f"일치 ({kinds} 샘플 번호 {len(base)}개 동일)"


def _check_start_time(rec: TransectRecord, checks: list[CheckItem]) -> str:
    if not rec.has_summary:
        return "비교 불가(요약 없음)"
    dis_t = parse_rsq_time(rec.dis_row_raw.get("start"))
    out = []
    for kind in ("vel", "sum", "snr"):
        t = parse_rsq_time(rec.first_time_raw.get(kind))
        if dis_t is None or t is None:
            continue
        if (t.tzinfo is None) != (dis_t.tzinfo is None):
            checks.append(CheckItem(LEVEL_WARN, "시간 기준", rec.label, "시간대 유무가 달라 시작 시각 비교 보류"))
            continue
        diff = (t - dis_t).total_seconds()
        out.append((kind, diff))
    if not out:
        return "비교 불가"
    parts = []
    for kind, diff in out:
        parts.append(f"{_kind_name(kind)} {'일치' if diff == 0 else _fmt_offset(diff) + ' 차이'}")
    if not any(d == 0 for _k, d in out):
        checks.append(CheckItem(LEVEL_WARN, "회차 연결", rec.label,
                                ".dis 시작시각과 일치하는 상세 파일 첫 샘플 시각이 없음 (연결은 파일명 번호 기준 유지)"))
    return ", ".join(parts)


def _fmt_offset(sec: float) -> str:
    sign = "+" if sec > 0 else "-"
    sec = abs(int(sec))
    return f"{sign}{sec // 3600:d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def _check_time_offsets(records, store, checks):
    """.sum/.snr 과 .vel 의 같은 샘플 번호끼리 시각 차이를 관찰만 해서 기록한다."""
    per_pair: dict[str, Counter] = {}
    for rec in records:
        dfs = {k: store[k].get(rec.num) for k in DETAIL_KINDS}
        if dfs["vel"] is None:
            continue
        v = dfs["vel"]
        vt = v.set_index(sample_col(v))[_time_col(v)].map(parse_rsq_time)
        for kind in ("sum", "snr"):
            d = dfs[kind]
            if d is None or _time_col(d) is None:
                continue
            dt = d.set_index(sample_col(d))[_time_col(d)].map(parse_rsq_time)
            common = dt.index.intersection(vt.index)
            if dt.index.has_duplicates or vt.index.has_duplicates:
                continue
            diffs = [(vt[i] - dt[i]).total_seconds() for i in common if pd.notna(vt[i]) and pd.notna(dt[i])
                     and (vt[i].tzinfo is None) == (dt[i].tzinfo is None)]
            per_pair.setdefault(kind, Counter()).update(diffs)
    for kind, cnt in per_pair.items():
        if not cnt:
            continue
        desc = ", ".join(f"{_fmt_offset(s)}: {n}개" for s, n in cnt.most_common(5))
        lvl = LEVEL_INFO if set(cnt) == {0.0} else LEVEL_WARN
        checks.append(CheckItem(lvl, "시간 기준", f"{_kind_name(kind)} ↔ .vel",
                                f"같은 샘플 번호의 시각 차이(.vel − {_kind_name(kind)}) 분포 → {desc}. "
                                "원인(UTC/한국시간 등) 미확인 · 원문 시간 그대로 표시하고 변환하지 않음"))


def _status(rec: TransectRecord) -> str:
    has_detail = any(k in rec.files for k in DETAIL_KINDS)
    fail = bool(rec.load_errors)
    if has_detail and rec.has_summary:
        s = "상세자료 있음 / 요약 결과 있음"
    elif has_detail:
        s = "상세자료 있음 / 요약 결과 없음"
    elif rec.has_summary:
        s = "상세자료 없음 / 요약 결과 있음"
    else:
        s = "자료 없음"
    if fail:
        s += " (일부 읽기 실패)"
    return s


def _source_compare(dis, colmap, dis_rows_by_num, summary, checks, sf) -> pd.DataFrame | None:
    """.dis 와 rsqmb Summary.json 값을 나란히 놓는다 (어느 쪽도 정답으로 정하지 않음)."""
    rows = []
    try:
        dis_total = None
        if dis is not None:
            for k, v in dis.sections.get("Discharge Results", {}).items():
                if k.startswith("Total Q"):
                    dis_total = to_number(v)
        js_total = to_number(summary.get("Discharge Results", {}).get("Total Q"))
        rows.append({"구분": "세션 전체 Total Q", "회차": "", "DIS 값": dis_total,
                     "rsqmb Summary.json 값": js_total})
        for item in summary.get("Measurement Results", []) or []:
            m = FILE_NUM_RE.match(str(item.get("File Name", "")))
            num = int(m.group(1)) if m else None
            dis_raw = dis_rows_by_num.get(num) if num is not None else None
            rows.append({"구분": "회차 Total Q", "회차": f"T{num:02d}" if num is not None else "번호 미확인",
                         "DIS 값": to_number(dis_raw.get("total_q")) if dis_raw else None,
                         "rsqmb Summary.json 값": to_number(item.get("Total Q"))})
    except Exception as e:  # noqa: BLE001
        checks.append(CheckItem(LEVEL_INFO, ".rsqmb 참고", sf.rsqmb.name, f"출처 비교표 생성 실패: {e}"))
        return None
    df = pd.DataFrame(rows)
    df["차이(Summary.json − DIS)"] = [
        _dec_diff(b, a) if (a is not None and b is not None) else None
        for a, b in zip(df["DIS 값"], df["rsqmb Summary.json 값"])
    ]
    n_diff = sum(1 for x in df["차이(Summary.json − DIS)"] if x not in (None, 0) and not pd.isna(x))
    if n_diff:
        checks.append(CheckItem(LEVEL_WARN, "출처 간 불일치", sf.name,
                                f".dis와 rsqmb Summary.json의 유량 값이 {n_diff}개 항목에서 다름 "
                                "(원인 미확인 · 화면/통계는 DIS 값만 사용, '출처비교' 표 참고)"))
    return df


def _dec_diff(b: float, a: float) -> float:
    """b − a 를 10진수로 계산 (3.7049 − 3.6913 = 0.0136, 부동소수 찌꺼기 0.01359999… 방지)."""
    from decimal import Decimal
    return float(Decimal(repr(b)) - Decimal(repr(a)))


# ---------------------------------------------------------------- v0.2 추가
SECTION_ORDER = ["시작 Edge", "횡단 섹션", "마침 Edge"]
SECTION_SOURCE = ".rsqmb 내부 AdcpData/<회차>_…/Configuration.json 의 SampleType"


def _link_sections(sf: SessionFiles, records, store, checks) -> dict[int, pd.Series]:
    """구간 정보를 '샘플 번호'로 상세 파일과 연결. 하나라도 안 맞으면 그 회차는 연결하지 않는다."""
    raw, msgs = read_rsqmb_sections(sf.rsqmb)
    for m in msgs:
        checks.append(CheckItem(LEVEL_INFO, "구간 정보", sf.rsqmb.name, m))
    out: dict[int, pd.Series] = {}
    for rec in records:
        rows = raw.get(rec.num)
        if not rows:
            rec.section_summary = "구간 정보 없음"
            if rec.files:
                checks.append(CheckItem(LEVEL_INFO, "구간 정보", rec.label,
                                        ".rsqmb에 이 회차의 구간 정보가 없어 전체 기록만 표시"))
            continue
        nums = [n for n, _t in rows]
        if len(set(nums)) != len(nums):
            rec.section_summary = "연결 안 함(구간 정보 샘플 번호 중복)"
            checks.append(CheckItem(LEVEL_WARN, "구간 정보", rec.label, "구간 정보에 중복 샘플 번호가 있어 연결하지 않음"))
            continue
        ref_kind = next((k for k in DETAIL_KINDS if store[k].get(rec.num) is not None), None)
        if ref_kind is None:
            rec.section_summary = "연결 안 함(상세 파일 없음)"
            continue
        df = store[ref_kind][rec.num]
        file_nums = list(df[sample_col(df)])
        if set(file_nums) != set(nums) or len(file_nums) != len(nums):
            a = len(set(file_nums) - set(nums))
            b = len(set(nums) - set(file_nums))
            rec.section_summary = "연결 안 함(샘플 번호 불일치)"
            checks.append(CheckItem(LEVEL_WARN, "구간 정보", rec.label,
                                    f"{_kind_name(ref_kind)}와 구간 정보의 샘플 번호가 다름(파일에만 {a}개, 구간 정보에만 {b}개) "
                                    "→ 추정하지 않고 연결하지 않음"))
            continue
        ser = pd.Series({n: t for n, t in rows})
        out[rec.num] = ser
        rec.section_summary = _runs_text(rows)
    if out:
        checks.append(CheckItem(LEVEL_INFO, "구간 정보", sf.name,
                                f"시작 Edge/횡단/마침 Edge 구간 = {SECTION_SOURCE} 값(RSQ가 기록한 값, 추정 아님). "
                                f"샘플 번호가 상세 파일과 모두 일치한 {len(out)}개 회차에만 표시. "
                                "RSQ 사이드바의 '샘플 타입'과 같은 정보로 판단(test 자료 T01 샘플 312 = 횡단 섹션 화면과 일치)"))
    return out


def _runs_text(rows: list[tuple[int, str]]) -> str:
    runs = []
    for n, t in rows:
        if runs and runs[-1][0] == t and n == runs[-1][2] + 1:
            runs[-1][2] = n
            runs[-1][3] += 1
        else:
            runs.append([t, n, n, 1])
    return " / ".join(f"{t} {a}–{b} ({c}개)" for t, a, b, c in runs)


def _decimals(raw: str) -> int:
    raw = str(raw).strip()
    return len(raw.split(".", 1)[1]) if "." in raw else 0


def _check_dis_total(dis, dis_rows_by_num, dis_file, checks):
    """DIS 전체 Total Q 가 '.dis 회차표에 들어간 회차들의 평균'과 같은지 점검(관찰 기록, 재계산 결과로 쓰지 않음)."""
    total_raw = None
    for k, v in dis.sections.get("Discharge Results", {}).items():
        if k.startswith("Total Q"):
            total_raw = v
    total = to_number(total_raw)
    qs = [to_number(r.get("total_q")) for r in dis_rows_by_num.values()]
    qs = [q for q in qs if q is not None]
    if total is None or not qs:
        return
    mean = sum(qs) / len(qs)
    labels = ", ".join(f"T{n:02d}" for n in sorted(dis_rows_by_num))
    same = round(mean, _decimals(total_raw)) == total
    msg = (f"DIS 전체 Total Q {total_raw} {'=' if same else '≠'} .dis 회차표 {len(qs)}개 회차({labels}) Total Q의 "
           f"산술평균 {mean:.{_decimals(total_raw) + 2}f}. ")
    if same:
        msg += ("→ DIS 전체값은 '.dis에 들어간 회차만의 평균'임. 회차를 넣고 빼면 전체값이 달라짐 "
                "(매뉴얼 117쪽: 요약 패널 Mean = 체크된 회차의 평균)")
    else:
        msg += "→ 단순 평균과 다름(원인 미확인, 판정하지 않음)"
    checks.append(CheckItem(LEVEL_INFO, "회차 포함/제외", dis_file.name, msg))


def _compare_dis_candidates(cands, used, checks):
    for p in cands:
        try:
            ov = dis_overview(p)
            nums = []
            for f in ov["files"]:
                m = FILE_NUM_RE.match(f)
                nums.append(f"T{int(m.group(1)):02d}" if m else "?")
            mark = "사용 중" if used is not None and Path(p) == Path(used) else "후보"
            checks.append(CheckItem(LEVEL_INFO, ".dis 후보", p.name,
                                    f"[{mark}] 회차 {len(nums)}개({', '.join(nums)}), 전체 Total Q {ov['total_q_raw']}"))
        except Exception as e:  # noqa: BLE001
            checks.append(CheckItem(LEVEL_WARN, ".dis 후보", p.name, f"후보 .dis를 읽지 못함: {e}"))


# ---------------------------------------------------------------- v0.4: RSQ 수위(Gauge Height)
def _read_gauge_heights(dis, checks, dis_file) -> dict[int, dict]:
    """.dis 'Supplemental Data' 표(세미콜론)에서 회차별 시작/끝 수위와 관측 시각을 읽는다.
    📘 매뉴얼 82·96쪽: RSQ에서 측정 시작·끝 수위와 관측 시각을 입력할 수 있음.
    - 값이 비어 있으면 '기록 없음'(직접 입력 대상). 0은 그대로 두되 '미입력일 수 있음'으로 점검내역에 남김.
    - 회차 연결은 회차표와 같이 File Name 앞 번호로 한다."""
    table = None
    for t in dis.tables:
        if any(h.strip().startswith("Start Gauge Height") for h in t.header):
            table = t
            break
    if table is None:
        return {}
    hdr = [h.strip() for h in table.header]

    def col(prefix, exclude=None):
        for i, h in enumerate(hdr):
            if h.startswith(prefix) and (exclude is None or exclude not in h):
                return i
        return None

    i_file = col("File Name")
    i_s, i_st = col("Start Gauge Height", "Time"), col("Start Gauge Height Observation Time")
    i_e, i_et = col("End Gauge Height", "Time"), col("End Gauge Height Observation Time")
    unit = unit_of(hdr[i_s]) if i_s is not None else ""
    tbasis = unit_of(hdr[i_st]) if i_st is not None else ""
    out: dict[int, dict] = {}
    for cells in table.rows:
        cells = [c.strip() for c in cells]
        get = (lambda i: cells[i] if i is not None and i < len(cells) else "")  # noqa: E731
        m = FILE_NUM_RE.match(get(i_file))
        if not m:
            continue
        num = int(m.group(1))
        g = {"gh_start": to_number(get(i_s)), "gh_start_time": get(i_st) or None,
             "gh_end": to_number(get(i_e)), "gh_end_time": get(i_et) or None,
             "unit": unit, "time_basis": tbasis}
        if g["gh_start"] is None and g["gh_end"] is None:
            continue
        out[num] = g
        if 0.0 in (g["gh_start"], g["gh_end"]):
            checks.append(CheckItem(LEVEL_WARN, "수위 기록", f"T{num:02d}",
                                    "RSQ 수위(Gauge Height)가 0으로 기록됨 — 실제 0인지 미입력 기본값인지 확인 필요"))
    if out:
        checks.append(CheckItem(LEVEL_INFO, "수위 기록", dis_file.name,
                                f"RSQ에 입력된 수위(Gauge Height) {len(out)}개 회차 읽음 (.dis Supplemental Data)"))
    return out
