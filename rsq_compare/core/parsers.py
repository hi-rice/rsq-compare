"""파일 읽기(파싱).

- .dis    : 구역마다 구분자가 다른 텍스트(';' 키-값, 탭 표, 빈 줄로 구역 구분)
- .sum/.snr/.vel : 쉼표로 구분된 텍스트(CSV)
- .rsqmb  : ZIP 형식. 안의 Summary.json / DataSessionProperties.json만 '참고용'으로 읽는다.
            (바이너리 원시자료는 해석하지 않음)

원칙
- 빈칸/#N/A/NaN 은 '값 없음(NaN)'으로 두고 0으로 바꾸지 않는다.
- 시간 문자열은 원문을 보존한다. 명시된 시간대는 버리지 않으며,
  시간대 없는 값에 어떤 기준을 적용할지는 비교 단계에서 결정한다.
"""
from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd

from rsq_compare.core.model import DisResult, DisTable

ENCODINGS = ("utf-8-sig", "cp949")
MISSING_TOKENS = {"", "#N/A", "N/A", "NA", "NaN", "nan", "-", "--"}


def read_text(path: Path) -> tuple[str, str]:
    """여러 인코딩을 차례로 시도해 텍스트를 읽는다. (내용, 사용한 인코딩)"""
    last = None
    for enc in ENCODINGS:
        try:
            return Path(path).read_text(encoding=enc), enc
        except UnicodeDecodeError as e:
            last = e
    raise ValueError(f"글자 인코딩을 알 수 없습니다(UTF-8/CP949 모두 실패): {last}")


def to_number(raw: str | None) -> float | None:
    """문자열 → 숫자. 비었거나 숫자가 아니면 None(0으로 바꾸지 않음)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s in MISSING_TOKENS:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def unit_of(header: str) -> str:
    """'Total Q (m ³/s)' → 'm ³/s'. 괄호가 없으면 ''."""
    m = re.search(r"\(([^()]*)\)\s*$", header)
    return m.group(1).strip() if m else ""


def parse_hms(raw: str | None) -> float | None:
    """'00:01:50' → 110.0 초 (형식 변환일 뿐 값 보정 아님)."""
    if not raw:
        return None
    m = re.fullmatch(r"\s*(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)\s*", raw)
    if not m:
        return None
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


_TIME_RE = re.compile(
    r"(?P<date>\d{4}-\d{1,2}-\d{1,2})\s+(?:(?P<ampm>오전|오후|AM|PM)\s*)?"
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})(?:\s*(?P<ampm2>AM|PM|오전|오후))?",
    re.IGNORECASE,
)


def parse_rsq_time(raw) -> datetime | None:
    """'2026-10-29 오전 1:40:18' / '2026-10-29 10:40:18' 을 읽는다.
    ISO 시각의 Z/오프셋은 보존한다. 시간대 없는 값은 그대로 둔다."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    try:
        return pd.Timestamp(str(raw).strip())
    except (ValueError, TypeError):
        pass
    m = _TIME_RE.fullmatch(str(raw).strip())
    if not m:
        return None
    h = int(m["h"])
    ampm = (m["ampm"] or m["ampm2"] or "").upper()
    if ampm in ("오후", "PM") and h < 12:
        h += 12
    elif ampm in ("오전", "AM") and h == 12:
        h = 0
    try:
        y, mo, d = (int(x) for x in m["date"].split("-"))
        return datetime(y, mo, d, h, int(m["m"]), int(m["s"]))
    except ValueError:
        return None


# ---------------------------------------------------------------- .dis
def parse_dis(path: Path) -> DisResult:
    """.dis 파일을 구역 단위로 읽는다.

    관찰된 구조(실제 파일 확인 결과):
    - 빈 줄로 구역이 나뉨
    - 구분자 없는 줄 = 구역 제목 (예: 'System Setup')
    - 'A;B' = 키-값, 'A;B;C;...' = 세미콜론 표 (예: Supplemental Data)
    - 탭이 들어간 줄 = 탭 표 (회차별 결과표)
    - 'Date Measured: 2026-10-29' 같은 ':' 키-값
    구조가 바뀌어도 죽지 않도록, 해석 못 한 줄은 warnings에 남긴다.
    """
    text, _enc = read_text(path)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    sections: dict[str, dict[str, str]] = {}
    tables: list[DisTable] = []
    notes: list[str] = []
    warnings: list[str] = []

    title: str | None = None
    cur_table: DisTable | None = None
    untitled = 0
    seen_titles: list[str] = []

    def section_name() -> str:
        nonlocal untitled, title
        if title is None:
            untitled += 1
            title = f"(제목 없는 구역 {untitled})"
        return title

    for ln_no, line in enumerate(lines, start=1):
        if not line.strip():
            title, cur_table = None, None
            continue
        if "\t" in line:
            cells = line.split("\t")
            if cur_table is None or cur_table.delimiter != "\t":
                cur_table = DisTable(title or "(탭 표)", [c.strip() for c in cells], [], "\t")
                tables.append(cur_table)
            else:
                if len(cells) != len(cur_table.header):
                    warnings.append(f"{ln_no}행: 표 열 개수({len(cells)})가 머리글({len(cur_table.header)})과 다름")
                cur_table.rows.append(cells)
            continue
        if ";" in line:
            cells = line.split(";")
            if cur_table is not None and cur_table.delimiter == ";":
                cur_table.rows.append(cells)
            elif len(cells) > 2:
                cur_table = DisTable(section_name(), [c.strip() for c in cells], [], ";")
                tables.append(cur_table)
            else:
                sections.setdefault(section_name(), {})[cells[0].strip()] = cells[1].strip()
            continue
        if ":" in line and title is not None:
            k, v = line.split(":", 1)
            sections.setdefault(title, {})[k.strip()] = v.strip()
            continue
        if title is None:
            title = line.strip()
            seen_titles.append(title)
        else:
            # 제목 다음 줄도 구분자가 없으면 일반 메모로 취급
            notes.append(line.strip())

    # 내용 없이 제목만 남은 줄(예: 'Report generated using ...')은 메모로 옮김
    used = set(sections) | {t.title for t in tables}
    notes = [t for t in seen_titles if t not in used] + notes
    return DisResult(Path(path), sections, tables, notes, warnings)


# ---------------------------------------------------------------- CSV 상세 파일
def read_detail_csv(path: Path) -> pd.DataFrame:
    """쉼표 구분 상세 파일을 읽는다. 결측은 NaN 그대로, 숫자는 원문 정밀도 유지."""
    last = None
    for enc in ENCODINGS:
        try:
            df = pd.read_csv(
                path,
                encoding=enc,
                float_precision="round_trip",
                na_values=["#N/A", "N/A", "NaN"],
                keep_default_na=True,
            )
            if df.empty and len(df.columns) == 0:
                raise ValueError("내용이 비어 있습니다")
            return df
        except UnicodeDecodeError as e:
            last = e
    raise ValueError(f"글자 인코딩을 알 수 없습니다: {last}")


# ---------------------------------------------------------------- .rsqmb (참고용)
def read_rsqmb_json(path: Path) -> tuple[dict | None, dict | None, list[str]]:
    """rsqmb(ZIP) 안의 Summary.json, DataSessionProperties.json 만 읽는다."""
    msgs: list[str] = []
    summary = props = None
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            for name in ("Summary.json", "DataSessionProperties.json"):
                if name not in names:
                    msgs.append(f"{name} 없음")
                    continue
                try:
                    data = json.loads(zf.read(name).decode("utf-8-sig"))
                except Exception as e:  # noqa: BLE001
                    msgs.append(f"{name} 읽기 실패: {e}")
                    continue
                if name == "Summary.json":
                    summary = data
                else:
                    props = data
    except zipfile.BadZipFile:
        msgs.append("ZIP 형식이 아니어서 읽지 않음")
    return summary, props, msgs


# ---------------------------------------------------------------- .rsqmb 구간 정보 (JSON)
SECTION_KOR = {"StartEdge": "시작 Edge", "TransectSection": "횡단 섹션", "EndEdge": "마침 Edge"}
_CFG_RE = re.compile(r"^AdcpData/(\d+)_[^/]*/Configuration\.json$")


def read_rsqmb_sections(path: Path) -> tuple[dict[int, list[tuple[int, str]]], list[str]]:
    """rsqmb 안 AdcpData/<번호>_.../Configuration.json 의 SampleConfigurations[].SampleType 을 읽는다.

    반환: {회차 번호: [(샘플 번호, 구간 이름), ...]}, 메시지 목록
    - 구간 이름은 StartEdge/TransectSection/EndEdge 를 한글로 바꿔 쓰고, 모르는 값은 원문 그대로 둔다.
    - 이 함수는 '읽기'만 한다. 상세 파일과의 연결 검증은 loader 에서 한다.
    """
    out: dict[int, list[tuple[int, str]]] = {}
    msgs: list[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                m = _CFG_RE.match(name)
                if not m:
                    continue
                num = int(m.group(1))
                try:
                    cfg = json.loads(zf.read(name).decode("utf-8-sig"))
                    items = cfg.get("SampleConfigurations") or []
                    rows = []
                    for it in items:
                        sn, stype = it.get("SampleNumber"), it.get("SampleType")
                        if sn is None or stype is None:
                            continue
                        rows.append((int(sn), SECTION_KOR.get(str(stype), str(stype))))
                    if rows:
                        if num in out:
                            msgs.append(f"회차 번호 {num:02d}의 Configuration.json이 여러 개라 구간 정보를 쓰지 않음")
                            out[num] = None  # 표시: 모호함
                        else:
                            out[num] = rows
                    else:
                        msgs.append(f"{name}: SampleConfigurations/SampleType 정보 없음")
                except Exception as e:  # noqa: BLE001
                    msgs.append(f"{name} 읽기 실패: {e}")
    except zipfile.BadZipFile:
        msgs.append("ZIP 형식이 아니어서 구간 정보를 읽지 않음")
    return {k: v for k, v in out.items() if v}, msgs


def dis_overview(path: Path) -> dict:
    """.dis 후보 비교용 간단 요약: 회차 파일명 목록과 전체 Total Q 원문."""
    d = parse_dis(path)
    total = None
    for k, v in d.sections.get("Discharge Results", {}).items():
        if k.startswith("Total Q"):
            total = v
    files = []
    for t in d.tables:
        hdr = [h.strip() for h in t.header]
        if "File Name" in hdr and any(h.startswith("Total Q") for h in hdr):
            i = hdr.index("File Name")
            files = [r[i].strip() for r in t.rows if i < len(r)]
    return {"total_q_raw": total, "files": files}
